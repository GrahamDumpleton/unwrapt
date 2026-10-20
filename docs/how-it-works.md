# How it works

unwrapt's shim is one function standing between every import statement
in the process and the import system. This page is the reference for
what that function does; the [limitations](limitations.md) page
covers what it cannot.

## Activation

`unwrapt.install()` is the switch. It is idempotent, it reads the
[environment](configuration.md) once to pick the mode, and it never
installs anything when there is nothing to do. With
[autowrapt](autowrapt.md) and `AUTOWRAPT_BOOTSTRAP=unwrapt`, the
callback runs at interpreter startup, before the application's own
imports; called directly, it takes effect from wherever it was called.

Importing the unwrapt package itself is inert: no hook, no wrapt
import, no side effects. The build backend imports it to read the
version, so anything heavier would break that, and the autowrapt
entry point loads the package before calling into it.

## The hook

The shim replaces `builtins.__import__` with a plain function, not a
wrapt function wrapper, because every import statement in the process
passes through it and the per-import cost has to stay down. Whatever
import function was installed before it (an APM agent, a coverage
tool, anything) is captured and chained to, so those keep working
unchanged.

An import is deferred only when every rule holds, cheapest checks
first so the pass-through path stays fast:

- It is absolute: `level == 0`.

- It is a whole-module import: the fromlist is empty. The eval loop
  passes `None` for a plain `import x` and a tuple for
  `from x import y`, so emptiness, not identity, is the test.

- It is a module-level statement: `globals` is not None and `locals is
  globals`. Function bodies pass None for locals and class bodies pass
  the class namespace, so neither is deferred.

- The module is not already in `sys.modules`: an already-loaded module
  is returned unchanged, nothing to defer.

- It is a candidate: named in the importing module's own
  `__lazy_modules__` (below 3.15) or in the external
  [configuration](external-config.md) (every version), per the
  version rules below.

On Python 3.15 and later one further rule comes first: a name with a
pending native lazy binding is native's business and passes through.
See [Python 3.15](python-3-15.md) for why.

Everything else chains unchanged to the import function the hook
replaced.

## Candidates

`__lazy_modules__` is read at call time, from the importing module's
own globals, so exactly as in PEP 810 it must be assigned before the
imports it governs. A list, tuple, set, frozenset or dict works:
membership is tested with `in`. The matching rule is an exact match
on the full dotted name, verified against the 3.15 implementation: a
listed `xml.dom` defers `import xml.dom`, while a listed `xml` does
not cover it and a listed `xml.dom` does not cover `import xml`.

Below 3.15, either source makes an import a candidate: the module's
own `__lazy_modules__` or the external configuration. With
`UNWRAPT_CONFIG_ONLY` set, only the configuration is consulted, which
is the A/B switch for experiments. From 3.15 the configuration is the
only source, always.

## The proxy and the resolve

A deferred import returns a `wrapt.LazyObjectProxy` built on a resolve
callback, standing in for the top-level package the statement binds:
`import a.b.c` binds `a`, so the proxy stands in for `a` while the
resolve imports the full dotted name.

On first use, the callback:

1. imports the module, through `importlib.import_module`, which does
   not pass through `builtins.__import__`, so a resolve can never be
   deferred again by the hook;

2. takes the object the statement would have bound, which for a
   dotted import is the top-level package, and

3. reifies, below.

The proxy behaves as the module through wrapt's object proxy
machinery, and `isinstance` checks work because wrapt proxies
`__class__`, which resolves the proxy as a side effect: that is the
point of first use. Strict C-level checks may differ: `x is
sys.modules["x"]` is false before reification, and
`type(x) is types.ModuleType` is false until the proxy is resolved.

wrapt synchronizes the first resolve, so two threads touching the
same proxy resolve it once, consistently, and the resolve never
caches a failure: a module whose import raises propagates the
ImportError to the code that touched the proxy, and the next touch
tries again.

## Reification

On first resolve, unwrapt scans the importing module's namespace and
replaces every entry whose value is the proxy with the real module:

```python
for key, value in list(caller_globals.items()):
    if value is proxy:
        caller_globals[key] = module
```

That is PEP 810's no-residual-overhead behaviour: after first use the
name holds the module itself, and a resolved proxy costs nothing
further. The cost is one scan per proxy, at first use, and only the
namespace of the module whose statement was deferred is fixed. Copies
made before first use, an assignment to another name or a value bound
inside a container, stay proxies and still work, with the small proxy
overhead.

## What cannot be deferred, and why

Two import forms cannot be deferred by the shim, on any Python below
3.15, and the reason is in the bytecode:

- `from x import y` compiles to an import call followed by an
  immediate attribute fetch (`IMPORT_FROM`). The fetch on the proxy
  resolves it, so the import is effectively eager.

- `import a.b as c` compiles to the same import call followed by the
  same `IMPORT_FROM b`, so it is eager for the same reason. Plain
  `import a.b`, which binds the top package, defers fine; so does
  `import x as y`.

The hook cannot see the `as`, so it cannot tell the two apart; the
[profile report](reading-the-report.md) reads the source line to
flag `import a.b as c` rows precisely.

One more caution the hook cannot do anything about: a
`try/except ImportError` around an import is invisible to it, so
deferring a guarded optional dependency moves the ImportError from
the statement to first use. Do not list those; the
[strategy guide](choosing-what-to-defer.md) makes it a triage rule.

## Python version rules

| Python | What the shim defers | What it never does |
| --- | --- | --- |
| 3.12 to 3.14 | `__lazy_modules__` plus the external configuration (or the configuration alone with `UNWRAPT_CONFIG_ONLY`) | read native controls that do not exist there |
| 3.15 and later | the external configuration only | read `__lazy_modules__`, call `sys.set_lazy_imports` or its filter, alter native behaviour in any way |

From 3.15, with no configuration there is nothing for unwrapt to do,
so nothing is installed and nothing is warned: running the bootstrap
on 3.15 with no configuration is a normal, harmless setup. The
[Python 3.15](python-3-15.md) page covers the mode in depth.

## Safety

The hook never raises from its own bookkeeping: only the underlying
import's exceptions propagate, so an import never behaves differently
merely because unwrapt is installed. Configuration mistakes warn once
on stderr and fall back to defaults, because a bad setting must never
stop the host application from starting. And unwrapt does no network
access and writes no files, other than the profile report when
[profile mode](profile-mode.md) is asked to write one.
