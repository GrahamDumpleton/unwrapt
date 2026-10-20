"""Test collection configuration.

Sets MYPYPATH so an editor-invoked mypy resolves unwrapt from the
source tree, and implements the Python version suffix convention for
test files: a file named test_*_pyXX.py is collected only on Python
XX or later, so behaviour that needs a newer interpreter (the Python
3.15 native lazy import interaction, for example) lives in files the
older versions never run.
"""

import os
import pathlib
import re
import sys

import pytest

version = tuple(sys.version_info[:2])

# Set MYPYPATH to the src directory relative to this conftest.py file.
# This allows mypy to find the source code for type checking.

_conftest_dir = pathlib.Path(__file__).parent
_src_dir = _conftest_dir.parent / "src"
os.environ["MYPYPATH"] = str(_src_dir)


class _SkippedModule(pytest.Module):
    """A collector that collects nothing, for files gated off."""

    def collect(self) -> list[pytest.Item]:
        return []


def pytest_pycollect_makemodule(
    module_path: pathlib.Path, parent: pytest.Collector
) -> pytest.Module | None:
    """Skip test files whose _pyXX suffix names a newer Python."""

    match = re.search(r"_py(\d)(\d*)", module_path.name)

    if match:
        major = int(match.group(1))
        minor = int(match.group(2)) if match.group(2) else 0

        if version < (major, minor):
            return _SkippedModule.from_parent(parent, path=module_path)

    return None
