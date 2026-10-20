# autowrapt

autowrapt is how unwrapt is injected into a process without changing
the application: no launcher script, no edit to the entry point, one
environment variable. It is a separate package, deliberately not a
dependency of unwrapt, and unwrapt never imports it.

```console
$ pip install autowrapt
$ AUTOWRAPT_BOOTSTRAP=unwrapt python app.py
```

## The mechanism

Installing autowrapt puts a startup file at the top of site-packages:
a `.start` file (PEP 829) on Python 3.15 and later, a `.pth` file
before that. At every interpreter startup it checks whether
`AUTOWRAPT_BOOTSTRAP` is set, and if it is not, nothing else loads: the
cost of autowrapt being installed is one small import.

The variable's value names an entry point group. autowrapt hands the
group to `wrapt.discover_post_import_hooks()`, which loads each entry
in it: a trigger module name mapped to a callback, called when that
module is imported. unwrapt's entry hooks the `os` module, which is
always already imported by the time site initialisation completes, so
the callback fires immediately, at startup, before the application's
own imports:

```toml
# From unwrapt's packaging metadata.

[project.entry-points.unwrapt]
os = "unwrapt.bootstrap:bootstrap"
```

The callback is `unwrapt.bootstrap:bootstrap`, which calls
`unwrapt.install()`; the entry point metadata is inert unless both
autowrapt is installed and the variable is set.

## Ordering

The hook is in place before the application's imports, which is the
whole point: anything already in `sys.modules` by then was imported
eagerly, by definition. `site` processes the startup files during
interpreter initialisation, so the ordering holds for any way of
starting the application: a script, `python -m`, a WSGI server, a
worker.

The same variable can name more than one group, comma separated, and
autowrapt's own README covers the general mechanism: unwrapt is one
consumer of it.

## Without autowrapt

`unwrapt.install()` is the explicit activation, for when you control
the process directly: a test suite, a notebook, a one-off experiment.

```python
import unwrapt

unwrapt.install()
```

Everything else reads the same environment variables either way. The
one difference is ordering: the explicit call takes effect from where
it was called, so modules imported earlier in the process are eager.
