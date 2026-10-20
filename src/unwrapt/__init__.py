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

from unwrapt._compat import is_installed


def install(module: object = None) -> bool:
    """Install the unwrapt import hook for this process.

    The mode is chosen once, here, from the environment. With
    UNWRAPT_PROFILE set, the recording hook of profile mode is
    installed and no deferral happens: the two modes are mutually
    exclusive in one process by design, because profiling an
    already-deferred program measures something different. Otherwise
    the shim hook is installed, subject to the Python version rules
    described in the documentation: below 3.15 it defers imports
    marked by the importing module's own __lazy_modules__ and by the
    external configuration, and from 3.15, where the interpreter
    handles __lazy_modules__ natively, it applies only the external
    configuration and installs nothing when there is none.

    Calling install() a second time does nothing, whatever mode was
    installed first.

    The module argument is ignored. It exists so the function can serve
    directly as the autowrapt post import hook callback, which is
    handed the trigger module (os, per the entry point) and carries no
    information.

    Returns True when this call installed a hook, False when one was
    already installed or there was nothing to install.
    """

    from unwrapt import _config
    from unwrapt._hook import install_shim
    from unwrapt._profile import install_profile

    settings = _config.read_settings()

    if settings.profile:
        return install_profile(settings)

    return install_shim(settings)


__all__ = ["__version__", "__version_info__", "install", "is_installed"]
