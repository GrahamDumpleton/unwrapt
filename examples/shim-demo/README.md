# Shim demo

The simplest possible demonstration of unwrapt on a Python below 3.15:
an application declares one import lazy in its own source, and running
it with the bootstrap defers that import until first use, with no
other change to how the application is started.

autowrapt must be installed alongside the application (it is not a
dependency of unwrapt):

```console
$ pip install unwrapt autowrapt
$ AUTOWRAPT_BOOTSTRAP=unwrapt python app.py
```

Expected output:

```
xml.dom loaded at startup: False
after first use: <class 'module'>
```

Without `AUTOWRAPT_BOOTSTRAP=unwrapt`, the same application loads
xml.dom eagerly at startup. On Python 3.15 and later the interpreter
handles `__lazy_modules__` itself, and unwrapt (which installs nothing
there without a configuration) is not needed for this example at all.
