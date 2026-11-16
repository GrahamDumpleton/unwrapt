# Configuration

unwrapt has two kinds of setting. A configuration file says what to
defer and how a profile report is written. Environment variables,
read by the [autowrapt](autowrapt.md) bootstrap, switch profiling on
and override the file's values. Everything is optional: with no file
and no variables, unwrapt applies each module's own
`__lazy_modules__` below Python 3.15 and nothing else.

## The configuration file

`unwrapt.toml` holds the configuration as the whole file. In a
`pyproject.toml` the same keys go under `[tool.unwrapt]`:

```toml
[tool.unwrapt]
config_only = false     # ignore modules' own __lazy_modules__ (below 3.15)
debug = false

[tool.unwrapt.lazy_modules]           # extra lazy targets: importer -> modules
"thirdparty.pkg.client" = ["numpy", "pandas"]

[tool.unwrapt.profile]                # how a report is written, when one is asked for
output = "unwrapt-%p.txt"             # relative to the config file's directory
format = "text"
min_ms = 1.0
packages = ["shop"]
```

`config_only` = true | false

: Ignore each module's own `__lazy_modules__` and use only
`lazy_modules`. An A/B switch for experiments, on any Python version.
On 3.15 the behaviour is always configuration-only, so the key makes
no difference there. The default is false.

`debug` = true | false

: Log to stderr the file the configuration was read from, the active
mode at startup, and each deferred import as it happens:

  ```
  unwrapt: configuration read from pyproject.toml
  unwrapt: shim mode installed
  unwrapt: deferring 'xml.dom' in myapp.web
  ```

  On 3.15 with no `lazy_modules` entries the debug line says there is
  nothing to do, and there is no warning: that case is normal, not a
  problem. The default is false.

`[lazy_modules]`

: Imports to defer in modules whose source you do not control: each
key is an importer's module name and each value the list of module
names to defer there. See the
[external configuration](external-config.md) page for the rules. On
Python 3.15 and later this is the only candidate source, and having
entries is what activates unwrapt there: with none, unwrapt installs
nothing. See [Python 3.15](python-3-15.md).

`[profile]`

: How a [profile report](profile-mode.md) is written, when one is
asked for:

  - `output`: the path the report is written to, with `%p` expanding
    to the process id. A relative path is relative to the directory
    of the configuration file. Without it the report goes to stderr.

  - `format`: `"text"` (the default) or `"json"`.

  - `min_ms`: hide text candidate rows whose cumulative time is below
    this many milliseconds. The JSON keeps every edge; this is a
    display filter.

  - `packages`: restrict the text report's candidate rows to importers
    under these top-level packages, treating the rest as not editable.
    An empty list is the same as leaving it out.

The file never switches deferral or profiling on: the caller decides
that. A `[profile]` table left in a `pyproject.toml` therefore never
makes every process in the directory write a report.

### Where the file is found

The first source found wins, and sources are never merged:

1. The path in `UNWRAPT_CONFIG`. It is used even when the file does
   not exist, so that the mistake is reported rather than silently
   falling through to another file.

2. `unwrapt.toml` in the current directory.

3. `pyproject.toml` in the current directory, if it has a
   `[tool.unwrapt]` table.

Finding no configuration is not a warning: unwrapt is useful without
one.

Before parsing a `pyproject.toml`, unwrapt checks the file's bytes for
`[tool.unwrapt`, so a process whose `pyproject.toml` has no unwrapt
table never loads the TOML parser and the modules it brings in, which
would otherwise be preloaded and impossible to defer. The table form
is therefore required: write `[tool.unwrapt]` or a
`[tool.unwrapt.lazy_modules]` style header. A dotted
`tool.unwrapt.debug = true` key, or an `unwrapt.debug` key inside a
`[tool]` table, is not found.

### The JSON form

A file named by `UNWRAPT_CONFIG` whose name ends in `.json` is read as
JSON, the form that holds only the deferrals: an object mapping each
importer's module name to the list of module names to defer there,
the same as the `[lazy_modules]` table.

```json
{"thirdparty.pkg.client": ["numpy", "pandas"]}
```

Every other setting takes its default, or comes from the environment.

### Errors

The file is checked strictly: a file that is missing, unreadable or
malformed, an unknown key, and a value of the wrong type or out of
range are all errors, so a misspelt key is reported instead of doing
nothing. Through the bootstrap an error is a warning on stderr, and
the process starts without the file, because a configuration mistake
must never stop the host application from starting. Code that calls
`unwrapt.load_config()` itself gets a `ConfigError` instead; see the
[API](api.md).

## Environment variables

The [autowrapt](autowrapt.md) bootstrap, and `unwrapt.install()`
called with no arguments, read these. All of them are optional, and an
invalid value warns once on stderr and is ignored, leaving the file's
value or the default in place.

### Activation

Activation is not an environment variable of unwrapt's own:
`AUTOWRAPT_BOOTSTRAP=unwrapt` is read by
[autowrapt](autowrapt.md), the companion that injects unwrapt at
interpreter startup. unwrapt itself is activated by `unwrapt.install()`
or `unwrapt.install_from_env()`, described on the [API](api.md) page,
and importing the package is always inert.

### Shim mode

`UNWRAPT_CONFIG` = *path*

: The configuration file to use, in place of the search above. A path
ending in `.json` is the JSON form.

`UNWRAPT_CONFIG_ONLY` = 1

: Override the file's `config_only`.

`UNWRAPT_DEBUG` = 1

: Override the file's `debug`.

### Profile mode

Profile mode is documented on its own [page](profile-mode.md), with
the [strategy guide](choosing-what-to-defer.md) as the way to use its
report. The variables:

`UNWRAPT_PROFILE` = 1

: Enable profile mode: install the recording hook instead of the
shim hook. No deferral happens. The two modes are mutually exclusive
in one process, by design: profiling an already-deferred program
measures something different.

`UNWRAPT_PROFILE_OUTPUT` = *path*

: Override the `output` profile option. A relative path is relative
to the current directory. The path form is the recommended one:
worker process setups (a mod_wsgi daemon process, for example) may
not run exit handlers reliably, and one file per process, with `%p`
in the path, keeps concurrent workers from interleaving their reports.

`UNWRAPT_PROFILE_FORMAT` = text | json

: Override the `format` profile option. The JSON form is what the
[AI assistant procedure](ai-assisted-tuning.md) and the
`python -m unwrapt.report` tool consume.

`UNWRAPT_PROFILE_MIN_MS` = *n*

: Override the `min_ms` profile option.

`UNWRAPT_PROFILE_PACKAGES` = a,b

: Override the `packages` profile option, as a comma separated list.

The profile variables override nothing when they are empty.

### Booleans

The flag variables accept, case-insensitively, `1`, `true`, `yes` and
`on` as true, and an empty value, `0`, `false`, `no` and `off` as
false. Anything else warns once and is ignored.
