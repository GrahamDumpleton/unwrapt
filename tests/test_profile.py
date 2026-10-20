"""Tests for profile mode, each in its own subprocess.

Profile mode installs a recording hook instead of the shim hook, so it
is as process global as the shim. Children run with UNWRAPT_PROFILE
set and a JSON report path, and the tests assert on the report
structure, never on absolute millisecond values.
"""

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from support import run_python, write_module

import unwrapt

PROFILE = {
    "UNWRAPT_PROFILE": "1",
    "UNWRAPT_PROFILE_FORMAT": "json",
}


def _load(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = json.loads(path.read_text())

    return report


def _report_facts(
    code: str, tmp_path: Path, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    output = tmp_path / "report.json"

    merged = {**PROFILE, "UNWRAPT_PROFILE_OUTPUT": str(output), **(env or {})}

    result = run_python(code, env=merged, cwd=tmp_path)

    assert result.returncode == 0, f"child failed:\n{result.stderr}"
    assert output.exists(), "report was not written"

    return _load(output)


def test_records_loaded_and_cache_hit_edges(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install()

        import wave
        import wave
        """,
        tmp_path,
    )

    csv_edges = [edge for edge in report["edges"] if edge["imported"] == "wave"]

    assert len(csv_edges) == 2
    assert csv_edges[0]["loaded"] is True
    assert csv_edges[1]["loaded"] is False


def test_kind_and_level_classification(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install()

        import wave
        from difflib import SequenceMatcher

        def use():
            import plistlib

        use()

        class Holder:
            import colorsys
        """,
        tmp_path,
    )

    by_name = {
        edge["imported"]: edge
        for edge in report["edges"]
        if edge["imported"] in ("wave", "difflib", "plistlib", "colorsys")
    }

    assert by_name["wave"]["kind"] == "import"
    assert by_name["wave"]["level"] == "module"

    assert by_name["difflib"]["kind"] == "from"
    assert by_name["difflib"]["level"] == "module"

    assert by_name["plistlib"]["level"] == "function"

    assert by_name["colorsys"]["level"] == "class"


def test_parent_tree_and_self_time(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "chainpkg.a",
        "import chainpkg.b\n",
    )
    write_module(
        tmp_path,
        "chainpkg.b",
        "import chainpkg.c\n",
    )
    write_module(
        tmp_path,
        "chainpkg.c",
        "value = 1\n",
    )

    report = _report_facts(
        """
        import unwrapt

        unwrapt.install()

        import chainpkg.a
        """,
        tmp_path,
    )

    edges = {
        edge["imported"]: edge
        for edge in report["edges"]
        if edge["imported"].startswith("chainpkg.")
    }

    a, b, c = edges["chainpkg.a"], edges["chainpkg.b"], edges["chainpkg.c"]

    assert a["parent_id"] is None
    assert b["parent_id"] == a["id"]
    assert c["parent_id"] == b["id"]

    # Self time excludes the nested import calls; cumulative time
    # contains them.

    assert c["self_ms"] <= c["cum_ms"]
    assert b["self_ms"] <= b["cum_ms"]
    assert a["self_ms"] < a["cum_ms"]


def test_profile_mode_does_not_defer(tmp_path: Path) -> None:
    # The module declares wave lazy, but profile mode never defers: the
    # edge is recorded wherever the import actually happens. Below 3.15
    # that is the import statement; on 3.15 native owns the declaration
    # and the edge is the first-use reification.

    report = _report_facts(
        """
        import json
        import sys

        import unwrapt

        unwrapt.install()

        __lazy_modules__ = ["wave"]
        import wave

        loaded_at_statement = "wave" in sys.modules

        value = wave.Wave_read

        print(json.dumps({"loaded_at_statement": loaded_at_statement}))
        """,
        tmp_path,
    )

    csv_edge = next(edge for edge in report["edges"] if edge["imported"] == "wave")

    assert csv_edge["loaded"] is True
    assert csv_edge["already_lazy"] is True

    if sys.version_info < (3, 15):
        assert csv_edge["native_lazy"] is False
    else:
        assert csv_edge["native_lazy"] is True


def test_route_columns(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install()

        import wave
        from difflib import SequenceMatcher
        """,
        tmp_path,
    )

    csv_edge = next(edge for edge in report["edges"] if edge["imported"] == "wave")
    difflib_edge = next(
        edge for edge in report["edges"] if edge["imported"] == "difflib"
    )

    assert csv_edge["deferrable"] == {"native": True, "unwrapt": True}
    assert csv_edge["unwrapt_limit"] is None

    assert difflib_edge["deferrable"] == {"native": True, "unwrapt": False}
    assert difflib_edge["unwrapt_limit"] == "from-import"


def test_dotted_as_edge_detected(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "asmod",
        "import xml.dom as dom\n",
    )

    report = _report_facts(
        """
        import unwrapt

        unwrapt.install()

        import asmod
        """,
        tmp_path,
    )

    edge = next(edge for edge in report["edges"] if edge["imported"] == "xml.dom")

    assert edge["deferrable"] == {"native": True, "unwrapt": False}
    assert edge["unwrapt_limit"] == "dotted-as"


def test_min_ms_filter_hides_candidates(tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    run_python(
        """
        import unwrapt

        unwrapt.install()

        import wave
        """,
        env={
            **PROFILE,
            "UNWRAPT_PROFILE_OUTPUT": str(output),
            "UNWRAPT_PROFILE_MIN_MS": "100000",
        },
        cwd=tmp_path,
    )

    report = _load(output)

    # Every edge is still recorded; the filter is a display filter.

    assert any(edge["imported"] == "wave" for edge in report["edges"])
    assert report["summary"]["filters"]["min_ms"] == 100000.0


def test_output_path_expands_pid(tmp_path: Path) -> None:
    output = tmp_path / "report-%p.json"

    run_python(
        """
        import unwrapt

        unwrapt.install()

        import wave
        """,
        env={**PROFILE, "UNWRAPT_PROFILE_OUTPUT": str(output)},
        cwd=tmp_path,
    )

    written = list(tmp_path.glob("report-*.json"))

    assert len(written) == 1
    assert written[0].name != "report-%p.json"


def test_packages_filter(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "mypkg.mod",
        "import wave\n",
    )

    output = tmp_path / "report.json"

    run_python(
        """
        import unwrapt

        unwrapt.install()

        import mypkg.mod
        import wave
        """,
        env={
            **PROFILE,
            "UNWRAPT_PROFILE_OUTPUT": str(output),
            "UNWRAPT_PROFILE_PACKAGES": "mypkg",
        },
        cwd=tmp_path,
    )

    report = _load(output)

    assert report["summary"]["filters"]["packages"] == ["mypkg"]

    # The wave imported by __main__ is outside the filter and the stdlib
    # importer of _csv is too; the render hides them. The JSON keeps
    # every edge.

    assert any(edge["imported"] == "wave" for edge in report["edges"])


def test_json_schema_shape(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install()

        import wave
        """,
        tmp_path,
    )

    assert report["schema"] == 1
    assert report["unwrapt"] == unwrapt.__version__
    assert "python" in report
    assert isinstance(report["total_import_ms"], float)
    assert isinstance(report["summary"]["modules_loaded"], int)
    assert isinstance(report["summary"]["edge_count"], int)
    assert isinstance(report["summary"]["estimated_saving_ms"], float)
    assert report["summary"]["estimate_note"]
    assert isinstance(report["edges"], list)
    assert isinstance(report["heavy_modules"], list)
    assert isinstance(report["chains"], list)
    assert isinstance(report["by_importer"], list)

    edge = report["edges"][0]

    for field in (
        "id",
        "parent_id",
        "imported",
        "importer",
        "line",
        "kind",
        "level",
        "loaded",
        "cum_ms",
        "self_ms",
        "deferrable",
        "unwrapt_limit",
        "already_lazy",
        "native_lazy",
        "other_eager_importers",
    ):
        assert field in edge


def test_summary_figures_are_sane(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install()

        import wave
        import xml.dom
        """,
        tmp_path,
    )

    summary = report["summary"]

    # Non-additivity: the estimate can never exceed the total.

    assert summary["estimated_saving_ms"] <= report["total_import_ms"]


def test_text_report_default_output(tmp_path: Path) -> None:
    result = run_python(
        """
        import unwrapt

        unwrapt.install()

        import wave
        """,
        env={"UNWRAPT_PROFILE": "1"},
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert f"unwrapt {unwrapt.__version__} profile report" in result.stderr
    assert "Candidates: module-level imports" in result.stderr
    assert "Heavy modules: by self time" in result.stderr
    assert "By importer: direct module-level loads" in result.stderr
    assert "Import chains: why each heavy module is loaded" in result.stderr
    assert "Limits of this report" in result.stderr


def test_install_twice_installs_once(tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    result = run_python(
        """
        import json

        import unwrapt

        first = unwrapt.install()
        second = unwrapt.install()

        import wave

        print(json.dumps({"first": first, "second": second}))
        """,
        env={**PROFILE, "UNWRAPT_PROFILE_OUTPUT": str(output)},
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr

    facts = json.loads(result.stdout.strip().splitlines()[-1])

    assert facts["first"] is True
    assert facts["second"] is False

    report = _load(output)

    assert report["summary"]["edge_count"] > 0
