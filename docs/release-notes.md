# Release notes

## Version 1.0.0

The first release series, in alpha ahead of the 1.0.0 final. Pre-releases
are published to [PyPI](https://pypi.org/project/unwrapt/); until the
final is out, a plain `pip install unwrapt` picks up the latest
pre-release automatically, and small changes are still possible.
Everything is new in this series, so rather than listing changes, see
the rest of the documentation, starting with
[getting started](getting-started.md). The pieces, at a glance:

- **Shim mode (Python 3.11 to 3.14):** whole-module imports named in a
  module's own `__lazy_modules__`, exactly as PEP 810 specifies, are
  deferred by an import hook built on wrapt, returning a lazy proxy
  that reifies into the importing module's namespace on first use.
  Activated with [autowrapt](autowrapt.md) or `unwrapt.install()`,
  chaining to whatever import wrappers were already installed.

- **External configuration:** a JSON file deferring imports in modules
  whose source you do not control, unioned with `__lazy_modules__`
  below 3.15.

- **Python 3.15 and later:** the interpreter owns the lazy import
  machinery; unwrapt applies only the external configuration, never
  reads `__lazy_modules__`, never alters native behaviour, and
  installs nothing without a configuration.

- **Profile mode:** records every import call of a real run, and
  reports candidates ranked by cumulative time, heavy modules by
  self time, per-importer cost, and the import chains with their best
  cuts, every row marked for both routes. Text or JSON, with a
  compare tool for two runs, a
  [strategy guide](choosing-what-to-defer.md) for turning the report
  into decisions, and an [AI assistant
  procedure](ai-assisted-tuning.md) for the same.

- The first pre-release of the series is `1.0.0a1`.

### Changes since 1.0.0a1

- **Python 3.11 is supported.** The shim, the external configuration
  and the profile mode now run on Python 3.11 as well, so writing
  `__lazy_modules__` gives lazy loading on every supported version
  with no change to the code: unwrapt emulates it from 3.11 to 3.14,
  and the interpreter handles it natively from 3.15.

- **The configuration is a TOML file, found as wrapture finds its
  own.** `unwrapt.toml` holds the whole configuration, and a
  `pyproject.toml` holds it under `[tool.unwrapt]`: `config_only`,
  `debug`, the `[lazy_modules]` deferrals, and a `[profile]` table
  saying how a report is written. The file never switches deferral or
  profiling on. It is found through `UNWRAPT_CONFIG`, then
  `unwrapt.toml`, then `pyproject.toml`, the first source winning, and
  a `.json` file named by `UNWRAPT_CONFIG` is still accepted as the
  form holding only the deferrals. See
  [configuration](configuration.md).

- **A configuration file is checked strictly.** An unknown key or a
  value of the wrong shape is an error rather than being skipped, so
  through the bootstrap a JSON file with one bad entry now warns and
  is left out whole, where before the bad entry alone was skipped.

- **New API:** `unwrapt.find_config()`, `unwrapt.load_config()`,
  `unwrapt.install_from_env()`, which is what the autowrapt bootstrap
  now calls, and the `Config`, `ProfileOptions` and `ConfigError`
  types. The `UNWRAPT_*` variables override the file's values. See the
  [API](api.md).

- The text report's filter notes now name the `min_ms` and `packages`
  options rather than the environment variables, since either can set
  them.
