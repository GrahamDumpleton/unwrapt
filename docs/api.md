# API

The public API is small: the install functions, the configuration
types, and the version. Everything listed here is importable from the
`unwrapt` package itself, and importing it stays inert: the
configuration types load on first access.

## unwrapt.install

```python
unwrapt.install(module: object = None) -> bool
```

Install the unwrapt import hook for this process. It reads the
configuration and the mode exactly as `install_from_env()` does,
below. Calling it a second time does nothing, whatever mode was
installed first.

The `module` argument is ignored: it exists so the function can serve
directly as a post import hook callback, which is handed the trigger
module and carries no information.

Returns True when this call installed a hook, False when one was
already installed or there was nothing to install (Python 3.15 and
later with no `lazy_modules` entries).

## unwrapt.install_from_env

```python
unwrapt.install_from_env() -> bool
```

What the [autowrapt](autowrapt.md) bootstrap calls. The configuration
comes from `load_config()`, with `UNWRAPT_CONFIG_ONLY`,
`UNWRAPT_DEBUG` and the `UNWRAPT_PROFILE_*` variables overriding the
file's values, and `UNWRAPT_PROFILE` picks the mode: with it set, the
recording hook of [profile mode](profile-mode.md); otherwise the shim
hook, subject to the Python version rules on the
[how it works](how-it-works.md) page. See
[configuration](configuration.md) for every setting.

It never stops start-up: a configuration file that cannot be used,
or an invalid environment variable, warns on stderr and is left out.
The return value is the same as for `install()`.

## unwrapt.is_installed

```python
unwrapt.is_installed() -> bool
```

Whether an unwrapt hook, of either mode, is installed in this process.

## unwrapt.find_config

```python
unwrapt.find_config() -> str | None
```

The path of the configuration file, or None when there is none: the
path in `UNWRAPT_CONFIG`, returned even when the file does not exist,
then `unwrapt.toml` in the current directory, then `pyproject.toml` in
the current directory if it has a `[tool.unwrapt]` table. The first
source found wins. Raises `ConfigError` when a `pyproject.toml` that
mentions the table cannot be parsed. See
[where the file is found](configuration.md#where-the-file-is-found).

## unwrapt.load_config

```python
unwrapt.load_config(path: str | os.PathLike[str] | None = None) -> Config
```

Load the configuration file at `path`, or with no path the one
`find_config()` locates, into a `Config`. With nothing found it
returns the defaults. A file named `pyproject.toml` contributes its
`[tool.unwrapt]` table, a file ending in `.json` is the JSON form
holding only the deferrals, and any other file is TOML whose whole
content is the configuration. The TOML parser is imported only for a
TOML file.

Raises `ConfigError` for a file that is missing, unreadable or
malformed, and for any key or value the format does not allow. It
reads no environment variable other than `UNWRAPT_CONFIG`, through
`find_config()`, when no path is given.

## unwrapt.Config

```python
unwrapt.Config(
    *,
    lazy_modules: Mapping[str, Collection[str]] = {},
    config_only: bool = False,
    debug: bool = False,
    profile: ProfileOptions = ProfileOptions(),
    path: str | None = None,
)
```

The configuration, as a frozen dataclass: the keys of the
[configuration file](configuration.md#the-configuration-file), plus
`path`, the file it was loaded from. The values of `lazy_modules` may
be any collection of module names other than a string, and are stored
as frozensets. A `Config` can be built in code as well as loaded. It
never switches deferral or profiling on.

## unwrapt.ProfileOptions

```python
unwrapt.ProfileOptions(
    *,
    output: str | None = None,
    format: Literal["text", "json"] = "text",
    min_ms: float = 0.0,
    packages: Sequence[str] | None = None,
)
```

How a profile report is written, as a frozen dataclass: the `[profile]`
table of the configuration file. `packages` is stored as a tuple, and
an empty sequence as None. A relative `output` loaded from a file has
already been resolved against the file's directory.

## unwrapt.ConfigError

```python
class unwrapt.ConfigError(Exception)
```

A configuration that cannot be used. Raised by `find_config()` and
`load_config()`, and by `Config` and `ProfileOptions` for a value of
the wrong type or out of range. The message names the file when there
is one.

## The version

```python
unwrapt.__version__      # "1.0.0a1"
unwrapt.__version_info__  # ("1", "0", "0", "a1")
```

`__version_info__` is a tuple of strings, three numeric parts plus an
optional fourth: a fourth part starting with `dev` or `post` is joined
with a dot, any other is appended directly, three parts alone are the
plain version. To release, only `__version_info__` changes;
`__version__` is derived from it, and the packaging reads it from
there.

## What is deliberately not API

The hook itself, the proxy class, the profile recorder and the report
structures are implementation modules (underscore-prefixed, except the
autowrapt `bootstrap` entry point and the `report` command module) and
carry no stability promise before 1.0.0: none of them need importing
from outside, and `python -m unwrapt.report` is the supported entry
to the report tooling.
