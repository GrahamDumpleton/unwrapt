# AI-assisted tuning

The profile report is designed to be handed to an AI assistant, and
this page is the procedure for doing that: what to give the assistant,
what to ask for, and the prompt that does it. The method is the
[strategy guide](choosing-what-to-defer.md); this page is the same
method from the assistant's side of the table.

## What to provide

1. The JSON report from a profiled run
   (`UNWRAPT_PROFILE_FORMAT=json`), which carries the facts: per-edge
   timings, the tree links, the route columns and their reasons, the
   already-lazy flags, and the labels.

2. The same report rendered as text, with
   `python -m unwrapt.report report.json`. The JSON holds facts only,
   and the text carries the analysis computed from them: the summary
   figures, the shared importers of each candidate, the chains and
   their best cuts.

3. The target Python version or versions, which select the route
   columns to honour.

4. The source of the top importing modules named in the report: the
   files behind the `by importer` section and the importers of the top
   candidate rows, because the triage questions (import-time use,
   guarded imports, side effects) are answered in source, not in the
   report.

5. Whether each module is editable: in code you own, the
   `__lazy_modules__` route; otherwise the
   [external configuration](external-config.md).

## The JSON schema

The report the assistant receives is schema 2, described field by
field on [reading the report](reading-the-report.md#the-json-form):
`schema` (bumped if a field ever changes incompatibly), `unwrapt` and
`python` (versions), `labels` (what the report is of), `label_sets`,
`filters`, and `edges`, one object per import call or folded run of
already-loaded hits, with:

- `cum_ms` (the wall time of the call, the saving from deferring that
  line) and `self_ms` (the call's own cost, nested imports excluded);

- `parent_id` (the enclosing import call, so chains can be walked);

- `importer`, `imported`, `file` and `line`;

- `kind` (`import`, `from`, or `resolve` for a deferred import loaded
  at first use), `level` (module, function or class) and `relative`;

- `loaded` (first importer or cache hit) and `count` (how many calls a
  folded edge stands for);

- `defer.native` and `defer.unwrapt` (the route columns) and
  `defer.reason` (why the shim would not defer it: `function-level`,
  `class-level`, `relative`, `from-import`, `dotted-as`,
  `already-loaded`);

- `already_lazy`, `native_lazy` (recorded at native reification on
  3.15), `deferred` and `resolution` (handed back as a lazy proxy, in a
  profile with deferral on, and the resolve edge that loaded it, if
  any), and `resolves` and `used_in` on a resolve edge;

- `labels`, an index into `label_sets`.

## The consumption procedure

For the assistant, the method is the guide's:

1. Take the candidate rows deferrable on the required routes, in
   descending `cum_ms`. For a 3.15-only target, use `defer.native`;
   for a mixed-support target, take rows true in both, and treat the
   rows whose `defer.reason` is a form the shim cannot defer as
   optional rewrites judged on the size of the saving.

2. For rows the text report marks `shared`, proceed only if every
   listed importer can also be deferred.

3. For every edge you intend to change, read the importing module's
   source and answer the triage table in the guide: import-time use
   of the name, `try/except ImportError` guards, import-time side
   effects, first-use latency. The report cannot see any of these.

4. Return, per edge, the decision, the evidence and the exact edit.

## The prompt template

> You are tuning import time for a Python application. You will be
> given a JSON profile report from the unwrapt profiler, its text
> rendering, the target Python version or versions, and the source of
> the importing modules it names. Produce a deferral plan.
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
> - Do not propose an edge whose shared importers, as the text
>   report lists them, cannot also be deferred, unless you also defer
>   all of those.
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
