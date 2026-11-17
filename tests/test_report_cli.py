"""Tests for the python -m unwrapt.report command line tool."""

import json
from pathlib import Path

import pytest

import unwrapt
from unwrapt._config import ProfileOptions
from unwrapt._report import Edge, build_report, main


def _write_report(path: Path, total: float, modules: list[str]) -> str:
    edges = [
        Edge(
            id=index,
            parent_id=None,
            importer="app",
            imported=name,
            kind="import",
            level_name="module",
            line=index + 1,
            file=None,
            loaded=True,
            cum_ms=total / len(modules),
            self_ms=total / len(modules),
            native_lazy=False,
            already_lazy=False,
        )
        for index, name in enumerate(modules)
    ]

    path.write_text(build_report(edges, ProfileOptions()).render_json())

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


def test_main_filter_options_override_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    modules = [f"mod{index}" for index in range(10)]
    report = _write_report(tmp_path / "report.json", 100.0, modules)

    assert main([report]) == 0
    assert "(2 more not shown)" in capsys.readouterr().out

    assert main([report, "--rows", "3"]) == 0
    assert "(7 more not shown)" in capsys.readouterr().out

    assert main([report, "--rows", "0"]) == 0
    assert "more not shown" not in capsys.readouterr().out

    assert main([report, "--min-ms", "20", "--packages", "app,other"]) == 0

    out = capsys.readouterr().out

    assert "(rows under 20.0 ms hidden by the min_ms filter)" in out
    assert "(rows outside app, other hidden by the packages filter)" in out


@pytest.mark.parametrize(
    "arguments",
    [
        ["--rows", "-1"],
        ["--rows", "lots"],
        ["--min-ms", "-1"],
        ["--min-ms", "soon"],
        ["--packages", " , "],
    ],
)
def test_main_invalid_filter_option_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], arguments: list[str]
) -> None:
    report = _write_report(tmp_path / "report.json", 100.0, ["csv"])

    with pytest.raises(SystemExit) as info:
        main([report, *arguments])

    assert info.value.code == 2
    assert "python -m unwrapt.report" in capsys.readouterr().err


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


def test_main_refuses_another_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"schema": 1, "edges": []}))

    assert main([str(path)]) == 1
    assert "schema 1 is not supported" in capsys.readouterr().err
