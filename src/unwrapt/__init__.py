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

from unwrapt._compat import is_installed

# The configuration API is typed for checkers through this block, which
# never runs. TYPE_CHECKING is defined here rather than imported from
# typing, so that importing unwrapt does not load typing into every
# bootstrapped process.

TYPE_CHECKING = False

if TYPE_CHECKING:
    from unwrapt._config import (
        Config,
        ConfigError,
        ProfileOptions,
        find_config,
        load_config,
    )

# The configuration API lives in unwrapt._config, which pulls in
# dataclasses and more, so it is loaded on first access through the
# module __getattr__ below rather than here: importing unwrapt must
# stay inert.

_CONFIG_NAMES = frozenset(
    {"Config", "ConfigError", "ProfileOptions", "find_config", "load_config"}
)


def __getattr__(name: str) -> object:
    """Load the configuration API on first access."""

    if name in _CONFIG_NAMES:
        from unwrapt import _config

        return getattr(_config, name)

    raise AttributeError(f"module 'unwrapt' has no attribute {name!r}")


def install_from_env() -> bool:
    """Install the unwrapt import hook as the autowrapt bootstrap does.

    The configuration comes from load_config(), with
    UNWRAPT_CONFIG_ONLY, UNWRAPT_DEBUG and the UNWRAPT_PROFILE_*
    variables overriding the file's values, and UNWRAPT_PROFILE picks
    the mode. With UNWRAPT_PROFILE set, the recording hook of profile
    mode is installed and no deferral happens: the two modes are
    mutually exclusive in one process. Otherwise the shim hook is
    installed, subject to the Python version rules described in the
    documentation: below 3.15 it defers imports marked by the
    importing module's own __lazy_modules__ and by the configuration's
    lazy_modules, and from 3.15, where the interpreter handles
    __lazy_modules__ natively, it applies only lazy_modules and
    installs nothing when there are no entries.

    Never stops start-up: a configuration file that cannot be used,
    or an invalid environment variable, warns on stderr and is left
    out.

    Returns True when this call installed a hook, False when one was
    already installed or there was nothing to install.
    """

    from unwrapt import _config
    from unwrapt._hook import install_shim
    from unwrapt._profile import install_profile

    config = _config.config_from_env()

    if config.debug and config.path is not None:
        print(f"unwrapt: configuration read from {config.path}", file=sys.stderr)

    if _config.env_flag("UNWRAPT_PROFILE"):
        return install_profile(config)

    return install_shim(config)


def install(module: object = None) -> bool:
    """Install the unwrapt import hook for this process.

    Reads the configuration and the mode from the environment exactly
    as install_from_env() does. Calling install() a second time does
    nothing, whatever mode was installed first.

    The module argument is ignored. It exists so the function can serve
    directly as a post import hook callback, which is handed the
    trigger module and carries no information.

    Returns True when this call installed a hook, False when one was
    already installed or there was nothing to install.
    """

    return install_from_env()


__all__ = [
    "Config",
    "ConfigError",
    "ProfileOptions",
    "__version__",
    "__version_info__",
    "find_config",
    "install",
    "install_from_env",
    "is_installed",
    "load_config",
]
