"""Tests for the worked example, run in CI against the sample
application under examples/worked-example.

The documentation's strategy guide walks this application end to end,
so these tests assert on the report structure the guide's narrative
depends on (chains, shared importers, route limits, a conservative
estimate), never on absolute millisecond values.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from support import run_python

from unwrapt._report import main as report_main

EXAMPLE = Path(__file__).parent.parent / "examples" / "worked-example"

# The entry point's own imports, as the child scripts them: the same
# statements myapp/__main__.py runs, in the same order.

ENTRY_IMPORTS = """
        import sqlite3
        import xml.dom

        import myapp.client
        import myapp.web
        """

PROFILE = {
    "UNWRAPT_PROFILE": "1",
    "UNWRAPT_PROFILE_FORMAT": "json",
}


def _profile(
    code: str, tmp_path: Path, env: dict[str, str] | None = None
) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)

    output = tmp_path / "report.json"

    merged = {**PROFILE, "UNWRAPT_PROFILE_OUTPUT": str(output), **(env or {})}

    result = run_python(code, env=merged, cwd=EXAMPLE)

    assert result.returncode == 0, f"child failed:\n{result.stderr}"

    report: dict[str, Any] = json.loads(output.read_text())

    return report


def test_baseline_report_structure(tmp_path: Path) -> None:
    report = _profile(
        """
        import unwrapt

        unwrapt.install()
        """
        + ENTRY_IMPORTS,
        tmp_path,
    )

    edges = report["edges"]

    by_imported = {edge["imported"]: edge for edge in edges}

    # The nest the chains show: the entry point's import of myapp.web
    # is the root, and everything below it is one subtree.

    web = by_imported["myapp.web"]

    assert web["parent_id"] is None
    assert web["loaded"] is True

    # The from-import limit: difflib is deferrable natively on 3.15 and
    # not by the shim, and the row is never dropped.

    difflib_edge = by_imported["difflib"]

    assert difflib_edge["deferrable"] == {"native": True, "unwrapt": False}
    assert difflib_edge["unwrapt_limit"] == "from-import"

    # xml.dom is imported twice: once by the entry point, once inside
    # the chain, so the shared note lists the other eager importer.

    dom_edges = [edge for edge in edges if edge["imported"] == "xml.dom"]

    assert len(dom_edges) == 2
    assert dom_edges[0]["loaded"] is True

    for edge in dom_edges:
        assert len(edge["other_eager_importers"]) == 1

    # The chain for xml explains why it loaded, outermost first.

    chains = {chain["module"]: chain for chain in report["chains"]}

    assert "xml" in chains

    # The estimate never exceeds the total, whatever the nest.

    assert report["summary"]["estimated_saving_ms"] <= report["total_import_ms"]


def test_config_route_defers_the_decisions(tmp_path: Path) -> None:
    # The lazy.json the guide arrives at, applied without touching the
    # source: the heavy imports are not loaded at startup, and load at
    # first use.

    result = run_python(
        """
        import json
        import sys

        import unwrapt

        unwrapt.install()
        """
        + ENTRY_IMPORTS
        + """
        facts = {
            "sqlite3_loaded": "sqlite3" in sys.modules,
            "xml_dom_loaded": "xml.dom" in sys.modules,
            "decimal_loaded": "decimal" in sys.modules,
            "wave_loaded": "wave" in sys.modules,
        }

        from myapp.__main__ import main

        main()

        # The workload touches three of the four; wave is only used
        # by client.silence(), which never runs, so it stays unloaded
        # entirely: the best case a deferral can produce.

        facts["loaded_after_use"] = (
            "sqlite3" in sys.modules
            and "xml.dom" in sys.modules
            and "decimal" in sys.modules
        )
        facts["wave_never_loaded"] = "wave" not in sys.modules

        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": str(EXAMPLE / "lazy.json")},
        cwd=EXAMPLE,
    )

    assert result.returncode == 0, f"child failed:\n{result.stderr}"

    facts = json.loads(result.stdout.strip().splitlines()[-1])

    assert facts["sqlite3_loaded"] is False
    assert facts["xml_dom_loaded"] is False
    assert facts["decimal_loaded"] is False
    assert facts["wave_loaded"] is False
    assert facts["loaded_after_use"] is True
    assert facts["wave_never_loaded"] is True


def test_compare_tool_reports_the_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The compare tool is for diffing two profiled runs: after a code
    # change, or between workloads. Profile mode never defers, so the
    # honest demo is a changed workload, not the same one with a
    # configuration (which the shim-run test covers: deferral under
    # the shim, verified directly).

    prefix = """
        import unwrapt

        unwrapt.install()
        """

    before = _profile(prefix + ENTRY_IMPORTS, tmp_path / "before")
    after = _profile(
        prefix + ENTRY_IMPORTS + "\n        import tarfile\n", tmp_path / "after"
    )

    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"

    before_path.write_text(json.dumps(before))
    after_path.write_text(json.dumps(after))

    assert report_main([str(before_path), "--compare", str(after_path)]) == 0

    out = capsys.readouterr().out

    newly_line = next(
        (line for line in out.splitlines() if line.startswith("Newly loaded:")), ""
    )

    # tarfile pulls in a couple of companions on some versions (grp,
    # pwd), so the exact list beside the label is not stable; the
    # label and the module both are.

    assert "Newly loaded:" in newly_line
    assert "tarfile" in newly_line
    assert "Total import time:" in out
