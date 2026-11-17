"""Tests for the report and its analysis, in-process with synthetic edges.

build_report and the analysis functions are pure computation, so the
trickier guarantees (ordering, non-additivity, moved cost, chains, best
cuts, label sets, the schema) are tested directly on hand-built edges,
where the times are exact and not timing noise.
"""

import json
from pathlib import Path
from typing import Literal, cast

import pytest

from unwrapt._config import ProfileOptions
from unwrapt._report import Edge, build_report
from unwrapt.report import (
    SCHEMA,
    Report,
    by_importer,
    candidates,
    chain,
    chains,
    compare_reports,
    deferred_unused,
    deferred_used,
    heavy_modules,
    summary,
    who_pays,
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
    deferred: bool = False,
    resolves: int | None = None,
    used_in: str | None = None,
    relative: bool = False,
    labels: int = 0,
    count: int = 1,
    written: str | None = None,
    submodules: tuple[str, ...] = (),
) -> Edge:
    return Edge(
        id=edge_id,
        parent_id=parent_id,
        importer=importer,
        imported=imported,
        kind=cast(Literal["import", "from", "resolve"], kind),
        level_name=cast(Literal["module", "function", "class"], level),
        line=line,
        file=file,
        loaded=loaded,
        cum_ms=cum_ms,
        self_ms=self_ms,
        native_lazy=native_lazy,
        already_lazy=already_lazy,
        deferred=deferred,
        resolves=resolves,
        used_in=used_in,
        relative=relative,
        labels=labels,
        count=count,
        written=written,
        submodules=submodules,
    )


def report_of(*edges: Edge, options: ProfileOptions | None = None) -> Report:
    return build_report(list(edges), options or ProfileOptions())


# The schema.


def test_to_dict_is_the_versioned_schema() -> None:
    report = report_of(
        edge(0, "csv", "app", cum_ms=10.0, self_ms=10.0, line=3, file="app.py")
    )
    report.labels.update(app="shop", release="r3", role="host", outcome="fork")

    data = report.to_dict()

    assert data["schema"] == SCHEMA == Report.SCHEMA == 3
    assert data["labels"] == {
        "app": "shop",
        "release": "r3",
        "role": "host",
        "outcome": "fork",
    }
    assert data["label_sets"] == [{}]
    assert data["filters"] == {"min_ms": 0.0, "packages": None}
    assert set(data) == {
        "schema",
        "unwrapt",
        "python",
        "labels",
        "label_sets",
        "filters",
        "edges",
    }

    assert data["edges"][0] == {
        "id": 0,
        "parent_id": None,
        "importer": "app",
        "imported": "csv",
        "written": "csv",
        "submodules": [],
        "file": "app.py",
        "line": 3,
        "kind": "import",
        "level": "module",
        "relative": False,
        "loaded": True,
        "count": 1,
        "cum_ms": 10.0,
        "self_ms": 10.0,
        "defer": {"native": True, "unwrapt": True, "reason": None},
        "already_lazy": False,
        "native_lazy": False,
        "deferred": False,
        "resolution": None,
        "resolves": None,
        "used_in": None,
        "labels": 0,
    }


def test_report_round_trips_through_json() -> None:
    report = report_of(edge(0, "csv", "app", cum_ms=10.0, self_ms=10.0))
    report.labels["role"] = "host"

    restored = Report.from_dict(json.loads(report.render_json()))

    assert restored.to_dict() == report.to_dict()
    assert restored.render_text() == report.render_text()


def test_from_dict_refuses_another_schema() -> None:
    data = dict(report_of().to_dict())
    data["schema"] = 1

    with pytest.raises(ValueError, match="schema 1 is not supported"):
        Report.from_dict(data)


def test_filters_stored_and_overridable() -> None:
    report = report_of(
        edge(0, "csv", "app", cum_ms=50.0, self_ms=50.0),
        edge(1, "wave", "app", cum_ms=0.1, self_ms=0.1),
        options=ProfileOptions(min_ms=10.0, packages=("app",)),
    )

    assert report.to_dict()["filters"] == {"min_ms": 10.0, "packages": ["app"]}

    # The filters are applied in the render only, so a view can choose
    # its own: every edge is still in the data.

    assert {e["imported"] for e in report.edges} == {"csv", "wave"}
    assert [row["imported"] for row in candidates(report)] == ["csv"]
    assert [row["imported"] for row in candidates(report, min_ms=0.0)] == [
        "csv",
        "wave",
    ]

    text = report.render_text()

    assert "hidden by the min_ms filter" in text
    assert "hidden by the packages filter" in text
    assert "wave" not in text.split("Candidates:")[1].split("Heavy modules:")[0]
    assert "hidden by the min_ms filter" not in report.render_text(min_ms=0.0)


# The defer facts, by the shim's own rules.


def test_defer_reasons(tmp_path: Path) -> None:
    source = tmp_path / "mod.py"
    source.write_text("import xml.dom as dom\nimport xml.dom\n")

    report = report_of(
        edge(0, "xml.dom", "mod", line=1, file=str(source)),
        edge(1, "xml.dom", "mod", line=2, file=str(source)),
        edge(2, "wave", "app", level="function"),
        edge(3, "colorsys", "app", level="class"),
        edge(4, "sub", "pkg", kind="from", relative=True),
        edge(5, "wave", "app", kind="from"),
        edge(6, "csv", "app", loaded=False),
        edge(7, "plistlib", "app", loaded=False, deferred=True),
        edge(8, "plistlib", "app", kind="resolve", resolves=7),
    )

    defer = {e["id"]: e["defer"] for e in report.edges}

    assert defer[0] == {"native": True, "unwrapt": False, "reason": "dotted-as"}
    assert defer[1] == {"native": True, "unwrapt": True, "reason": None}
    assert defer[2] == {"native": False, "unwrapt": False, "reason": "function-level"}
    assert defer[3] == {"native": False, "unwrapt": False, "reason": "class-level"}
    assert defer[4] == {"native": True, "unwrapt": False, "reason": "relative"}
    assert defer[5] == {"native": True, "unwrapt": False, "reason": "from-import"}
    assert defer[6] == {"native": False, "unwrapt": False, "reason": "already-loaded"}
    assert defer[7] == {"native": True, "unwrapt": True, "reason": None}
    assert defer[8] == {"native": True, "unwrapt": True, "reason": None}


def test_deferred_edge_links_to_its_resolution() -> None:
    report = report_of(
        edge(0, "plistlib", "app", loaded=False, deferred=True),
        edge(1, "wave", "app", loaded=False, deferred=True),
        edge(
            2,
            "plistlib",
            "app",
            kind="resolve",
            resolves=0,
            used_in="app.web",
            line=12,
            cum_ms=4.0,
            self_ms=4.0,
            already_lazy=True,
        ),
    )

    by_id = {e["id"]: e for e in report.edges}

    assert by_id[0]["resolution"] == 2
    assert by_id[1]["resolution"] is None

    assert deferred_unused(report) == [{"edge": 1, "module": "wave", "importer": "app"}]
    assert deferred_used(report) == [
        {
            "edge": 0,
            "resolution": 2,
            "module": "plistlib",
            "importer": "app",
            "used_in": "app.web",
            "line": 12,
            "load_ms": 4.0,
            "loaded": True,
        }
    ]

    # A resolve is not a candidate statement, nor a direct load.

    assert candidates(report) == []
    assert by_importer(report) == []


# Labels.


def test_labels_index_into_label_sets() -> None:
    sets = [{}, {"entrypoint": "hooks"}, {"entrypoint": "mount:api"}]

    report = build_report(
        [
            edge(0, "numpy", "shop.hooks", cum_ms=90.0, self_ms=90.0, labels=1),
            edge(1, "numpy", "shop.api", loaded=False, labels=2, count=3),
            edge(2, "numpy", "shop.hooks", loaded=False, labels=1),
        ],
        ProfileOptions(),
        sets,
    )

    assert report.to_dict()["label_sets"] == sets
    assert report.label_set(2) == {"entrypoint": "mount:api"}
    assert report.label_set(99) == {}

    # The cost stays with the first load; the already-loaded edge under
    # a later label shows which other entry point needs the module.

    paid = who_pays(report)

    assert len(paid) == 1
    assert paid[0]["module"] == "numpy"
    assert paid[0]["importer"] == "shop.hooks"
    assert paid[0]["labels"] == {"entrypoint": "hooks"}
    assert paid[0]["cum_ms"] == 90.0
    assert paid[0]["also_needed_by"] == [
        {"importer": "shop.api", "labels": {"entrypoint": "mount:api"}, "count": 3}
    ]


# The analysis.


def test_candidates_sorted_by_cumulative_time() -> None:
    report = report_of(
        edge(0, "csv", "app", cum_ms=10.0, self_ms=1.0),
        edge(1, "wave", "app", cum_ms=50.0, self_ms=2.0),
        edge(2, "string", "app", cum_ms=30.0, self_ms=3.0),
    )

    assert [row["imported"] for row in candidates(report)] == ["wave", "string", "csv"]
    assert [row["saving_ms"] for row in candidates(report)] == [50.0, 30.0, 10.0]


def test_candidate_saving_subtracts_shared_cost() -> None:
    # web loads analytics which loads xml.dom, and other imports xml.dom
    # too: deferring web alone moves xml.dom's load to other.

    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=10.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=30.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
        edge(3, "xml.dom", "other", loaded=False),
        edge(4, "wave", "app", kind="from", cum_ms=20.0, self_ms=20.0),
    )

    rows = {row["edge"]: row for row in candidates(report)}

    assert rows[0]["saving_ms"] == 50.0
    assert rows[2]["saving_ms"] == 0.0
    assert rows[2]["shared"] == ["other"]

    # The shim cannot defer a from-import, so it saves nothing on its
    # own under unwrapt.

    assert rows[4]["unwrapt"] is False
    assert rows[4]["reason"] == "from-import"
    assert rows[4]["saving_ms"] == 0.0


def test_heavy_modules_sum_self_time() -> None:
    report = report_of(
        edge(0, "xml.dom", "app", cum_ms=100.0, self_ms=40.0),
        edge(1, "csv", "app", cum_ms=10.0, self_ms=8.0),
    )

    assert heavy_modules(report) == [
        {"module": "xml", "self_ms": 40.0},
        {"module": "csv", "self_ms": 8.0},
    ]


def test_by_importer_sums_direct_loads_only() -> None:
    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "csv", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=85.0),
        edge(2, "mypkg.client", "app", cum_ms=20.0, self_ms=2.0),
    )

    entries = {entry["importer"]: entry["cum_ms"] for entry in by_importer(report)}

    assert entries == {"app": 120.0, "mypkg.web": 90.0}


def test_total_is_sum_of_outermost_edges() -> None:
    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "csv", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=85.0),
        edge(2, "wave", "app", cum_ms=20.0, self_ms=20.0),
        edge(3, "os", "app", loaded=False, cum_ms=0.5, self_ms=0.5, count=5),
    )

    figures = summary(report)

    assert figures["total_import_ms"] == 120.5
    assert figures["edge_count"] == 4
    assert figures["import_calls"] == 8


def test_estimated_saving_three_level_nest_is_outermost() -> None:
    # A imports B imports C: cum(A) already contains the others, so the
    # saving of deferring the outermost is its own cumulative time, and
    # never a sum across the nest.

    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=10.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=20.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
    )

    assert summary(report)["estimated_saving_ms"] == 100.0
    assert summary(report)["total_import_ms"] == 100.0


def test_estimated_saving_subtracts_moved_cost() -> None:
    # The same nest, but another module imports the heavy module with a
    # from-import, which the shim does not defer: deferring the chain
    # only moves the cost, so the estimate subtracts it.

    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=10.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=20.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
        edge(3, "xml.dom", "other", kind="from", loaded=False),
    )

    assert summary(report)["estimated_saving_ms"] == 50.0


def test_already_loaded_hit_of_a_deferrable_form_is_in_the_plan() -> None:
    # An `import xml.dom` that found it loaded is a statement the plan
    # defers too, so it never stands as an eager importer.

    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=10.0),
        edge(1, "xml.dom", "mypkg.web", parent_id=0, cum_ms=50.0, self_ms=50.0),
        edge(2, "xml.dom", "other", loaded=False),
    )

    assert summary(report)["estimated_saving_ms"] == 100.0


def test_shared_note_lists_other_importers() -> None:
    report = report_of(
        edge(0, "xml.dom", "app", cum_ms=100.0, self_ms=100.0),
        edge(1, "xml.dom", "mypkg.analytics", loaded=False),
        edge(2, "xml.dom", "other", kind="from", loaded=False),
        edge(3, "mypkg.client", "other", cum_ms=5.0, self_ms=5.0),
    )

    rows = {row["edge"]: row for row in candidates(report)}

    assert rows[0]["shared"] == ["mypkg.analytics", "other"]

    # Importing a sibling of the top package is not importing the same
    # module.

    assert rows[3]["shared"] == []


def test_relative_edge_keeps_the_statement_as_written() -> None:
    report = report_of(
        edge(
            0,
            "flask",
            "flask",
            kind="from",
            relative=True,
            written=".",
            submodules=("flask.json",),
        ),
        edge(1, "csv", "app"),
    )

    relative, absolute = report.edges

    assert relative["imported"] == "flask"
    assert relative["written"] == "."
    assert relative["submodules"] == ["flask.json"]

    # An edge built without the written form records the name it
    # imported.

    assert absolute["written"] == "csv"
    assert absolute["submodules"] == []


def test_shared_note_matches_submodules() -> None:
    report = report_of(
        edge(0, "xml", "app", kind="from", submodules=("xml.dom",), cum_ms=9.0),
        edge(1, "xml.dom", "mypkg.analytics", loaded=False),
        edge(2, "xml", "mypkg.client", kind="from", loaded=False),
        edge(3, "flask", "__main__", kind="from", cum_ms=5.0),
        edge(4, "flask", "flask.ctx", kind="from", submodules=("flask.typing",)),
    )

    rows = {row["edge"]: row for row in candidates(report)}

    # `from xml import dom` is an importer of xml.dom, as `import
    # xml.dom` is, and not of the xml package, which a from-import of
    # an attribute of xml would be.

    assert rows[0]["submodules"] == ["xml.dom"]
    assert rows[0]["shared"] == ["mypkg.analytics"]

    # Binding a submodule of flask does not make flask.ctx an importer
    # of flask for the entry point's `from flask import Flask`.

    assert rows[3]["shared"] == []


def test_imported_cell_lists_submodules() -> None:
    report = report_of(
        edge(
            0,
            "pkg",
            "app",
            kind="from",
            submodules=("pkg.a", "pkg.b"),
            cum_ms=5.0,
            self_ms=5.0,
        ),
    )

    text = report.render_text()

    assert "pkg.a, pkg.b  app" in text
    assert "app -> pkg.a, pkg.b" in text


def test_who_pays_for_submodules_of_from_imports() -> None:
    report = report_of(
        # `from pkg import a` obtains pkg as it starts, and the package's
        # own `from . import a`, nested inside it, loads pkg.a.
        edge(0, "pkg", "app", kind="from", submodules=("pkg.a",), cum_ms=9.0),
        edge(
            1,
            "pkg",
            "pkg",
            parent_id=0,
            kind="from",
            relative=True,
            written=".",
            submodules=("pkg.a",),
            cum_ms=4.0,
        ),
        # `import other.x` loads other.x, which a later from-import that
        # loads something else also names: the first claim pays.
        edge(2, "other.x", "app", cum_ms=3.0),
        edge(
            3,
            "other",
            "app",
            kind="from",
            submodules=("other.x", "other.y"),
            cum_ms=2.0,
        ),
        # A cache hit naming a submodule needs it.
        edge(4, "pkg", "late", kind="from", submodules=("pkg.a",), loaded=False),
    )

    paid = {payment["module"]: payment for payment in who_pays(report)}

    assert {module: payment["edge"] for module, payment in paid.items()} == {
        "pkg": 0,
        "pkg.a": 1,
        "other.x": 2,
        "other": 3,
        "other.y": 3,
    }

    assert paid["pkg.a"]["also_needed_by"] == [
        {"importer": "late", "labels": {}, "count": 1}
    ]


def test_already_lazy_edges_are_not_savings() -> None:
    report = report_of(
        edge(0, "csv", "app", cum_ms=100.0, self_ms=100.0, already_lazy=True),
        edge(1, "wave", "app", cum_ms=50.0, self_ms=50.0),
    )

    assert summary(report)["estimated_saving_ms"] == 50.0
    assert {row["imported"]: row["saving_ms"] for row in candidates(report)} == {
        "csv": 0.0,
        "wave": 50.0,
    }


def test_chain_links_outermost_to_loading_edge() -> None:
    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=5.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
    )

    found = chain(report, "xml.dom")

    assert found is not None
    assert found["module"] == "xml"
    assert found["links"] == [0, 1, 2]
    assert found["best_cut"] == 0
    assert chain(report, "numpy") is None


def test_best_cut_moves_inward_when_outer_link_cannot_defer() -> None:
    report = report_of(
        edge(0, "mypkg.web", "app", kind="from", cum_ms=100.0, self_ms=5.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=5.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
    )

    found = chain(report, "xml")

    # The outermost link is a from-import the shim does not defer, so the
    # best cut is the first link both routes can.

    assert found is not None and found["best_cut"] == 1


def test_best_cut_none_when_shared_cost_moves() -> None:
    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "xml.dom", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=90.0),
        edge(2, "xml.dom", "other", kind="from", loaded=False),
    )

    found = chain(report, "xml")

    assert found is not None and found["best_cut"] is None
    assert summary(report)["estimated_saving_ms"] == 100.0 - 90.0


def test_best_cut_overall_is_largest() -> None:
    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "mypkg.analytics", "mypkg.web", parent_id=0, cum_ms=80.0, self_ms=5.0),
        edge(2, "xml.dom", "mypkg.analytics", parent_id=1, cum_ms=50.0, self_ms=50.0),
        edge(3, "wave", "app", cum_ms=20.0, self_ms=20.0),
    )

    assert summary(report)["best_cut"] == 0
    assert [item["module"] for item in chains(report)] == ["xml", "wave", "mypkg"]


# The renderers.


def test_render_text_with_no_edges() -> None:
    text = report_of().render_text()

    assert "0 edges (0 import calls)" in text
    assert "(nothing to show)" in text


def test_render_text_shows_report_labels() -> None:
    report = report_of(edge(0, "csv", "app", cum_ms=1.0, self_ms=1.0))
    report.labels.update(app="shop", role="host")

    assert "Labels: app=shop, role=host" in report.render_text()


def test_render_text_native_lazy_warning() -> None:
    text = report_of(
        edge(0, "csv", "app", cum_ms=10.0, self_ms=10.0, native_lazy=True)
    ).render_text()

    assert "native lazy imports on Python 3.15" in text
    assert "recorded at first use" in text


def test_render_text_marks_best_cut() -> None:
    text = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "xml.dom", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=90.0),
    ).render_text()

    assert "<- best cut" in text


def test_render_json_is_the_dict_form() -> None:
    report = report_of(edge(0, "csv", "app", cum_ms=1.0, self_ms=1.0))

    assert json.loads(report.render_json()) == report.to_dict()


def test_compare_reports_lists_changes() -> None:
    before = report_of(edge(0, "csv", "app", cum_ms=100.0, self_ms=100.0))
    after = report_of(
        edge(0, "wave", "app", cum_ms=60.0, self_ms=60.0),
        edge(1, "csv", "app", cum_ms=30.0, self_ms=30.0),
    )

    text = compare_reports(before, after)

    assert "100.0 ms -> 90.0 ms" in text
    assert "Newly loaded: wave" in text
    assert "No longer loaded:" not in text
    assert "csv: 100.0 ms -> 30.0 ms" in text


def test_compare_reports_no_longer_loaded() -> None:
    before = report_of(edge(0, "csv", "app", cum_ms=100.0, self_ms=100.0))
    after = report_of(edge(0, "wave", "app", cum_ms=10.0, self_ms=10.0))

    text = compare_reports(before, after)

    assert "No longer loaded: csv" in text
    assert "Newly loaded: wave" in text
