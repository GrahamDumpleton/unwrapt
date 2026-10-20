<img src="https://raw.githubusercontent.com/GrahamDumpleton/unwrapt/develop/docs/_static/unwrapt-logo.svg" alt="unwrapt" width="240">

# unwrapt

**Don't open it until you need it.**

[![Tests](https://github.com/GrahamDumpleton/unwrapt/actions/workflows/build-test-release.yml/badge.svg?branch=develop)](https://github.com/GrahamDumpleton/unwrapt/actions/workflows/build-test-release.yml)
[![Documentation](https://readthedocs.org/projects/unwrapt/badge/?version=latest)](https://unwrapt.readthedocs.io)

Every `import` in your program is a present your program unwraps
immediately, whether or not it uses what is inside. unwrapt leaves the
wrapping on until first use. It defers whole-module imports until the
moment they are touched, cutting start-up time, without changing your
application's code.

Python 3.15 adds lazy imports (PEP 810): a `lazy import x` statement,
and a module-level `__lazy_modules__` list that keeps the imports it
names deferred while remaining ordinary valid code on older Pythons.
unwrapt brings the `__lazy_modules__` behaviour to Python 3.12 to 3.14,
emulating it on top of [wrapt](https://github.com/GrahamDumpleton/wrapt)
so that the same source behaves the same on every version, and it
ships a profile mode that measures what your imports actually cost and
reports what is worth deferring, on any version including 3.15.

It is a sibling project to [wrapt](https://github.com/GrahamDumpleton/wrapt)
and
[autowrapt](https://github.com/GrahamDumpleton/autowrapt), and works
without changing your application code: with
[autowrapt](https://github.com/GrahamDumpleton/autowrapt) installed,
one environment variable activates it.

> **Status: alpha, ahead of 1.0.0.** Pre-releases are published to
> PyPI, and until 1.0.0 is final a plain `pip install unwrapt` picks
> up the latest pre-release automatically, so there is no need to pin
> a specific version. Small API changes are still possible before
> 1.0.0. Reports of it working, or not, on real code, and of what
> confused or was missing, go to the
> [issue tracker](https://github.com/GrahamDumpleton/unwrapt/issues).

## Installation

unwrapt is on [PyPI](https://pypi.org/project/unwrapt/):

```console
$ pip install unwrapt
```

or with uv:

```console
$ uv add unwrapt
```

autowrapt is the companion that injects unwrapt at interpreter startup
without any application change. It is deliberately not a dependency of
unwrapt; install it alongside the application you want to affect:

```console
$ pip install autowrapt
```

## At a glance

Your module declares what to defer, exactly as PEP 810 specifies, and
the code stays valid on every Python version:

```python
# app.py

__lazy_modules__ = ["xml.dom"]
import xml.dom

print("loaded at startup:", "xml.dom" in sys.modules)  # False

xml.dom.Node  # first use unwraps it

print("loaded after use:", "xml.dom" in sys.modules)  # True
```

Run it with the bootstrap, and nothing else changes:

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt python app.py
```

The import returns a lazy proxy instead of the module; the first use
of the name imports the real module and swaps it into place, so after
first use there is no residual overhead. On Python 3.15 the
interpreter does all of this natively and unwrapt is not involved.

## What it does

- **Shim mode (Python 3.12 to 3.14).** With
  `AUTOWRAPT_BOOTSTRAP=unwrapt`, unwrapt replaces
  `builtins.__import__` with a hook that returns a wrapt lazy proxy
  for each whole-module import your modules mark in their own
  `__lazy_modules__`, reifying on first use. Chained to whatever
  import wrappers were already installed, cheap on the pass-through
  path, and never raising from its own bookkeeping.

- **Wrapping things you can't edit.** A JSON configuration names
  imports to defer in modules whose source you do not control:
  `UNWRAPT_CONFIG=lazy.json`. On Python 3.15 and later this is the
  only thing unwrapt does: the interpreter handles `__lazy_modules__`
  natively, unwrapt never touches it or native behaviour, and with no
  configuration it installs nothing at all.

- **Peeking at the label.** `UNWRAPT_DEBUG=1` logs each deferred
  import to stderr, and the active mode at startup.

- **Finding what is worth wrapping.** `UNWRAPT_PROFILE=1` records
  every import call of a real run, with timings and the tree of nested
  imports, and reports the candidates ranked by cumulative time, the
  heavy modules by self time, the import chains that explain why each
  one loaded, and the best cut in each chain. Every row shows both
  routes: what native 3.15 lazy imports can defer, and what the shim
  can, with the reasons spelled out. The report comes as text or JSON,
  and the [choosing what to
  defer](https://unwrapt.readthedocs.io/en/latest/choosing-what-to-defer.html)
  guide is the way to turn it into decisions.

## What it is not

- **Not a replacement for PEP 810.** On 3.15+ the interpreter is the
  mechanism; unwrapt only applies the external configuration there,
  and never reads `__lazy_modules__` or alters native behaviour.

- **Not a source rewriter.** Nothing about your files changes; the
  profile mode only reports.

- **Not able to defer every import form.** `from x import y` and
  `import a.b as c` stay eager under the shim on Pythons below 3.15:
  the attribute fetch resolves the proxy immediately. The profile
  flags exactly these rows, deferrable natively on 3.15 but not by the
  shim, and the guide covers the rewrite.

## Known limitations

- `from x import y` and `import a.b as c` stay eager in shim mode.

- Only module-level imports are considered. Function bodies and class
  bodies are left alone (function-level imports are already deferred
  until the function runs).

- A `try/except ImportError` around an import is invisible to the
  hook: deferring a guarded optional dependency moves its ImportError
  to first use. Do not list those.

- Already-imported modules are returned as-is. In particular, wrapt
  itself and the standard library modules it imports (json, inspect,
  copy, subprocess and friends) are always in sys.modules before the
  hook goes in, so they can never be deferred in a process running
  unwrapt.

- Older Pythons import eagerly without unwrapt. Never rely on
  laziness for correctness: import side effects and circular imports
  that only work lazily behave differently, and errors surface at
  first use instead of at the import statement.

- Imports through `importlib.import_module`, the C import API, and
  anything imported before the bootstrap runs are unaffected.

- There is per-import hook overhead for every import statement in the
  process while the shim is installed; the non-deferred path exits
  early and stays small, but it is not zero.

- Proxies copied elsewhere before first use (assigned to another name,
  bound into a container) remain proxies and still work, with the
  small proxy overhead.

## Documentation

Full documentation is at [unwrapt.readthedocs.io](https://unwrapt.readthedocs.io).
Start with the [getting started](https://unwrapt.readthedocs.io/en/latest/getting-started.html)
page: everything on it can be pasted into a Python interpreter. For
the profile mode, start with the [choosing what to
defer](https://unwrapt.readthedocs.io/en/latest/choosing-what-to-defer.html)
strategy guide, which turns the report into decisions step by step.

## Developed with AI

This package was developed with the help of AI coding assistants,
working to the author's design and direction, with the author
reviewing what they produce. If you would rather not use software
produced that way, that is understood, and this package is not for
you.

## Requirements

- Python 3.12 or later.

- wrapt 2.4.1 or later.

- For zero-code injection: autowrapt 2.0 or later (not a dependency of
  unwrapt).

## Issues

Bug reports and feature requests go to the
[issue tracker](https://github.com/GrahamDumpleton/unwrapt/issues).
A report is easiest to act on when it names the unwrapt and Python
versions and includes a small application that reproduces the problem.

## License

BSD 2-Clause, see [LICENSE](LICENSE).
