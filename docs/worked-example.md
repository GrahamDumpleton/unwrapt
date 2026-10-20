# Worked example

A complete run of the [strategy guide](choosing-what-to-defer.md) on
the sample application in
[examples/worked-example](https://github.com/GrahamDumpleton/unwrapt/tree/develop/examples/worked-example),
which the CI suite runs on every push, so what this page says the
report shows is what it actually shows. The application is shaped like
a small real one:

- `myapp/__main__.py`: the entry point, importing sqlite3, xml.dom and
  two of its own modules eagerly.

- `myapp/web.py`: imports decimal and `myapp.analytics`.

- `myapp/analytics.py`: imports xml.dom, which the entry point imports
  too: the shared case.

- `myapp/client.py`: a from-import (`from difflib import
  SequenceMatcher`) and an import (wave) that the workload never
  touches.

## The baseline

From the example directory, with the same bootstrap the shim uses
(`pip install autowrapt` once):

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_PROFILE=1 UNWRAPT_PROFILE_FORMAT=json \
    UNWRAPT_PROFILE_OUTPUT=before.json python -m myapp
$ python -m unwrapt.report before.json
```

The shape of what comes back (abridged; the figures are illustrative,
the assertions in CI are not):

```
Summary: 9.4 ms total import time, 13 modules loaded, 47 edges
Estimated saving if every deferrable edge were deferred: 8.8 ms (conservative; edge times nest and are not additive)
Best single cut: __main__ -> myapp.web (3.2 ms cumulative)

Candidates: module-level imports, ranked by cumulative time
  cum ms  self ms  imported         imported by   3.15  unwrapt  notes
     3.2      0.1  myapp.web        __main__        yes      yes
     3.0      0.1  myapp.analytics  myapp.web       yes      yes
     1.9      1.9  sqlite3          __main__        yes      yes
     1.2      0.2  xml.dom          __main__        yes      yes  shared (+1: myapp.analytics)
     0.6      0.4  decimal          myapp.web       yes      yes
     0.5      0.5  wave             myapp.client    yes      yes
     0.3      0.3  difflib          myapp.client    yes   no (1)
```

## Reading it

Top-down, per the guide: the summary says the imports are most of the
start-up; heavy modules name sqlite3, xml and decimal; the chain for
xml runs from the entry point through web and analytics down to the
load; the candidates rank the entry point's own `import myapp.web` on
top, a thin wrapper pulling in a nest.

The triage, in the guide's order:

- `myapp.web` and `myapp.analytics`: module-level plain imports, used
  only inside functions after import. **Defer**, in the modules that
  import them. (Or defer the entry point's `import myapp.web` alone:
  the chain's best cut, which removes the whole subtree.)

- `sqlite3`: heavy, used only in `main()`. **Defer**, in the entry
  point.

- `xml.dom`: shared between the entry point and analytics. Defer in
  both or the cost moves. **Defer twice.**

- `decimal`: module-level plain import in web.py, used inside
  `render()`. **Defer**, in myapp/web.py.

- `wave`: imported by client.py and never touched by the workload.
  **Defer** and it never loads at all, the best case.

- `difflib`: a from-import, so the shim cannot defer it on older
  Pythons; the guide's rewrite (`import difflib` and
  `difflib.SequenceMatcher`) would open it, and the saving is a
  rounding error. **Leave eager**, on both routes.

## Applying

The decisions in source, in code the example owns:

```python
# myapp/__main__.py

__lazy_modules__ = ["sqlite3", "xml.dom"]
import sqlite3
import xml.dom
```

```python
# myapp/web.py

__lazy_modules__ = ["decimal", "myapp.analytics"]
import decimal
import myapp.analytics
```

```python
# myapp/analytics.py

__lazy_modules__ = ["xml.dom"]
import xml.dom
```

The same decisions without touching any source, through the external
configuration (`lazy.json` in the example directory):

```json
{
    "__main__": ["sqlite3", "xml.dom"],
    "myapp.analytics": ["xml.dom"],
    "myapp.client": ["wave"],
    "myapp.web": ["decimal"]
}
```

## Verifying

Profile mode never defers, so verify the decision by running the
application with the shim active and watching what loads:

```console
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_CONFIG=lazy.json python -m myapp
```

With the deferrals applied, sqlite3, xml.dom, decimal and wave are not
in `sys.modules` at start-up; the first use in `main()` loads the
first three, and wave, which nothing touches, never loads at all. The
CI test asserts exactly that.

The compare tool diffs two profiled runs of the workload, before and
after a code change:

```console
$ python -m unwrapt.report before.json --compare after.json
```

Run the test suite on an older Python with the shim active and on
3.15 with the same declarations native, and the worked example is
done: what the strategy guide promised is what the application now
does.
