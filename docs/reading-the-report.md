# Reading the report

The column-by-column reference for the profile report. The
[strategy guide](choosing-what-to-defer.md) explains what to *do* with
all this; this page explains what each thing *is*.

## The summary header

```
Summary: 1240.5 ms total import time, 412 modules loaded (187 packages), 1260 edges (3190 import calls)
Estimated saving if every deferrable edge were deferred: 640.0 ms (conservative; edge times nest and are not additive)
Best single cut: myapp -> myapp.analytics (412.3 ms cumulative)
Declared lazy, loaded eagerly: 2 imports (96.4 ms cumulative), counted in the estimated saving; turning deferral on is what saves them
```

- **Total import time** is the sum of the outermost import calls. A
  nest of imports counts once, at its root.

- **Modules loaded** counts the modules the run added to
  `sys.modules`, each package and submodule on its own, and the
  **packages** beside it the distinct top-level packages they belong
  to.

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
  one. It leaves out the candidates [used at load](#used-at-load),
  since deferring those saves nothing, and it counts the imports
  declared lazy that the run loaded eagerly.

- **The best single cut** is the largest best cut across the chains:
  the one link whose deferral removes the most.

- **Declared lazy, loaded eagerly**, when there are any among the
  candidates listed, counts the imports named in `__lazy_modules__`
  (below Python 3.15) or in the configuration's `lazy_modules` that
  this run loaded at their statements, both routes could defer, and
  their importers do not use at load. That is what an eager profile,
  with deferral off, does with them. They are decided already, so
  they are not offered as new candidates or best cuts, but their cost
  is real, and turning deferral on is what saves it, so it is in the
  estimated saving.

On Python 3.15 runs with native lazy imports, a warning block follows
the header explaining the edges recorded at first use; see
[Python 3.15](python-3-15.md).

## Deferral sections

A profile with deferral on, the recorder above the shim, has two more
sections after the header, telling whether each deferral paid off:

```
Deferred but used anyway: loaded during the run, so not a saving
  load ms  module   deferred in  first used in  line  notes
     12.8  decimal  mypkg.web    mypkg.web        41
      3.1  numpy    mypkg.calc   mypkg.calc        9  used at load, deferring saves nothing; remove the declaration

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

- **used at load** in the notes marks a deferred import used while its
  importer was still loading: the resolve happened inside the import
  call that loaded the importer, so the deferral saved nothing, only
  moved the load a few lines down. The declaration can go. This is
  how a use the source check cannot see, through `getattr()` or
  `globals()`, shows once the deferral is tried.

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
  imported the same module and are neither lazy nor declared lazy,
  loaded or cache hit: the cost moves to the next one unless all of
  them are deferred. The same module means the same name in the
  imported column, so `from xml import dom` and `import xml.dom` are
  importers of the same module, while `import xml` is not. An
  extension module that imports the module as it loads is one of
  them.

- `already lazy` marks an import this run deferred, natively on 3.15:
  no action needed.

- `declared lazy, loaded eagerly` marks an import declared deferred,
  by `__lazy_modules__` below 3.15 or by the configuration, that this
  run loaded at its statement anyway. With `deferral is off in this
  run`, the profile was an eager one, and turning deferral on is what
  saves it; with `unwrapt cannot defer this form`, the declaration
  names a form the shim leaves eager, footnote (1). Either way it is
  decided already, not a new candidate, and its cost counts in the
  estimated saving when both routes can defer it.

- `used at load (line N), deferring saves nothing` marks a row whose
  importer uses the name the import binds while it loads, on line N
  of its source: see [used at load](#used-at-load).

Rows under the `min_ms` profile option are hidden, and the
`packages` option hides importers outside the named top-level
packages; both are display filters, and the JSON keeps every edge.
They filter the [heavy modules](#heavy-modules) and the
[importers](#by-importer) too.

The footnotes:

(1) unwrapt hands back a lazy proxy, and the attribute fetch in a
`from x import y` or `import a.b as c` resolves it immediately, and it
never defers a relative import. The saving is real on Python 3.15+, or
after a rewrite to `import x` and attribute access on older Pythons.

(2) function level imports are already deferred until the function
runs, so there is nothing to decide.

(3) an extension module made the import as it loaded, so there is no
statement either route could defer. These rows appear only in the
import chains, never among the candidates.

### Used at load

A deferred import resolves the moment its name is used, so an import
whose importer uses it at module level, while the importer is still
loading, saves nothing by being deferred. For each candidate row a
route could defer, and that this run did not, the report reads the
importer's source and looks for a use of the name the statement binds
(`numpy` for `import numpy`, `c` for `import a.b as c`, each name for
a `from` import) in the code that runs at load:

- the module body, outside function bodies;

- class bodies, which run as the class is defined;

- decorators and default arguments, which run as the function is
  defined;

- annotations, when the profiled Python evaluates them as the function
  or variable is defined: below Python 3.14, without
  `from __future__ import annotations`.

An `if TYPE_CHECKING:` body never runs, and an
`if __name__ == "__main__":` body runs only in the main module, so
neither counts in an imported module. Such a row is marked
`used_at_load`, saves nothing, and is left out of the plan, the
estimated saving and the best cuts; the module it imports then counts
as one some importer loads anyway.

Only the rows listed are checked, so the display filters bound the
cost. A source that cannot be read or parsed, such as a report
re-rendered on another machine, leaves its rows as they are. A use the
source does not spell out, through `getattr()` or `globals()`, is not
seen; the [deferral sections](#deferral-sections) show it once the
deferral is tried.

## Heavy modules

By self time: what each module cost on its own, separating it from
what it pulled in. This is the section that names the culprit; the
chains then explain how it got there.

```
Heavy modules: by self time
  11.6 ms  werkzeug
  6.0 ms  jinja2
  4.8 ms  flask
  ...
  (87 more not shown)
```

The section lists the eight heaviest top-level packages, and says how
many it left out; the `rows` profile option, or `--rows` when
re-rendering a saved report, changes the number, and 0 lists them all.
`heavy_modules()` in `unwrapt.report` returns every one. The display
filters apply here as well, and leave a note when they do:

- `min_ms` hides modules whose self time is below it.

- `packages` keeps the modules loaded through the named packages: a
  module stays when an import that loaded it, or an import call it
  happened inside, was made by a module under one of them, so the
  third-party dependencies your code pulls in stay listed. The named
  packages themselves always stay. What the rest of the process loads
  on its own, such as the imports the entry point makes outside your
  packages, is hidden.

## By importer

The cumulative time of each importing module's direct module-level
loads. These are the files to edit first: the sum never counts the
imports made by the modules a file goes on to load, so it is the cost
sitting behind `import` statements in that one file. The imports an
extension module makes as it loads are left out, since there is no
file to edit.

The section lists the eight costliest importers, as many as `rows`
says, and says how many it left out; `by_importer()` in
`unwrapt.report` returns every one. As
with the candidates, `min_ms` hides importers whose direct loads add
up to less than it, and `packages` hides importers outside the named
packages, each with a note saying so.

## Import chains

For each heavy module listed above, the path of import calls that
loaded it, outermost first:

```
  numpy  388.0 ms self
    app.main -> mypkg.web          cum 640.2 ms  3.15 yes  unwrapt yes
    mypkg.web -> mypkg.analytics   cum 412.3 ms  3.15 yes  unwrapt yes  <- best cut
    mypkg.analytics -> numpy       cum 398.1 ms  3.15 yes  unwrapt yes  shared (+2: ...)
```

A chain is the list of places the load could be cut. Deferring an
outer link removes the whole subtree beneath it, so the outermost safe
link saves the most, and that is what the **best cut** mark is: the
outermost link both routes can defer that is neither already lazy nor
declared lazy, that its importer does not use at load, and whose
deferral is not undone by another eager importer of a module in its
subtree. When every link is undone, no link is marked, and when the
outermost safe link is declared lazy already, none is either: that
chain is decided.

A link whose importer is an extension module, such as
`_decimal -> numbers`, is an import the extension made as it loaded,
with no file or line and `no (3)` in both route columns. It is an
eager importer of its module: the module loads whenever the extension
does.

## The JSON form

`UNWRAPT_PROFILE_FORMAT=json`, or `Report.render_json()`, writes the
report as JSON. It is versioned data, and a contract: the `schema`
field says which version of the format it is, and is bumped whenever
a field changes incompatibly. This page describes schema 4.

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

- `filters`: the `min_ms`, `packages` and `rows` display filters the
  text rendering uses unless told otherwise. They never drop an edge.
  A report from 1.0.0a3, which has no `rows`, reads as the default of
  8.

- `edges`: the import calls, in the order they started.

Each edge carries:

- `id` and `parent_id`: the call, and the import call it happened
  inside, null for an outermost one. The tree and the chains are
  built from these.

- `importer`, `imported`, `file` and `line`: the importing module, the
  full dotted name imported, and the statement's file and line, null
  when the call came from C code. The statement is found even when
  another hook wraps `builtins.__import__` over the recorder and
  passes calls on: it is the nearest frame, from the hook's caller up,
  whose globals are the ones the import was given. For an import an
  extension module made as it loaded, the importer is the extension,
  and `file` and `line` are null. `imported` is always absolute: a
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

- `self_modules`: how many modules the call added to `sys.modules`,
  less those its nested import calls added. The summary's modules
  loaded is their sum.

- `defer`: whether the import can be deferred. `native` is whether
  native lazy imports on Python 3.15 could defer the statement's form.
  `unwrapt` is whether the shim would defer this call if it were
  listed, by the shim's own rules, so a consumer never suggests a
  deferral the shim would refuse, and `reason` is the first rule it
  fails: `extension-module` for an import an extension module made
  as it loaded, which neither route can defer, `function-level`,
  `class-level`, `relative`, `from-import`, `dotted-as`, or
  `already-loaded` for a call that found the module loaded.

- `declared_lazy`: the import is declared deferred, by
  `__lazy_modules__` below 3.15, by the configuration's
  `lazy_modules`, or natively on 3.15, whether or not this run
  deferred it. `already_lazy`: this run deferred it, by the shim
  (`deferred`) or natively (`native_lazy`). An eager profile, with
  deferral off, has declared imports that are not already lazy.
  `native_lazy`: recorded at native reification on 3.15.

- `deferred` and `resolution`: the shim handed back a lazy proxy, in a
  profile with deferral on, and the id of the `resolve` edge that
  later loaded it, or null if the run never used it. On a `resolve`
  edge, `resolves` is the id of the deferred edge, `used_in` the
  module that used the proxy first, and `file` and `line` where.

- `labels`: the index of the label set in force when the statement
  ran.

`python -m unwrapt.report` reads schema 4 reports, and says so for
any other version rather than misreading it. An older report cannot
be converted: schema 3, from unwrapt 1.0.0a3 and 1.0.0a4, never
recorded how many modules each call loaded, nor told an import
declared lazy from one the run deferred, and credited the imports of
extension modules to the import system; schema 2, from 1.0.0a2, never
recorded how many levels up a relative import reached. Profile the
application again.

## Limits of this report

Every report ends with this block, because the report cannot see
everything:

- import-time use of the imported name by the importing module is
  checked in its source, for the candidates listed (see
  [used at load](#used-at-load)), but a use the source does not spell
  out, through `getattr()` or `globals()`, is not seen until the
  deferral is tried, when the deferral sections show it;

- a `try/except ImportError` around the import, so deferring a guarded
  optional dependency would move its error to first use;

- other workloads: the report describes the run that was profiled;

- imports through `importlib.import_module`, or by C code that calls
  the import machinery without going through `__import__`: their time
  is inside the enclosing cumulative figure but they get no row of
  their own. A submodule a `from` import loads is named on that
  import's row and shares its figures, except those a
  `from x import *` brings in, which are not named;

- and itself: per-import timing overhead inflates every figure.
  Compare relative sizes, against `python -X importtime` for example,
  and never treat a millisecond figure as a wall-clock promise.

The [strategy guide](choosing-what-to-defer.md) makes each of these a
triage step rather than a surprise.
