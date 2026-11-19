# Python 3.15

Python 3.15 provides PEP 810 lazy imports natively: a `lazy import x`
statement, the module-level `__lazy_modules__` list that keeps the
imports it names deferred, and the `sys.set_lazy_imports()` controls.
Everything a module declares for itself is the interpreter's business,
and unwrapt never competes with it.

## Which form to write

Write `__lazy_modules__`. It gives lazy loading on every Python
version unwrapt supports, with no change to the code: unwrapt emulates
it from 3.11 to 3.14, and the interpreter handles it natively from
3.15. The `lazy import x` statement is a syntax error before 3.15, so
a module written with it cannot be imported on the older versions at
all. Use the statement only in a project that supports nothing older
than 3.15.

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
  An eager `import x` in another module, while `x` is pending, is not
  a reification, and is told apart by the instruction its statement
  is at (see [the registry](#the-lazy-import-registry)), so a
  configuration entry for it applies as for any other statement.

- An explicit `lazy import x` statement is likewise native's, and is
  recognised the same way: the statement registers its binding in
  `sys.lazy_modules` too. So a configuration entry that duplicates
  either an explicit `lazy import` or a `__lazy_modules__` name is left
  to native, and `UNWRAPT_DEBUG=1` reports the overlap.

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

## The lazy import registry

`sys.lazy_modules` is the interpreter's set of lazy imports declared
but not yet loaded, and it is what both unwrapt layers read to
recognise native reifying an import. What it holds, verified on 3.15.0
and 3.15.1, default and free-threaded builds alike:

| Statement | Registered when the statement runs | The `__import__` call at first use |
| --- | --- | --- |
| `lazy import x`, or `import x` with `x` in `__lazy_modules__` | `x` | `("x", fromlist=None)` |
| `lazy from x import n` | `x.n` for each name, attributes included, and `x` only if it was not yet loaded | `("x", fromlist=("n",))` |
| `lazy from . import n` in package `p` | `p.n` (the package is always loaded by then) | `("p", fromlist=("n",))` |

A relative import is always reified with its absolute name and level
0, and each entry is removed once its import has been loaded. So a
call is a reification when its name is pending, or, for a from-import,
when any `name.n` for the names in its fromlist is. Early 3.15
pre-releases registered less (before 3.15.0a8 an explicit `lazy import`
left no entry at all), and are not what these facts describe.

The registry holds names, not the modules that declared them, and
three more facts follow from that, verified on 3.15.0:

- An eager `import x` in one module while another module has `x`
  pending also finds its name in the registry. It is told apart from a
  reification by the instruction its frame is at: an import statement
  that is not lazy calls `__import__` from `IMPORT_NAME`, while native
  reifies from the instruction that first loads the name
  (`LOAD_GLOBAL`, `LOAD_NAME` or `LOAD_ATTR`), or from C code. Both
  unwrapt layers read that instruction, and only for a pending name.

- Native reifies with the globals of the frame whose code first used
  the name, not those of the module that declared it: `modb` reading
  `moda.x` makes the call with `modb`'s globals. Nothing the hook is
  given names the declaring module, and the one place that does,
  `builtins.__lazy_import__` at the `lazy` statement, cannot be
  wrapped: a pass-through wrapper over it makes every `lazy import`
  fail with "only allowed at module level". So the profile credits
  such an import to the module that used it first.

- Once `x` has been loaded, by an eager import elsewhere for example,
  its entry is gone, but a binding declared lazy still reifies on its
  first use with an `__import__` call. That call has nothing pending,
  and is recorded as an ordinary already-loaded import by the module
  that used the binding.

## Profile mode on 3.15

The profiler does not neutralise native laziness, because the
mechanism that could (the `sys.set_lazy_imports_filter` hook) makes
the forced imports bypass `builtins.__import__` entirely, hiding them
from the recording hook: a worse measurement than the honest one.
Instead:

- A run with native laziness switched to all mode
  (`sys.get_lazy_imports()` not `normal`) is warned about at install,
  because every import it touches is then measured at first use.

- A native lazy import that is touched during the run, `lazy from`
  forms included, is recorded when native reifies it, at first use,
  recognised by its [registry entry](#the-lazy-import-registry),
  flagged `native_lazy` in the
  [JSON report](reading-the-report.md), marked already lazy, and
  explained by a warning block in the text report: the cost is real,
  but it is attributed to the module whose code first used the name,
  which is the declaring module unless another module reached the
  binding through it (see [the registry](#the-lazy-import-registry)),
  and the line is the site of first use.

- An eager import of a name another module has pending is recorded as
  the eager load it is, not as a native reification.

- A native lazy import never touched is never loaded, and so never
  appears in the report at all: the documented reason the guide says
  to profile an eager run for the baseline.

The verification steps in the [strategy guide](choosing-what-to-defer.md)
cover both routes: run the suite on an older Python with the shim, and
on 3.15 with native.
