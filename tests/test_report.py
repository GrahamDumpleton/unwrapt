"""Tests for the report aggregation, in-process with synthetic edges.

build_report is pure computation, so the trickier guarantees (ordering,
non-additivity, moved cost, chains, best cuts) are tested directly on
hand-built edges, where the times are exact and not timing noise.
"""

from pathlib import Path
from typing import Literal, cast

from unwrapt._config import Settings
from unwrapt._report import (
    Edge,
    Report,
    build_report,
    compare_reports,
    render_text,
)


def edge(
    edge_id: int,
    imported: str,
    importer: str,
    *,
    parent_id: int | None = None,
    kind: str = "import",
    level: str = "module",
    line: int | None = None,
    file: str | None = None,
    loaded: bool = True,
    cum_ms: float = 0.0,
    self_ms: float = 0.0,
    already_lazy: bool = False,
    native_lazy: bool = False,
) -> Edge:
    return Edge(
        id=edge_id,
        parent_id=parent_id,
        importer=importer,
        imported=imported,
        kind=cast(Literal["import", "from"], kind),
        level_name=cast(Literal["module", "function", "class"], level),
        line=line,
        file=file,
        loaded=loaded,
        cum_ms=cum_ms,
        self_ms=self_ms,
        native_lazy=native_lazy,
        already_lazy=already_lazy,
    )


def test_candidates_sorted_by_cumulative_time() -> None:
    edges = [
        edge(0, "csv", "app", cum_ms=10.0, self_ms=1.0),
        edge(1, "wave", "app", cum_ms=50.0, self_ms=2.0),
        edge(2, "string", "app", cum_ms=30.0, self_ms=3.0),
    ]

    report = build_report(edges, Settings())

    rows = [e for e in report["edges"] if e["level"] == "module" and e["loaded"]]
    rows.sort(key=lambda e: (-e["cum_ms"], e["id"]))

    assert [row["imported"] for row in rows] == ["wave", "string", "csv"]


def test_heavy_modules_sum_self_time() -> None:
    edges = [
        edge(0, "xml.dom", "app", cum_ms=100.0, self_ms=40.0),
        edge(1, "csv", "app", cum_ms=10.0, self_ms=8.0),
    ]

    report = build_report(edges, Settings())

    assert report["heavy_modules"][0] == {"module": "xml", "self_ms": 40.0}
    assert report["heavy_modules"][1] == {"module": "csv", "self_ms": 8.0}


def test_by_importer_sums_direct_loads_only() -> None:
    edges = [
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "csv", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=85.0),
        edge(2, "mypkg.client", "app", cum_ms=20.0, self_ms=2.0),
    ]

    report = build_report(edges, Settings())

    entries = {entry["importer"]: entry["cum_ms"] for entry in report["by_importer"]}

    assert entries["app"] == 120.0
    assert entries["mypkg.web"] == 90.0


def test_total_is_sum_of_outermost_edges() -> None:
    edges = [
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "csv", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=85.0),
        edge(2, "wave", "app", cum_ms=20.0, self_ms=20.0),
    ]

    report = build_report(edges, Settings())

    assert report["total_import_ms"] == 120.0


def test_estimated_saving_three_level_nest_is_outermost() -> None:
    # A imports B imports C: cum(A) already contains the others, so the
    # saving of deferring the outermost is its own cumulative time, and
    # never a sum across the nest.

    edges = [
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=10.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=20.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
    ]

    report = build_report(edges, Settings())

    assert report["summary"]["estimated_saving_ms"] == 100.0
    assert report["total_import_ms"] == 100.0


def test_estimated_saving_subtracts_moved_cost() -> None:
    # The same nest, but another module imports the heavy module with a
    # from-import, which neither route defers: deferring the chain only
    # moves the cost, so the estimate subtracts it.

    edges = [
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=10.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=20.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
        edge(3, "xml.dom", "other", kind="from", cum_ms=50.0, self_ms=0.0),
    ]

    report = build_report(edges, Settings())

    assert report["summary"]["estimated_saving_ms"] == 50.0


def test_shared_note_lists_other_importers() -> None:
    edges = [
        edge(0, "xml.dom", "app", cum_ms=100.0, self_ms=100.0),
        edge(1, "xml.dom", "mypkg.analytics", cum_ms=5.0, self_ms=5.0),
        edge(2, "xml.dom", "other", kind="from", cum_ms=5.0, self_ms=5.0),
    ]

    report = build_report(edges, Settings())

    by_id = {e["id"]: e for e in report["edges"]}

    assert by_id[0]["other_eager_importers"] == ["mypkg.analytics", "other"]
    assert by_id[1]["other_eager_importers"] == ["app", "other"]


def test_shared_note_groups_by_exact_name() -> None:
    # Importing a sibling of the top package is not importing the same
    # module: mypkg.client does not import mypkg.web.

    edges = [
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=100.0),
        edge(1, "mypkg.client", "other", cum_ms=5.0, self_ms=5.0),
    ]

    report = build_report(edges, Settings())

    by_id = {e["id"]: e for e in report["edges"]}

    assert by_id[0]["other_eager_importers"] == []
    assert by_id[1]["other_eager_importers"] == []


def test_already_lazy_edges_are_not_savings() -> None:
    edges = [
        edge(0, "csv", "app", cum_ms=100.0, self_ms=100.0, already_lazy=True),
        edge(1, "wave", "app", cum_ms=50.0, self_ms=50.0),
    ]

    report = build_report(edges, Settings())

    assert report["summary"]["estimated_saving_ms"] == 50.0


def test_chains_link_outermost_to_loading_edge() -> None:
    edges = [
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=5.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
    ]

    report = build_report(edges, Settings())

    chain = next(chain for chain in report["chains"] if chain["module"] == "xml")

    assert chain["links"] == [0, 1, 2]
    assert chain["best_cut"] == 0


def test_best_cut_moves_inward_when_outer_link_cannot_defer() -> None:
    edges = [
        edge(0, "mypkg.web", "app", kind="from", cum_ms=100.0, self_ms=5.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=5.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
    ]

    report = build_report(edges, Settings())

    chain = next(chain for chain in report["chains"] if chain["module"] == "xml")

    # The outermost link is a from-import neither route in the plan
    # defers, so the best cut is the first link both can.

    assert chain["best_cut"] == 1


def test_best_cut_none_when_shared_cost_moves() -> None:
    # Every link on the chain has the heavy module also imported by an
    # eager from-import elsewhere, so no cut on the chain keeps it
    # unloaded.

    edges = [
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "xml.dom", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=90.0),
        edge(2, "xml.dom", "other", kind="from", cum_ms=50.0, self_ms=50.0),
    ]

    report = build_report(edges, Settings())

    chain = next(chain for chain in report["chains"] if chain["module"] == "xml")

    assert chain["best_cut"] is None
    assert report["summary"]["estimated_saving_ms"] == 100.0 - 90.0


def test_best_cut_overall_is_largest() -> None:
    edges = [
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=5.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
        edge(3, "wave", "app", cum_ms=20.0, self_ms=20.0),
    ]

    report = build_report(edges, Settings())

    assert report["summary"]["best_cut"] == 0


def test_dotted_as_detection_reads_source(tmp_path: Path) -> None:
    source = tmp_path / "mod.py"
    source.write_text("import xml.dom as dom\nimport xml.dom\n")

    edges = [
        edge(0, "xml.dom", "mod", line=1, file=str(source)),
        edge(1, "xml.dom", "mod", line=2, file=str(source)),
    ]

    report = build_report(edges, Settings())

    by_id = {e["id"]: e for e in report["edges"]}

    assert by_id[0]["deferrable"] == {"native": True, "unwrapt": False}
    assert by_id[0]["unwrapt_limit"] == "dotted-as"

    assert by_id[1]["deferrable"] == {"native": True, "unwrapt": True}
    assert by_id[1]["unwrapt_limit"] is None


def test_function_and_class_level_classification() -> None:
    edges = [
        edge(0, "wave", "app", level="function"),
        edge(1, "colorsys", "app", level="class"),
    ]

    report = build_report(edges, Settings())

    by_id = {e["id"]: e for e in report["edges"]}

    assert by_id[0]["deferrable"] == {"native": False, "unwrapt": False}
    assert by_id[0]["unwrapt_limit"] == "function-level"

    assert by_id[1]["deferrable"] == {"native": False, "unwrapt": False}
    assert by_id[1]["unwrapt_limit"] == "class-level"


def test_filters_stored_in_summary() -> None:
    edges = [edge(0, "csv", "app", cum_ms=10.0, self_ms=10.0)]

    report = build_report(
        edges,
        Settings(profile_min_ms=5.0, profile_packages=("mypkg",)),
    )

    assert report["summary"]["filters"]["min_ms"] == 5.0
    assert report["summary"]["filters"]["packages"] == ["mypkg"]


def test_render_text_with_no_edges() -> None:
    report = build_report([], Settings())

    text = render_text(report)

    assert "0 edges" in text
    assert "(nothing to show)" in text


def test_render_text_native_lazy_warning() -> None:
    edges = [
        edge(0, "csv", "app", cum_ms=10.0, self_ms=10.0, native_lazy=True),
    ]

    text = render_text(build_report(edges, Settings()))

    assert "native lazy imports on Python 3.15" in text
    assert "recorded at first use" in text


def test_render_text_marks_best_cut() -> None:
    edges = [
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "xml.dom", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=90.0),
    ]

    text = render_text(build_report(edges, Settings()))

    assert "<- best cut" in text


def test_compare_reports_lists_changes() -> None:
    before = build_report(
        [edge(0, "csv", "app", cum_ms=100.0, self_ms=100.0)],
        Settings(),
    )
    after = build_report(
        [
            edge(0, "wave", "app", cum_ms=60.0, self_ms=60.0),
            edge(1, "csv", "app", cum_ms=30.0, self_ms=30.0),
        ],
        Settings(),
    )

    text = compare_reports(before, after)

    assert "100.0 ms -> 90.0 ms" in text
    assert "Newly loaded: wave" in text
    assert "No longer loaded:" not in text
    assert "csv: 100.0 ms -> 30.0 ms" in text


def test_compare_reports_no_longer_loaded() -> None:
    before = build_report(
        [edge(0, "csv", "app", cum_ms=100.0, self_ms=100.0)],
        Settings(),
    )
    after = build_report(
        [edge(0, "wave", "app", cum_ms=10.0, self_ms=10.0)],
        Settings(),
    )

    text = compare_reports(before, after)

    assert "No longer loaded: csv" in text
    assert "Newly loaded: wave" in text


def test_report_round_trips_through_json() -> None:
    import json

    edges = [edge(0, "csv", "app", cum_ms=10.0, self_ms=10.0)]

    report = build_report(edges, Settings())

    restored = cast(Report, json.loads(json.dumps(report)))

    assert render_text(restored) == render_text(report)


def test_min_ms_hides_rows_in_render() -> None:
    edges = [
        edge(0, "csv", "app", cum_ms=50.0, self_ms=50.0),
        edge(1, "wave", "app", cum_ms=0.1, self_ms=0.1),
    ]

    report = build_report(edges, Settings(profile_min_ms=10.0))

    text = render_text(report)

    assert "csv" in text
    assert "hidden by UNWRAPT_PROFILE_MIN_MS" in text

    # The hidden row is filtered in the render, not in the schema:
    # every edge is still in the JSON.

    assert {e["imported"] for e in report["edges"]} == {"csv", "wave"}
