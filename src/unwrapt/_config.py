"""Environment variable parsing and the external JSON configuration.

Both hooks read their settings from here, and the shim consults the
candidate check here on every import call, so nothing in this module
may import wrapt or do anything expensive. Nothing here installs
anything either: reading settings has no side effects beyond a
warning for a bad value, because a configuration mistake must never
stop the host application from starting.
"""

import os
import sys
import warnings
from collections.abc import Container, Mapping
from dataclasses import dataclass, field

from unwrapt._compat import has_native_lazy_imports


class ConfigWarning(UserWarning):
    """A warning about an unwrapt configuration problem.

    Every warning of this kind is followed by falling back to a
    default, so the host application always starts.
    """


@dataclass(frozen=True)
class Settings:
    """The settings resolved from the environment for one install.

    config maps an importer module name to the set of module names the
    external JSON configuration marks as deferrable there. profile_min_ms
    hides low-cost rows from the text report's candidate list, and
    profile_packages, when set, restricts the candidate list to
    importers under the named top-level packages.
    """

    debug: bool = False
    config_only: bool = False
    profile: bool = False
    config_path: str | None = None
    config: Mapping[str, frozenset[str]] = field(default_factory=dict)
    profile_output: str | None = None
    profile_format: str = "text"
    profile_min_ms: float = 0.0
    profile_packages: tuple[str, ...] | None = None


_TRUE_FLAGS = frozenset({"1", "true", "yes", "on"})
_FALSE_FLAGS = frozenset({"", "0", "false", "no", "off"})


def read_settings() -> Settings:
    """Resolve every UNWRAPT_* environment variable into Settings.

    Invalid values warn once and fall back to their default. The
    external configuration file, when UNWRAPT_CONFIG names one, is
    loaded here rather than at import time so that importing unwrapt
    stays inert.
    """

    config_path = os.environ.get("UNWRAPT_CONFIG") or None
    config = load_config(config_path) if config_path is not None else {}

    return Settings(
        debug=_env_flag("UNWRAPT_DEBUG"),
        config_only=_env_flag("UNWRAPT_CONFIG_ONLY"),
        profile=_env_flag("UNWRAPT_PROFILE"),
        config_path=config_path,
        config=config,
        profile_output=os.environ.get("UNWRAPT_PROFILE_OUTPUT") or None,
        profile_format=_profile_format(),
        profile_min_ms=_profile_min_ms(),
        profile_packages=_profile_packages(),
    )


def load_config(path: str) -> dict[str, frozenset[str]]:
    """Load the external JSON configuration file at path.

    The file maps an importer module name to a list of the module names
    to defer in that importer, for example:

    {"thirdparty.pkg.client": ["numpy", "pandas"]}

    A missing, unreadable or malformed file warns once and yields an
    empty mapping: unwrapt must not stop the host application from
    starting. Within a valid file, entries that are not shaped as
    described are skipped with a warning and the rest are kept.
    """

    # json is imported here rather than at module level so that reading
    # settings never preloads a module an application might want to
    # defer: an already imported module is returned unchanged by the
    # hook, so anything unwrapt itself loads early can never be
    # deferred in that process.

    import json

    try:
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
    except FileNotFoundError:
        _warn(f"UNWRAPT_CONFIG file {path!r} does not exist: continuing without it")

        return {}
    except OSError as exc:
        _warn(f"UNWRAPT_CONFIG file {path!r} could not be read: {exc}")

        return {}
    except json.JSONDecodeError as exc:
        _warn(f"UNWRAPT_CONFIG file {path!r} is not valid JSON: {exc}")

        return {}

    if not isinstance(data, dict):
        _warn(
            f"UNWRAPT_CONFIG file {path!r} must be a JSON object mapping"
            " importer names to lists of module names: continuing without it"
        )

        return {}

    config: dict[str, frozenset[str]] = {}
    invalid: list[str] = []

    for importer, names in data.items():
        if (
            not isinstance(importer, str)
            or not isinstance(names, list)
            or not all(isinstance(name, str) for name in names)
        ):
            invalid.append(repr(importer))

            continue

        config[importer] = frozenset(names)

    if invalid:
        _warn(
            f"ignored UNWRAPT_CONFIG entries for {', '.join(sorted(invalid))}:"
            " each key must be an importer name and each value a list of"
            " module names"
        )

    return config


def is_native_pending(name: str) -> bool:
    """Whether a native lazy binding for name is still pending.

    Only meaningful on Python 3.15 and later, where sys.lazy_modules is
    the interpreter's registry of declared-but-not-yet-resolved lazy
    imports: a name is in it from the moment its statement is deferred
    until first use. unwrapt never adds to or removes from the registry;
    it reads it for one purpose. On 3.15 a name declared in a module's
    __lazy_modules__ reaches the hook only when native reifies it, at
    first use, and by then it is in this registry, so the registry is
    how the hook recognises a native reification call (which it must
    pass through: native expects the real module back) without ever
    reading the importer's own __lazy_modules__.

    Below 3.15 the attribute does not exist and this is always False.
    """

    pending = getattr(sys, "lazy_modules", None)

    if not isinstance(pending, (set, frozenset)):
        return False

    return name in pending


def is_candidate(name: str, globals: Mapping[str, object], settings: Settings) -> bool:
    """Whether the import of name into globals is marked deferrable.

    The external configuration applies on every Python version. The
    importing module's own __lazy_modules__ is consulted only below
    Python 3.15, where unwrapt emulates it: from 3.15 the interpreter
    handles __lazy_modules__ natively and unwrapt never reads it. With
    UNWRAPT_CONFIG_ONLY set, only the external configuration is
    consulted, on any version.

    __lazy_modules__ is read at call time, from the importing module's
    own globals, so as in PEP 810 it must be assigned before the
    imports it governs. A list, tuple, set, frozenset or dict works:
    membership is tested with `in`. A plain string is treated as
    absent, and so is anything that does not support membership
    testing.
    """

    importer = globals.get("__name__")

    if isinstance(importer, str):
        deferred = settings.config.get(importer)

        if deferred is not None and name in deferred:
            return True

    if settings.config_only or has_native_lazy_imports():
        return False

    lazy_modules = globals.get("__lazy_modules__")

    if isinstance(lazy_modules, str) or not isinstance(lazy_modules, Container):
        return False

    return name in lazy_modules


def _env_flag(name: str) -> bool:
    """Read a boolean environment variable: 1/true/yes/on, case insensitive.

    An unset variable is false. An empty value or 0/false/no/off is
    false. Anything else warns once and reads as false.
    """

    value = os.environ.get(name)

    if value is None:
        return False

    normalized = value.strip().lower()

    if normalized in _TRUE_FLAGS:
        return True

    if normalized not in _FALSE_FLAGS:
        _warn(f"{name}={value!r} is not a valid boolean value: treating it as not set")

    return False


def _profile_format() -> str:
    """Read UNWRAPT_PROFILE_FORMAT: text (the default) or json."""

    value = os.environ.get("UNWRAPT_PROFILE_FORMAT") or "text"
    normalized = value.strip().lower()

    if normalized not in ("text", "json"):
        _warn(f"UNWRAPT_PROFILE_FORMAT={value!r} is not text or json: using text")

        return "text"

    return normalized


def _profile_min_ms() -> float:
    """Read UNWRAPT_PROFILE_MIN_MS: hide cheaper candidate rows."""

    value = os.environ.get("UNWRAPT_PROFILE_MIN_MS")

    if value is None:
        return 0.0

    try:
        min_ms = float(value)
    except ValueError:
        _warn(f"UNWRAPT_PROFILE_MIN_MS={value!r} is not a number: hiding nothing")

        return 0.0

    if min_ms < 0.0:
        _warn(f"UNWRAPT_PROFILE_MIN_MS={value!r} is negative: hiding nothing")

        return 0.0

    return min_ms


def _profile_packages() -> tuple[str, ...] | None:
    """Read UNWRAPT_PROFILE_PACKAGES: restrict candidates to these roots."""

    value = os.environ.get("UNWRAPT_PROFILE_PACKAGES")

    if value is None:
        return None

    packages = tuple(package.strip() for package in value.split(","))
    packages = tuple(package for package in packages if package)

    return packages or None


def _warn(message: str) -> None:
    """Emit one configuration warning on stderr; never raise."""

    warnings.warn(f"unwrapt: {message}", ConfigWarning, stacklevel=2)
