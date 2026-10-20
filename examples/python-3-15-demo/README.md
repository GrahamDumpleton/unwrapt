# Python 3.15 demo

How unwrapt and native lazy imports divide the work on Python 3.15 and
later. The application declares one import lazy itself, which the
interpreter defers natively, and the configuration asks unwrapt to
defer a second import that the source does not declare: each handles
its own part, and native behaviour is never altered.

Requires Python 3.15 or later, and autowrapt installed:

```console
$ pip install unwrapt autowrapt
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_CONFIG=lazy.json python app.py
```

Expected output:

```
native deferred colorsys: True
unwrapt deferred decimal: True
```

With `UNWRAPT_DEBUG=1` the run also states the active mode:

```
unwrapt: external-config-only mode installed
```

Without `UNWRAPT_CONFIG`, unwrapt installs nothing on 3.15: the
application's own declaration keeps working exactly the same.
