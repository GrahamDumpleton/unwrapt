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

# The mode of the hook installed in this process, "shim" or "profile",
# or None when no hook is installed. Written once, by the installer.
_installed_mode: str | None = None


def has_native_lazy_imports() -> bool:
    """Whether this interpreter provides PEP 810 lazy imports natively.

    Python 3.15 and later do: a `lazy import` statement, the module
    level `__lazy_modules__` list, and the sys.set_lazy_imports()
    controls. Below 3.15 none of it exists and unwrapt's shim emulates
    the `__lazy_modules__` part.
    """

    return sys.version_info >= NATIVE_LAZY_IMPORTS


def installed_mode() -> str | None:
    """Return the mode of the hook installed in this process.

    "shim" or "profile", or None when no hook is installed.
    """

    return _installed_mode


def is_installed() -> bool:
    """Whether an unwrapt hook is installed in this process."""

    return _installed_mode is not None


def mark_installed(mode: str) -> None:
    """Record that a hook of the given mode was installed.

    The installers call this once, after replacing builtins.__import__,
    so the flag never says installed for a hook that is not in place.
    """

    global _installed_mode

    _installed_mode = mode
