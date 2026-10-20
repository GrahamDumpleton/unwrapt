# AI-assisted tuning

The profile report is designed to be handed to an AI assistant, and
this page is the procedure for doing that: what to give the assistant,
what to ask for, and the prompt that does it. The method is the
[strategy guide](choosing-what-to-defer.md); this page is the same
method from the assistant's side of the table.

## What to provide

1. The JSON report from a profiled run
   (`UNWRAPT_PROFILE_FORMAT=json`), which carries everything the
   assistant needs: per-edge timings, the tree links, the route
   columns, the shared importers, and the already-lazy flags.

2. The target Python version or versions, which select the route
   columns to honour.

3. The source of the top importing modules named in the report: the
   files behind the `by importer` section and the importers of the top
   candidate rows, because the triage questions (import-time use,
   guarded imports, side effects) are answered in source, not in the
   report.

4. Whether each module is editable: in code you own, the
   `__lazy_modules__` route; otherwise the
   [external configuration](external-config.md).

## The JSON schema

The report the assistant receives has this shape: `schema` (bumped if
the structure ever changes incompatibly), `unwrapt` and `python`
(versions), `total_import_ms`, and four sections:

- `edges`: one object per import call, with `cum_ms` (the wall time
  of the call, the saving from deferring that line), `self_ms` (the
  call's own cost, nested imports excluded), `parent_id` (the
  enclosing import call, so chains can be walked), `kind` (`import`
  or `from`), `level` (module, function or class), `loaded` (first
  importer or cache hit), `deferrable.native` and `deferrable.unwrapt`
  (the route columns), `unwrapt_limit` (the reason a route cannot:
  `from-import`, `dotted-as`, `function-level`, `class-level`),
  `already_lazy`, `native_lazy` (recorded at native reification on
  3.15), and `other_eager_importers` (the shared note).

- `heavy_modules`: by self time.

- `chains`: for the heaviest modules, the `links` (edge ids,
  outermost first) and the `best_cut` edge id, or null.

- `by_importer`: cumulative time of each module's direct loads.

The summary carries `best_cut`, the conservative
`estimated_saving_ms` (never a sum across nested edges), and the
`filters` the report was built with.

## The consumption procedure

For the assistant, the method is the guide's:

1. Take the edges deferrable on the required routes, in descending
   `cum_ms`. For a 3.15-only target, use `deferrable.native`; for a
   mixed-support target, take edges true in both, and treat the
   `unwrapt_limit` edges as optional rewrites judged on the size of
   the saving.

2. For edges with `other_eager_importers`, proceed only if every
   listed importer can also be deferred.

3. For every edge you intend to change, read the importing module's
   source and answer the triage table in the guide: import-time use
   of the name, `try/except ImportError` guards, import-time side
   effects, first-use latency. The report cannot see any of these.

4. Return, per edge, the decision, the evidence and the exact edit.

## The prompt template

> You are tuning import time for a Python application. You will be
> given a JSON profile report from the unwrapt profiler, the target
> Python version or versions, and the source of the importing modules
> it names. Produce a deferral plan.
>
> For each edge you propose to change, return three things:
>
> - **the decision**, exactly one of: defer, rewrite then defer,
>   leave eager, or move into a function;
>
> - **the evidence**, quoting the source that justifies it: the use
>   of the imported name at import time, a `try/except ImportError`
>   guard, an import-time side effect, or the absence of all three;
>
> - **the exact edit**: a `__lazy_modules__` line for code the
>   application owns, a configuration entry for code it does not, or
>   the rewrite for a shim-limited form.
>
> Rules:
>
> - Do not propose deferring any edge the triage table says to leave
>   eager: an import used while the importing module is being
>   imported, a guarded optional dependency, or a module with
>   import-time side effects that start-up depends on.
>
> - Do not propose an edge whose `other_eager_importers` cannot also
>   be deferred, unless you also defer all of those.
>
> - Rank by `cum_ms`, not `self_ms`; the chain's best cut outranks a
>   deeper link.
>
> - Never sum `cum_ms` across edges that are ancestors or descendants
>   of each other; the estimate is the report's, not yours to
>   recompute.
>
> - Say so plainly when the honest answer is that a candidate is not
>   worth deferring.
>
> A human reviews every edit and re-profiles after each batch; your
> plan is the proposal, not the change.

## What the human does with the answer

Reviews the evidence for each decision, applies the edits (or asks
for the configuration file whole), re-runs the workload under profile
mode, and compares: `python -m unwrapt.report before.json --compare
after.json`. The [strategy guide](choosing-what-to-defer.md) covers
the guard step that keeps the win from regressing, and the
[worked example](worked-example.md) shows the whole loop once.
