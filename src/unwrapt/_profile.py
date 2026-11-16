"""The recorder: import edges and timings, recorded through an import hook.

The recorder installs a recording __import__ hook over whatever import
function is current: the original one, or the shim when deferral is on
too. Every import call through the hook, including sys.modules cache
hits, is recorded as an edge with the wall time it took and its place
in the tree of nested imports, and, when the shim sits below, whether
the shim deferred it. On Python 3.15 and later native lazy imports are
left exactly as they are, and are recorded when native reifies them,
at first use.

The report is built when the recorder is stopped: by stop_profile(),
or by the exit handler registered at install, which stop_profile()
unregisters so a process that stops the recorder (a preforking server
at the fork, for example) never writes a second report at exit.

Recording must never import anything itself: everything the recorder
needs is imported before the hook goes in, so a recorded import can
never recurse into the hook through the recording machinery. Nothing
here imports wrapt.
"""

import atexit
import builtins
import os
import sys
import threading
import time
import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Literal, TypeAlias, cast

from unwrapt import _labels
from unwrapt._compat import has_native_lazy_imports, mark_profile
from unwrapt._config import Config, ProfileOptions, is_candidate, is_native_pending
from unwrapt._records import Resolution
from unwrapt._report import Edge, Report, build_report

ImportFunction = Callable[..., types.ModuleType]

# Each entry of a thread's stack of in-progress import calls holds the
# id of the call (which is the parent_id of anything it imports) and an
# accumulator of the time spent in nested import calls (which turns
# cumulative time into self time) and of how many there were (which
# says whether the call can be folded).

_StackEntry: TypeAlias = tuple[int, list[float]]

# A folded run of already-loaded hits is keyed by importer, module and
# label set, and by the form facts the analysis reads (kind, level,
# relative), and by whether the hits were outermost, so that the
# folded times still add up to the total import time.

_FoldKey: TypeAlias = tuple[str | None, str, int, str, str, bool, bool]


class _Fold:
    """Repeated already-loaded hits, folded: the first hit and the sums."""

    __slots__ = ("count", "cum_ms", "first", "self_ms")

    def __init__(self, first: Edge) -> None:
        self.first = first
        self.count = 0
        self.cum_ms = 0.0
        self.self_ms = 0.0

    def edge(self) -> Edge:
        """The folded edge: the first hit, with the count and the sums."""

        return replace(
            self.first,
            count=self.count,
            cum_ms=self.cum_ms,
            self_ms=self.self_ms,
        )


class _ResolveToken:
    """The state of one resolve between begin_resolve and end_resolve."""

    __slots__ = ("child_time", "edge_id", "labels", "parent_id", "start")

    def __init__(
        self,
        edge_id: int,
        parent_id: int | None,
        child_time: list[float],
        start: float,
    ) -> None:
        self.edge_id = edge_id
        self.parent_id = parent_id
        self.child_time = child_time
        self.start = start
        self.labels = _labels.current


class Recorder:
    """One installed recorder layer.

    active is False once the recorder is stopped, which turns its hook
    into plain pass-through. next_import is the import function it
    chains to, the shim or the original. shim_local is the shim's
    thread-local deferred flag when the shim sits below, or None, and
    deferred_edges maps each of the shim's deferral records to the id
    of the edge that recorded the deferral, so a later resolve can be
    tied back to it.

    Repeated already-loaded hits, which make up most of the import
    calls a large application makes, are folded into folds rather than
    kept one edge each. Nothing is pruned: every edge that loaded a
    module, was deferred or resolved, or made nested import calls is
    kept as it is.

    One lock guards the state shared across threads, the edge id counter
    and the edge list: import calls can be made from any thread,
    including concurrently on a free-threaded build. The stack of
    in-progress import calls is per thread, in local, since imports in
    different threads are not nested in each other.
    """

    __slots__ = (
        "active",
        "config",
        "deferred_edges",
        "edges",
        "folds",
        "hook",
        "local",
        "lock",
        "next_id",
        "next_import",
        "shim_local",
    )

    def __init__(
        self,
        config: Config,
        next_import: ImportFunction,
        shim_local: threading.local | None,
    ) -> None:
        self.active = True
        self.config = config
        self.next_import = next_import
        self.shim_local = shim_local
        self.lock = threading.Lock()
        self.next_id = 0
        self.edges: list[Edge] = []
        self.folds: dict[_FoldKey, _Fold] = {}
        self.deferred_edges: dict[object, int] = {}
        self.local = threading.local()
        self.hook: ImportFunction = _make_hook(self)

    def stack(self) -> list[_StackEntry]:
        """This thread's stack of in-progress import calls."""

        stack: list[_StackEntry] | None = getattr(self.local, "stack", None)

        if stack is None:
            stack = []
            self.local.stack = stack

        return stack

    def begin_resolve(self) -> object | None:
        """Open a resolve as an import call, so its imports nest in it.

        Returns None to record nothing: when the recorder is stopped, or
        the resolve was triggered by the recorder's own bookkeeping.
        """

        if not self.active or getattr(self.local, "reentrant", False):
            return None

        stack = self.stack()
        parent_id = stack[-1][0] if stack else None

        with self.lock:
            edge_id = self.next_id
            self.next_id += 1

        child_time = [0.0, 0.0]
        stack.append((edge_id, child_time))

        return _ResolveToken(edge_id, parent_id, child_time, time.perf_counter())

    def end_resolve(
        self,
        token: object,
        record: object,
        resolution: Resolution | None,
    ) -> None:
        """Close a resolve, recording it as a resolve edge.

        The edge carries the module's load cost, where it was first used,
        and the id of the deferred edge it resolves. A resolve whose
        import raised records nothing, and neither does one that ends
        after the recorder was stopped.
        """

        state = cast(_ResolveToken, token)
        elapsed = (time.perf_counter() - state.start) * 1000.0

        stack = self.stack()

        if stack and stack[-1][0] == state.edge_id:
            stack.pop()

        if stack:
            stack[-1][1][0] += elapsed
            stack[-1][1][1] += 1.0

        if resolution is None or not self.active:
            return

        edge = Edge(
            id=state.edge_id,
            parent_id=state.parent_id,
            importer=resolution.importer,
            imported=resolution.module,
            kind="resolve",
            level_name="module",
            line=resolution.line,
            file=resolution.file,
            loaded=resolution.loaded,
            cum_ms=elapsed,
            self_ms=elapsed - state.child_time[0],
            native_lazy=False,
            already_lazy=True,
            resolves=self.deferred_edges.get(record),
            used_in=resolution.used_in,
            labels=state.labels,
        )

        with self.lock:
            self.edges.append(edge)


# The recorder layer currently installed, or None.

_current: Recorder | None = None


def current() -> Recorder | None:
    """The recorder layer currently installed, or None."""

    return _current


def install_profile(config: Config, shim_local: threading.local | None) -> bool:
    """Install the recording hook over the current import function.

    shim_local is the deferred flag of the shim installed just below,
    or None when deferral is off. Native lazy imports on Python 3.15 are
    left exactly as they are: forcing them eager with the
    sys.set_lazy_imports_filter mechanism PEP 810 provides would hide
    them from the hook entirely (the forced load bypasses
    builtins.__import__), so instead the profiler records a native lazy
    import when native reifies it, at first use, flags it in the report
    and warns. A run with native laziness switched to "all" mode is
    warned about at install, because every import it touches is then
    measured at first use.

    The report is written at process exit unless stop_profile() is
    called first. Worker process setups (a mod_wsgi daemon process, for
    example) may not run exit handlers reliably, so an output path is
    the recommended way to get the report, with %p in the path
    expanding to the process id.

    Returns True when this call installed the hook, False when a
    recorder was already installed.
    """

    global _current

    if _current is not None:
        return False

    # sys.get_lazy_imports only exists from Python 3.15, so it is
    # reached through getattr to keep the module importable, and
    # typeable, on older versions.

    get_lazy_imports = getattr(sys, "get_lazy_imports", None)

    if get_lazy_imports is not None and get_lazy_imports() != "normal":
        print(
            "unwrapt: warning: native lazy imports are active"
            " (sys.get_lazy_imports() is not 'normal'): the profile"
            " measures them at first use, not at their import"
            " statements. Run with PYTHON_LAZY_IMPORTS=normal, or remove"
            " the sys.set_lazy_imports call, to profile an eager run.",
            file=sys.stderr,
        )

    recorder = Recorder(config, builtins.__import__, shim_local)
    builtins.__import__ = recorder.hook
    _current = recorder
    mark_profile(True)

    atexit.register(_at_exit)

    if config.debug:
        above = " above the shim" if shim_local is not None else ""
        print(f"unwrapt: profile mode installed{above}", file=sys.stderr)

    return True


def stop_profile(write: bool) -> "Report | None":
    """Stop the recorder and return its report, or None when none runs.

    The exit handler is unregistered first, so the report is never
    written a second time at exit. With write set, the report also goes
    where the profile options say: to the output path, or to stderr.
    """

    recorder = _current

    if recorder is None:
        return None

    atexit.unregister(_at_exit)

    return _stop(recorder, write)


def _stop(recorder: Recorder, write: bool) -> Report:
    """Take the recorder out, build its report, and write it if asked.

    The recorder is taken out before the report is built, so nothing
    that runs while the report is computed or written is recorded. The
    import function below it is put back only when the recorder is
    still the current builtins.__import__; otherwise something was
    installed over it, and the recorder stays in the chain as plain
    pass-through rather than removing that too.
    """

    global _current

    recorder.active = False

    if builtins.__import__ is recorder.hook:
        builtins.__import__ = recorder.next_import

    _current = None
    mark_profile(False)

    # The shim, when installed, no longer reports resolves to this
    # recorder. It is looked up rather than imported, since the
    # recorder alone never imports wrapt.

    hook_module = sys.modules.get("unwrapt._hook")

    if hook_module is not None and hook_module.tracer() is recorder:
        hook_module.set_tracer(None)

    with recorder.lock:
        edges = list(recorder.edges)
        edges.extend(fold.edge() for fold in recorder.folds.values())
        recorder.edges.clear()
        recorder.folds.clear()
        recorder.deferred_edges.clear()

    options = recorder.config.profile
    report = build_report(edges, options, _labels.label_sets())

    if write:
        _write(report, options)

    return report


def _write(report: Report, options: ProfileOptions) -> None:
    """Write the report as the options say. Never raises.

    A failure to write is reported on stderr: the report has been built
    and is returned to the caller anyway, and at exit a failure must
    not break the exit of the host application.
    """

    try:
        if options.format == "json":
            text = report.render_json()
        else:
            text = report.render_text()

        if options.output is None:
            print(text, file=sys.stderr)

            return

        path = options.output.replace("%p", str(os.getpid()))

        with open(path, "w", encoding="utf-8") as fp:
            fp.write(text)
            fp.write("\n")
    except Exception as exc:
        print(f"unwrapt: writing the profile report failed: {exc}", file=sys.stderr)


def _at_exit() -> None:
    """Write the profile report at process exit. Never raises."""

    recorder = _current

    if recorder is None:
        return

    try:
        _stop(recorder, write=True)
    except Exception as exc:
        print(f"unwrapt: building the profile report failed: {exc}", file=sys.stderr)


def _make_hook(recorder: Recorder) -> ImportFunction:
    """Build the recording hook function for one recorder layer.

    The hook is a closure over the layer rather than a bound method, so
    the eval loop calls a plain function and the importing frame stays
    exactly one level up, which is where the hook reads the statement's
    file and line.
    """

    next_import = recorder.next_import
    shim_local = recorder.shim_local
    local = recorder.local
    lock = recorder.lock
    edges = recorder.edges
    folds = recorder.folds
    config = recorder.config

    def _profiling_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] | None = (),
        level: int = 0,
    ) -> types.ModuleType:
        """The recording hook: one edge per import call, nested or not.

        A re-entrant call is an import that the hook's own bookkeeping
        triggered: on Python 3.15 an application can switch native lazy
        imports to all mode, which leaves unwrapt's own module level
        imports deferred, and resolving one of those while the hook is
        running would otherwise arrive here mid-recording and cycle.
        The guard is therefore up for the bookkeeping and down for the
        real import, so the imports a loaded module makes are recorded
        as children while unwrapt's own machinery chains straight
        through, unrecorded.

        The shim, when it sits below, sets its deferred flag to the
        proxy's record when it hands one back. The flag is cleared
        before the call and read and cleared again after it, so a
        deferral by a nested call is never mistaken for this one.
        """

        if not recorder.active or getattr(local, "reentrant", False):
            return next_import(name, globals, locals, fromlist, level)

        # The guard goes up before any bookkeeping, all of which may
        # touch a deferred binding of unwrapt's own machinery, and comes
        # down only for the real import.

        local.reentrant = True

        try:
            stack = recorder.stack()

            parent_id = stack[-1][0] if stack else None

            before = len(sys.modules)
            child_time = [0.0, 0.0]
            labels = _labels.current

            # The importing frame is one level up: the hook is a plain
            # function called directly by the eval loop, with no wrapper
            # layers of its own. Calls made from C code have no such
            # frame, and the line is recorded as None rather than
            # guessed.

            try:
                caller = sys._getframe(1)
                line: int | None = caller.f_lineno
                file: str | None = caller.f_code.co_filename
            except ValueError:
                line = None
                file = None

            with lock:
                edge_id = recorder.next_id
                recorder.next_id += 1

            # A native lazy import (Python 3.15) only reaches the hook
            # when native reifies it, at first use; the pending binding
            # in sys.lazy_modules identifies it, and it counts as
            # already lazy in the report. The check must happen before
            # the real import runs: native removes the pending entry
            # once the module is loaded.

            native_lazy = has_native_lazy_imports() and is_native_pending(name)

            stack.append((edge_id, child_time))

            if shim_local is not None:
                shim_local.deferred = None

            start = time.perf_counter()

            # Down for the real import: the imports a loaded module
            # makes are the children of this edge and must be recorded.

            local.reentrant = False

            try:
                return next_import(name, globals, locals, fromlist, level)
            finally:
                local.reentrant = True

                elapsed = (time.perf_counter() - start) * 1000.0
                stack.pop()

                record: object = None

                if shim_local is not None:
                    record = getattr(shim_local, "deferred", None)
                    shim_local.deferred = None

                if record is not None:
                    with lock:
                        recorder.deferred_edges[record] = edge_id

                if stack:
                    stack[-1][1][0] += elapsed
                    stack[-1][1][1] += 1.0

                importer = _importer_name(globals)
                loaded = len(sys.modules) != before

                edge = Edge(
                    id=edge_id,
                    parent_id=parent_id,
                    importer=importer,
                    imported=name,
                    kind="from" if fromlist else "import",
                    level_name=_import_level(locals, globals),
                    line=line,
                    file=file,
                    loaded=loaded,
                    cum_ms=elapsed,
                    self_ms=elapsed - child_time[0],
                    native_lazy=native_lazy,
                    already_lazy=native_lazy
                    or (
                        is_candidate(name, globals, config)
                        if globals is not None
                        else False
                    ),
                    deferred=record is not None,
                    relative=level > 0,
                    labels=labels,
                )

                # An already-loaded hit with nothing nested beneath it
                # folds into the run of hits like it. Anything else, a
                # load, a deferral, a native reification or a call with
                # nested imports, is kept as its own edge.

                if (
                    not loaded
                    and record is None
                    and not native_lazy
                    and child_time[1] == 0.0
                ):
                    key = (
                        importer,
                        name,
                        labels,
                        edge.kind,
                        edge.level_name,
                        edge.relative,
                        parent_id is None,
                    )

                    with lock:
                        fold = folds.get(key)

                        if fold is None:
                            fold = folds[key] = _Fold(edge)

                        fold.count += 1
                        fold.cum_ms += edge.cum_ms
                        fold.self_ms += edge.self_ms
                else:
                    with lock:
                        edges.append(edge)
        finally:
            local.reentrant = False

    return _profiling_import


def _importer_name(globals: Mapping[str, object] | None) -> str | None:
    """The __name__ of the importing module, when it has one."""

    if globals is None:
        return None

    importer = globals.get("__name__")

    return importer if isinstance(importer, str) else None


def _import_level(
    locals: Mapping[str, object] | None,
    globals: Mapping[str, object] | None,
) -> Literal["module", "function", "class"]:
    """Classify where the import statement sits.

    Module level statements pass the module namespace as both globals
    and locals, function bodies pass None for locals, and class bodies
    pass the class namespace, which is neither. The distinction has
    been verified on every supported version, including the PEP 667
    frame locals changes of 3.13.
    """

    if globals is not None and locals is globals:
        return "module"

    if locals is None:
        return "function"

    return "class"
