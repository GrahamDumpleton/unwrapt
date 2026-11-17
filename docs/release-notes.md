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

- **External configuration:** a TOML file (`unwrapt.toml`, or
  `[tool.unwrapt]` in `pyproject.toml`) deferring imports in modules
  whose source you do not control, unioned with `__lazy_modules__`
  below 3.15. A JSON file holding only the deferrals is accepted too.

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

### Changes in 1.0.0a3

- **The profile report names relative imports by the modules they
  load.** A relative import was recorded by the name as written, so
  `from . import x` showed as a blank module, with every such import
  across unrelated packages merged into one row and one shared list,
  and `from .sansio.app import App` in `flask` was grouped as a heavy
  module called `sansio`. Each edge's `imported` is now the absolute
  name, resolved against the importer's package as the import system
  resolves it, so the candidates, heavy modules, chains and shared
  lists all use the real module names. The rows are still marked
  relative, and still not deferrable by the shim.

- **A `from` import names the submodules it loads.** Each edge now
  carries `submodules`, the names a `from` import imports that are
  submodules, by their full names, so `from . import json` in `flask`
  shows in the text report as `flask.json`, the module that cost the
  time, rather than as the package it came from. This applies to
  absolute `from` imports too. `who_pays()` attributes each submodule
  to the import that loaded it, and the shared lists match a
  `from xml import dom` with an `import xml.dom` elsewhere.

- **The JSON form is schema 3.** Each edge gains `written`, the name
  as the statement wrote it with a relative import's leading dots, and
  `submodules`; `imported` is always absolute. Schema 2 reports, from
  1.0.0a2, are not read, since they never recorded how far up a
  relative import reached: profile again. See
  [reading the report](reading-the-report.md#the-json-form).

### Changes in 1.0.0a2

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

- **Deferral and profiling are independent layers.**
  `unwrapt.install(config=None, *, defer=True, profile=False)` is the
  explicit API: it does what its arguments say and reads no
  environment variable other than `UNWRAPT_CONFIG` when it finds the
  file itself. With both on, the recorder sits above the shim, so the
  profile measures the program with its deferrals in place, and each
  deferred import is an edge marked `deferred`. The `module` argument
  `install()` used to take is gone.

- **New API:** `unwrapt.stop_profile()` takes out only the recorder,
  leaves deferral in place, unregisters the exit handler and returns
  the report; `unwrapt.uninstall()` takes out both layers; and
  `unwrapt.installed()` returns an `Installed(defer=..., profile=...)`
  or None. A layer with a wrapper installed over it is left in the
  chain as pass-through rather than removing the wrapper. See the
  [API](api.md).

- **`UNWRAPT_DEFER`** switches deferral for the bootstrap. It defaults
  to off when `UNWRAPT_PROFILE` is set, so `UNWRAPT_PROFILE=1` alone is
  still the eager profile for finding candidates, and to on otherwise.
  See [configuration](configuration.md).

- The recorder alone no longer imports wrapt, so an eager profile no
  longer has wrapt and its standard library imports loaded ahead of
  the application.

- **Deferred imports are reported, and so is their resolution.**
  `unwrapt.deferred()` lists each proxy the shim handed out, with
  whether it has been resolved, and `unwrapt.on_resolve(callback)`
  calls back with a `Resolution` (importer, module, load time, thread
  and where it was first used) when one resolves. A profile with
  deferral on records each resolve as a `resolve` edge, with the
  module's own imports nested beneath it, and the report gains two
  sections: deferred but used anyway, and deferred and never used. See
  [reading the report](reading-the-report.md#deferral-sections).

- **The profile report is versioned data, with labels.**
  `stop_profile(write=False)` returns a `Report`, whose `to_dict()` is
  schema 2 of the JSON form, documented field by field on
  [reading the report](reading-the-report.md#the-json-form). The JSON
  holds facts only: each edge now carries its statement's file,
  whether it was relative, a `count`, a `defer` object (whether each
  route can defer it, and if the shim cannot, why: `function-level`,
  `class-level`, `relative`, `from-import`, `dotted-as` or
  `already-loaded`), the `resolution` of a deferred import, and the
  label set in force. `report.labels` holds the caller's own labels,
  and `unwrapt.scope()`, or `unwrapt.push_scope()` and
  `unwrapt.pop_scope()`, label the code being loaded. Schema 1
  reports are not read; profile again.

- **Repeated already-loaded hits are folded** in memory into one edge
  per importer, module and label set, with a count. Nothing is
  pruned, and the display thresholds apply only when the report is
  rendered: `render_text(min_ms=..., packages=...)` overrides them.

- **The analysis is a set of functions** in `unwrapt.report`:
  `summary()`, `who_pays()`, `candidates()` (now with each
  candidate's own saving), `chain()` and `chains()`, `heavy_modules()`,
  `by_importer()`, `deferred_used()`, `deferred_unused()` and
  `compare_reports()`, plus `load_report()`. The derived sections
  (summary, heavy modules, chains, by importer, the shared importers
  and the deferral lists) are no longer stored in the JSON. The text
  report shows the report's labels and the import calls behind the
  edges, and marks relative imports as not deferrable by the shim.
