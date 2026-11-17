"""The configuration: the file, its search, and the environment overrides.

The configuration says what to defer and how a profile report is
written. It never switches deferral or profiling on: the caller decides
that. It comes from a TOML file (unwrapt.toml, or the [tool.unwrapt]
table of a pyproject.toml), or from a JSON file of deferrals alone,
found by find_config() and parsed by load_config(), and the autowrapt
bootstrap lets UNWRAPT_* environment variables override the file's
values.

Both hooks read their configuration from here, and the shim consults
the candidate check here on every import call, so nothing in this
module may import wrapt or do anything expensive at module level.
tomllib and json are imported only when a file of that kind is read,
because an already imported module can never be deferred in that
process, and tomllib brings datetime and re with it. Nothing here
installs anything either.
"""

import os
import sys
import warnings
from collections.abc import Collection, Container, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from unwrapt._compat import has_native_lazy_imports


class ConfigError(Exception):
    """An unwrapt configuration that cannot be used.

    Raised by find_config() and load_config() for a file that cannot be
    read or parsed, and by Config and ProfileOptions for a value of the
    wrong type or out of range. The message names the file when there
    is one. install_from_env() turns it into a warning and starts the
    process without the file, so the bootstrap never stops start-up.
    """


class ConfigWarning(UserWarning):
    """A warning about an unwrapt configuration problem.

    Every warning of this kind is followed by carrying on without the
    value or file at fault, so the host application always starts.
    """


ProfileFormat = Literal["text", "json"]


@dataclass(frozen=True, kw_only=True)
class ProfileOptions:
    """How a profile report is written, when one is asked for.

    output is the path the report is written to, with %p expanding to
    the process id, or None for stderr. A relative output read from a
    configuration file is resolved against the file's directory when
    the file is loaded. format is "text" or "json". min_ms hides text
    candidate rows whose cumulative time is below it, and packages,
    when set, restricts the text candidate rows to importers under the
    named top-level packages; both are display filters only. An empty
    packages sequence is the same as None.
    """

    output: str | None = None
    format: ProfileFormat = "text"
    min_ms: float = 0.0
    packages: Sequence[str] | None = None

    def __post_init__(self) -> None:
        """Validate the values and normalise packages to a tuple."""

        output: object = self.output

        if output is not None and not isinstance(output, str):
            raise ConfigError("profile output must be a path string")

        if self.format not in ("text", "json"):
            raise ConfigError(
                f"profile format must be 'text' or 'json', not {self.format!r}"
            )

        min_ms: object = self.min_ms

        if isinstance(min_ms, bool) or not isinstance(min_ms, (int, float)):
            raise ConfigError(f"profile min_ms must be a number, not {min_ms!r}")

        if not min_ms >= 0.0:
            raise ConfigError(f"profile min_ms must not be negative, not {min_ms!r}")

        object.__setattr__(self, "min_ms", float(min_ms))

        packages: object = self.packages

        if packages is not None:
            if (
                isinstance(packages, str)
                or not isinstance(packages, Sequence)
                or not all(isinstance(package, str) for package in packages)
            ):
                raise ConfigError("profile packages must be a list of package names")

            object.__setattr__(self, "packages", tuple(packages) or None)


@dataclass(frozen=True, kw_only=True)
class Config:
    """What to defer, and how a profile report is written.

    lazy_modules maps an importer module name to the module names to
    defer in that importer, on every Python version. config_only
    ignores each module's own __lazy_modules__ below Python 3.15, so
    only lazy_modules is consulted. debug logs the active mode and each
    deferred import to stderr. profile holds the report options. path
    is the file the configuration was loaded from, or None.

    The values of lazy_modules may be any collection of names other
    than a string, and are stored as frozensets. A Config never
    switches deferral or profiling on: the caller decides that.
    """

    lazy_modules: Mapping[str, Collection[str]] = field(default_factory=dict)
    config_only: bool = False
    debug: bool = False
    profile: ProfileOptions = field(default_factory=ProfileOptions)
    path: str | None = None

    def __post_init__(self) -> None:
        """Validate the values and normalise lazy_modules."""

        for name in ("config_only", "debug"):
            if not isinstance(getattr(self, name), bool):
                raise ConfigError(f"{name} must be true or false")

        profile: object = self.profile

        if not isinstance(profile, ProfileOptions):
            raise ConfigError("profile must be a ProfileOptions")

        lazy_modules: object = self.lazy_modules

        if not isinstance(lazy_modules, Mapping):
            raise ConfigError(
                "lazy_modules must map importer names to lists of module names"
            )

        normalised: dict[str, frozenset[str]] = {}

        for importer, names in lazy_modules.items():
            if (
                not isinstance(importer, str)
                or isinstance(names, str)
                or not isinstance(names, Collection)
                or not all(isinstance(name, str) for name in names)
            ):
                raise ConfigError(
                    f"lazy_modules entry {importer!r} must be a list of module names"
                )

            normalised[importer] = frozenset(names)

        object.__setattr__(self, "lazy_modules", normalised)


_TOP_LEVEL_KEYS = frozenset({"config_only", "debug", "lazy_modules", "profile"})
_PROFILE_KEYS = frozenset({"output", "format", "min_ms", "packages"})

_TRUE_FLAGS = frozenset({"1", "true", "yes", "on"})
_FALSE_FLAGS = frozenset({"", "0", "false", "no", "off"})


def find_config() -> str | None:
    """Locate the configuration file, or return None when there is none.

    The precedence chain, the first source found winning outright, with
    sources never merged:

    1. The path in the UNWRAPT_CONFIG environment variable. It is
       returned even when the file does not exist, so that loading it
       fails loudly rather than silently falling through to a lower
       source.

    2. unwrapt.toml in the current directory.

    3. pyproject.toml in the current directory, when it has a
       [tool.unwrapt] table.

    The pyproject.toml bytes are checked for "[tool.unwrapt" before the
    file is parsed, so a process whose pyproject.toml has no unwrapt
    table never imports tomllib. The table form is therefore required:
    a dotted tool.unwrapt key outside a [tool.unwrapt] header is not
    found. Raises ConfigError when a pyproject.toml that passes the
    byte check cannot be read or parsed.
    """

    nominated = os.environ.get("UNWRAPT_CONFIG")

    if nominated:
        return nominated

    if os.path.isfile("unwrapt.toml"):
        return "unwrapt.toml"

    if os.path.isfile("pyproject.toml") and _has_unwrapt_table("pyproject.toml"):
        return "pyproject.toml"

    return None


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load the configuration file at path into a Config.

    With no path, the file is the one find_config() locates, and with
    nothing found the result is the default Config. A file named
    pyproject.toml contributes its [tool.unwrapt] table, a file ending
    in .json is the JSON form holding only the deferrals, and any other
    file is TOML whose whole content is the configuration. Raises
    ConfigError for a file that is missing, unreadable or malformed,
    and for any key or value the format does not allow.
    """

    if path is None:
        path = find_config()

        if path is None:
            return Config()

    location = os.fspath(path)

    if os.path.splitext(location)[1].lower() == ".json":
        return _load_json(location)

    document = _read_toml(location)

    if os.path.basename(location) == "pyproject.toml":
        tool = document.get("tool", {})
        table = tool.get("unwrapt") if isinstance(tool, dict) else None

        if not isinstance(table, dict):
            raise ConfigError(f"{location} has no [tool.unwrapt] table")

        return _config_from(table, location, "[tool.unwrapt]")

    return _config_from(document, location, "the file")


def config_from_env() -> Config:
    """The configuration the autowrapt bootstrap uses.

    The file comes from load_config(), and UNWRAPT_CONFIG_ONLY,
    UNWRAPT_DEBUG and the UNWRAPT_PROFILE_* variables, when set,
    override its values. Never raises: a file that cannot be used warns
    and is left out, and an invalid variable warns and is ignored,
    because a configuration mistake must never stop the host
    application from starting.
    """

    try:
        config = load_config()
    except ConfigError as exc:
        _warn(f"{exc}: continuing without the configuration file")

        config = Config()

    overrides: dict[str, Any] = {}

    for name, key in (
        ("UNWRAPT_CONFIG_ONLY", "config_only"),
        ("UNWRAPT_DEBUG", "debug"),
    ):
        flag = env_flag(name)

        if flag is not None:
            overrides[key] = flag

    profile = replace(config.profile, **_profile_overrides())

    return replace(config, profile=profile, **overrides)


def env_flag(name: str) -> bool | None:
    """Read a boolean environment variable, or None when it is not set.

    1/true/yes/on are true and an empty value or 0/false/no/off is
    false, case insensitively. Anything else warns once and reads as
    not set.
    """

    value = os.environ.get(name)

    if value is None:
        return None

    normalized = value.strip().lower()

    if normalized in _TRUE_FLAGS:
        return True

    if normalized in _FALSE_FLAGS:
        return False

    _warn(f"{name}={value!r} is not a valid boolean value: treating it as not set")

    return None


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


def is_candidate(name: str, globals: Mapping[str, object], config: Config) -> bool:
    """Whether the import of name into globals is marked deferrable.

    The configuration's lazy_modules applies on every Python version.
    The importing module's own __lazy_modules__ is consulted only below
    Python 3.15, where unwrapt emulates it: from 3.15 the interpreter
    handles __lazy_modules__ natively and unwrapt never reads it. With
    config_only set, only lazy_modules is consulted, on any version.

    __lazy_modules__ is read at call time, from the importing module's
    own globals, so as in PEP 810 it must be assigned before the
    imports it governs. A list, tuple, set, frozenset or dict works:
    membership is tested with `in`. A plain string is treated as
    absent, and so is anything that does not support membership
    testing.
    """

    importer = globals.get("__name__")

    if isinstance(importer, str):
        deferred = config.lazy_modules.get(importer)

        if deferred is not None and name in deferred:
            return True

    if config.config_only or has_native_lazy_imports():
        return False

    lazy_modules = globals.get("__lazy_modules__")

    if isinstance(lazy_modules, str) or not isinstance(lazy_modules, Container):
        return False

    return name in lazy_modules


def _has_unwrapt_table(path: str) -> bool:
    """Whether the pyproject.toml at path has a [tool.unwrapt] table.

    The byte check comes first and settles the common case, a project
    with no unwrapt table, without importing tomllib. Only a file that
    mentions the table header is parsed, which also rules out a match
    such as [tool.unwrapt-extra] or one inside a comment.
    """

    try:
        with open(path, "rb") as fp:
            data = fp.read()
    except OSError as exc:
        raise ConfigError(f"{path} could not be read: {exc}") from exc

    if b"[tool.unwrapt" not in data:
        return False

    import tomllib

    try:
        document = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    tool = document.get("tool", {})

    return isinstance(tool, dict) and isinstance(tool.get("unwrapt"), dict)


def _read_toml(location: str) -> dict[str, Any]:
    """Parse the TOML file at location, raising ConfigError on failure."""

    import tomllib

    try:
        with open(location, "rb") as fp:
            return tomllib.load(fp)
    except FileNotFoundError:
        raise ConfigError(f"config file {location!r} does not exist") from None
    except OSError as exc:
        raise ConfigError(f"config file {location!r} could not be read: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {location!r} is not valid TOML: {exc}") from exc


def _config_from(document: dict[str, Any], location: str, table: str) -> Config:
    """Build a Config from a parsed TOML table.

    Unknown keys are errors rather than being ignored, so a misspelt
    key is reported instead of silently doing nothing. table names the
    table in messages: the file, or [tool.unwrapt] in a pyproject.toml.
    """

    unknown = sorted(set(document) - _TOP_LEVEL_KEYS)

    if unknown:
        raise ConfigError(
            f"{location}: unknown key {', '.join(map(repr, unknown))} in {table}"
        )

    profile_table = document.get("profile", {})

    if not isinstance(profile_table, dict):
        raise ConfigError(f"{location}: profile must be a table")

    unknown = sorted(set(profile_table) - _PROFILE_KEYS)

    if unknown:
        raise ConfigError(
            f"{location}: unknown key {', '.join(map(repr, unknown))}"
            " in the profile table"
        )

    # A relative output is relative to the file that names it, not to
    # whatever directory the process happens to start in. It is
    # normalised so a path written with forward slashes reads with the
    # platform's separators on Windows.

    output = profile_table.get("output")

    if isinstance(output, str) and not os.path.isabs(output):
        base = os.path.dirname(os.path.abspath(location))
        output = os.path.normpath(os.path.join(base, output))

    try:
        profile = ProfileOptions(
            output=output,
            format=profile_table.get("format", "text"),
            min_ms=profile_table.get("min_ms", 0.0),
            packages=profile_table.get("packages"),
        )

        return Config(
            lazy_modules=document.get("lazy_modules", {}),
            config_only=document.get("config_only", False),
            debug=document.get("debug", False),
            profile=profile,
            path=location,
        )
    except ConfigError as exc:
        raise ConfigError(f"{location}: {exc}") from None


def _load_json(location: str) -> Config:
    """Load the JSON form: an object of importer names to module lists.

    For example {"thirdparty.pkg.client": ["numpy", "pandas"]}. The JSON
    form holds only the deferrals; everything else takes its default.
    """

    import json

    try:
        with open(location, encoding="utf-8") as fp:
            data = json.load(fp)
    except FileNotFoundError:
        raise ConfigError(f"config file {location!r} does not exist") from None
    except OSError as exc:
        raise ConfigError(f"config file {location!r} could not be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file {location!r} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(
            f"config file {location!r} must be a JSON object mapping"
            " importer names to lists of module names"
        )

    try:
        return Config(lazy_modules=data, path=location)
    except ConfigError as exc:
        raise ConfigError(f"{location}: {exc}") from None


def _profile_overrides() -> dict[str, Any]:
    """The UNWRAPT_PROFILE_* variables that override the file's values.

    A variable that is unset or empty overrides nothing, and an invalid
    value warns and overrides nothing.
    """

    overrides: dict[str, Any] = {}

    output = os.environ.get("UNWRAPT_PROFILE_OUTPUT")

    if output:
        overrides["output"] = output

    value = os.environ.get("UNWRAPT_PROFILE_FORMAT")

    if value:
        normalized = value.strip().lower()

        if normalized in ("text", "json"):
            overrides["format"] = normalized
        else:
            _warn(f"UNWRAPT_PROFILE_FORMAT={value!r} is not text or json: ignoring it")

    value = os.environ.get("UNWRAPT_PROFILE_MIN_MS")

    if value:
        try:
            min_ms: float | None = float(value)
        except ValueError:
            min_ms = None

        if min_ms is None or not min_ms >= 0.0:
            _warn(
                f"UNWRAPT_PROFILE_MIN_MS={value!r} is not a non-negative"
                " number: ignoring it"
            )
        else:
            overrides["min_ms"] = min_ms

    value = os.environ.get("UNWRAPT_PROFILE_PACKAGES")

    if value:
        names = (package.strip() for package in value.split(","))
        packages = tuple(package for package in names if package)

        if packages:
            overrides["packages"] = packages

    return overrides


def _warn(message: str) -> None:
    """Emit one configuration warning on stderr; never raise."""

    warnings.warn(f"unwrapt: {message}", ConfigWarning, stacklevel=2)
