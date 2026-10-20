"""Tests for the __lazy_modules__ emulation, below Python 3.15 only.

Below 3.15 unwrapt emulates PEP 810's __lazy_modules__: the module's
own list is a candidate source alongside the external configuration.
From 3.15 the interpreter handles __lazy_modules__ natively and
unwrapt never reads it, so these tests are skipped there (the 3.15
behaviour is covered by the py315 test files). Each scenario runs in a
subprocess, as everywhere in this suite.
"""

import sys
from pathlib import Path

import pytest
from support import json_config, run_facts

pytestmark = pytest.mark.skipif(
    sys.version_info >= (3, 15),
    reason="below 3.15 unwrapt emulates __lazy_modules__; on 3.15 it is native",
)

SETUP = """
        import json, sys, types

        import unwrapt

        installed = unwrapt.install()
        """


def test_defers_until_first_use() -> None:
    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["wave"]
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
        """
    )

    assert facts["installed"] is True
    assert facts["deferred"] is True
    assert facts["proxy_type"] == "LazyObjectProxy"
    assert facts["loaded_after_use"] is True
    assert facts["real_after_use"] is True


def test_reification_binds_real_module() -> None:
    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["wave"]
        import wave

        wave.Wave_read

        facts = {
            "is_sys_modules_csv": wave is sys.modules["wave"],
            "real": type(wave) is types.ModuleType,
        }
        print(json.dumps(facts))
        """
    )

    assert facts["is_sys_modules_csv"] is True
    assert facts["real"] is True


def test_dotted_import_binds_top_package() -> None:
    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["xml.dom"]
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
        """
    )

    assert facts["deferred"] is True
    assert facts["proxy_type"] == "LazyObjectProxy"
    assert facts["full_name_loaded"] is True
    assert facts["top_real_after_use"] is True


def test_any_container_and_exact_match() -> None:
    # The PEP 810 matching rule, verified against the 3.15
    # implementation, is an exact match on the full dotted name: a
    # listed parent does not cover a submodule import and a listed
    # submodule does not cover the parent.

    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["xml.dom", "plistlib", "wave"]
        import xml.dom
        import xml
        import plistlib
        import wave

        facts = {
            "xml_dom_deferred": "xml.dom" not in sys.modules,
            "xml_parent_eager": "xml" in sys.modules,
            "plistlib_deferred": "plistlib" not in sys.modules,
            "wave_deferred": "wave" not in sys.modules,
        }
        print(json.dumps(facts))
        """
    )

    assert facts["xml_dom_deferred"] is True
    assert facts["xml_parent_eager"] is True
    assert facts["plistlib_deferred"] is True
    assert facts["wave_deferred"] is True


def test_dotted_as_import_is_eager() -> None:
    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["xml.dom"]
        import xml.dom as dom

        facts = {
            "loaded_at_statement": "xml.dom" in sys.modules,
            "real_module": type(dom) is types.ModuleType,
        }
        print(json.dumps(facts))
        """
    )

    assert facts["loaded_at_statement"] is True
    assert facts["real_module"] is True


def test_from_import_is_eager() -> None:
    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["difflib"]
        from difflib import SequenceMatcher

        facts = {
            "loaded_at_statement": "difflib" in sys.modules,
            "attribute_works": SequenceMatcher(None, "abc", "abc").ratio() == 1.0,
        }
        print(json.dumps(facts))
        """
    )

    assert facts["loaded_at_statement"] is True
    assert facts["attribute_works"] is True


def test_already_loaded_module_returned_unchanged() -> None:
    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["os"]
        import os

        facts = {
            "real_module": type(os) is types.ModuleType,
            "is_sys_modules_os": os is sys.modules["os"],
        }
        print(json.dumps(facts))
        """
    )

    assert facts["real_module"] is True
    assert facts["is_sys_modules_os"] is True


def test_lazy_modules_assignment_after_import_has_no_effect() -> None:
    facts = run_facts(
        SETUP
        + """
        import wave

        eager = "wave" in sys.modules

        __lazy_modules__ = ["wave"]
        import wave

        facts = {
            "eager": eager,
            "still_real": type(wave) is types.ModuleType,
        }
        print(json.dumps(facts))
        """
    )

    assert facts["eager"] is True
    assert facts["still_real"] is True


def test_config_and_lazy_modules_union(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["wave"]})

    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["plistlib"]

        import plistlib
        import wave

        facts = {
            "plistlib_deferred": "plistlib" not in sys.modules,
            "wave_deferred": "wave" not in sys.modules,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["plistlib_deferred"] is True
    assert facts["wave_deferred"] is True


def test_config_only_ignores_lazy_modules(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["wave"]})

    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["plistlib"]

        import plistlib
        import wave

        facts = {
            "plistlib_eager": "plistlib" in sys.modules,
            "wave_deferred": "wave" not in sys.modules,
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config, "UNWRAPT_CONFIG_ONLY": "1"},
    )

    assert facts["plistlib_eager"] is True
    assert facts["wave_deferred"] is True


def test_reification_replaces_only_matching_entries() -> None:
    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["wave"]
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
        """
    )

    assert facts["name_real"] is True
    assert facts["alias_real"] is True
    assert facts["copy_in_container_still_proxy"] == "LazyObjectProxy"


def test_debug_output_names_deferred_imports() -> None:
    from support import run_python

    process = run_python(
        """
        import unwrapt

        unwrapt.install()

        __lazy_modules__ = ["wave"]
        import wave

        wave.Wave_read
        """,
        env={"UNWRAPT_DEBUG": "1"},
    )

    assert "unwrapt: shim mode installed" in process.stderr
    assert "unwrapt: deferring 'wave' in __main__" in process.stderr
