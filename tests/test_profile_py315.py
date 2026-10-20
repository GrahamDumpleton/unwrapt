"""Tests for profile mode on Python 3.15 and later.

Native lazy imports are never altered by unwrapt, and forcing them
eager with the sys.set_lazy_imports_filter mechanism hides them from
the hook entirely, so the profiler instead records a native lazy
import when native reifies it, at first use, flags the edge and warns.
These tests are collected only on 3.15+.
"""

import json
from pathlib import Path
from typing import Any, cast

from support import run_python

from unwrapt._report import Report, render_text

PROFILE = {
    "UNWRAPT_PROFILE": "1",
    "UNWRAPT_PROFILE_FORMAT": "json",
}


def _report(
    tmp_path: Path, code: str, env: dict[str, str] | None = None
) -> dict[str, Any]:
    output = tmp_path / "report.json"

    result = run_python(
        code,
        env={**PROFILE, "UNWRAPT_PROFILE_OUTPUT": str(output), **(env or {})},
        cwd=tmp_path,
    )

    assert result.returncode == 0, f"child failed:\n{result.stderr}"

    report: dict[str, Any] = json.loads(output.read_text())

    return report


def test_native_lazy_import_recorded_at_first_use(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        """
        import unwrapt

        unwrapt.install()

        __lazy_modules__ = ["csv"]

        import csv

        rows = list(csv.reader(["a,b"]))
        """,
    )

    csv_edge = next(edge for edge in report["edges"] if edge["imported"] == "csv")

    assert csv_edge["native_lazy"] is True
    assert csv_edge["already_lazy"] is True
    assert csv_edge["loaded"] is True
    assert csv_edge["importer"] == "__main__"

    text = render_text(cast(Report, report))

    assert "native lazy imports on Python 3.15" in text
    assert "recorded at first use" in text


def test_untouched_native_lazy_import_never_appears(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        """
        import unwrapt

        unwrapt.install()

        __lazy_modules__ = ["csv"]

        import csv
        """,
    )

    # The module is never touched, so native never loads it: a lazy
    # program's invisible imports are the documented reason to profile
    # an eager run.

    assert not any(edge["imported"] == "csv" for edge in report["edges"])


def test_all_mode_warns_at_install(tmp_path: Path) -> None:
    result = run_python(
        """
        import sys

        sys.set_lazy_imports("all")

        import unwrapt

        unwrapt.install()
        """,
        env={"UNWRAPT_PROFILE": "1"},
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert "native lazy imports are active" in result.stderr
    assert "PYTHON_LAZY_IMPORTS=normal" in result.stderr


def test_explicit_lazy_import_statement_recorded_at_first_use(
    tmp_path: Path,
) -> None:
    report = _report(
        tmp_path,
        """
        import unwrapt

        unwrapt.install()

        lazy import colorsys

        value = colorsys.rgb_to_hls(1, 0, 0)
        """,
    )

    edge = next(edge for edge in report["edges"] if edge["imported"] == "colorsys")

    assert edge["native_lazy"] is True
    assert edge["already_lazy"] is True
