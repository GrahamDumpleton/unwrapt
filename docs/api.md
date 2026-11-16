# API

The public API is small: the functions that install and remove the
layers, the configuration types, and the version. Everything listed here is importable from the
`unwrapt` package itself, and importing it stays inert: the
configuration types load on first access.

## unwrapt.install

```python
unwrapt.install(
    config: Config | None = None,
    *,
    defer: bool = True,
    profile: bool = False,
) -> bool
```

Install unwrapt's layers for this process. What it is given is what
happens: it reads no environment variable, except `UNWRAPT_CONFIG`
when it is given no `config` and finds the file through
`load_config()`, which raises `ConfigError` for a file that cannot be
used.

`defer` installs the shim and `profile` the
[profile mode](profile-mode.md) recorder, independently:

| `defer` | `profile` | Below 3.15 | 3.15 and later |
| --- | --- | --- | --- |
| on | off | The shim: each module's `__lazy_modules__` plus `lazy_modules` | The shim only if `lazy_modules` has entries, else nothing |
| off | on | A profile with nothing deferred | The same, with native lazy imports measured at first use |
| on | on | The recorder above the shim: a profile of the program with its deferrals | The same, with the shim only if there are entries |
| off | off | Nothing | Nothing |

The report of a profile is written at exit, where the configuration's
`[profile]` options say, unless `stop_profile()` is called first. The
shim, and with it wrapt, is imported only when the shim is installed.

Calling it while unwrapt is installed returns False and changes
nothing; `uninstall()` first to install again. Returns True when this
call installed a layer, False when unwrapt was already installed or
there was nothing to install.

## unwrapt.install_from_env

```python
unwrapt.install_from_env() -> bool
```

What the [autowrapt](autowrapt.md) bootstrap calls. The configuration
comes from `load_config()`, with `UNWRAPT_CONFIG_ONLY`,
`UNWRAPT_DEBUG` and the `UNWRAPT_PROFILE_*` variables overriding the
file's values. `UNWRAPT_PROFILE` sets `profile`, and `UNWRAPT_DEFER`
sets `defer`, which defaults to off when `UNWRAPT_PROFILE` is set and
to on otherwise. Then `install()` does the rest. See
[configuration](configuration.md) for every setting.

It never stops start-up: a configuration file that cannot be used,
or an invalid environment variable, warns on stderr and is left out.
The return value is the same as for `install()`.

## unwrapt.stop_profile

```python
unwrapt.stop_profile(*, write: bool = True) -> Report | None
```

Stop the recorder and return the profile report, leaving deferral in
place: the shim, when installed, carries on. The exit handler that
would write the report at exit is unregistered, so a process that
forks after calling it never has its workers write copies of the
report. With `write` set, the report also goes where the `[profile]`
options say, to the output path or to stderr; a failure to write is
reported on stderr and the report is still returned. Returns None
when no recorder is installed.

The report is the structure the JSON form of the report holds, as
described on [reading the report](reading-the-report.md#the-json-form).

## unwrapt.uninstall

```python
unwrapt.uninstall() -> bool
```

Take out both layers, the recorder without writing its report, and
clear the installed state, so `install()` can run again. Proxies
already handed out keep working. Returns True when anything was
installed.

Both `stop_profile()` and `uninstall()` put back the import function
below a layer only when the layer is still the current
`builtins.__import__`. When something has wrapped `builtins.__import__`
over unwrapt since, the layer stays in the chain as plain
pass-through instead, so a wrapper installed over unwrapt is never
removed.

## unwrapt.installed

```python
unwrapt.installed() -> Installed | None
```

Which layers are installed, as an `Installed(defer=..., profile=...)`,
or None when neither is.

## unwrapt.is_installed

```python
unwrapt.is_installed() -> bool
```

Whether either layer is installed in this process.

## unwrapt.deferred

```python
unwrapt.deferred() -> list[Deferral]
```

Each lazy proxy the shim has handed out in this process, in order, as
a `Deferral`: the importer whose statement was deferred, the module,
and whether the proxy has been resolved. It needs no recording, so a
server can log at the fork what was deferred and what of it was
loaded anyway, with only deferral on. Proxies handed out before
`uninstall()` are still listed, since they outlive the layer. Empty
when the shim has never been installed.

## unwrapt.on_resolve

```python
unwrapt.on_resolve(callback: Callable[[Resolution], object]) -> Callable[[], None]
```

Call `callback` each time a deferred proxy resolves, with a
`Resolution`. It runs in the thread that used the proxy, once the
module is imported. Subscribing costs nothing until a proxy resolves,
and then one call per subscriber. An exception from a callback is
never raised into the code that used the proxy: it is reported on
stderr as a `RuntimeWarning`, and the next callback still runs.
Returns a function that unsubscribes the callback; calling it again
does nothing.

The profile recorder, when it sits above the shim, records each
resolve as well: see [profile mode](profile-mode.md).

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

## unwrapt.Installed

```python
unwrapt.Installed(*, defer: bool, profile: bool)
```

Which layers are installed, as a frozen dataclass: `defer` is the
shim and `profile` the recorder.

## unwrapt.Deferral

```python
unwrapt.Deferral(*, importer: str | None, module: str, resolved: bool)
```

One proxy the shim handed out, as a frozen dataclass snapshot:
`importer` is the `__name__` of the module whose statement was
deferred, or None, `module` the full dotted name it imports, and
`resolved` whether the proxy has been used.

## unwrapt.Resolution

```python
unwrapt.Resolution(
    *,
    importer: str | None,
    module: str,
    load_ms: float,
    loaded: bool,
    thread: threading.Thread,
    used_in: str | None,
    file: str | None,
    line: int | None,
)
```

A deferred proxy resolving, as a frozen dataclass. `importer` and
`module` say which deferral resolved. `load_ms` is the wall time the
import took, and `loaded` whether it loaded the module or found it
already loaded by something else. `thread` is the thread that used the
proxy, so a server can tie the resolution to the request that caused
it. `used_in`, `file` and `line` locate the code that used it first:
the module's `__name__`, the file and the line, each None when
unknown.

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
