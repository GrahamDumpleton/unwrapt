"""The small record types the public API returns.

Loaded only on first access through the package's module __getattr__,
or by the layers once installed, since dataclasses brings inspect, re
and more with it and importing unwrapt must stay inert.
"""

import threading
from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Installed:
    """Which unwrapt layers are installed in this process.

    defer is the shim, which defers imports, and profile the recorder,
    which records them. unwrapt.installed() returns None rather than an
    Installed with both false.
    """

    defer: bool
    profile: bool


@dataclass(frozen=True, kw_only=True)
class Deferral:
    """One lazy proxy the shim handed out.

    importer is the module whose import statement was deferred, or None
    when it has no __name__, module the full dotted name it imports,
    and resolved whether the proxy has been used and the module loaded.
    """

    importer: str | None
    module: str
    resolved: bool


@dataclass(frozen=True, kw_only=True)
class Resolution:
    """A deferred proxy resolving, as on_resolve() callbacks receive it.

    importer and module say which deferral resolved, as in Deferral.
    load_ms is the wall time the import took, and loaded whether the
    resolve loaded the module or found it already loaded by something
    else. thread is the thread that used the proxy. used_in, file and
    line locate the code that used it first: the importing module's
    __name__, the file and the line, each None when unknown.
    """

    importer: str | None
    module: str
    load_ms: float
    loaded: bool
    thread: threading.Thread
    used_in: str | None
    file: str | None
    line: int | None
