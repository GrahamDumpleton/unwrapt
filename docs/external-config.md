# External configuration

The external configuration defers imports in modules whose source you
do not control, or do not want to edit: third-party code, a vendored
package, your own modules while experimenting. It is the
`lazy_modules` table of the [configuration file](configuration.md),
mapping each importer's module name to the module names that importer
should defer:

```toml
# unwrapt.toml

[lazy_modules]
"thirdparty.pkg.client" = ["numpy", "pandas"]
"myapp.cli" = ["sqlite3"]
```

In a `pyproject.toml` the table is `[tool.unwrapt.lazy_modules]`. The
same mapping can also be a JSON file named by `UNWRAPT_CONFIG`, the
form that holds only the deferrals:

```json
{
    "thirdparty.pkg.client": ["numpy", "pandas"],
    "myapp.cli": ["sqlite3"]
}
```

The [configuration](configuration.md) page says where the file is
found.

## The rules

- The importer key is the value of `__name__` where the import
  statement runs. An application run as `python app.py` or
  `python -m app` has the entry point's own imports under
  `"__main__"`, which is why the examples show it.

- The names are matched exactly, like `__lazy_modules__`: a listed
  `xml.dom` defers `import xml.dom` in the named importer, and nothing
  else.

- Only whole-module imports are deferred, on the same eligibility
  rules as `__lazy_modules__`: `from x import y` and
  `import a.b as c` in the importing module stay eager. See
  [how it works](how-it-works.md).

- Below Python 3.15 the sources union: an import is deferred if either
  the configuration or the module's own `__lazy_modules__` names it,
  unless `config_only` restricts it to the configuration.

- From Python 3.15 the configuration is the only source, always: the
  interpreter handles `__lazy_modules__` itself and unwrapt never
  reads it. Having entries is what activates unwrapt there. An entry
  that duplicates an import the code already declares lazy, by
  `__lazy_modules__` or an explicit `lazy import` statement, is left to
  the interpreter. See [Python 3.15](python-3-15.md).

## Errors

A file that is missing, unreadable or malformed, or that has an entry
of the wrong shape (an importer whose value is not a list of module
names), is an error. Through the bootstrap the error warns once on
stderr and the process starts without the file: unwrapt must not stop
the host application from starting.

## What it is for

The configuration is the no-edit route in the
[strategy guide](choosing-what-to-defer.md): after a profile run names
the candidates, the ones in code you own become `__lazy_modules__`
lines in that source, and the ones in code you do not own become
entries here. The [worked example](worked-example.md) shows both.

On 3.15 it also serves a second purpose: trying a candidate list from
the profile report without editing any source at all, while native
handles everything the code declares itself.
