# Worked example

A sample application for the
[worked example](https://unwrapt.readthedocs.io/en/latest/worked-example.html)
page of the documentation, which walks the
[choosing what to defer](https://unwrapt.readthedocs.io/en/latest/choosing-what-to-defer.html)
strategy on it end to end: a baseline profile report, the triage of each
candidate, the decisions, and the verification.

The application is deliberately shaped like a small real one: an entry
point that imports eagerly, a web module that pulls in an analytics
module, and a client module with a from-import. Nothing here is
installed; run it in place from this directory.

## The baseline

The profile mode is activated the same way the shim is, through the
autowrapt bootstrap (`pip install autowrapt` once):

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_PROFILE=1 UNWRAPT_PROFILE_FORMAT=json \
    UNWRAPT_PROFILE_OUTPUT=before.json python -m myapp
```

`python -m unwrapt.report before.json` re-renders the report as text
any time.

## The same run, with the heavy imports deferred

The `lazy.json` file marks the imports the strategy guide decides to
defer, through the external configuration, which is the route for code
you cannot or do not want to edit. Profile mode itself never defers
(it measures the program as it is), so verify the decision by running
the application with the shim active:

```console
$ pip install autowrapt
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_CONFIG=lazy.json python -m myapp
```

The documentation page shows the same decisions applied as
`__lazy_modules__` lines in the source, and what each route does on
each Python version.

## Comparing runs

The compare tool diffs two profiled runs of a workload, for example
before and after a code change:

```console
$ python -m unwrapt.report before.json --compare after.json
```

See the documentation page for the full walk-through, including the
triage of every candidate and the verification steps.
