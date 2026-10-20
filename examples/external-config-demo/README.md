# External configuration demo

Deferring an import in a module you cannot or do not want to edit,
below Python 3.15 or on 3.15 and later, with a JSON configuration and
no source changes at all.

```console
$ pip install unwrapt autowrapt
$ AUTOWRAPT_BOOTSTRAP=unwrapt UNWRAPT_CONFIG=lazy.json python app.py
```

Expected output:

```
decimal loaded at startup: False
after first use: <class 'module'>
```

The configuration maps each importer's module name to the names it
should defer; see `lazy.json`. On Python 3.15 and later this is the
only thing unwrapt does (native lazy imports handle everything a
module declares itself), and supplying the configuration is what
activates it.
