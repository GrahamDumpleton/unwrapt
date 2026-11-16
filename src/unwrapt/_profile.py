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
from typing import Literal, TypeAlias

from unwrapt._compat import has_native_lazy_imports, mark_profile
from unwrapt._config import Config, ProfileOptions, is_candidate, is_native_pending
from unwrapt._report import Edge, Report, build_report, render_json, render_text

ImportFunction = Callable[..., types.ModuleType]

# Each entry of a thread's stack of in-progress import calls holds the
# id of the call (which is the parent_id of anything it imports) and a
# one-cell accumulator for the time spent in nested import calls (which
# turns cumulative time into self time).

_StackEntry: TypeAlias = tuple[int, list[float]]


class Recorder:
    """One installed recorder layer.

    active is False once the recorder is stopped, which turns its hook
    into plain pass-through. next_import is the import function it
    chains to, the shim or the original. shim_local is the shim's
    thread-local deferred flag when the shim sits below, or None.

    One lock guards the state shared across threads, the edge id counter
    and the edge list: import calls can be made from any thread,
    including concurrently on a free-threaded build. The stack of
    in-progress import calls is per thread, in local, since imports in
    different threads are not nested in each other.
    """

    __slots__ = (
        "active",
        "config",
        "edges",
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
        self.local = threading.local()
        self.hook: ImportFunction = _make_hook(self)


# The recorder layer currently installed, or None.

_current: Recorder | None = None


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


def stop_profile(write: bool) -> Report | None:
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

    with recorder.lock:
        edges = list(recorder.edges)
        recorder.edges.clear()

    options = recorder.config.profile
    report = build_report(edges, options)

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
            text = render_json(report)
        else:
            text = render_text(report)

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

        The shim, when it sits below, sets its deferred flag when it
        hands back a proxy. The flag is cleared before the call and read
        and cleared again after it, so a deferral by a nested call is
        never mistaken for this one.
        """

        if not recorder.active or getattr(local, "reentrant", False):
            return next_import(name, globals, locals, fromlist, level)

        # The guard goes up before any bookkeeping, all of which may
        # touch a deferred binding of unwrapt's own machinery, and comes
        # down only for the real import.

        local.reentrant = True

        try:
            stack: list[_StackEntry] | None = getattr(local, "stack", None)

            if stack is None:
                stack = []
                local.stack = stack

            parent_id = stack[-1][0] if stack else None

            before = len(sys.modules)
            child_time = [0.0]

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
                shim_local.deferred = False

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

                deferred = False

                if shim_local is not None:
                    deferred = getattr(shim_local, "deferred", False)
                    shim_local.deferred = False

                if stack:
                    stack[-1][1][0] += elapsed

                importer = _importer_name(globals)

                edge = Edge(
                    id=edge_id,
                    parent_id=parent_id,
                    importer=importer,
                    imported=name,
                    kind="from" if fromlist else "import",
                    level_name=_import_level(locals, globals),
                    line=line,
                    file=file,
                    loaded=len(sys.modules) != before,
                    cum_ms=elapsed,
                    self_ms=elapsed - child_time[0],
                    native_lazy=native_lazy,
                    already_lazy=native_lazy
                    or (
                        is_candidate(name, globals, config)
                        if globals is not None
                        else False
                    ),
                    deferred=deferred,
                )

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
