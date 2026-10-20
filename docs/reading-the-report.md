# Reading the report

The column-by-column reference for the profile report. The
[strategy guide](choosing-what-to-defer.md) explains what to *do* with
all this; this page explains what each thing *is*.

## The summary header

```
Summary: 1240.5 ms total import time, 187 modules loaded, 412 edges
Estimated saving if every deferrable edge were deferred: 640.0 ms (conservative; edge times nest and are not additive)
Best single cut: myapp -> myapp.analytics (412.3 ms cumulative)
```

- **Total import time** is the sum of the outermost import calls. A
  nest of imports counts once, at its root.

- **Modules loaded** counts the distinct top-level packages the run
  actually loaded.

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
  where the binding lives.

- **3.15 / unwrapt**: the route columns. A limit of the shim is not a
  property of the code, so the two routes are reported separately and
  no row is ever dropped because a route cannot handle it:

| Import form | 3.15 | unwrapt |
| --- | --- | --- |
| `import x`, `import x as y`, `import a.b` | yes | yes |
| `import a.b as c` | yes | no (1) |
| `from x import y` | yes | no (1) |
| function level | n/a (2) | n/a (2) |

- **notes**: `shared (+N: ...)` lists the other modules that also
  imported the same module and are not already lazy, loaded or cache
  hit: the cost moves to the next one unless all of them are deferred.
  `already lazy` marks an import already declared deferred, by
  `__lazy_modules__`, by the configuration, or natively on 3.15: no
  action needed.

Rows under `UNWRAPT_PROFILE_MIN_MS` are hidden, and
`UNWRAPT_PROFILE_PACKAGES` hides importers outside the named
top-level packages; both are display filters, and the JSON keeps
every edge.

The footnotes:

(1) unwrapt hands back a lazy proxy, and the attribute fetch in a
`from x import y` or `import a.b as c` resolves it immediately. The
saving is real on Python 3.15+, or after a rewrite to `import x` and
attribute access on older Pythons.

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

`UNWRAPT_PROFILE_FORMAT=json` writes the same report as JSON, with one
object per edge and every derived section. The fields are stable from
1.0.0; if they ever change incompatibly, the `schema` number is bumped.
The shape:

```{literalinclude} _static/report-schema.json
:language: json
```

Each edge carries `deferrable.native` and `deferrable.unwrapt`
(booleans), `unwrapt_limit` (the footnote reason, or null),
`already_lazy`, `native_lazy` (recorded at native reification on
3.15), `other_eager_importers` (the shared note), the `parent_id`
linking it into the tree, and the timings. The `ai-assisted-tuning`
page describes the same fields as an assistant sees them.

## Limits of this report

Every report ends with this block, because the report cannot see:

- import-time use of the imported name by the importing module: class
  bases, decorators, default arguments, annotations without
  `from __future__ import annotations` and module-level calls all
  force resolution at import time, and none of them show here;

- a `try/except ImportError` around the import, so deferring a guarded
  optional dependency would move its error to first use;

- other workloads: the report describes the run that was profiled;

- imports through `importlib.import_module` and the C import API, and
  submodule loads inside `from` imports: their time is inside the
  enclosing cumulative figure but they get no row of their own;

- and itself: per-import timing overhead inflates every figure.
  Compare relative sizes, against `python -X importtime` for example,
  and never treat a millisecond figure as a wall-clock promise.

The [strategy guide](choosing-what-to-defer.md) makes each of these a
triage step rather than a surprise.
