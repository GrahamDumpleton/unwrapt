# FAQ

**Why does `from x import y` stay eager?**

The bytecode. `from x import y` compiles to an import call followed
immediately by an attribute fetch (`IMPORT_FROM`), and the fetch
resolves the lazy proxy: whatever the hook hands back, the statement
needs an attribute of the real module before it finishes. Native 3.15
lazy imports defer the form, and the profile report marks every such
row for both routes; on older Pythons the rewrite (`import x`, then
`x.y` where it is used) opens it. See
[limitations](limitations.md).

**Why does `import a.b as c` stay eager but `import a.b` defer?**

The same attribute fetch, and the hook cannot see the `as`: both
compile to the same import call, and the `as` form adds the fetch
after it. The report reads the source line to tell them apart.

**Why is my deferred module already in `sys.modules`?**

Something imported it before the statement the hook deferred, most
often wrapt itself or the standard library modules wrapt imports (a
fixed set including json, inspect, copy and subprocess), or anything
imported before the bootstrap ran. Already-imported modules are
returned unchanged; pick a module nothing preloads, or a purpose-built
one. See [limitations](limitations.md).

**What does `import a.b.c` actually defer?**

The statement binds `a`, so the proxy stands in for the top-level
package while the resolve imports the full dotted name on first use.
After first use the importing module's `a` holds the real package.

**Can I rely on laziness for correctness?**

No. Older Pythons import eagerly without the shim, and even with it
the program can be run without it. Import side effects happen at a
different time, circular imports that only work lazily bite at first
use, and an ImportError moves from the import statement to the first
touch. Laziness is a start-up optimization, never a semantic property.

**What happens if the deferred import fails?**

The ImportError or ModuleNotFoundError propagates to the code that
first touched the proxy, exactly as if the import statement had run
there. The failure is not cached: the next touch tries the import
again. Inside a `try/except ImportError` in the importing module,
however, the guard is long gone by then, which is why guarded optional
dependencies must not be deferred.

**Why is json never deferred in my process?**

wrapt imports it, and the hook's installation imports wrapt. The same
holds for a small, Python-version-dependent set of standard library
modules; see [limitations](limitations.md).

**Do I need autowrapt?**

Only for zero-application-change injection. `unwrapt.install()`
called directly does the same thing from wherever you call it; the
difference is ordering, since the bootstrap runs before the
application's imports. autowrapt is never a dependency of unwrapt.

**What does unwrapt do on Python 3.15?**

The interpreter provides the lazy import machinery natively, so
unwrapt narrows to applying the [external
configuration](external-config.md) of extra deferrals, and installs
nothing without one. It never reads a module's `__lazy_modules__`
there and never alters native behaviour. See
[Python 3.15](python-3-15.md).

**Why is my profile's total import time different every run?**

Per-import timing overhead and machine noise, mostly. Compare like
with like, take a representative run as the baseline, and read
relative sizes rather than absolute milliseconds; the report's limits
block says the same, and `python -X importtime` is a useful
cross-check.

**Why does the report show a module I never imported directly?**

Something you imported imported it: the import chains exist to show
you the path. The candidate rows rank where to cut, and the chain
shows what the cut removes.

**Is the proxy expensive after first use?**

No: on first resolve, unwrapt rewrites the importing module's
namespace to hold the real module, so from that point the name costs
nothing. Only copies made before first use stay proxies. See
[how it works](how-it-works.md).
