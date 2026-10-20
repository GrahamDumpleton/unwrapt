# Testing

## Where the tests are

Tests live in the [tests/](tests/) directory at the top of the
repository, separate from the package code in src/unwrapt/. Test files
are named `test_*.py` and are discovered by pytest, which is
configured via the `[tool.pytest.ini_options]` section of
[pyproject.toml](pyproject.toml).

## Running the tests

All tooling in this project goes through [uv](https://docs.astral.sh/uv/),
which manages the project environment and installs the package and its
development dependencies (including pytest) automatically.

The simplest way to run the test suite is via the Justfile target:

```console
just test
```

Extra arguments are passed through to pytest, for example:

```console
just test -v
just test tests/test_version.py
just test -k profile
```

Equivalently, run pytest directly with uv:

```console
uv run pytest
```

## Testing across Python versions

The project supports Python 3.12 through 3.15, including the free
threaded builds of 3.14 and 3.15 (3.13t is skipped: that build was
experimental and its companion tooling no longer installs cleanly on
some platforms). The supported list is defined at the top of the
[Justfile](Justfile). The default version used by plain `just test` is
pinned in [.python-version](.python-version).

Run the test suite on every supported version:

```console
just test-all
```

Run the test suite on one nominated version:

```console
just test-python 3.12
just test-python 3.15t
```

Extra arguments are passed through to pytest for these targets too. uv
downloads any Python version it does not already have, and each version
gets its own environment (.venv-VERSION) so the default .venv is left
untouched.

## Python version specific test files

Some tests exercise behaviour that only exists on a newer interpreter:
the Python 3.15 native lazy import interaction lives in files named
`test_*_py315.py`, which the conftest collects only on 3.15 and later.
Conversely, the `__lazy_modules__` emulation only exists below 3.15, so
its file (test_lazy_modules.py) is skipped entirely there with a marker.
The general convention, when a test needs a minimum version, is the
`test_*_pyXX.py` suffix handled by the conftest.

## Why so many subprocesses

unwrapt replaces `builtins.__import__` for the whole process, so a test
that installs the hook would change how every later test in the same
process imports anything. The shim and profile tests therefore run each
scenario in a subprocess with controlled environment variables, and
assert on facts the child prints as one JSON line; the helpers are in
tests/support.py. In-process tests cover only what is process-local:
configuration parsing, the report aggregation (pure functions over
synthetic edges) and the version.

One consequence for writing tests: pick deferred-import test modules
that nothing preloads. wrapt itself (imported when the hook installs)
preloads json, inspect, copy, subprocess and a few more, and exactly
which those are varies by Python version, so the suite uses modules
such as wave, plistlib, difflib, xml.dom and decimal, or purpose-built
temp modules. A module already in sys.modules is returned unchanged
by the hook: that is documented behaviour, and a test that defers a
preloaded module is testing nothing.

## autowrapt

autowrapt is not a dependency of unwrapt. It is installed in the test
environment (the `test` dependency group) so the end-to-end bootstrap
tests can run, and those tests skip themselves when it is absent. The
CI plain install job runs the suite without it on purpose: it keeps
honest the promise that base unwrapt needs only wrapt.

## Docs and type checks

- `just docs` builds the documentation with warnings as errors, and the
  CI workflow builds it on every push and pull request.

- `just typecheck` runs mypy in strict mode over the package and the
  tests. All code must be fully annotated; py.typed ships in the
  wheel, and tests/downstream_check.py is a small downstream-style
  file mypy checks so the exported types stay usable from outside.

- `just lint` checks with ruff, and `just format` fixes; CI runs both.
