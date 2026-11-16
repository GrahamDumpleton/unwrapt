"""Python version gating and the record of what is installed.

This module must stay importable with the standard library only: it is
imported at module level by unwrapt/__init__.py, which must not import
wrapt or install anything, since the build backend imports the package
to read the version. The install state lives here rather than in the
hook modules so is_installed() can be answered without importing them.
"""

import sys

# Callable is needed only for annotations, and importing collections.abc
# would load collections into every process that imports unwrapt, so it
# is imported for type checkers alone and the annotations are strings.

TYPE_CHECKING = False

if TYPE_CHECKING:
    from collections.abc import Callable

# PEP 810 lazy imports are provided natively from Python 3.15.
NATIVE_LAZY_IMPORTS = (3, 15)

# Which of the two layers are installed in this process: the shim that
# defers, and the recorder that profiles. Written by the installers and
# the removers, never by anything else.

_defer_installed = False
_profile_installed = False

# The on_resolve() subscribers, as a tuple replaced whole on each
# change, so a resolve in one thread can read it while another thread
# subscribes. They live here rather than with the shim so subscribing
# never imports wrapt.

_resolve_subscribers: "tuple[Callable[..., object], ...]" = ()


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


def resolve_subscribers() -> "tuple[Callable[..., object], ...]":
    """The on_resolve() callbacks, in the order they subscribed."""

    return _resolve_subscribers


def subscribe(callback: "Callable[..., object]") -> "Callable[[], None]":
    """Add an on_resolve() callback, returning the function that removes it.

    Removing it twice, or after it was removed some other way, does
    nothing.
    """

    global _resolve_subscribers

    _resolve_subscribers = (*_resolve_subscribers, callback)

    def unsubscribe() -> None:
        """Stop calling the callback when a deferred proxy resolves."""

        global _resolve_subscribers

        subscribers = list(_resolve_subscribers)

        if callback in subscribers:
            subscribers.remove(callback)
            _resolve_subscribers = tuple(subscribers)

    return unsubscribe
