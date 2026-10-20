"""Shared helpers for the test suite.

unwrapt's hook is process global, so most of the suite runs each
scenario in a subprocess with controlled environment variables, and
asserts on facts the child prints as one JSON line. The helpers here
scrub inherited UNWRAPT_* and AUTOWRAPT_* variables so a test controls
its child's environment completely.
"""

import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Mapping
from pathlib import Path
from typing import Any

TIMEOUT = 60


def run_python(
    code: str,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run code with the test environment's interpreter.

    Inherited UNWRAPT_* and AUTOWRAPT_* variables are removed first, so
    a child only sees what its test passes. Returns the completed
    process with captured output.
    """

    merged = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("UNWRAPT_") and key != "AUTOWRAPT_BOOTSTRAP"
    }

    if env is not None:
        merged.update(env)

    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env=merged,
        cwd=cwd,
        timeout=TIMEOUT,
    )


def run_facts(
    code: str,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Run code whose last stdout line is a JSON object of facts.

    Fails the test with the child's stderr when the child exits badly,
    which is where a broken hook shows up as an import error.
    """

    result = run_python(code, env=env, cwd=cwd)

    assert result.returncode == 0, f"child exited {result.returncode}:\n{result.stderr}"

    assert result.stdout.strip(), "child printed no facts"

    facts: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])

    return facts


def write_module(root: Path, name: str, source: str) -> Path:
    """Write a module (or package module, dotted name) under root.

    A dotted name creates the package directories and __init__.py
    files along the way. Returns the path of the module file.
    """

    parts = name.split(".")
    directory = root.joinpath(*parts[:-1])
    directory.mkdir(parents=True, exist_ok=True)

    for index in range(1, len(parts)):
        package = root.joinpath(*parts[:index], "__init__.py")

        if not package.exists():
            package.write_text("")

    path = directory / f"{parts[-1]}.py"
    path.write_text(textwrap.dedent(source))

    return path


def json_config(path: Path, config: Mapping[str, list[str]]) -> str:
    """Write an external configuration file, returning its path."""

    path.write_text(json.dumps(config))

    return str(path)
