"""Shim mode: the lazy-aware replacement for builtins.__import__.

Below Python 3.15 the hook emulates PEP 810's __lazy_modules__ for
whole-module imports: it replaces builtins.__import__ with a plain
function (not a wrapt function wrapper, to keep the per-import cost
down, since every import statement in the process passes through it)
that returns a wrapt.LazyObjectProxy for each deferred import and
chains everything else to the import function it replaced, so import
wrappers installed before unwrapt keep working. From Python 3.15 the
interpreter handles __lazy_modules__ natively and the hook's only job
is the external configuration, in external-config-only mode: it
installs nothing when there is none.
"""

import builtins
import importlib
import sys
import types
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from typing import cast

import wrapt

from unwrapt._compat import (
    has_native_lazy_imports,
    is_installed,
    mark_installed,
)
from unwrapt._config import Settings, is_candidate, is_native_pending

# The import function that was installed when the hook went in. Every
# non-deferred call chains to it, so import wrappers installed before
# unwrapt (APM agents, coverage tools, anything else) keep working.

_original_import: Callable[..., types.ModuleType] | None = None

# The settings the hook was installed with.

_settings: Settings | None = None


def install_shim(settings: Settings) -> bool:
    """Install the shim hook, or decline to.

    Below Python 3.15 the hook defers imports marked in the importing
    module's own __lazy_modules__ and in the external configuration,
    either source being enough, unless UNWRAPT_CONFIG_ONLY restricts
    it to the configuration alone. From Python 3.15 the interpreter
    already handles __lazy_modules__, so the hook runs in
    external-config-only mode and defers only what the external
    configuration names; with no configuration there is nothing for
    unwrapt to do, so nothing is installed. That case is not a warning:
    running the bootstrap on 3.15 with no configuration is a normal,
    harmless setup.

    Returns True when this call installed the hook, False when a hook
    was already installed or there was nothing to install.
    """

    global _original_import, _settings

    if is_installed():
        return False

    if has_native_lazy_imports() and not settings.config:
        if settings.debug:
            print(
                "unwrapt: nothing to do on Python 3.15 or later without"
                " UNWRAPT_CONFIG: native lazy imports handle __lazy_modules__",
                file=sys.stderr,
            )

        return False

    _settings = settings
    _original_import = builtins.__import__
    builtins.__import__ = _lazy_aware_import
    mark_installed("shim")

    if settings.debug:
        if has_native_lazy_imports():
            mode = "external-config-only mode"
        elif settings.config_only:
            mode = "shim mode (external configuration only)"
        else:
            mode = "shim mode"

        print(f"unwrapt: {mode} installed", file=sys.stderr)

    return True


def _lazy_aware_import(
    name: str,
    globals: Mapping[str, object] | None = None,
    locals: Mapping[str, object] | None = None,
    fromlist: Sequence[str] | None = (),
    level: int = 0,
) -> types.ModuleType:
    """The shim hook: return a lazy proxy for a deferred import.

    An import is a deferral candidate only when the whole-module rules
    hold, cheapest checks first so the common pass-through path stays
    cheap:

    - level is 0: an absolute import.

    - fromlist is empty: a whole-module import. The eval loop passes
      None for a plain `import x` (and a tuple for `from x import y`),
      so emptiness rather than identity is the test, and a call made
      from Python with the argument omitted arrives as () which is
      empty too.

    - globals is not None, and locals is globals: a module level
      statement. Function bodies pass None for locals and class bodies
      pass the class namespace, so neither is deferred.

    - the module is not already in sys.modules: there is nothing left
      to defer.

    - the import is a candidate: named in the importing module's
      __lazy_modules__ or in the external configuration, per the
      version rules of the configuration module.

    One further rule applies on Python 3.15 and later, before the
    candidate check: a name with a pending native lazy binding is
    native's business and passes through. A __lazy_modules__ entry
    only reaches the hook at all when native reifies it, at first
    use, and deferring that call would hand native a lazy proxy
    where it expects the real module, so the hook recognises the
    reification by the pending binding in sys.lazy_modules and
    chains through. An explicit `lazy import` statement leaves no
    registry entry, so a config entry that duplicates one is not
    detectable; the documentation says not to write those.

    Everything else chains unchanged to the import function the hook
    replaced, so an import never behaves differently merely because
    unwrapt is installed.
    """

    if (
        _settings is not None
        and level == 0
        and not fromlist
        and globals is not None
        and locals is globals
        and name not in sys.modules
    ):
        if has_native_lazy_imports() and is_native_pending(name):
            if _settings.debug:
                importer = globals.get("__name__", "<unknown>")
                print(
                    f"unwrapt: leaving {name!r} in {importer} to native lazy imports",
                    file=sys.stderr,
                )
        elif is_candidate(name, globals, _settings):
            if _settings.debug:
                importer = globals.get("__name__", "<unknown>")
                print(f"unwrapt: deferring {name!r} in {importer}", file=sys.stderr)

            return _make_proxy(name, globals)

    assert _original_import is not None

    return _original_import(name, globals, locals, fromlist, level)


def _make_proxy(name: str, caller_globals: Mapping[str, object]) -> types.ModuleType:
    """Build the lazy proxy handed back for a deferred import.

    The proxy stands in for the top-level package the statement binds:
    `import a.b.c` binds a, so the proxy is returned for a while the
    resolve imports the full dotted name. On first use the proxy
    imports the module, reifies the importing module's namespace (see
    below) and returns the real module.

    The real import goes through importlib.import_module, which does
    not pass through builtins.__import__, so resolving a proxy can
    never be deferred again by the hook, on any Python version.

    The proxy presents as the module it stands in for. wrapt's own
    stubs type it honestly as LazyObjectProxy[ModuleType], not a
    ModuleType, so this is the one place the type system is told
    something that is not literally true, and the design confines the
    lie to this single cast. Every caller on the pass-through path
    receives a real module, and the proxy behaves as one through
    wrapt's ObjectProxy machinery: isinstance checks work because
    wrapt proxies __class__, which resolves the proxy as a side
    effect, the point of first use.
    """

    mutable_globals = cast(MutableMapping[str, object], caller_globals)

    def resolve() -> types.ModuleType:
        importlib.import_module(name)

        module = sys.modules[name.partition(".")[0]]

        # Reify: swap the proxy out of the importing namespace so the
        # module pays no further proxy overhead after first use. Only
        # the namespace of the module whose statement was deferred is
        # fixed; copies made before first use (an assignment to another
        # name, a from-import elsewhere) stay proxies and still work.

        for key, value in list(mutable_globals.items()):
            if value is proxy:
                mutable_globals[key] = module

        return module

    # The resolve closure refers to the proxy it reifies; it only runs
    # after this assignment, on first use.

    proxy = wrapt.LazyObjectProxy(resolve, interface=types.ModuleType)

    return cast(types.ModuleType, proxy)
