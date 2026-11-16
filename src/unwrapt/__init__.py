"""
unwrapt defers whole-module imports until first use, without changing
application code.

On Pythons below 3.15 it emulates the __lazy_modules__ mechanism of
PEP 810 by replacing builtins.__import__ with a hook that returns a
lazy proxy for each marked import. From Python 3.15, where the
interpreter provides the mechanism natively, it applies only an
external configuration of extra deferrals. It is built on wrapt,
designed to be injected with autowrapt, and has a profile mode that
reports what an application's imports cost and what is worth
deferring.

Importing this package must stay inert: it installs nothing and
imports nothing beyond the standard library. The build backend imports
it to read the version, and importing it at any time must have no
effect on the running process. install() is the entry point that does
the work.
"""


def _format_version(parts: tuple[str, ...]) -> str:
    base = ".".join(parts[:3])

    if len(parts) == 3:
        return base

    suffix = parts[3]
    return (
        f"{base}.{suffix}" if suffix.startswith(("dev", "post")) else f"{base}{suffix}"
    )


__version_info__: tuple[str, ...] = ("1", "0", "0", "a1")
__version__ = _format_version(__version_info__)

import sys

from unwrapt._compat import installed_layers, is_installed, subscribe

# The configuration API is typed for checkers through this block, which
# never runs. TYPE_CHECKING is defined here rather than imported from
# typing, so that importing unwrapt does not load typing into every
# bootstrapped process.

TYPE_CHECKING = False

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from unwrapt._config import (
        Config,
        ConfigError,
        ProfileOptions,
        find_config,
        load_config,
    )
    from unwrapt._records import Deferral, Installed, Resolution
    from unwrapt._report import Report

# The configuration API lives in unwrapt._config, the record types in
# unwrapt._records and the Report in unwrapt._report, all of which pull
# in dataclasses and more, so they are loaded on first access through
# the module __getattr__ below rather than here: importing unwrapt must
# stay inert.

_LAZY_NAMES = {
    "Config": "unwrapt._config",
    "ConfigError": "unwrapt._config",
    "ProfileOptions": "unwrapt._config",
    "find_config": "unwrapt._config",
    "load_config": "unwrapt._config",
    "Deferral": "unwrapt._records",
    "Installed": "unwrapt._records",
    "Resolution": "unwrapt._records",
    "Report": "unwrapt._report",
}


def __getattr__(name: str) -> object:
    """Load the configuration API, record types and Report on first access."""

    module_name = _LAZY_NAMES.get(name)

    if module_name is not None:
        import importlib

        return getattr(importlib.import_module(module_name), name)

    raise AttributeError(f"module 'unwrapt' has no attribute {name!r}")


def install(
    config: "Config | None" = None,
    *,
    defer: bool = True,
    profile: bool = False,
) -> bool:
    """Install unwrapt's import layers for this process.

    What it is given is what happens: it reads no environment variable,
    except UNWRAPT_CONFIG through load_config() when no config is
    given. With no config, the configuration comes from load_config(),
    which raises ConfigError for a file that cannot be used.

    defer and profile are independent. defer installs the shim, which
    defers the imports marked by each module's own __lazy_modules__
    and by the configuration's lazy_modules below Python 3.15, and
    only lazy_modules from 3.15, where it installs nothing when that
    has no entries. profile installs the recorder, above the shim when
    both are on, so the profile measures the program with its
    deferrals in place; with defer off it measures an eager run. The
    report is written at exit unless stop_profile() is called first.

    Calling it while unwrapt is installed returns False and changes
    nothing; uninstall() first to install again.

    Returns True when this call installed a layer, False when unwrapt
    was already installed or there was nothing to install.
    """

    if is_installed():
        return False

    if config is None:
        from unwrapt._config import load_config

        config = load_config()

    shim_local = None

    if defer:
        from unwrapt import _hook

        _hook.install_shim(config)

        shim = _hook.current()
        shim_local = shim.local if shim is not None else None

    if profile:
        from unwrapt import _profile

        _profile.install_profile(config, shim_local)

        # The recorder also times each deferred proxy's resolve, so the
        # imports a deferred module makes when it loads nest beneath it.

        recorder = _profile.current()

        if shim_local is not None and recorder is not None:
            _hook.set_tracer(recorder)

    return is_installed()


def install_from_env() -> bool:
    """Install unwrapt as the autowrapt bootstrap does.

    The configuration comes from load_config(), with
    UNWRAPT_CONFIG_ONLY, UNWRAPT_DEBUG and the UNWRAPT_PROFILE_*
    variables overriding the file's values. UNWRAPT_PROFILE sets
    profile, and UNWRAPT_DEFER sets defer, which defaults to off when
    UNWRAPT_PROFILE is set and to on otherwise: UNWRAPT_PROFILE=1 alone
    is an eager profile for finding candidates, and adding
    UNWRAPT_DEFER=1 profiles the program with its deferrals in place.
    Then install() does the rest.

    Never stops start-up: a configuration file that cannot be used,
    or an invalid environment variable, warns on stderr and is left
    out.

    Returns True when this call installed a layer, False when unwrapt
    was already installed or there was nothing to install.
    """

    from unwrapt import _config

    config = _config.config_from_env()

    if config.debug and config.path is not None:
        print(f"unwrapt: configuration read from {config.path}", file=sys.stderr)

    profile = _config.env_flag("UNWRAPT_PROFILE") is True
    defer = _config.env_flag("UNWRAPT_DEFER")

    if defer is None:
        defer = not profile

    return install(config, defer=defer, profile=profile)


def stop_profile(*, write: bool = True) -> "Report | None":
    """Stop the recorder, leave deferral in place, and return the report.

    Only the recorder is taken out: the shim, when installed, carries
    on deferring. The import function below the recorder is put back
    only when the recorder is still the current builtins.__import__;
    otherwise the recorder stays in the chain as plain pass-through, so
    it never removes a wrapper installed over it. The exit handler that
    would write the report at exit is unregistered.

    With write set, the report also goes where the profile options
    say: to the output path, or to stderr. A failure to write is
    reported on stderr, and the report is still returned. The Report
    is versioned data: to_dict() is the JSON schema, and labels can be
    added to it before it is rendered or stored.

    Returns None when no recorder is installed.
    """

    if not installed_layers()[1]:
        return None

    from unwrapt._profile import stop_profile as _stop_profile

    return _stop_profile(write)


def uninstall() -> bool:
    """Take out both of unwrapt's layers, and clear the installed state.

    The recorder is stopped without writing its report, then the shim
    is taken out. Each layer puts back the import function below it
    only when it is still the current builtins.__import__; otherwise it
    stays in the chain as plain pass-through, so a wrapper installed
    over unwrapt is never removed. Proxies already handed out keep
    working. install() can run again afterwards.

    Returns True when anything was installed.
    """

    defer, profile = installed_layers()

    if profile:
        from unwrapt._profile import stop_profile as _stop_profile

        _stop_profile(False)

    if defer:
        from unwrapt._hook import uninstall_shim

        uninstall_shim()

    return defer or profile


def scope(**labels: str) -> "AbstractContextManager[object]":
    """A context manager labelling the imports made inside it.

    Each edge the recorder records carries the labels in force when its
    statement ran, so a report can say which entry point needed which
    module: with unwrapt.scope(entrypoint="hooks"): ... The labels are
    process wide, not per thread, and nested scopes merge, the inner
    value winning. Values must be strings. Scoping works whether or not
    anything is installed, and costs next to nothing.
    """

    from unwrapt._labels import Scope

    return Scope(dict(labels))


def push_scope(**labels: str) -> object:
    """Bring labels into force until pop_scope() is given the result.

    The same as entering scope(), for a caller that brackets work with
    two callbacks rather than one block.
    """

    from unwrapt._labels import push

    return push(dict(labels))


def pop_scope(token: object) -> None:
    """End the labels push_scope() brought into force.

    Scopes end in the reverse order they began: a token that is not the
    latest raises ValueError, and so does anything push_scope() did not
    return.
    """

    from unwrapt._labels import ScopeToken, pop

    if not isinstance(token, ScopeToken):
        raise ValueError("pop_scope() takes what push_scope() returned")

    pop(token)


def installed() -> "Installed | None":
    """Which layers are installed, or None when neither is."""

    defer, profile = installed_layers()

    if not (defer or profile):
        return None

    from unwrapt._records import Installed

    return Installed(defer=defer, profile=profile)


def deferred() -> "list[Deferral]":
    """List each lazy proxy the shim has handed out in this process.

    Each Deferral gives the importer, the module and whether the proxy
    has been resolved. It needs no recording, so a server can log what
    was deferred, and what of it was loaded anyway, with only deferral
    on. Proxies handed out before uninstall() are still listed. Empty
    when the shim has never been installed.
    """

    hook_module = sys.modules.get("unwrapt._hook")

    if hook_module is None:
        return []

    result: list[Deferral] = hook_module.deferred()

    return result


def on_resolve(callback: "Callable[[Resolution], object]") -> "Callable[[], None]":
    """Call callback each time a deferred proxy resolves.

    The callback receives a Resolution: the importer, the module, the
    time the load took, whether it loaded the module or found it
    already loaded, the thread, and where the proxy was first used. It
    runs in the thread that used the proxy, after the module is
    imported. It costs nothing until a proxy resolves, and then one
    call per subscriber. An exception from a callback is never raised
    into the code that used the proxy: it is reported as a
    RuntimeWarning on stderr.

    Returns a function that unsubscribes the callback.
    """

    return subscribe(callback)


__all__ = [
    "Config",
    "ConfigError",
    "Deferral",
    "Installed",
    "ProfileOptions",
    "Report",
    "Resolution",
    "__version__",
    "__version_info__",
    "deferred",
    "find_config",
    "install",
    "install_from_env",
    "installed",
    "is_installed",
    "load_config",
    "on_resolve",
    "pop_scope",
    "push_scope",
    "scope",
    "stop_profile",
    "uninstall",
]
