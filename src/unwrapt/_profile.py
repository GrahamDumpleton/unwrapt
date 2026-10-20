"""Profile mode: record import edges and timings through an import hook.

Profile mode installs a recording __import__ hook instead of the shim
hook: nothing is deferred, and every import call through the hook,
including sys.modules cache hits, is recorded as an edge with the wall
time it took and its place in the tree of nested imports. The report is
written at process exit, and on Python 3.15+ native lazy imports are
neutralised for the run, because otherwise the profile would measure an
already-deferred program.

Recording must never import anything itself: everything the recorder
needs is imported before the hook goes in, so a recorded import can
never recurse into the hook through the recording machinery.
"""

import atexit
import builtins
import os
import sys
import threading
import time
import types
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from unwrapt._compat import (
    has_native_lazy_imports,
    is_installed,
    mark_installed,
)
from unwrapt._config import Settings, is_candidate, is_native_pending
from unwrapt._report import Edge, build_report, render_json, render_text

# The import function that was installed when the hook went in.

_original_import: Callable[..., types.ModuleType] | None = None

# The settings the hook was installed with.

_settings: Settings | None = None

# One lock guards the two pieces of state shared across threads: the
# edge id counter and the edge list. Import calls can be made from any
# thread, including concurrently on a free-threaded build.

_lock = threading.Lock()
_next_id = 0
_edges: list[Edge] = []

# The stack of in-progress import calls, one per thread. Each entry
# holds the id of the call (which is the parent_id of anything it
# imports) and a one-cell accumulator for the time spent in nested
# import calls (which turns cumulative time into self time). Imports in
# different threads are not nested in each other, so the stack lives in
# thread local storage.

_local = threading.local()

type _StackEntry = tuple[int, list[float]]


def install_profile(settings: Settings) -> bool:
    """Install the profile mode recording hook.

    Deferral is not part of profile mode, whatever the configuration
    says: the profile must measure the program as it is. Native lazy
    imports on Python 3.15 are left exactly as they are: forcing them
    eager with the sys.set_lazy_imports_filter mechanism PEP 810
    provides would hide them from the hook entirely (the forced load
    bypasses builtins.__import__), so instead the profiler records a
    native lazy import when native reifies it, at first use, flags it
    in the report and warns. A run with native laziness switched to
    "all" mode is warned about at install, because every import it
    touches is then measured at first use.

    The report is written at process exit. Worker process setups (a
    mod_wsgi daemon process, for example) may not run exit handlers
    reliably, so UNWRAPT_PROFILE_OUTPUT is the recommended way to get
    the report, with %p in the path expanding to the process id.

    Returns True when this call installed the hook, False when a hook
    was already installed.
    """

    global _original_import, _settings

    if is_installed():
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

    _settings = settings
    _original_import = builtins.__import__
    builtins.__import__ = _profiling_import
    mark_installed("profile")

    atexit.register(_write_report)

    if settings.debug:
        print("unwrapt: profile mode installed", file=sys.stderr)

    return True


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
    running would otherwise arrive here mid-recording and cycle. The
    guard is therefore up for the bookkeeping and down for the real
    import, so the imports a loaded module makes are recorded as
    children while unwrapt's own machinery chains straight through,
    unrecorded.
    """

    global _next_id

    assert _original_import is not None and _settings is not None

    if getattr(_local, "reentrant", False):
        return _original_import(name, globals, locals, fromlist, level)

    # The guard goes up before any bookkeeping, all of which may touch
    # a deferred binding of unwrapt's own machinery, and comes down
    # only for the real import.

    _local.reentrant = True

    try:
        stack: list[_StackEntry] | None = getattr(_local, "stack", None)

        if stack is None:
            stack = []
            _local.stack = stack

        parent_id = stack[-1][0] if stack else None

        before = len(sys.modules)
        child_time = [0.0]

        # The importing frame is one level up: the hook is a plain
        # function called directly by the eval loop, with no wrapper
        # layers of its own. Calls made from C code have no such
        # frame, and the line is recorded as None rather than guessed.

        try:
            caller = sys._getframe(1)
            line: int | None = caller.f_lineno
            file: str | None = caller.f_code.co_filename
        except ValueError:
            line = None
            file = None

        with _lock:
            edge_id = _next_id
            _next_id += 1

        # A native lazy import (Python 3.15) only reaches the hook when
        # native reifies it, at first use; the pending binding in
        # sys.lazy_modules identifies it, and it counts as already
        # lazy in the report. The check must happen before the real
        # import runs: native removes the pending entry once the
        # module is loaded.

        native_lazy = has_native_lazy_imports() and is_native_pending(name)

        stack.append((edge_id, child_time))
        start = time.perf_counter()

        # Down for the real import: the imports a loaded module makes
        # are the children of this edge and must be recorded.

        _local.reentrant = False

        try:
            return _original_import(name, globals, locals, fromlist, level)
        finally:
            _local.reentrant = True

            elapsed = (time.perf_counter() - start) * 1000.0
            stack.pop()

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
                    is_candidate(name, globals, _settings)
                    if globals is not None
                    else False
                ),
            )

            with _lock:
                _edges.append(edge)
    finally:
        _local.reentrant = False


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


def _write_report() -> None:
    """Write the profile report at process exit.

    The hook is taken out first, so nothing that runs while the report
    is computed or written is recorded (or recurses into the writing).
    Never raises: a failure to write the report must not break the exit
    of the host application.
    """

    assert _original_import is not None and _settings is not None

    settings = _settings

    try:
        builtins.__import__ = _original_import

        with _lock:
            edges = list(_edges)

        report = build_report(edges, settings)

        if settings.profile_format == "json":
            text = render_json(report)
        else:
            text = render_text(report)

        output = settings.profile_output

        if output is None:
            print(text, file=sys.stderr)

            return

        path = output.replace("%p", str(os.getpid()))

        with open(path, "w", encoding="utf-8") as fp:
            fp.write(text)
            fp.write("\n")
    except Exception as exc:
        print(f"unwrapt: writing the profile report failed: {exc}", file=sys.stderr)
