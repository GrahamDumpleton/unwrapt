"""Tests for profile mode, each in its own subprocess.

Profile mode installs a recording hook instead of the shim hook, so it
is as process global as the shim. Children run with UNWRAPT_PROFILE
set and a JSON report path, and the tests assert on the report
structure, never on absolute millisecond values. The recorder's pure
name helpers are the exception, tested in process.
"""

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from support import json_config, run_facts, run_python, write_module

import unwrapt
from unwrapt._profile import _extension_loading, _resolve_name, _submodules
from unwrapt.report import (
    Report,
    by_importer,
    candidates,
    deferred_used,
    heavy_modules,
    summary,
    who_pays,
)

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

        unwrapt.install_from_env()

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

        unwrapt.install_from_env()

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

        unwrapt.install_from_env()

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

        unwrapt.install_from_env()

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
    assert csv_edge["declared_lazy"] is True

    # Below 3.15 the declaration is unwrapt's to honour, and with
    # deferral off nothing in the run defers it; on 3.15 native did.

    if sys.version_info < (3, 15):
        assert csv_edge["native_lazy"] is False
        assert csv_edge["already_lazy"] is False
    else:
        assert csv_edge["native_lazy"] is True
        assert csv_edge["already_lazy"] is True


def test_route_columns(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import wave
        from difflib import SequenceMatcher
        """,
        tmp_path,
    )

    csv_edge = next(edge for edge in report["edges"] if edge["imported"] == "wave")
    difflib_edge = next(
        edge for edge in report["edges"] if edge["imported"] == "difflib"
    )

    assert csv_edge["defer"] == {"native": True, "unwrapt": True, "reason": None}

    assert difflib_edge["defer"] == {
        "native": True,
        "unwrapt": False,
        "reason": "from-import",
    }


def test_dotted_as_edge_detected(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "asmod",
        "import xml.dom as dom\n",
    )

    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import asmod
        """,
        tmp_path,
    )

    edge = next(edge for edge in report["edges"] if edge["imported"] == "xml.dom")

    assert edge["defer"] == {"native": True, "unwrapt": False, "reason": "dotted-as"}


def test_min_ms_filter_hides_candidates(tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    run_python(
        """
        import unwrapt

        unwrapt.install_from_env()

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
    assert report["filters"]["min_ms"] == 100000.0


def test_output_path_expands_pid(tmp_path: Path) -> None:
    output = tmp_path / "report-%p.json"

    run_python(
        """
        import unwrapt

        unwrapt.install_from_env()

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

        unwrapt.install_from_env()

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

    assert report["filters"]["packages"] == ["mypkg"]

    # The wave imported by __main__ is outside the filter and the stdlib
    # importer of _csv is too; the render hides them. The JSON keeps
    # every edge.

    assert any(edge["imported"] == "wave" for edge in report["edges"])


def test_json_schema_shape(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import wave
        """,
        tmp_path,
    )

    assert report["schema"] == 4
    assert report["unwrapt"] == unwrapt.__version__
    assert "python" in report
    assert report["labels"] == {}
    assert report["label_sets"] == [{}]
    assert report["filters"] == {"min_ms": 0.0, "packages": None, "rows": 8}
    assert isinstance(report["edges"], list)

    # Facts only: the analysis is computed from them, not stored.

    assert set(report) == {
        "schema",
        "unwrapt",
        "python",
        "labels",
        "label_sets",
        "filters",
        "edges",
    }

    edge = next(edge for edge in report["edges"] if edge["imported"] == "wave")

    assert set(edge) == {
        "id",
        "parent_id",
        "importer",
        "imported",
        "written",
        "submodules",
        "file",
        "line",
        "kind",
        "level",
        "relative",
        "loaded",
        "count",
        "cum_ms",
        "self_ms",
        "self_modules",
        "defer",
        "declared_lazy",
        "already_lazy",
        "native_lazy",
        "deferred",
        "resolution",
        "resolves",
        "used_in",
        "labels",
    }
    assert edge["file"] == "<string>"
    assert edge["count"] == 1


def test_repeated_hits_are_folded(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import wave

        def again():
            import wave

        for _ in range(500):
            again()
        """,
        tmp_path,
    )

    waves = [edge for edge in report["edges"] if edge["imported"] == "wave"]

    # The load is kept as it is, and the 500 hits from the function are
    # one folded edge with their count and summed time.

    assert len(waves) == 2

    loaded = next(edge for edge in waves if edge["loaded"])
    folded = next(edge for edge in waves if not edge["loaded"])

    assert loaded["count"] == 1
    assert folded["count"] == 500
    assert folded["level"] == "function"
    assert folded["defer"]["reason"] == "function-level"
    assert folded["cum_ms"] >= 0.0


def test_relative_import_is_flagged(tmp_path: Path) -> None:
    write_module(tmp_path, "mypkg.__init__", "from . import sub\n")
    write_module(tmp_path, "mypkg.sub", "VALUE = 1\n")

    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import mypkg
        """,
        tmp_path,
    )

    edge = next(
        edge
        for edge in report["edges"]
        if edge["importer"] == "mypkg" and edge["relative"]
    )

    assert edge["defer"] == {"native": True, "unwrapt": False, "reason": "relative"}


def test_relative_imports_are_resolved(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "relpkg.__init__",
        "from . import alpha\nfrom .sub import VALUE\n",
    )
    write_module(tmp_path, "relpkg.alpha", "A = 1\n")
    write_module(tmp_path, "relpkg.sub.__init__", "from ..other import Z\nVALUE = 1\n")
    write_module(tmp_path, "relpkg.other", "Z = 2\n")

    # The entry point's from-import is the outer call, and the package's
    # own `from . import alpha` the inner one that loads relpkg.alpha.

    facts = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        from relpkg import alpha
        """,
        tmp_path,
    )

    edges = {
        (edge["importer"], edge["written"]): edge
        for edge in facts["edges"]
        if edge["importer"] is not None
        and edge["importer"].partition(".")[0] in ("__main__", "relpkg")
    }

    # Each relative import is recorded by the module it names, with the
    # statement as written beside it, and still marked relative.

    alpha = edges[("relpkg", ".")]

    assert alpha["imported"] == "relpkg"
    assert alpha["submodules"] == ["relpkg.alpha"]
    assert alpha["relative"] is True
    assert alpha["defer"]["reason"] == "relative"

    sub = edges[("relpkg", ".sub")]

    assert sub["imported"] == "relpkg.sub"
    assert sub["submodules"] == []

    other = edges[("relpkg.sub", "..other")]

    assert other["imported"] == "relpkg.other"
    assert other["relative"] is True

    # An absolute from-import names its submodules too, and is not
    # relative.

    outer = edges[("__main__", "relpkg")]

    assert outer["imported"] == "relpkg"
    assert outer["submodules"] == ["relpkg.alpha"]
    assert outer["relative"] is False

    # The candidates name the modules each statement is for, heavy
    # modules group by the top-level package, and no chain link is
    # blank.

    report = Report.from_dict(facts)

    rows = {
        (row["importer"], row["imported"], tuple(row["submodules"]))
        for row in candidates(report)
    }

    assert rows == {
        ("__main__", "relpkg", ("relpkg.alpha",)),
        ("relpkg", "relpkg", ("relpkg.alpha",)),
        ("relpkg", "relpkg.sub", ()),
        ("relpkg.sub", "relpkg.other", ()),
    }

    text = report.render_text()

    assert "__main__ -> relpkg.alpha" in text
    assert " ->   cum" not in text

    heavy = {entry["module"] for entry in heavy_modules(report)}

    assert "relpkg" in heavy
    assert not heavy & {"", "sub", "other", "alpha"}

    # The outer call obtains relpkg as it starts and pays for it; the
    # inner from-import loads relpkg.alpha and pays for that.

    paid = {payment["module"]: payment["edge"] for payment in who_pays(report)}

    assert paid["relpkg"] == outer["id"]
    assert paid["relpkg.alpha"] == alpha["id"]
    assert paid["relpkg.sub"] == sub["id"]
    assert paid["relpkg.other"] == other["id"]


def test_resolve_name_follows_importlib() -> None:
    package = {"__name__": "pkg.mod", "__package__": "pkg"}

    assert _resolve_name("", package, 1) == "pkg"
    assert _resolve_name("sub", package, 1) == "pkg.sub"

    deep = {"__name__": "pkg.sub.mod", "__package__": "pkg.sub"}

    assert _resolve_name("other", deep, 2) == "pkg.other"
    assert _resolve_name("", deep, 2) == "pkg"

    # Without __package__, __spec__.parent, then __name__, less its last
    # part unless the module is a package.

    spec = SimpleNamespace(parent="pkg.sub")

    assert _resolve_name("x", {"__name__": "pkg.sub.m", "__spec__": spec}, 1) == (
        "pkg.sub.x"
    )
    assert _resolve_name("x", {"__name__": "pkg.sub.m"}, 1) == "pkg.sub.x"
    assert _resolve_name("x", {"__name__": "pkg.sub", "__path__": []}, 1) == (
        "pkg.sub.x"
    )

    # Whatever cannot be resolved is recorded as written: beyond the
    # top-level package, no package at all, or no globals.

    assert _resolve_name("x", package, 3) == "x"
    assert _resolve_name("x", {"__name__": "top"}, 1) == "x"
    assert _resolve_name("x", None, 1) == "x"


def test_submodules_are_the_loaded_fromlist_modules() -> None:
    import xml.dom  # noqa: F401

    assert _submodules("xml", ("dom", "no_such_module", "*")) == ("xml.dom",)
    assert _submodules("xml", ()) == ()


def test_scoped_labels_are_recorded(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        with unwrapt.scope(entrypoint="hooks"):
            import wave

            token = unwrapt.push_scope(role="inner")

            import difflib

            unwrapt.pop_scope(token)

        import plistlib
        """,
        tmp_path,
    )

    sets = report["label_sets"]

    def labels_of(name: str) -> dict[str, str]:
        found = next(edge for edge in report["edges"] if edge["imported"] == name)

        result: dict[str, str] = sets[found["labels"]]

        return result

    # Nested scopes merge, and the labels end with their scope.

    assert labels_of("wave") == {"entrypoint": "hooks"}
    assert labels_of("difflib") == {"entrypoint": "hooks", "role": "inner"}
    assert labels_of("plistlib") == {}


def test_summary_figures_are_sane(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import wave
        import xml.dom
        """,
        tmp_path,
    )

    figures = summary(Report.from_dict(report))

    # Non-additivity: the estimate can never exceed the total.

    assert figures["estimated_saving_ms"] <= figures["total_import_ms"]


def test_text_report_default_output(tmp_path: Path) -> None:
    result = run_python(
        """
        import unwrapt

        unwrapt.install_from_env()

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

        first = unwrapt.install_from_env()
        second = unwrapt.install_from_env()

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

    assert len(report["edges"]) > 0


# The statement's place, under a hook wrapping __import__ over the
# recorder.

WRAPPER = """
import builtins


def install(same_globals):
    inner = builtins.__import__

    def wrapper(name, globals=None, locals=None, fromlist=(), level=0):
        passed = globals if same_globals else dict(globals or {})
        return inner(name, passed, locals, fromlist, level)

    builtins.__import__ = wrapper
"""


def test_place_found_through_a_wrapping_hook(tmp_path: Path) -> None:
    write_module(tmp_path, "wrapmod", WRAPPER)
    app = write_module(
        tmp_path,
        "shop.app",
        "import wave\nfrom difflib import SequenceMatcher\n"
        "import xml.dom.minidom as minidom\n",
    )

    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import wrapmod

        wrapmod.install(same_globals=True)

        import shop.app
        """,
        tmp_path,
    )

    edges = {
        edge["imported"]: edge
        for edge in report["edges"]
        if edge["importer"] == "shop.app"
    }

    # Each edge names the statement, not the wrapper's line, and the
    # source line read there tells `import a.b as c` apart.

    assert [(edges[name]["file"], edges[name]["line"]) for name in edges] == [
        (str(app), 1),
        (str(app), 2),
        (str(app), 3),
    ]

    assert edges["wave"]["defer"] == {"native": True, "unwrapt": True, "reason": None}
    assert edges["difflib"]["defer"]["reason"] == "from-import"
    assert edges["xml.dom.minidom"]["defer"] == {
        "native": True,
        "unwrapt": False,
        "reason": "dotted-as",
    }


def test_place_falls_back_to_the_caller(tmp_path: Path) -> None:
    wrapper = write_module(tmp_path, "wrapmod", WRAPPER)
    write_module(tmp_path, "shop.app", "import wave\n")

    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import wrapmod

        wrapmod.install(same_globals=False)

        import shop.app
        """,
        tmp_path,
    )

    edge = next(
        edge
        for edge in report["edges"]
        if edge["importer"] == "shop.app" and edge["imported"] == "wave"
    )

    # Other globals than the statement's: no frame matches, and the
    # place is the hook's caller, the wrapper.

    line = WRAPPER.splitlines().index(
        "        return inner(name, passed, locals, fromlist, level)"
    )

    assert edge["file"] == str(wrapper)
    assert edge["line"] == line + 1


# Imports made by an extension module as it loads.


def test_extension_module_imports_are_credited_to_it(tmp_path: Path) -> None:
    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import _decimal
        """,
        tmp_path,
    )

    by_id = {edge["id"]: edge for edge in report["edges"]}

    numbers = next(
        edge
        for edge in report["edges"]
        if edge["imported"] == "numbers"
        and edge["parent_id"] is not None
        and by_id[edge["parent_id"]]["imported"] == "_decimal"
    )

    # The import is the extension's, has no statement, and neither route
    # can defer it.

    assert numbers["importer"] == "_decimal"
    assert numbers["file"] is None
    assert numbers["line"] is None
    assert numbers["defer"] == {
        "native": False,
        "unwrapt": False,
        "reason": "extension-module",
    }

    assert not any(
        edge["importer"] == "importlib._bootstrap" for edge in by_id.values()
    )

    loaded = Report.from_dict(report)

    assert all(row["edge"] != numbers["id"] for row in candidates(loaded))
    assert "_decimal" not in {entry["importer"] for entry in by_importer(loaded)}


def test_modules_and_packages_loaded(tmp_path: Path) -> None:
    write_module(tmp_path, "countpkg.a", "import countpkg.b\n")
    write_module(tmp_path, "countpkg.b", "import wave\n")

    output = tmp_path / "report.json"

    facts = run_facts(
        f"""
        import json
        import sys

        import unwrapt

        config = unwrapt.Config(
            profile=unwrapt.ProfileOptions(format="json", output={str(output)!r}),
        )

        unwrapt.install(config, defer=False, profile=True)

        before = len(sys.modules)

        import countpkg.a

        added = len(sys.modules) - before
        report = unwrapt.stop_profile(write=False)

        from unwrapt.report import summary

        figures = summary(report)

        print(json.dumps({{"added": added, **figures}}))
        """,
        cwd=tmp_path,
    )

    # Modules counts every module the run added to sys.modules, the
    # packages and their submodules included; packages the top-level
    # packages.

    assert facts["modules_loaded"] == facts["added"]
    assert facts["modules_loaded"] >= 4
    assert facts["packages_loaded"] < facts["modules_loaded"]


# Declared lazy, and deferred in this run.


def test_declared_lazy_loaded_eagerly_with_deferral_off(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["wave"]})

    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import wave
        """,
        tmp_path,
        {"UNWRAPT_CONFIG": config},
    )

    wave = next(edge for edge in report["edges"] if edge["imported"] == "wave")

    assert wave["loaded"] is True
    assert wave["declared_lazy"] is True
    assert wave["already_lazy"] is False

    loaded = Report.from_dict(report)
    row = next(row for row in candidates(loaded) if row["edge"] == wave["id"])

    # Not a new candidate, but its cost is real and in the saving.

    assert row["declared_lazy"] is True
    assert row["saving_ms"] == wave["cum_ms"]
    assert summary(loaded)["estimated_saving_ms"] >= wave["cum_ms"]

    text = loaded.render_text()

    assert "declared lazy, loaded eagerly: deferral is off in this run" in text
    assert "Declared lazy, loaded eagerly: 1 imports" in text


def test_declared_lazy_deferred_with_deferral_on(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["wave"]})

    report = _report_facts(
        """
        import unwrapt

        unwrapt.install_from_env()

        import wave
        """,
        tmp_path,
        {"UNWRAPT_CONFIG": config, "UNWRAPT_DEFER": "1"},
    )

    wave = next(edge for edge in report["edges"] if edge["imported"] == "wave")

    assert wave["deferred"] is True
    assert wave["declared_lazy"] is True
    assert wave["already_lazy"] is True


@pytest.mark.skipif(
    sys.version_info >= (3, 15), reason="__lazy_modules__ is native on 3.15"
)
def test_lazy_modules_declaration_with_deferral_off_and_on(tmp_path: Path) -> None:
    write_module(
        tmp_path,
        "declpkg.mod",
        '__lazy_modules__ = ["wave"]\nimport wave\n',
    )

    code = """
        import unwrapt

        unwrapt.install_from_env()

        import declpkg.mod
        """

    def wave_edge(report: dict[str, Any]) -> dict[str, Any]:
        found: dict[str, Any] = next(
            edge
            for edge in report["edges"]
            if edge["importer"] == "declpkg.mod" and edge["imported"] == "wave"
        )

        return found

    eager = _report_facts(code, tmp_path)
    edge = wave_edge(eager)

    assert (edge["declared_lazy"], edge["already_lazy"]) == (True, False)

    loaded = Report.from_dict(eager)

    assert summary(loaded)["estimated_saving_ms"] >= edge["cum_ms"]
    assert "declared lazy, loaded eagerly" in loaded.render_text()

    deferred = _report_facts(code, tmp_path, {"UNWRAPT_DEFER": "1"})
    edge = wave_edge(deferred)

    assert (edge["declared_lazy"], edge["already_lazy"]) == (True, True)


# Imports used while their importer loads.


def _use_package(root: Path) -> None:
    write_module(
        root,
        "usepkg.eager",
        "import wave\n\nREADER = wave.Wave_read\n",
    )
    write_module(
        root,
        "usepkg.lazyuse",
        "import plistlib\n\n\ndef go():\n    return plistlib.dumps({})\n",
    )


def test_used_at_load_found_in_the_source(tmp_path: Path) -> None:
    _use_package(tmp_path)

    report = Report.from_dict(
        _report_facts(
            """
            import unwrapt

            unwrapt.install_from_env()

            import usepkg.eager
            import usepkg.lazyuse
            """,
            tmp_path,
        )
    )

    rows = {
        row["imported"]: row
        for row in candidates(report)
        if row["importer"] in ("usepkg.eager", "usepkg.lazyuse")
    }

    # The module-level use leaves wave out of the plan, and plistlib,
    # used only in a function, stays advised.

    assert rows["wave"]["used_at_load"] is True
    assert rows["wave"]["saving_ms"] == 0.0
    assert rows["plistlib"]["used_at_load"] is False
    assert rows["plistlib"]["saving_ms"] > 0.0

    text = report.render_text()

    assert "used at load (line 3), deferring saves nothing" in text
    assert "-> wave" not in text.split("Best single cut:")[-1].splitlines()[0]


def test_used_at_load_found_in_the_run(tmp_path: Path) -> None:
    _use_package(tmp_path)

    config = json_config(
        tmp_path / "lazy.json",
        {"usepkg.eager": ["wave"], "usepkg.lazyuse": ["plistlib"]},
    )

    report = Report.from_dict(
        _report_facts(
            """
            import unwrapt

            unwrapt.install_from_env()

            import usepkg.eager
            import usepkg.lazyuse

            usepkg.lazyuse.go()
            """,
            tmp_path,
            {"UNWRAPT_CONFIG": config, "UNWRAPT_DEFER": "1"},
        )
    )

    used = {entry["module"]: entry for entry in deferred_used(report)}

    assert used["wave"]["used_at_load"] is True
    assert used["plistlib"]["used_at_load"] is False

    assert "used at load, deferring saves nothing; remove the declaration" in (
        report.render_text()
    )


def test_extension_loading_needs_the_import_systems_frame() -> None:
    # Any other frame, such as a source loader's reading its file, whose
    # C code imports _io, is not an extension module loading.

    assert _extension_loading(sys._getframe()) is None
