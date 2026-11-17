# Reading the report

The column-by-column reference for the profile report. The
[strategy guide](choosing-what-to-defer.md) explains what to *do* with
all this; this page explains what each thing *is*.

## The summary header

```
Summary: 1240.5 ms total import time, 187 modules loaded, 412 edges (3190 import calls)
Estimated saving if every deferrable edge were deferred: 640.0 ms (conservative; edge times nest and are not additive)
Best single cut: myapp -> myapp.analytics (412.3 ms cumulative)
```

- **Total import time** is the sum of the outermost import calls. A
  nest of imports counts once, at its root.

- **Modules loaded** counts the distinct top-level packages the run
  actually loaded.

- **Edges** counts the records in the report, and **import calls** the
  calls they stand for: repeated already-loaded hits are folded into
  one edge with a count, as [the JSON form](#the-json-form) describes.

- **Labels**, when the report has any, follow the title line: what the
  caller said the report is of.

- **The estimated saving** is the conservative figure for deferring
  every edge both routes can defer, minus the cost that would move to
  another eager importer rather than disappear. It never sums
  cumulative times across ancestors and descendants, because they
  nest: the outermost edges only. It is an estimate, and labelled as
  one.

- **The best single cut** is the largest best cut across the chains:
  the one link whose deferral removes the most.

On Python 3.15 runs with native lazy imports, a warning block follows
the header explaining the edges recorded at first use; see
[Python 3.15](python-3-15.md).

## Deferral sections

A profile with deferral on, the recorder above the shim, has two more
sections after the header, telling whether each deferral paid off:

```
Deferred but used anyway: loaded during the run, so not a saving
  load ms  module   deferred in  first used in  line
     12.8  decimal  mypkg.web    mypkg.web        41

Deferred and never used: deferred for the whole run
  module  deferred in
  wave    mypkg.client
```

- **Deferred but used anyway** lists each deferred import the run went
  on to use, costliest first: the module, the importer whose statement
  was deferred, the module and line that used it first, and what its
  load cost there. `(loaded)` in place of the cost means something else
  had already loaded the module by then. Each is also a `resolve` edge
  in the JSON, with the imports the module made nested beneath it, so
  its cost still counts in the total, the heavy modules and the
  chains. It is not a candidate row: the statement is already
  deferred.

- **Deferred and never used** lists the deferrals the run never
  touched. These are the savings, but what each would have cost is
  known only from a profile with nothing deferred, so the report
  names them and leaves the figure to the compare tool:
  `python -m unwrapt.report eager.json --compare deferred.json`.

Both describe the profiled run only: a deferred import used after
`unwrapt.stop_profile()`, or never used before the report was
written, shows as never used.

## Candidates

Module-level imports the run loaded, ranked by cumulative time:

```
  cum ms  self ms  imported         imported by        3.15  unwrapt  notes
   412.3     0.4  mypkg.analytics  mypkg.web           yes      yes
   398.1   388.0  numpy            mypkg.analytics    yes      yes   shared (+2: mypkg.a, mypkg.b)
    96.4     0.2  yaml             mypkg.config        yes   no (1)
```

- **cum ms**: the wall time of the import call, including everything
  the import went on to load. This is the saving from deferring that
  line, and the sort key: a thin wrapper with near-zero self time can
  be the best candidate in the report.

- **self ms**: the same time minus the nested import calls: what the
  imported module cost on its own.

- **imported / imported by**: the edge. `import a.b.c` binds `a`, so
  an edge's imported name is the full dotted name and the chain shows
  where the binding lives. A relative import shows the absolute module
  it names, so `from .serving import run_simple` in `werkzeug` shows
  as `werkzeug.serving`. A `from` import whose names are submodules
  shows those instead, comma separated: `from . import json` in
  `flask` shows as `flask.json`, the module the statement is for.

- **3.15 / unwrapt**: the route columns. A limit of the shim is not a
  property of the code, so the two routes are reported separately and
  no row is ever dropped because a route cannot handle it:

| Import form | 3.15 | unwrapt |
| --- | --- | --- |
| `import x`, `import x as y`, `import a.b` | yes | yes |
| `import a.b as c` | yes | no (1) |
| `from x import y` | yes | no (1) |
| `from . import y`, `from .x import y` | yes | no (1) |
| function level | n/a (2) | n/a (2) |

- **notes**: `shared (+N: ...)` lists the other modules that also
  imported the same module and are not already lazy, loaded or cache
  hit: the cost moves to the next one unless all of them are deferred.
  The same module means the same name in the imported column, so
  `from xml import dom` and `import xml.dom` are importers of the same
  module, while `import xml` is not.
  `already lazy` marks an import already declared deferred, by
  `__lazy_modules__`, by the configuration, or natively on 3.15: no
  action needed.

Rows under the `min_ms` profile option are hidden, and the
`packages` option hides importers outside the named top-level
packages; both are display filters, and the JSON keeps every edge.

The footnotes:

(1) unwrapt hands back a lazy proxy, and the attribute fetch in a
`from x import y` or `import a.b as c` resolves it immediately, and it
never defers a relative import. The saving is real on Python 3.15+, or
after a rewrite to `import x` and attribute access on older Pythons.

(2) function level imports are already deferred until the function
runs, so there is nothing to decide.

## Heavy modules

By self time: what each module cost on its own, separating it from
what it pulled in. This is the section that names the culprit; the
chains then explain how it got there.

## By importer

The cumulative time of each importing module's direct module-level
loads. These are the files to edit first: the sum never counts the
imports made by the modules a file goes on to load, so it is the cost
sitting behind `import` statements in that one file.

## Import chains

For each of the heaviest modules, the path of import calls that loaded
it, outermost first:

```
  numpy  388.0 ms self
    app.main -> mypkg.web          cum 640.2 ms  3.15 yes  unwrapt yes
    mypkg.web -> mypkg.analytics   cum 412.3 ms  3.15 yes  unwrapt yes  <- best cut
    mypkg.analytics -> numpy       cum 398.1 ms  3.15 yes  unwrapt yes  shared (+2: ...)
```

A chain is the list of places the load could be cut. Deferring an
outer link removes the whole subtree beneath it, so the outermost safe
link saves the most, and that is what the **best cut** mark is: the
outermost link both routes can defer that is not already lazy, and
whose deferral is not undone by another eager importer of a module in
its subtree. When every link is undone, no link is marked.

## The JSON form

`UNWRAPT_PROFILE_FORMAT=json`, or `Report.render_json()`, writes the
report as JSON. It is versioned data, and a contract: the `schema`
field says which version of the format it is, and is bumped whenever
a field changes incompatibly. This page describes schema 3.

The JSON holds the facts the recorder saw, and nothing derived from
them. The analysis the text report shows (the summary figures, who
pays for each module, the candidates and their savings, the chains,
the deferral sections) is computed from the facts by the functions in
`unwrapt.report`, described on the [API](api.md#unwraptreport) page,
so a consumer can call them, or compute its own.

```{literalinclude} _static/report-schema.json
:language: json
```

At the top level:

- `schema`, `unwrapt` and `python`: the format version, and the
  versions that produced the report.

- `labels`: the caller's description of what the report is of, such as
  the application, the release, the process's role and the outcome.
  Empty unless the caller added some, through `report.labels`.

- `label_sets`: the table of the label sets that were in force while
  the imports ran, as `unwrapt.scope()` set them. Each edge's `labels`
  is an index into it, and index 0 is the empty set, outside any scope.

- `filters`: the `min_ms` and `packages` display filters the text
  rendering uses unless told otherwise. They never drop an edge.

- `edges`: the import calls, in the order they started.

Each edge carries:

- `id` and `parent_id`: the call, and the import call it happened
  inside, null for an outermost one. The tree and the chains are
  built from these.

- `importer`, `imported`, `file` and `line`: the importing module, the
  full dotted name imported, and the statement's file and line, null
  when the call came from C code. `imported` is always absolute: a
  relative import is resolved against the importer's package, as the
  import system resolves it, so `from . import json` in `flask` has
  `flask`, and `from ..other import z` in `pkg.sub` has `pkg.other`.

- `written`: the name as the statement wrote it, with a relative
  import's leading dots (`.`, `.serving`, `..other`). For an absolute
  import it is the same as `imported`, and so it is for a native lazy
  import on 3.15 recorded at reification, which arrives with the
  absolute name.

- `submodules`: for a `from` import, the names it imports that are
  submodules of `imported`, by their full names, whether this call
  loaded them or found them loaded: `["flask.json"]` for
  `from . import json` in `flask`. Empty for anything else, and for
  `from x import *`, whose submodules are not named.

- `kind` (`import`, `from`, or `resolve` for a deferred import loaded
  at first use), `level` (`module`, `function` or `class`) and
  `relative`.

- `loaded`: whether the call loaded the module, rather than finding it
  already loaded. The first importer pays; the rest are cache hits.

- `count`: how many calls the edge stands for. Repeated already-loaded
  hits, which make up most of the import calls a large application
  makes, are folded into one edge per importer, module and label set
  (and per statement as written, submodules, kind, level, and whether
  the hits were outermost), with a
  count, the times summed, and the first hit's file, line and parent.
  Nothing else is folded and nothing is pruned: every edge that loaded
  a module, was deferred or resolved, or made nested import calls is
  its own edge.

- `cum_ms` and `self_ms`: the wall time of the call, and that time
  minus the time spent in nested import calls.

- `defer`: whether the import can be deferred. `native` is whether
  native lazy imports on Python 3.15 could defer the statement's form.
  `unwrapt` is whether the shim would defer this call if it were
  listed, by the shim's own rules, so a consumer never suggests a
  deferral the shim would refuse, and `reason` is the first rule it
  fails: `function-level`, `class-level`, `relative`, `from-import`,
  `dotted-as`, or `already-loaded` for a call that found the module
  loaded.

- `already_lazy`: the import is already declared deferred, by
  `__lazy_modules__`, by the configuration, or natively on 3.15.
  `native_lazy`: recorded at native reification on 3.15.

- `deferred` and `resolution`: the shim handed back a lazy proxy, in a
  profile with deferral on, and the id of the `resolve` edge that
  later loaded it, or null if the run never used it. On a `resolve`
  edge, `resolves` is the id of the deferred edge, `used_in` the
  module that used the proxy first, and `file` and `line` where.

- `labels`: the index of the label set in force when the statement
  ran.

`python -m unwrapt.report` reads schema 3 reports, and says so for
any other version rather than misreading it. A schema 2 report, from
unwrapt 1.0.0a2, cannot be converted, since it never recorded how many
levels up a relative import reached: profile the application again.

## Limits of this report

Every report ends with this block, because the report cannot see:

- import-time use of the imported name by the importing module: class
  bases, decorators, default arguments, annotations without
  `from __future__ import annotations` and module-level calls all
  force resolution at import time, and none of them show here;

- a `try/except ImportError` around the import, so deferring a guarded
  optional dependency would move its error to first use;

- other workloads: the report describes the run that was profiled;

- imports through `importlib.import_module` and the C import API:
  their time is inside the enclosing cumulative figure but they get no
  row of their own. A submodule a `from` import loads is named on that
  import's row and shares its figures, except those a
  `from x import *` brings in, which are not named;

- and itself: per-import timing overhead inflates every figure.
  Compare relative sizes, against `python -X importtime` for example,
  and never treat a millisecond figure as a wall-clock promise.

The [strategy guide](choosing-what-to-defer.md) makes each of these a
triage step rather than a surprise.
