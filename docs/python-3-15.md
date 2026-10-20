# Python 3.15

Python 3.15 provides PEP 810 lazy imports natively: a `lazy import x`
statement, the module-level `__lazy_modules__` list that keeps the
imports it names deferred, and the `sys.set_lazy_imports()` controls.
Everything a module declares for itself is the interpreter's business,
and unwrapt never competes with it.

## What unwrapt does there

One thing: the [external configuration](external-config.md). It is
the only candidate source on 3.15 and later, and supplying it is
itself the opt-in; there is no force switch. In
external-config-only mode the hook defers exactly the imports the
configuration names, in modules that are not otherwise declared lazy,
and leaves everything else to the interpreter:

- A module's own `__lazy_modules__` is never read. The interpreter
  handles it, deferring those imports without ever calling the hook,
  so the hook only sees such an import if native reifies it, at first
  use, and it recognises that call by the pending binding in
  `sys.lazy_modules` and passes it straight through: native expects
  the real module back, and deferring it again would hand it a proxy.

- An explicit `lazy import x` statement is likewise native's. A
  configuration entry that duplicates one cannot be detected (the
  statement leaves no registry entry), so do not write those: the
  entry would interfere with native's reification. Entries duplicating
  a `__lazy_modules__` name are handled automatically, and
  `UNWRAPT_DEBUG=1` reports the overlap.

- With no configuration, unwrapt installs nothing: no hook, no
  overhead, no warning. Running the bootstrap on 3.15 with no
  configuration is a normal, harmless setup; with `UNWRAPT_DEBUG=1`
  the debug line says so.

- unwrapt never calls `sys.set_lazy_imports` or its filter, never
  changes the mode, and never alters native behaviour in any way.

Everything else about the shim is unchanged on 3.15: the same
eligibility rules, the same proxy, the same reification, the same
limits, so `from x import y` and `import a.b as c` stay eager under
unwrapt there too (native can defer the from-import form itself, for
names the code declares).

## A worked example

The [python-3-15-demo](https://github.com/GrahamDumpleton/unwrapt/tree/develop/examples/python-3-15-demo)
example runs both routes side by side:

```python
lazy import colorsys

import decimal
```

with `UNWRAPT_CONFIG=lazy.json` naming decimal:

```json
{"__main__": ["decimal"]}
```

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_CONFIG=lazy.json python app.py
native deferred colorsys: True
unwrapt deferred decimal: True
```

colorsys stays deferred with no help from unwrapt, decimal is
deferred by the configuration, and `UNWRAPT_DEBUG=1` states the
active mode once:

```
unwrapt: external-config-only mode installed
```

This is the shape of trying a profile report's candidate list on
3.15: put the candidates in a configuration, run, measure, and only
the ones that survive the [strategy guide](choosing-what-to-defer.md)
triage become `__lazy_modules__` lines or `lazy import` statements in
the source.

## Profile mode on 3.15

The profiler does not neutralise native laziness, because the
mechanism that could (the `sys.set_lazy_imports_filter` hook) makes
the forced imports bypass `builtins.__import__` entirely, hiding them
from the recording hook: a worse measurement than the honest one.
Instead:

- A run with native laziness switched to all mode
  (`sys.get_lazy_imports()` not `normal`) is warned about at install,
  because every import it touches is then measured at first use.

- A native lazy import that is touched during the run is recorded
  when native reifies it, at first use, flagged `native_lazy` in the
  [JSON report](reading-the-report.md), marked already lazy, and
  explained by a warning block in the text report: the cost is real
  and attributed to the importing module, but the line is the site of
  first use.

- A native lazy import never touched is never loaded, and so never
  appears in the report at all: the documented reason the guide says
  to profile an eager run for the baseline.

The verification steps in the [strategy guide](choosing-what-to-defer.md)
cover both routes: run the suite on an older Python with the shim, and
on 3.15 with native.
