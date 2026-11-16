"""Python version gating and the record of what is installed.

This module must stay importable with the standard library only: it is
imported at module level by unwrapt/__init__.py, which must not import
wrapt or install anything, since the build backend imports the package
to read the version. The install state lives here rather than in the
hook modules so is_installed() can be answered without importing them.
"""

import sys

# PEP 810 lazy imports are provided natively from Python 3.15.
NATIVE_LAZY_IMPORTS = (3, 15)

# Which of the two layers are installed in this process: the shim that
# defers, and the recorder that profiles. Written by the installers and
# the removers, never by anything else.

_defer_installed = False
_profile_installed = False


def has_native_lazy_imports() -> bool:
    """Whether this interpreter provides PEP 810 lazy imports natively.

    Python 3.15 and later do: a `lazy import` statement, the module
    level `__lazy_modules__` list, and the sys.set_lazy_imports()
    controls. Below 3.15 none of it exists and unwrapt's shim emulates
    the `__lazy_modules__` part.
    """

    return sys.version_info >= NATIVE_LAZY_IMPORTS


def installed_layers() -> tuple[bool, bool]:
    """Whether the shim and the recorder are installed, in that order."""

    return _defer_installed, _profile_installed


def is_installed() -> bool:
    """Whether an unwrapt layer, the shim or the recorder, is installed."""

    return _defer_installed or _profile_installed


def mark_defer(installed: bool) -> None:
    """Record whether the shim is installed.

    The shim's installer calls this after replacing builtins.__import__
    and its remover after taking it out, so the flag never says
    installed for a layer that is not in place.
    """

    global _defer_installed

    _defer_installed = installed


def mark_profile(installed: bool) -> None:
    """Record whether the recorder is installed, as mark_defer() does."""

    global _profile_installed

    _profile_installed = installed
