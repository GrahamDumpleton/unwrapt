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
    declared_lazy: bool = False,
    self_modules: int = 0,
    extension_module: bool = False,
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
        declared_lazy=declared_lazy,
        self_modules=self_modules,
        extension_module=extension_module,
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

    assert data["schema"] == SCHEMA == Report.SCHEMA == 4
    assert data["labels"] == {
        "app": "shop",
        "release": "r3",
        "role": "host",
        "outcome": "fork",
    }
    assert data["label_sets"] == [{}]
    assert data["filters"] == {"min_ms": 0.0, "packages": None, "rows": 8}
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
        "self_modules": 0,
        "defer": {"native": True, "unwrapt": True, "reason": None},
        "declared_lazy": False,
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


def test_from_dict_reads_a_report_without_rows() -> None:
    # A 1.0.0a3 report has no rows filter, and reads as the default.

    data = json.loads(report_of(edge(0, "csv", "app")).render_json())
    del data["filters"]["rows"]

    assert Report.from_dict(data).filters["rows"] == 8

    data["filters"]["rows"] = -1

    with pytest.raises(ValueError, match="rows must be a non-negative"):
        Report.from_dict(data)


def test_from_dict_refuses_another_schema() -> None:
    data = dict(report_of().to_dict())
    data["schema"] = 1

    with pytest.raises(ValueError, match="schema 1 is not supported"):
        Report.from_dict(data)


def test_filters_stored_and_overridable() -> None:
    report = report_of(
        edge(0, "csv", "app", cum_ms=50.0, self_ms=50.0),
        edge(1, "wave", "app", cum_ms=0.1, self_ms=0.1),
        options=ProfileOptions(min_ms=10.0, packages=("app",), rows=3),
    )

    assert report.to_dict()["filters"] == {
        "min_ms": 10.0,
        "packages": ["app"],
        "rows": 3,
    }

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
        edge(9, "numbers", "_decimal", extension_module=True),
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
    assert defer[9] == {
        "native": False,
        "unwrapt": False,
        "reason": "extension-module",
    }


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
            "used_at_load": False,
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


def _heavy_section(text: str) -> list[str]:
    section = text.split("Heavy modules: by self time\n")[1].split("\n\n")[0]

    return section.splitlines()


def _chain_modules(text: str) -> list[str]:
    section = text.split("Import chains: why each heavy module is loaded\n")[1]
    section = section.split("Limits of this report:")[0]

    return [
        line.split()[0]
        for line in section.splitlines()
        if line.startswith("  ") and not line.startswith("    ")
    ]


def test_heavy_modules_text_lists_the_eight_heaviest() -> None:
    report = report_of(
        *(
            edge(index, f"mod{index}", "app", cum_ms=20.0 - index, self_ms=20.0 - index)
            for index in range(10)
        )
    )

    lines = _heavy_section(report.render_text())

    assert [line.split()[-1] for line in lines[:-1]] == [
        f"mod{index}" for index in range(8)
    ]
    assert lines[-1] == "  (2 more not shown)"

    # Each listed module has its chain, and no other module does.

    assert _chain_modules(report.render_text()) == [f"mod{index}" for index in range(8)]

    # The analysis function still returns every module.

    assert len(heavy_modules(report)) == 10

    # rows changes how many are listed, each with its chain, and 0
    # lists them all.

    text = report.render_text(rows=3)

    assert _heavy_section(text)[-1] == "  (7 more not shown)"
    assert _chain_modules(text) == ["mod0", "mod1", "mod2"]

    lines = _heavy_section(report.render_text(rows=0))

    assert len(lines) == 10
    assert "more not shown" not in "\n".join(lines)

    with pytest.raises(ValueError, match="rows must be a non-negative"):
        report.render_text(rows=-1)


def test_rows_filter_is_stored_in_the_report() -> None:
    report = report_of(
        *(
            edge(index, f"mod{index}", f"app.m{index}", cum_ms=20.0 - index)
            for index in range(5)
        ),
        options=ProfileOptions(rows=2),
    )

    text = report.render_text()

    assert _heavy_section(text)[-1] == "  (3 more not shown)"
    assert _by_importer_section(text)[-1] == "  (3 more not shown)"
    assert len(_heavy_section(report.render_text(rows=0))) == 5


def test_heavy_modules_text_filters_on_self_time() -> None:
    report = report_of(
        edge(0, "numpy", "app", cum_ms=90.0, self_ms=80.0),
        edge(1, "wrapper", "app", cum_ms=95.0, self_ms=0.5),
    )

    text = report.render_text(min_ms=1.0)
    lines = _heavy_section(text)

    assert lines == [
        "(modules under 1.0 ms self time hidden by the min_ms filter)",
        "  80.0 ms  numpy",
        "  (1 more not shown)",
    ]
    assert _chain_modules(text) == ["numpy"]


def test_heavy_modules_text_keeps_modules_loaded_through_packages() -> None:
    report = report_of(
        # The application's own package, imported by the entry point,
        # and what it pulls in, directly and further down.
        edge(0, "app", "__main__", cum_ms=60.0, self_ms=5.0),
        edge(1, "numpy", "app", parent_id=0, cum_ms=55.0, self_ms=30.0),
        edge(2, "_multiarray", "numpy", parent_id=1, cum_ms=25.0, self_ms=25.0),
        # Imports the entry point makes itself, outside the package.
        edge(3, "sqlite3", "__main__", cum_ms=40.0, self_ms=10.0),
        edge(4, "_sqlite3", "sqlite3", parent_id=3, cum_ms=30.0, self_ms=30.0),
    )

    text = report.render_text(packages=["app"])
    lines = _heavy_section(text)

    assert lines == [
        "(modules not loaded through app hidden by the packages filter)",
        "  30.0 ms  numpy",
        "  25.0 ms  _multiarray",
        "  5.0 ms  app",
        "  (2 more not shown)",
    ]
    assert _chain_modules(text) == ["numpy", "_multiarray", "app"]

    # Without the filter every module is listed.

    assert len(_heavy_section(report.render_text())) == 5


def test_by_importer_sums_direct_loads_only() -> None:
    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=5.0),
        edge(1, "csv", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=85.0),
        edge(2, "mypkg.client", "app", cum_ms=20.0, self_ms=2.0),
    )

    entries = {entry["importer"]: entry["cum_ms"] for entry in by_importer(report)}

    assert entries == {"app": 120.0, "mypkg.web": 90.0}


def _by_importer_section(text: str) -> list[str]:
    section = text.split("the files to edit first\n")[1].split("\n\n")[0]

    return section.splitlines()


def test_by_importer_text_lists_the_eight_costliest() -> None:
    report = report_of(
        *(
            edge(index, "csv", f"app.mod{index}", cum_ms=20.0 - index)
            for index in range(10)
        )
    )

    lines = _by_importer_section(report.render_text())

    assert [line.split()[-1] for line in lines[:-1]] == [
        f"app.mod{index}" for index in range(8)
    ]
    assert lines[-1] == "  (2 more not shown)"

    # The analysis function still returns every importer.

    assert len(by_importer(report)) == 10


def test_by_importer_text_applies_the_filters() -> None:
    report = report_of(
        edge(0, "numpy", "app.analytics", cum_ms=90.0),
        edge(1, "csv", "app.client", cum_ms=0.5),
        edge(2, "markupsafe", "jinja2", cum_ms=40.0),
    )

    lines = _by_importer_section(report.render_text(min_ms=1.0, packages=["app"]))

    assert lines == [
        "(importers under 1.0 ms hidden by the min_ms filter)",
        "(importers outside app hidden by the packages filter)",
        "  90.0 ms  app.analytics",
        "  (2 more not shown)",
    ]


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


# The figures for modules and packages.


def test_summary_counts_modules_and_packages() -> None:
    report = report_of(
        edge(0, "xml.dom.minidom", "app", self_modules=4),
        edge(1, "xml.dom.domreg", "xml.dom", parent_id=0, self_modules=1),
        edge(2, "wave", "app", self_modules=1),
        edge(3, "wave", "other", loaded=False),
    )

    figures = summary(report)

    assert figures["modules_loaded"] == 6
    assert figures["packages_loaded"] == 2
    assert "6 modules loaded (2 packages)" in report.render_text()


def test_compare_reports_counts_modules_and_packages() -> None:
    before = report_of(edge(0, "csv", "app", self_modules=2))
    after = report_of(
        edge(0, "csv", "app", self_modules=2),
        edge(1, "xml.dom", "app", self_modules=2),
    )

    text = compare_reports(before, after)

    assert "Modules loaded: 2 -> 4" in text
    assert "Packages loaded: 1 -> 2" in text


# Imports made by extension modules.


def test_extension_module_import_is_an_eager_importer() -> None:
    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=10.0),
        edge(1, "numbers", "mypkg.web", parent_id=0, cum_ms=40.0, self_ms=40.0),
        edge(2, "_decimal", "decimal", kind="from", cum_ms=5.0, self_ms=5.0),
        edge(
            3, "numbers", "_decimal", parent_id=2, loaded=False, extension_module=True
        ),
    )

    # The extension needs numbers whenever it loads, so deferring
    # mypkg.web only moves the cost of numbers, and nothing is advised.

    assert all(row["importer"] != "_decimal" for row in candidates(report))
    assert summary(report)["estimated_saving_ms"] == 100.0 - 40.0
    assert {row["imported"]: row["shared"] for row in candidates(report)}[
        "numbers"
    ] == ["_decimal"]

    found = chain(report, "numbers")

    assert found is not None and found["best_cut"] is None

    text = report.render_text()

    assert "(3) an extension module made the import" in text


# Declared lazy, and deferred in this run.


def test_declared_lazy_loaded_eagerly_is_planned_but_not_offered() -> None:
    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=10.0, declared_lazy=True),
        edge(1, "xml.dom", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=90.0),
        edge(2, "wave", "app", cum_ms=20.0, self_ms=20.0),
    )

    rows = {row["imported"]: row for row in candidates(report)}

    # Decided already, so no best cut, but the cost is in the saving.

    assert rows["mypkg.web"]["declared_lazy"] is True
    assert rows["mypkg.web"]["already_lazy"] is False
    assert rows["mypkg.web"]["saving_ms"] == 100.0

    figures = summary(report)

    assert figures["estimated_saving_ms"] == 120.0
    assert figures["best_cut"] == 2

    found = chain(report, "xml")

    assert found is not None and found["best_cut"] is None

    text = report.render_text()

    assert "declared lazy, loaded eagerly: deferral is off in this run" in text
    assert "Declared lazy, loaded eagerly: 1 imports (100.0 ms cumulative)" in text


def test_declared_lazy_form_the_shim_cannot_defer() -> None:
    text = report_of(
        edge(0, "wave", "app", kind="from", cum_ms=10.0, declared_lazy=True)
    ).render_text()

    assert "declared lazy, loaded eagerly: unwrapt cannot defer this form" in text


def test_declared_lazy_is_not_an_eager_importer() -> None:
    report = report_of(
        edge(0, "mypkg.web", "app", cum_ms=100.0, self_ms=10.0),
        edge(1, "xml.dom", "mypkg.web", parent_id=0, cum_ms=90.0, self_ms=90.0),
        edge(2, "xml.dom", "other", kind="from", loaded=False, declared_lazy=True),
    )

    # The other importer is decided lazy, so the cost does not move.

    assert summary(report)["estimated_saving_ms"] == 100.0
    assert {row["imported"]: row["shared"] for row in candidates(report)}[
        "xml.dom"
    ] == []


# Imports used while their importer loads.


SOURCE = """\
import wave
import plistlib
import colorsys
import difflib
import string
import xml.dom as dom
import csv
import gzip

READER = wave.Wave_read


class Holder:
    colour = colorsys.rgb_to_hsv


@string.capwords
def decorated(value=difflib.SequenceMatcher):
    return plistlib.dumps({})


def annotated(value: csv.Dialect) -> None:
    pass


if TYPE_CHECKING:
    gzip.open

if __name__ == "__main__":
    dom.Node
"""


def _source_report(tmp_path: Path, python: str) -> Report:
    path = tmp_path / "mod.py"
    path.write_text(SOURCE)

    names = ["wave", "plistlib", "colorsys", "difflib", "string", "xml.dom", "csv"]
    names.append("gzip")

    report = report_of(
        *(
            edge(index, name, "mod", line=index + 1, file=str(path), cum_ms=1.0)
            for index, name in enumerate(names)
        )
    )
    report.python = python

    return report


def test_used_at_load_reads_the_load_time_code(tmp_path: Path) -> None:
    report = _source_report(tmp_path, "3.13.2")

    used = {row["imported"]: row["used_at_load"] for row in candidates(report)}

    # Module-level code, class bodies, decorators, default arguments and
    # evaluated annotations run at load; function bodies, TYPE_CHECKING
    # blocks and a __main__ guard in an imported module do not.

    assert used == {
        "wave": True,
        "plistlib": False,
        "colorsys": True,
        "difflib": True,
        "string": True,
        "xml.dom": False,
        "csv": True,
        "gzip": False,
    }

    rows = {row["imported"]: row for row in candidates(report)}

    assert rows["wave"]["saving_ms"] == 0.0
    assert rows["plistlib"]["saving_ms"] == 1.0

    # Left out of the plan, so the saving is that of the rows not used
    # at load that both routes can defer: plistlib and gzip, since
    # `import xml.dom as dom` is a form the shim cannot defer.

    assert summary(report)["estimated_saving_ms"] == 2.0
    assert "used at load (line 10), deferring saves nothing" in report.render_text()


def test_used_at_load_annotations_lazy_from_3_14(tmp_path: Path) -> None:
    report = _source_report(tmp_path, "3.14.0")

    used = {row["imported"]: row["used_at_load"] for row in candidates(report)}

    assert used["csv"] is False
    assert used["wave"] is True


def test_used_at_load_leaves_an_unreadable_source_alone(tmp_path: Path) -> None:
    broken = tmp_path / "broken.py"
    broken.write_text("import wave\nwave.x(\n")

    report = report_of(
        edge(0, "wave", "broken", line=1, file=str(broken), cum_ms=5.0),
        edge(1, "csv", "gone", line=1, file=str(tmp_path / "gone.py"), cum_ms=5.0),
    )

    assert [row["used_at_load"] for row in candidates(report)] == [False, False]
    assert summary(report)["estimated_saving_ms"] == 10.0


def test_used_at_load_found_in_the_run() -> None:
    report = report_of(
        edge(0, "app.web", "app", cum_ms=50.0),
        edge(1, "plistlib", "app.web", parent_id=0, loaded=False, deferred=True),
        edge(
            2,
            "plistlib",
            "app.web",
            parent_id=0,
            kind="resolve",
            resolves=1,
            used_in="app.web",
            already_lazy=True,
            declared_lazy=True,
        ),
        edge(3, "wave", "app.web", parent_id=0, loaded=False, deferred=True),
        edge(
            4,
            "wave",
            "app.web",
            kind="resolve",
            resolves=3,
            used_in="app",
            already_lazy=True,
            declared_lazy=True,
        ),
    )

    # The resolve inside the import call that loaded app.web saved
    # nothing; the one after it did.

    used = {entry["module"]: entry["used_at_load"] for entry in deferred_used(report)}

    assert used == {"plistlib": True, "wave": False}
    assert "remove the declaration" in report.render_text()


def test_documented_schema_example_is_current() -> None:
    # The JSON example on the reading-the-report page is the schema the
    # report writes: same version, and every edge with the same fields.

    path = Path(__file__).parent.parent / "docs" / "_static" / "report-schema.json"
    example = json.loads(path.read_text())
    written = report_of(edge(0, "csv", "app")).to_dict()

    assert example["schema"] == SCHEMA
    assert set(example) == set(written)

    for item in example["edges"]:
        assert set(item) == set(written["edges"][0])

    assert Report.from_dict(example).render_text()
