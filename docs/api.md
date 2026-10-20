# API

The public API is deliberately small: two functions and the version.

## unwrapt.install

```python
unwrapt.install(module: object = None) -> bool
```

Install the unwrapt import hook for this process. The mode is chosen
once, here, from the [environment](configuration.md): with
`UNWRAPT_PROFILE` set, the recording hook of
[profile mode](profile-mode.md); otherwise the shim hook, subject to
the Python version rules on the [how it works](how-it-works.md) page.
Calling it a second time does nothing, whatever mode was installed
first.

The `module` argument is ignored: it exists so the function can serve
directly as the autowrapt post import hook callback, which is handed
the trigger module (os, per the entry point) and carries no
information. The [autowrapt](autowrapt.md) page covers the bootstrap.

Returns True when this call installed a hook, False when one was
already installed or there was nothing to install (Python 3.15 and
later with no `UNWRAPT_CONFIG`).

## unwrapt.is_installed

```python
unwrapt.is_installed() -> bool
```

Whether an unwrapt hook, of either mode, is installed in this process.

## The version

```python
unwrapt.__version__      # "1.0.0a1"
unwrapt.__version_info__  # ("1", "0", "0", "a1")
```

`__version_info__` is a tuple of strings, three numeric parts plus an
optional fourth: a fourth part starting with `dev` or `post` is joined
with a dot, any other is appended directly, three parts alone are the
plain version. To release, only `__version_info__` changes;
`__version__` is derived from it, and the packaging reads it from
there.

## What is deliberately not API

The hook itself, the proxy class, the profile recorder and the report
structures are implementation modules (underscore-prefixed, except the
autowrapt `bootstrap` entry point and the `report` command module) and
carry no stability promise before 1.0.0: none of them need importing
from outside, and `python -m unwrapt.report` is the supported entry
to the report tooling.
