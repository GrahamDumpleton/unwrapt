"""Tests for the python -m unwrapt.report command line tool."""

import json
from pathlib import Path

import pytest

import unwrapt
from unwrapt._report import main


def _write_report(path: Path, total: float, modules: list[str]) -> str:
    report = {
        "schema": 1,
        "unwrapt": unwrapt.__version__,
        "python": "3.14.0",
        "total_import_ms": total,
        "summary": {
            "modules_loaded": len(modules),
            "edge_count": len(modules),
            "best_cut": None,
            "estimated_saving_ms": 0.0,
            "estimate_note": "conservative; edge times nest and are not additive",
            "filters": {"min_ms": 0.0, "packages": None},
        },
        "edges": [
            {
                "id": index,
                "parent_id": None,
                "imported": name,
                "importer": "app",
                "line": index + 1,
                "kind": "import",
                "level": "module",
                "loaded": True,
                "cum_ms": total / len(modules),
                "self_ms": total / len(modules),
                "deferrable": {"native": True, "unwrapt": True},
                "unwrapt_limit": None,
                "already_lazy": False,
                "native_lazy": False,
                "other_eager_importers": [],
            }
            for index, name in enumerate(modules)
        ],
        "heavy_modules": [
            {"module": name, "self_ms": total / len(modules)} for name in modules
        ],
        "chains": [],
        "by_importer": [{"importer": "app", "cum_ms": total}],
    }

    path.write_text(json.dumps(report))

    return str(path)


def test_main_renders_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = _write_report(tmp_path / "before.json", 100.0, ["csv", "wave"])

    assert main([report]) == 0

    out = capsys.readouterr().out

    assert f"unwrapt {unwrapt.__version__} profile report" in out
    assert "Candidates: module-level imports" in out
    assert "csv" in out


def test_main_compares_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _write_report(tmp_path / "before.json", 100.0, ["csv"])
    after = _write_report(tmp_path / "after.json", 40.0, ["wave"])

    assert main([before, "--compare", after]) == 0

    out = capsys.readouterr().out

    assert "100.0 ms -> 40.0 ms" in out
    assert "Newly loaded: wave" in out
    assert "No longer loaded: csv" in out


def test_main_missing_file_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "nope.json")]) == 1

    captured = capsys.readouterr()

    assert "unwrapt:" in captured.err


def test_main_invalid_json_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{oops")

    assert main([str(path)]) == 1
