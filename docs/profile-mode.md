# Profile mode

Profile mode records what an application's imports actually cost on a
real run, and reports what is worth deferring. It is the measurement
half of the [strategy guide](choosing-what-to-defer.md); this page is
the reference for the mechanism and the variables, and
[reading the report](reading-the-report.md) is the reference for the
output.

## Running it

Profile mode is activated the same way the shim is: through the
[autowrapt](autowrapt.md) bootstrap, or an explicit
`unwrapt.install(profile=True)`.

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_PROFILE=1 python -m myapp
```

The text report prints to stderr at process exit, or when the
application calls `unwrapt.stop_profile()` before then. The recommended form
writes it to a file, in the JSON the tooling consumes:

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_PROFILE=1 UNWRAPT_PROFILE_FORMAT=json \
    UNWRAPT_PROFILE_OUTPUT=report-%p.json python -m myapp
```

`%p` expands to the process id, which keeps concurrent workers from
interleaving their reports: worker process setups (a mod_wsgi daemon
process, for example) may not run exit handlers reliably, and one file
per process is the robust route.

Where the report goes and what it shows can also be set in the
`[profile]` table of the [configuration file](configuration.md), with
a relative `output` resolved against the file's directory. The table
never switches profiling on: `UNWRAPT_PROFILE` does that. All the
settings are on the [configuration](configuration.md) page; the
profile variables are `UNWRAPT_PROFILE`, `UNWRAPT_PROFILE_OUTPUT`,
`UNWRAPT_PROFILE_FORMAT`, `UNWRAPT_PROFILE_MIN_MS` and
`UNWRAPT_PROFILE_PACKAGES`, and each of the last four overrides the
file's value.

## What it does

Installs a recording `__import__` hook. Recording and deferral are
independent layers, and which runs is the caller's choice:

- **An eager profile**, deferral off, measures the program as it is,
  whatever the configuration or the modules' `__lazy_modules__` say.
  This is the profile for finding candidates, and what
  `UNWRAPT_PROFILE=1` alone gives.

- **A profile with deferral on** puts the recorder above the shim and
  measures the program with its deferrals in place: what start-up
  really pays, and which deferred modules are loaded anyway.
  `UNWRAPT_PROFILE=1` with `UNWRAPT_DEFER=1` gives this one, and so
  does `unwrapt.install(defer=True, profile=True)`. Each import the
  shim deferred is an edge marked `deferred`.

The report is written at exit by an exit handler, unless the
application calls `unwrapt.stop_profile()` first. That takes out only
the recorder, leaves deferral in place, unregisters the exit handler,
and returns the report, writing it where the profile options say
unless asked not to with `write=False`. A preforking server calls it
at the fork, so the workers neither carry on timing nor inherit the
exit handler and write a copy of the host's report each. See the
[API](api.md).

For every import call through the hook, including `sys.modules` cache
hits, one edge is recorded:

- the importing module and the imported name;

- whether it was an `import` or a `from` form, whether it was
  relative, and whether the statement sat at module, function or
  class level;

- the statement's file and line, when the call was made from Python;

- whether the module was loaded by the call or already cached, which is
  how the report knows who paid the cost: the first importer pays,
  later importers are cache hits;

- the wall time of the call (cumulative), and that time minus the
  time spent in nested import calls (self), which is how the report
  separates a module's own cost from the cost of what it pulls in;

- the ids linking each edge to the import call it happened inside,
  which is how the report builds the tree and the chains;

- the labels in force when the statement ran, as an index into the
  report's table of label sets.

Repeated already-loaded hits, which make up most of the tens of
thousands of import calls a large application makes, are folded in
memory into one edge per importer, module and label set, with a count.
Nothing is pruned: every edge that loaded a module is kept, and the
`min_ms` and `packages` thresholds apply only when the report is
rendered.

## Labels

A host that loads several entry points can label each, so the report
says which entry point needed which module:

```python
import unwrapt

with unwrapt.scope(entrypoint="hooks"):
    import shop.hooks

with unwrapt.scope(entrypoint="mount:api"):
    import shop.api
```

The cost of a module shared by both stays with the first load, under
`entrypoint=hooks`, while the already-loaded edges under
`entrypoint=mount:api` show that the API needs it too.
`unwrapt.push_scope()` and `unwrapt.pop_scope()` do the same for a
caller that brackets the work with two callbacks. Labels describing
the whole report go on the `Report` itself, before it is stored:
`report.labels.update(role="host", outcome="fork")`. See the
[API](api.md#unwraptscope).

A module the shim deferred is loaded at first use through
`importlib.import_module`, which does not pass through
`builtins.__import__`. The shim times that load itself, and the
recorder records it as a `resolve` edge, with where the module was
first used and the imports it made nested beneath it. The report's
[deferral sections](reading-the-report.md#deferral-sections) then say
which deferred imports were used anyway, and which never were.

On Python 3.15 and later, native lazy imports are left exactly as
they are: a declared-lazy import that the run touches is recorded at
native's reification, at first use, and flagged in the report; one the
run never touches never loads and never appears. The reason the
profiler does not force declared-lazy imports eager is verified
behaviour: the forcing mechanism routes the import around
`builtins.__import__`, which would hide it from the hook entirely. A
run with native laziness switched to all mode is warned about at
install. See [Python 3.15](python-3-15.md).

## What it is for

Finding candidates. The [strategy guide](choosing-what-to-defer.md)
is the method; the [worked example](worked-example.md) runs it end to
end; the [AI assistant procedure](ai-assisted-tuning.md) hands the
JSON form to an assistant with the same method. The report is useful
on its own even with no deferral intended: it is a start-up profile of
your application's import graph, with timings.

## Comparing runs

```console
$ python -m unwrapt.report before.json --compare after.json
```

re-renders a saved JSON report as text, and with `--compare` diffs
two of them: total import time, per-module self time changes, and
modules newly loaded or no longer loaded. This is the verify and guard
step of the strategy, without re-running the application.
