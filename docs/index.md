# unwrapt

```{image} _static/unwrapt-logo.svg
:alt: unwrapt
:width: 480px
```

**Don't open it until you need it.**

Every `import` in your program is a present your program unwraps
immediately, whether or not it uses what is inside. unwrapt leaves the
wrapping on until first use: it defers whole-module imports until the
moment they are touched, cutting start-up time, without changing your
application's code.

Python 3.15 adds lazy imports (PEP 810): a `lazy import x` statement,
and a module-level `__lazy_modules__` list that keeps the imports it
names deferred while remaining ordinary valid code on older Pythons.
unwrapt brings the `__lazy_modules__` behaviour to Python 3.12 to 3.14,
emulating it on top of
[wrapt](https://github.com/GrahamDumpleton/wrapt) so the same source
behaves the same on every version. It is a sibling project to
[wrapt](https://github.com/GrahamDumpleton/wrapt) and
[autowrapt](https://github.com/GrahamDumpleton/autowrapt), and with
[autowrapt](https://github.com/GrahamDumpleton/autowrapt) installed one
environment variable activates it, with no application change.

It also ships a profile mode that measures what your imports actually
cost on a real run and reports what is worth deferring, on any Python
version including 3.15.

```{note}
unwrapt is in beta ahead of 1.0.0, with pre-releases published to
[PyPI](https://pypi.org/project/unwrapt/). Until 1.0.0 is final, a
plain `pip install unwrapt` picks up the latest pre-release
automatically, so there is no need to pin a specific version. Small
API changes are still possible before 1.0.0. What the beta series
needs now is use: reports of it working, or not, on real code, and of
what confused or was missing, go to the
[issue tracker](https://github.com/GrahamDumpleton/unwrapt/issues).
```

## What it does

On Pythons below 3.15, activated through
[autowrapt](autowrapt.md) or an explicit `unwrapt.install()`:

- Your modules mark whole-module imports to defer in their own
  `__lazy_modules__`, exactly as PEP 810 specifies: the same source is
  a lazy module on 3.15 and a deferred one below it, with unwrapt
  standing in for the interpreter's part.

- Each deferred import returns a lazy proxy instead of the module.
  First use imports the real module and swaps it into the importing
  namespace, so after first use there is no residual overhead.

- A [JSON configuration](external-config.md) defers imports in modules
  whose source you do not control.

On Python 3.15 and later the interpreter handles `__lazy_modules__`
natively, and unwrapt's job narrows to applying the external
configuration of extra deferrals, without ever touching native
behaviour: with no configuration, it installs nothing. See
[Python 3.15](python-3-15.md).

Alongside the deferral sits the [profile mode](profile-mode.md):
`UNWRAPT_PROFILE=1` records every import call of a real run, and the
report ranks candidates by cumulative time, shows the heavy modules by
self time, and draws the import chains that explain why each one
loaded, with every row marked for both routes (native 3.15 lazy
imports, and the shim). The
[choosing what to defer](choosing-what-to-defer.md) guide is the way
to turn that report into decisions.

```{toctree}
:maxdepth: 2
:caption: Start here

getting-started
```

```{toctree}
:maxdepth: 2
:caption: Using unwrapt

configuration
external-config
autowrapt
python-3-15
```

```{toctree}
:maxdepth: 2
:caption: The profile

choosing-what-to-defer
worked-example
profile-mode
reading-the-report
ai-assisted-tuning
```

```{toctree}
:maxdepth: 2
:caption: Reference

how-it-works
limitations
api
faq
release-notes
```

## Source, issues and releases

unwrapt is developed on GitHub at
[GrahamDumpleton/unwrapt](https://github.com/GrahamDumpleton/unwrapt),
under the BSD 2-Clause licence. Bug reports and feature requests go to
the [issue tracker](https://github.com/GrahamDumpleton/unwrapt/issues);
a report is easiest to act on when it names the unwrapt and Python
versions and includes a small application that reproduces the problem.
Releases are published to [PyPI](https://pypi.org/project/unwrapt/),
and each page of these docs carries an "Edit on GitHub" link to its
source under `docs/` in the repository, so a documentation fix can be
raised the same way.
