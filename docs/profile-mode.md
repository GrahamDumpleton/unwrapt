# Profile mode

Profile mode records what an application's imports actually cost on a
real run, and reports what is worth deferring. It is the measurement
half of the [strategy guide](choosing-what-to-defer.md); this page is
the reference for the mechanism and the variables, and
[reading the report](reading-the-report.md) is the reference for the
output.

## Running it

Profile mode is activated the same way the shim is: through the
[autowrapt](autowrapt.md) bootstrap, or an explicit `unwrapt.install()`.

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_PROFILE=1 python -m myapp
```

The text report prints to stderr at process exit. The recommended form
writes it to a file, in the JSON the tooling consumes:

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_PROFILE=1 UNWRAPT_PROFILE_FORMAT=json \
    UNWRAPT_PROFILE_OUTPUT=report-%p.json python -m myapp
```

`%p` expands to the process id, which keeps concurrent workers from
interleaving their reports: worker process setups (a mod_wsgi daemon
process, for example) may not run exit handlers reliably, and one file
per process is the robust route.

All the variables are on the [configuration](configuration.md) page;
the profile ones are `UNWRAPT_PROFILE`, `UNWRAPT_PROFILE_OUTPUT`,
`UNWRAPT_PROFILE_FORMAT`, `UNWRAPT_PROFILE_MIN_MS` and
`UNWRAPT_PROFILE_PACKAGES`.

## What it does

Installs a recording `__import__` hook instead of the shim hook. No
deferral happens, whatever the configuration or the modules'
`__lazy_modules__` say: profile mode measures the program as it is.
The two modes are mutually exclusive in one process, by design, and
`unwrapt.install()` picks profile mode whenever `UNWRAPT_PROFILE` is
set.

For every import call through the hook, including `sys.modules` cache
hits, one edge is recorded:

- the importing module and the imported name;

- whether it was an `import` or a `from` form, and whether the
  statement sat at module, function or class level;

- the statement's file and line, when the call was made from Python;

- whether the module was loaded by the call or already cached, which is
  how the report knows who paid the cost: the first importer pays,
  later importers are cache hits;

- the wall time of the call (cumulative), and that time minus the
  time spent in nested import calls (self), which is how the report
  separates a module's own cost from the cost of what it pulls in;

- the ids linking each edge to the import call it happened inside,
  which is how the report builds the tree and the chains.

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
