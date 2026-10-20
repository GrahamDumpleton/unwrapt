# Choosing what to defer

The profile report tells you what your imports cost. This guide is the
method for turning that report into decisions: which imports to defer,
which to rewrite first, which to leave alone, and how to verify the
result. It is written for a human first, and it is also the basis of
the [AI assistant procedure](ai-assisted-tuning.md); the
[reference pages](reading-the-report.md) explain each field, while
this page explains what to *do* with them.

## When laziness is worth pursuing

Start-up dominated workloads benefit most: command-line tools that
should answer in tens of milliseconds, serverless cold starts, test
suites, short-lived workers. For a long-running server the cost moves
to first use rather than disappearing, so the question is whether
first-request latency matters more than start-up.

One case deserves plain words: a pre-forking server that imports
everything *before* forking shares the imported code across workers,
so deferring an import can trade one shared start-up cost for a
per-worker first-use cost. Whether that is a win depends on the
server; measure it.

Who you are matters too:

- **Application owners** control the entry point. Use
  `__lazy_modules__` in your own modules and the
  [external configuration](external-config.md) for third-party code;
  both routes are open to you.

- **Library authors** should defer your own heavy, optional imports
  (the profiler is how you find them) and must never rely on
  laziness for correctness: your users run your code under import
  systems and Python versions you do not control.

## Set the goal first

Before running anything, decide:

- **The target Python versions.** This selects the route columns: a
  3.15-only project reads the `3.15` column, a mixed-support project
  needs rows both routes can defer, and the shim-only rows become
  rewrites to judge individually.

- **The workloads to profile.** Pure start-up, a typical command, the
  slowest `--help` or health-check path: profile the runs that matter,
  not just the easiest one to launch.

- **A stopping rule.** For example: stop when each remaining candidate
  saves less than a few percent of the baseline. Without a rule,
  deferring imports is a rabbit hole with diminishing returns.

## Take a baseline

Run [profile mode](profile-mode.md) on each workload several times,
and keep the JSON of a representative run:

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_PROFILE=1 UNWRAPT_PROFILE_FORMAT=json \
    UNWRAPT_PROFILE_OUTPUT=baseline-%p.json python -m myapp
```

Note the run-to-run noise on the total so small differences are not
mistaken for wins, and remember that the timing overhead inflates
absolute figures: compare like with like, never a profile run against
a wall clock.

On Python 3.15, profile an eager run for the baseline (unset native
laziness), because a declared-lazy import that is never touched never
loads and so never appears in the report at all. See
[Python 3.15](python-3-15.md).

## Read the report top-down

The order of attention is not the order of the sections:

1. **The summary header** answers how big the prize is: the total, and
   the conservative estimate of what deferral could remove.

2. **Heavy modules** say what is expensive in itself. Self time
   separates a module's own import work from the modules it pulls in,
   which is why a thin wrapper that drags in a heavy dependency shows
   near-zero self time while the dependency shows the cost.

3. **Import chains** answer why a heavy module is loaded at all: the
   path of imports from the outermost statement down to the load, one
   link per line, each with its cumulative time and its route columns,
   and the best cut marked. A flat ranking cannot answer "where is the
   right place to cut?" a chain can.

4. **Only then, the candidate list.** Cumulative time ranks it because
   the saving from deferring one import line is its cumulative time:
   the wrapper with near-zero self time is often the best candidate.

One rule holds across all of it: edge times nest. If A imports B
imports C, cum(A) already contains cum(B) and cum(C), so no figure in
the report ever adds them together, and neither should you.

## Choose cut points

Five principles, each visible in the report:

1. **Cut as close to the root as is safe.** Deferring an outer link
   removes the whole subtree beneath it, so the outermost safe link
   saves the most. That is why the report marks it.

2. **Cut in code you control** where possible: a `__lazy_modules__`
   line in the importing module. The
   [external configuration](external-config.md) is for code you do
   not own, and for trying candidates before committing.

3. **A module only stays unloaded if every eager path to it is cut.**
   For rows marked `shared`, the other eager importers are listed:
   defer every one of them, or the cost moves to the next one rather
   than disappearing. The estimate already accounts for this.

4. **Prefer links whose imported name is only used inside functions
   and methods.** The profile cannot see this; reading the source for
   the candidate row is the check, and the triage table below is the
   order of questions.

5. **Take the largest estimated saving first, and re-profile between
   batches.** Deferring the top item changes the chains: the
   next-largest candidate is often a different one afterwards.

## Triage each candidate

For every edge you intend to change, answer in this order:

| Question | If yes | If no |
| --- | --- | --- |
| Is it a module-level `import x` or `import x as y`, ready on both routes? | continue | `from x import y` or `import a.b as c`: on 3.15+ continue; on older Pythons either rewrite to `import x` and use `x.y`, or accept the cost, judged on the size of the saving |
| Is the name used while the importing module itself is being imported (class bases, decorators, default arguments, annotations without `from __future__ import annotations`, module-level calls)? | **leave eager**, or move the use inside a function first | continue |
| Is the import inside `try/except ImportError` (an optional dependency)? | **leave eager**: laziness would move the error to first use, where nobody is listening for it | continue |
| Does the module have import-time side effects that must happen at start-up (registering handlers or plugins, patching, configuring logging, signal handlers)? | **leave eager** | continue |
| Is the first-use latency acceptable on the path that touches it (a request handler, a latency-critical loop)? | continue | consider warming it explicitly at a chosen point, or leave eager |
| For a shared row: do all the other eager importers also qualify? | **defer** | defer only if the remaining importers can be changed too |

The outcomes are exactly four: **defer**, **rewrite then defer**,
**leave eager**, or **move into a function** instead, the classic
alternative that is still the right answer when a whole feature is
optional.

How to spot each condition quickly in the source:

- Import-time use: search the module for the imported name outside
  function and method bodies. Class bases, decorators, default
  arguments and module-level calls all count; annotations count
  unless `from __future__ import annotations` is in effect.

- A guarded import: look for the statement inside a `try:` block with
  `except ImportError`.

- Side effects: open the imported module's top level and look for
  registration, patching and configuration calls.

The profile cannot see any of this; that is why it is the
[limits block](reading-the-report.md#limits-of-this-report) of every
report, and why the triage is yours.

## Apply

In code you own, declare the names in `__lazy_modules__`, before the
imports they govern, in each importing module:

```python
__lazy_modules__ = ["numpy", "myapp.analytics"]

import numpy
import myapp.analytics
```

A 3.15-only project can write `lazy import numpy` directly instead; a
mixed-support project cannot, because the older interpreters do not
know the syntax, which is exactly what `__lazy_modules__` is for.

In code you do not own, list the entries in the
[external configuration](external-config.md). On 3.15 the
configuration is the only route unwrapt applies; on older versions it
unions with the modules' own lists.

## Verify, iterate, guard

- **Verify.** Re-profile the same workloads and compare the totals;
  `python -m unwrapt.report before.json --compare after.json` diffs
  two JSON reports without re-running anything. Confirm the target
  module is no longer loaded at start-up by running the application
  with the shim active and checking `sys.modules`. Run the test
  suite on an older Python (the shim route) and on 3.15 (the native
  route).

- **Watch for the cost reappearing.** It may now be paid at first use
  somewhere surprising. Profile the first request or command, not just
  start-up, when that matters to the workload.

- **Iterate.** Second-order effects are normal: deferring one path
  exposes another import of the same heavy module, or the next chain
  link becomes the best cut. Stop at the stopping rule you set before
  the baseline.

- **Guard.** Keep the baseline JSON (or an import-time budget) in CI
  so a new eager import of a heavy module is noticed before it ships.
  The compare tool is the diff to run against it.

Anti-patterns to name:

- Deferring everything. Each deferral adds a failure mode (the error
  moves to first use) for a saving the report may show as zero.

- Deferring cheap imports for no measurable gain.

- Deferring where correctness depends on import order or on
  side effects happening at start-up.

- Adding laziness to silence a circular import: the cycle is still
  there, and it will bite at first use instead.

## The short form

1. Ask the target Python version or versions.

2. Take rows deferrable on the required routes, in descending
   cumulative time. For 3.15-only projects use the `3.15` column; for
   mixed support take rows true in both and treat the shim-limited
   rows as optional rewrites judged on the size of the saving.

3. For `shared` rows, proceed only if every module in
   `other_eager_importers` can also be deferred.

4. Before editing, read the importing module's source and check for
   import-time use of the name, and for `try/except ImportError`.

5. Add the module to `__lazy_modules__` in code you own, or to the
   [configuration](external-config.md) for code you do not.

6. Re-profile after each batch and compare the totals.
