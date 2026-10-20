# Getting started

unwrapt is on PyPI. Add it to a project:

```console
$ uv add unwrapt
```

or:

```console
$ pip install unwrapt
```

For the zero-application-change activation, add the companion that
injects it at interpreter startup (never a dependency of unwrapt):

```console
$ pip install autowrapt
```

Everything on this page can be run in place. The interpreter
transcripts assume a working directory you can write to; save each
application to a file there and run it as shown.

## Your first deferral

Write a one-file application that declares an import lazy in its own
source, exactly as PEP 810 specifies. The `__lazy_modules__` list is
ordinary valid code on every Python version: on 3.15 the interpreter
handles it natively, and below 3.15 unwrapt does.

```python
# app.py

import sys

__lazy_modules__ = ["xml.dom"]
import xml.dom

print("loaded at startup:", "xml.dom" in sys.modules)

node = xml.dom.Node

print("loaded after use:", "xml.dom" in sys.modules)
```

Run it with the bootstrap, and nothing else changes:

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt python app.py
loaded at startup: False
loaded after use: True
```

Without `AUTOWRAPT_BOOTSTRAP=unwrapt` the same application imports
xml.dom eagerly at startup, on any Python below 3.15. On 3.15 the
interpreter defers the import itself, with or without unwrapt: there,
unwrapt only matters for the [external configuration](external-config.md).

## What just happened

The `import xml.dom` statement returned a lazy proxy instead of the
xml package: a stand-in built on wrapt that behaves as the module
everywhere it is passed, and imports the real module the first time it
is used. `xml.dom.Node` was that first use. The proxy then swapped
itself out of the application's namespace, so the name `xml` holds
the real module from that point on, with no residual proxy overhead.

Check the swap directly:

```python
# swapcheck.py

import sys, types
import unwrapt

unwrapt.install()

__lazy_modules__ = ["csv"]
import csv as csv_mod

print("before use:", type(csv_mod).__name__)

rows = list(csv_mod.reader(["a,b"]))

print("after use:", type(csv_mod) is types.ModuleType)
print("is the real module:", csv_mod is sys.modules["csv"])
```

```console
$ python swapcheck.py
before use: LazyObjectProxy
after use: True
is the real module: True
```

This run called `unwrapt.install()` itself, which is the explicit
activation for when autowrapt is not an option: a test suite, a
notebook, a single process you control. The install is idempotent, and
importing unwrapt alone never installs anything.

## Deferring an import you cannot edit

The same deferral works on modules whose source you do not control,
through a JSON configuration. Write one:

```json
{
    "__main__": ["decimal"]
}
```

Save it as `lazy.json` beside an application that imports decimal,
with no mention of laziness anywhere in the application:

```python
# eagerapp.py

import decimal

print("loaded at startup:", "decimal" in sys.modules)

value = decimal.Decimal(1)

print("loaded after use:", "decimal" in sys.modules)
```

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_CONFIG=lazy.json python eagerapp.py
loaded at startup: False
loaded after use: True
```

The configuration maps each importer's module name to the names it
should defer; see the [external configuration](external-config.md)
page for the format and rules.

## Finding what is worth deferring

Deferring a module nobody uses is easy. Finding which imports actually
cost something is the hard part, and that is what the profile mode
does. Run any application under it:

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_PROFILE=1 python app.py
```

The report prints at exit: a summary header, the candidate imports
ranked by cumulative time, the heavy modules by self time, the cost by
importing module, and the chains of imports that explain why each
heavy module loaded. Each candidate row shows whether native 3.15
lazy imports can defer it (the `3.15` column) and whether the shim
can (the `unwrapt` column), with the reasons spelled out.

Turn the report into decisions with the
[choosing what to defer](choosing-what-to-defer.md) guide; the
[worked example](worked-example.md) walks a sample application end to
end with it.

## Where to go next

- [Configuration](configuration.md): every environment variable, in one
  place.

- [How it works](how-it-works.md): the hook, the proxy, the
  reification, and the rules that decide what is deferred.

- [Python 3.15](python-3-15.md): what native lazy imports change, and
  what unwrapt does there.

- [Limitations](limitations.md): the honest list, including the import
  forms the shim cannot defer.
