# Limitations

The honest list, each with its reason. Everything here is behaviour
the code actually has; where a limit has a route that escapes it
(Python 3.15, a rewrite), that is said too.

## Import forms the shim cannot defer

`from x import y` and `import a.b as c` stay eager under the shim on
every Python below 3.15. The bytecode fetches an attribute
(`IMPORT_FROM`) right after the import call, and the fetch resolves
the lazy proxy immediately, so the import is effectively eager
however the hook answers. The hook cannot see the `as`, so it cannot
tell `import a.b as c` from the deferrable `import a.b`. Native 3.15
lazy imports defer both forms, and the profile report marks each row
for both routes, with the rewrite (`import x`, then `x.y`) documented
in the [strategy guide](choosing-what-to-defer.md).

Plain `import x`, `import x as y` and `import a.b` defer fine.

## Only module-level statements

Function bodies and class bodies are left alone: the hook sees
different arguments there and passes through. Function-level imports
are already deferred until the function runs, so nothing is lost;
class-level imports are rare and the hook errs on the side of not
surprising anyone.

## Guarded optional dependencies

A `try/except ImportError` around an import is invisible to the hook.
Deferring such an import moves the ImportError from the statement,
where the guard listens, to first use, where nothing does. Do not
list guarded imports in `__lazy_modules__` or in the
[configuration](external-config.md); the strategy guide makes it a
triage rule.

## Already-imported modules are returned as-is

An import whose module is already in `sys.modules` is passed through
unchanged. In particular, wrapt itself, which the hook's installation
imports, pulls in a fixed set of standard library modules (json,
inspect, copy, subprocess, functools and friends), and exactly which
ones varies by Python version. Those modules can never be deferred in
a process running the shim, and the module you defer for a demo should
be one nothing preloads. The same rule applies to anything imported
before the bootstrap runs, by definition of the bootstrap.

## Laziness is never a correctness property

Older Pythons import eagerly unless the shim is active, and even with
it active the program may be run without it. Never rely on laziness
for correctness: import side effects that only happen eagerly,
circular imports that only work lazily, and error timing all behave
differently, and an ImportError surfaces at first use instead of at
the import statement.

## What the hook cannot see

`importlib.import_module`, the C import API, and imports that happen
before the bootstrap: none of them are deferred. The first and the
last never pass through the hook. An extension module's imports
through the C API do, but they arrive with the globals of the import
system's own frame rather than those of a module with a
`__lazy_modules__`, so nothing marks them; the profile credits them to
the extension, and marks them `extension-module`, deferrable by
neither route. The profile report records what passes through the
hook, and its limits block says the same about the measurement.

The profile looks for an import's statement as the nearest frame,
from the hook's caller up, whose globals are the ones the import was
given, which finds it through a hook that wraps `builtins.__import__`
over the recorder and passes calls on. It looks at most eight frames
up, and a wrapper that passes other globals than the statement's has
its own frame recorded as the place instead.

On Python 3.15 a native lazy import is recorded when native reifies
it, and is credited to the module whose code first used the name:
native passes that module's globals, and nothing visible to the hook
names the declaring module, so `modb` reading `moda.x` shows as `modb`
importing `x`. See
[the lazy import registry](python-3-15.md#the-lazy-import-registry).

The profile's check for an import used while its importer loads reads
the importer's source, so it sees only uses the source spells out:
a name reached through `getattr()` or `globals()` is not seen until
the import is deferred, when the deferral sections report the resolve
as used at load.

The submodules a `from` import loads (`from . import json`, which
loads `flask.json`) do not pass through the hook either: the import
system loads them directly once the statement's own import returns.
The profile names them on the `from` import's edge, which carries
their time, except for those that `from x import *` brings in through
a package's `__all__`, which are not named.

## Per-import overhead

Every import statement in the process passes through the hook while
the shim is installed. The non-deferred path exits early on cheap
checks and stays small, but it is not zero, and a profile run adds
the recording overhead on top. The report's own limits block says the
same about its figures.

## Copies made before first use

Reification rewrites the namespace of the module whose statement was
deferred, and only that namespace. A proxy copied elsewhere before
first use, assigned to another name or bound inside a container,
remains a proxy and still works, with the small proxy overhead.
