"""Tests for reporting deferred imports and their resolution.

unwrapt.deferred() lists the proxies the shim handed out, on_resolve()
calls back when one resolves, and a profile with deferral on records
each resolve as an edge and reports what was deferred and used anyway,
and what was deferred and never used. Each scenario runs in its own
subprocess, with an explicit Config so nothing is read from a file or
the environment.
"""

from pathlib import Path
from typing import Any

from support import run_facts, run_python, write_module

SETUP = """
        import json, sys, threading

        import unwrapt

        config = unwrapt.Config(
            lazy_modules={"__main__": ["wave", "difflib", "mypkg.outer"]},
            profile=unwrapt.ProfileOptions(format="json"),
        )

        def listed():
            return [
                [item.importer, item.module, item.resolved]
                for item in unwrapt.deferred()
            ]
        """


def test_deferred_before_and_after_resolution(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        before_install = listed()
        hook_loaded = "unwrapt._hook" in sys.modules

        unwrapt.install(config, defer=True)

        import wave
        import difflib

        before_use = listed()

        difflib.SequenceMatcher

        after_use = listed()

        unwrapt.uninstall()

        print(json.dumps({
            "before_install": before_install,
            "hook_loaded": hook_loaded,
            "before_use": before_use,
            "after_use": after_use,
            "after_uninstall": listed(),
        }))
        """,
        cwd=tmp_path,
    )

    # Asking before the shim was ever installed lists nothing and loads
    # nothing.

    assert facts["before_install"] == []
    assert facts["hook_loaded"] is False

    assert facts["before_use"] == [
        ["__main__", "wave", False],
        ["__main__", "difflib", False],
    ]
    assert facts["after_use"] == [
        ["__main__", "wave", False],
        ["__main__", "difflib", True],
    ]

    # The proxies outlive the layer, and so does the list.

    assert facts["after_uninstall"] == facts["after_use"]


def test_on_resolve_callback_arguments(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        seen = []

        unsubscribe = unwrapt.on_resolve(seen.append)
        unwrapt.install(config, defer=True)

        import wave
        import difflib

        def first_use():
            return difflib.SequenceMatcher

        threading.Thread(target=first_use, name="worker-1").start()

        for thread in threading.enumerate():
            if thread is not threading.current_thread():
                thread.join()

        use_line = first_use.__code__.co_firstlineno + 1

        unsubscribe()
        unsubscribe()

        wave.Wave_read

        resolution = seen[0]

        print(json.dumps({
            "count": len(seen),
            "type": type(resolution).__name__,
            "importer": resolution.importer,
            "module": resolution.module,
            "load_ms": resolution.load_ms,
            "loaded": resolution.loaded,
            "thread": resolution.thread.name,
            "used_in": resolution.used_in,
            "file": resolution.file,
            "line": resolution.line,
            "expected_line": use_line,
        }))
        """,
        cwd=tmp_path,
    )

    # The unsubscribed callback never saw wave resolve.

    assert facts["count"] == 1
    assert facts["type"] == "Resolution"
    assert facts["importer"] == "__main__"
    assert facts["module"] == "difflib"
    assert isinstance(facts["load_ms"], float) and facts["load_ms"] >= 0.0
    assert facts["loaded"] is True
    assert facts["thread"] == "worker-1"
    assert facts["used_in"] == "__main__"
    assert facts["file"] == "<string>"
    assert facts["line"] == facts["expected_line"]


def test_on_resolve_found_already_loaded(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        seen = []

        unwrapt.on_resolve(seen.append)
        unwrapt.install(config, defer=True)

        import wave

        # Something else loads wave before the proxy is used: the
        # resolve finds it already loaded.

        __import__("importlib").import_module("wave")

        wave.Wave_read

        print(json.dumps({"loaded": seen[0].loaded}))
        """,
        cwd=tmp_path,
    )

    assert facts == {"loaded": False}


def test_on_resolve_callback_that_raises(tmp_path: Path) -> None:
    result = run_python(
        SETUP
        + """
        seen = []

        def broken(resolution):
            raise ValueError("callback failure")

        unwrapt.on_resolve(broken)
        unwrapt.on_resolve(seen.append)
        unwrapt.install(config, defer=True)

        import difflib

        matcher = difflib.SequenceMatcher

        print(json.dumps({
            "used": matcher.__name__,
            "second_called": [item.module for item in seen],
        }))
        """,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr

    facts: dict[str, Any] = __import__("json").loads(result.stdout.splitlines()[-1])

    # The code that used the proxy never saw the exception, the next
    # callback still ran, and the failure was reported.

    assert facts == {"used": "SequenceMatcher", "second_called": ["difflib"]}
    assert "RuntimeWarning" in result.stderr
    assert "callback failure" in result.stderr


def _deferred_profile(tmp_path: Path) -> dict[str, Any]:
    write_module(tmp_path, "mypkg.outer", "import mypkg.inner\n")
    write_module(tmp_path, "mypkg.inner", "VALUE = 1\n")

    return run_facts(
        SETUP
        + """
        unwrapt.install(config, defer=True, profile=True)

        import wave
        import difflib
        import mypkg.outer

        def use():
            return difflib.SequenceMatcher, mypkg.outer.__name__

        use()

        use_line = use.__code__.co_firstlineno + 1

        report = unwrapt.stop_profile(write=False)
        from unwrapt.report import deferred_unused, deferred_used

        print(json.dumps({
            "report": report.to_dict(),
            "unused": deferred_unused(report),
            "used": deferred_used(report),
            "text": report.render_text(),
            "use_line": use_line,
        }))
        """,
        env={"PYTHONPATH": str(tmp_path)},
        cwd=tmp_path,
    )


def test_report_sections_for_a_deferred_run(tmp_path: Path) -> None:
    facts = _deferred_profile(tmp_path)
    report = facts["report"]
    edges = {edge["id"]: edge for edge in report["edges"]}

    deferred_ids = {
        edge["imported"]: edge["id"] for edge in report["edges"] if edge["deferred"]
    }

    assert set(deferred_ids) == {"wave", "difflib", "mypkg.outer"}

    assert facts["unused"] == [
        {"edge": deferred_ids["wave"], "module": "wave", "importer": "__main__"}
    ]

    used = {entry["module"]: entry for entry in facts["used"]}

    assert set(used) == {"difflib", "mypkg.outer"}

    for module in ("difflib", "mypkg.outer"):
        entry = used[module]

        assert entry["edge"] == deferred_ids[module]
        assert entry["importer"] == "__main__"
        assert entry["used_in"] == "__main__"
        assert entry["line"] == facts["use_line"]
        assert entry["loaded"] is True

        resolution = edges[entry["resolution"]]

        assert resolution["kind"] == "resolve"
        assert resolution["resolves"] == deferred_ids[module]
        assert resolution["cum_ms"] == entry["load_ms"]

    # The deferred module's own imports nest beneath its resolve edge,
    # so they are not counted again as outermost edges.

    inner = [edge for edge in report["edges"] if edge["imported"] == "mypkg.inner"]

    assert len(inner) == 1
    assert inner[0]["parent_id"] == used["mypkg.outer"]["resolution"]
    assert inner[0]["importer"] == "mypkg.outer"

    # A resolve is not a candidate statement.

    text = facts["text"]

    assert "Deferred but used anyway" in text
    assert "Deferred and never used" in text
    assert "--compare" in text

    candidates = text.split("Candidates:")[1].split("Heavy modules:")[0]

    assert "difflib" not in candidates


def test_eager_report_has_no_deferral_sections(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        unwrapt.install(config, defer=False, profile=True)

        import wave

        report = unwrapt.stop_profile(write=False)
        print(json.dumps({
            "report": report.to_dict(),
            "text": report.render_text(),
        }))
        """,
        cwd=tmp_path,
    )

    assert not any(edge["deferred"] for edge in facts["report"]["edges"])
    assert not any(edge["kind"] == "resolve" for edge in facts["report"]["edges"])
    assert "Deferred" not in facts["text"]
