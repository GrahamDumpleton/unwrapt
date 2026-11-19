"""Tests for profile mode on Python 3.15 and later.

Native lazy imports are never altered by unwrapt, and forcing them
eager with the sys.set_lazy_imports_filter mechanism hides them from
the hook entirely, so the profiler instead records a native lazy
import when native reifies it, at first use, flags the edge and warns.
These tests are collected only on 3.15+.
"""

import json
from pathlib import Path
from typing import Any

from support import run_python, write_module

from unwrapt.report import Report
from unwrapt.report import candidates as loaded_candidates

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

        unwrapt.install_from_env()

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

    text = Report.from_dict(report).render_text()

    assert "native lazy imports on Python 3.15" in text
    assert "recorded at first use" in text


def test_native_lazy_from_imports_recorded_at_first_use(tmp_path: Path) -> None:
    write_module(tmp_path, "nlpkg.__init__", "lazy from . import rel_sub\n")
    write_module(tmp_path, "nlpkg.rel_sub", "X = 1\n")
    write_module(tmp_path, "nlpkg.other", "Y = 2\n")

    # Neither statement registers the package, which is loaded by the
    # time each runs: only nlpkg.rel_sub and nlpkg.other are pending.

    report = _report(
        tmp_path,
        """
        import unwrapt

        unwrapt.install_from_env()

        import nlpkg

        lazy from nlpkg import other

        values = (nlpkg.rel_sub.X, other.Y)
        """,
    )

    reified = {
        tuple(edge["submodules"]): edge
        for edge in report["edges"]
        if edge["imported"] == "nlpkg" and edge["kind"] == "from"
    }

    for submodules in (("nlpkg.rel_sub",), ("nlpkg.other",)):
        edge = reified[submodules]

        assert edge["native_lazy"] is True
        assert edge["already_lazy"] is True
        assert edge["loaded"] is True

    text = Report.from_dict(report).render_text()

    assert "2 native lazy imports on Python 3.15" in text


def test_untouched_native_lazy_import_never_appears(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        """
        import unwrapt

        unwrapt.install_from_env()

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

        unwrapt.install_from_env()
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

        unwrapt.install_from_env()

        lazy import colorsys

        value = colorsys.rgb_to_hls(1, 0, 0)
        """,
    )

    edge = next(edge for edge in report["edges"] if edge["imported"] == "colorsys")

    assert edge["native_lazy"] is True
    assert edge["already_lazy"] is True


def test_eager_import_of_a_name_pending_elsewhere(tmp_path: Path) -> None:
    # sys.lazy_modules holds names only, so an eager import statement
    # for a name another module has pending looks pending too. It is an
    # eager load, and recorded as one, not as a native reification.

    write_module(tmp_path, "pendlazy", "lazy import wave\n")
    write_module(tmp_path, "pendeager", "import wave\n")

    report = _report(
        tmp_path,
        """
        import unwrapt

        unwrapt.install_from_env()

        import pendlazy
        import pendeager
        """,
    )

    eager = next(
        edge
        for edge in report["edges"]
        if edge["importer"] == "pendeager" and edge["imported"] == "wave"
    )

    assert eager["loaded"] is True
    assert eager["native_lazy"] is False
    assert eager["already_lazy"] is False
    assert eager["defer"] == {"native": True, "unwrapt": True, "reason": None}

    loaded = Report.from_dict(report)
    row = next(row for row in loaded_candidates(loaded) if row["edge"] == eager["id"])

    assert row["saving_ms"] == eager["cum_ms"]
    assert "already lazy" not in loaded.render_text()


def test_native_reification_still_recognised(tmp_path: Path) -> None:
    write_module(tmp_path, "pendlazy", "lazy import wave\n")

    report = _report(
        tmp_path,
        """
        import unwrapt

        unwrapt.install_from_env()

        import pendlazy

        pendlazy.wave.Wave_read
        """,
    )

    edge = next(edge for edge in report["edges"] if edge["imported"] == "wave")

    assert edge["native_lazy"] is True
    assert edge["already_lazy"] is True
