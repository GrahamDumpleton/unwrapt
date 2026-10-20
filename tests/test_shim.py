"""Tests for shim mode behaviour, each in its own subprocess.

The hook is process global, so every scenario runs as a child that
installs the hook, exercises one behaviour, and reports facts as JSON.

These tests drive deferral through the external configuration, which
works on every Python version, so what they exercise is unwrapt's own
proxy and reification on all of them. The __lazy_modules__ emulation,
which only exists below Python 3.15, has its own file, skipped there
and collected here only for the version-independent behaviour.

Modules chosen for deferral are ones wrapt does not import itself: a
module already in sys.modules is returned unchanged, and wrapt (which
the install imports) preloads json, inspect, copy, subprocess and
friends.
"""

import sys
from pathlib import Path

from support import json_config, run_facts, run_python

SETUP = """
        import json, sys, types

        import unwrapt

        installed = unwrapt.install()
        """

BELOW_315 = sys.version_info < (3, 15)


def _config(tmp_path: Path) -> str:
    return json_config(tmp_path / "lazy.json", {"__main__": ["wave"]})


def test_external_config_defers_until_first_use(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        import wave

        deferred = "wave" not in sys.modules
        proxy_type = type(wave).__name__

        value = wave.Wave_read

        facts = {
            "installed": installed,
            "deferred": deferred,
            "proxy_type": proxy_type,
            "loaded_after_use": "wave" in sys.modules,
            "real_after_use": type(wave) is types.ModuleType,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": _config(tmp_path)},
    )

    assert facts["installed"] is True
    assert facts["deferred"] is True
    assert facts["proxy_type"] == "LazyObjectProxy"
    assert facts["loaded_after_use"] is True
    assert facts["real_after_use"] is True


def test_reification_binds_real_module(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        import wave

        wave.Wave_read

        facts = {
            "is_sys_modules_csv": wave is sys.modules["wave"],
            "real": type(wave) is types.ModuleType,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": _config(tmp_path)},
    )

    assert facts["is_sys_modules_csv"] is True
    assert facts["real"] is True


def test_alias_import_defers_and_reifies(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["wave"]})

    facts = run_facts(
        SETUP
        + """
        import wave as wave_mod

        deferred = "wave" not in sys.modules

        value = wave_mod.Wave_read

        facts = {
            "deferred": deferred,
            "loaded_after_use": "wave" in sys.modules,
            "real_after_use": type(wave_mod) is types.ModuleType,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["deferred"] is True
    assert facts["loaded_after_use"] is True
    assert facts["real_after_use"] is True


def test_dotted_import_binds_top_package(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["xml.dom"]})

    facts = run_facts(
        SETUP
        + """
        import xml.dom

        deferred = "xml.dom" not in sys.modules
        proxy_type = type(xml).__name__

        xml.dom.Node

        facts = {
            "deferred": deferred,
            "proxy_type": proxy_type,
            "full_name_loaded": "xml.dom" in sys.modules,
            "top_real_after_use": type(xml) is types.ModuleType,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["deferred"] is True
    assert facts["proxy_type"] == "LazyObjectProxy"
    assert facts["full_name_loaded"] is True
    assert facts["top_real_after_use"] is True


def test_dotted_as_import_is_eager(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["xml.dom"]})

    facts = run_facts(
        SETUP
        + """
        import xml.dom as dom

        facts = {
            "loaded_at_statement": "xml.dom" in sys.modules,
            "real_module": type(dom) is types.ModuleType,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["loaded_at_statement"] is True
    assert facts["real_module"] is True


def test_from_import_is_eager(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["difflib"]})

    facts = run_facts(
        SETUP
        + """
        from difflib import SequenceMatcher

        facts = {
            "loaded_at_statement": "difflib" in sys.modules,
            "attribute_works": SequenceMatcher(None, "abc", "abc").ratio() == 1.0,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["loaded_at_statement"] is True
    assert facts["attribute_works"] is True


def test_function_level_import_is_not_deferred(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["plistlib"]})

    facts = run_facts(
        SETUP
        + """
        def uses_plistlib():
            import plistlib

            return type(plistlib).__name__

        loaded_at_def = "plistlib" in sys.modules
        name = uses_plistlib()

        facts = {
            "loaded_at_def": loaded_at_def,
            "loaded_at_call": "plistlib" in sys.modules,
            "type_name": name,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["loaded_at_def"] is False
    assert facts["loaded_at_call"] is True
    assert facts["type_name"] == "module"


def test_class_level_import_is_not_deferred(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["wave"]})

    facts = run_facts(
        SETUP
        + """
        class Holder:
            import wave

        facts = {
            "loaded_at_class_body": "wave" in sys.modules,
            "real_module": type(Holder.wave) is types.ModuleType,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["loaded_at_class_body"] is True
    assert facts["real_module"] is True


def test_module_wrapt_preloads_stays_eager(tmp_path: Path) -> None:
    # wrapt itself imports json, so json can never be deferred once the
    # shim is installed: a documented limitation, pinned here.

    config = json_config(tmp_path / "lazy.json", {"__main__": ["json"]})

    facts = run_facts(
        SETUP
        + """
        import json

        facts = {
            "loaded": "json" in sys.modules,
            "real_module": type(json) is types.ModuleType,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["loaded"] is True
    assert facts["real_module"] is True


def test_not_a_candidate_is_eager() -> None:
    facts = run_facts(
        SETUP
        + """
        import wave

        facts = {"loaded": "wave" in sys.modules}
        print(json.dumps(facts))
        """
    )

    # No declarations and no configuration: nothing is deferred, on any
    # version. On Python 3.15 there is not even a hook to bypass.

    assert facts["loaded"] is True


def test_missing_config_file_warns_and_continues(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        import wave

        facts = {
            "installed": installed,
            "loaded": "wave" in sys.modules,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": str(tmp_path / "nope.json")},
    )

    # The warning is the point; check it on the raw output.

    process = run_python(
        "import unwrapt\nunwrapt.install()\n",
        env={"UNWRAPT_CONFIG": str(tmp_path / "nope.json")},
    )

    assert "UNWRAPT_CONFIG file" in process.stderr
    assert "does not exist" in process.stderr

    # Below 3.15 an empty configuration still installs the hook (the
    # importer's own __lazy_modules__ remains a candidate source); on
    # 3.15 there is nothing left for unwrapt to do.

    assert facts["loaded"] is True

    if BELOW_315:
        assert facts["installed"] is True
    else:
        assert facts["installed"] is False


def test_invalid_config_file_warns_and_continues(tmp_path: Path) -> None:
    path = tmp_path / "lazy.json"
    path.write_text("{not json")

    facts = run_facts(
        SETUP
        + """
        import wave

        facts = {"installed": installed, "loaded": "wave" in sys.modules}
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": str(path)},
    )

    assert facts["loaded"] is True

    if BELOW_315:
        assert facts["installed"] is True
    else:
        assert facts["installed"] is False


def test_chains_to_previously_installed_wrapper(tmp_path: Path) -> None:
    config = _config(tmp_path)

    facts = run_facts(
        """
        import builtins, json, sys

        calls = []

        original = builtins.__import__

        def wrapper(name, globals=None, locals=None, fromlist=(), level=0):
            calls.append(name)

            return original(name, globals, locals, fromlist, level)

        builtins.__import__ = wrapper

        import unwrapt

        unwrapt.install()

        import wave
        import plistlib

        facts = {
            "wrapper_saw_eager": "plistlib" in calls,
            "wrapper_saw_deferred": "wave" in calls,
            "plistlib_loaded": "plistlib" in sys.modules,
            "wave_deferred": "wave" not in sys.modules,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    # The wrapper installed before unwrapt stays in the chain for every
    # import unwrapt passes through, and is bypassed only for the
    # deferred one.

    assert facts["wrapper_saw_eager"] is True
    assert facts["wrapper_saw_deferred"] is False
    assert facts["plistlib_loaded"] is True
    assert facts["wave_deferred"] is True


def test_install_is_idempotent(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        again = unwrapt.install()

        import wave

        facts = {
            "first": installed,
            "second": again,
            "deferred": "wave" not in sys.modules,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": _config(tmp_path)},
    )

    assert facts["first"] is True
    assert facts["second"] is False
    assert facts["deferred"] is True


def test_reification_replaces_only_matching_entries(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        import wave

        in_list = [wave]
        alias = wave

        wave.Wave_read

        facts = {
            "name_real": type(wave) is types.ModuleType,
            "alias_real": type(alias) is types.ModuleType,
            "copy_in_container_still_proxy": type(in_list[0]).__name__,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": _config(tmp_path)},
    )

    assert facts["name_real"] is True
    assert facts["alias_real"] is True
    assert facts["copy_in_container_still_proxy"] == "LazyObjectProxy"


def test_concurrent_first_use_resolves_once(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        import threading

        import wave

        barrier = threading.Barrier(8)
        results = []
        errors = []

        def touch():
            try:
                barrier.wait()
                results.append(type(wave.Wave_read).__name__)
            except Exception as exc:
                errors.append(repr(exc))

        threads = [threading.Thread(target=touch) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        facts = {
            "errors": errors,
            "all_reader": all(name == "type" for name in results),
            "count": len(results),
            "csv_in_sys_modules": "wave" in sys.modules,
            "real_after": type(wave) is types.ModuleType,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": _config(tmp_path)},
    )

    assert facts["errors"] == []
    assert facts["all_reader"] is True
    assert facts["count"] == 8
    assert facts["csv_in_sys_modules"] is True
    assert facts["real_after"] is True


def test_failing_import_raises_at_first_use(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["no_such_module_xyz"]})

    facts = run_facts(
        SETUP
        + """
        import no_such_module_xyz

        statement_ok = True

        error = None

        try:
            no_such_module_xyz.thing
        except ImportError as exc:
            error = type(exc).__name__

        facts = {
            "statement_ok": statement_ok,
            "deferred": "no_such_module_xyz" not in sys.modules,
            "error": error,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["statement_ok"] is True
    assert facts["deferred"] is True

    # ModuleNotFoundError is an ImportError subclass; either is the
    # documented behaviour.

    assert facts["error"] in ("ImportError", "ModuleNotFoundError")


def test_debug_output_names_deferred_imports(tmp_path: Path) -> None:
    process = run_python(
        """
        import unwrapt

        unwrapt.install()

        import wave

        wave.Wave_read
        """,
        env={"UNWRAPT_CONFIG": _config(tmp_path), "UNWRAPT_DEBUG": "1"},
    )

    assert "unwrapt: deferring 'wave' in __main__" in process.stderr

    # The mode line names the mode the version runs in.

    if BELOW_315:
        assert "unwrapt: shim mode installed" in process.stderr
    else:
        assert "unwrapt: external-config-only mode installed" in process.stderr


def test_temp_module_records_its_import(tmp_path: Path) -> None:
    # A purpose-built module that records being imported, so the deferral
    # of a module no stdlib preloads can be asserted on directly.

    from support import write_module

    marker = tmp_path / "imported.txt"
    write_module(
        tmp_path,
        "mymarker",
        f"""
        from pathlib import Path

        Path({str(marker)!r}).write_text("imported")
        """,
    )

    config = json_config(tmp_path / "lazy.json", {"__main__": ["mymarker"]})

    code = """
        import json
        import os
        import pathlib

        import unwrapt

        unwrapt.install()

        import mymarker

        marker = pathlib.Path(os.environ["MARKER_PATH"])

        print(json.dumps({"marker_exists": marker.exists()}))
        """

    facts = run_facts(
        code,
        env={
            "PYTHONPATH": str(tmp_path),
            "MARKER_PATH": str(marker),
            "UNWRAPT_CONFIG": config,
        },
    )

    assert facts["marker_exists"] is False

    touched_code = code.replace(
        "import mymarker\n",
        "import mymarker\n\n        value = mymarker.__name__\n",
    )

    facts = run_facts(
        touched_code,
        env={
            "PYTHONPATH": str(tmp_path),
            "MARKER_PATH": str(marker),
            "UNWRAPT_CONFIG": config,
        },
    )

    assert facts["marker_exists"] is True


def test_isinstance_module_resolves_proxy(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        import wave

        deferred = "wave" not in sys.modules

        # isinstance consults the proxied __class__, which resolves the
        # proxy: the documented behaviour.

        is_module = isinstance(wave, types.ModuleType)

        facts = {
            "deferred": deferred,
            "is_module": is_module,
            "loaded_after_check": "wave" in sys.modules,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": _config(tmp_path)},
    )

    assert facts["deferred"] is True
    assert facts["is_module"] is True
    assert facts["loaded_after_check"] is True
