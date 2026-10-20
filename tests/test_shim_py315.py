"""Tests for shim mode on Python 3.15 and later.

On 3.15 the interpreter provides PEP 810 lazy imports natively, so
unwrapt runs in external-config-only mode: the external configuration
is the only candidate source, the module's own __lazy_modules__ is
native's business, and with no configuration unwrapt installs nothing
at all. These tests are collected only on 3.15+.
"""

from pathlib import Path

from support import json_config, run_facts, run_python

SETUP = """
        import json, sys, types

        import unwrapt

        installed = unwrapt.install()
        """


def test_no_config_installs_nothing_silently() -> None:
    facts = run_facts(
        SETUP
        + """
        import wave

        facts = {
            "installed": installed,
            "is_installed": unwrapt.is_installed(),
            "loaded": "wave" in sys.modules,
        }
        print(json.dumps(facts))
        """
    )

    assert facts["installed"] is False
    assert facts["is_installed"] is False
    assert facts["loaded"] is True


def test_no_config_produces_no_output() -> None:
    process = run_python(
        """
        import unwrapt

        unwrapt.install()
        """,
    )

    assert process.stderr == ""


def test_no_config_debug_line_explains() -> None:
    process = run_python(
        """
        import unwrapt

        unwrapt.install()
        """,
        env={"UNWRAPT_DEBUG": "1"},
    )

    assert "nothing to do" in process.stderr
    assert "native lazy imports" in process.stderr


def test_external_config_only_mode(tmp_path: Path) -> None:
    # A config entry defers the import through unwrapt's proxy, while
    # the module's own __lazy_modules__ is handled natively: both come
    # out lazy, each by its own route, and native behaviour is never
    # touched.

    config = json_config(tmp_path / "lazy.json", {"__main__": ["wave"]})

    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["colorsys"]

        import colorsys
        import wave

        facts = {
            "installed": installed,
            "native_lazy_colorsys": "colorsys" not in sys.modules,
            "native_colorsys_type": type(colorsys).__name__,
            "unwrapt_lazy_wave": "wave" not in sys.modules,
            "unwrapt_wave_type": type(wave).__name__,
            "lazy_mode": sys.get_lazy_imports(),
            "filter": sys.get_lazy_imports_filter(),
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["installed"] is True
    assert facts["native_lazy_colorsys"] is True
    assert facts["native_colorsys_type"] == "module"
    assert facts["unwrapt_lazy_wave"] is True
    assert facts["unwrapt_wave_type"] == "LazyObjectProxy"
    assert facts["lazy_mode"] == "normal"
    assert facts["filter"] is None


def test_config_entry_overlapping_lazy_modules_left_to_native(
    tmp_path: Path,
) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["wave"]})

    facts = run_facts(
        SETUP
        + """
        __lazy_modules__ = ["wave"]

        import wave

        facts = {
            "deferred_natively": "wave" not in sys.modules,
            "native_type": type(wave).__name__,
        }

        wave.Wave_read

        facts["resolved"] = "wave" in sys.modules
        facts["real_after_use"] = type(wave) is types.ModuleType
        facts["identity_sane"] = wave is sys.modules["wave"]

        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["deferred_natively"] is True
    assert facts["native_type"] == "module"
    assert facts["resolved"] is True
    assert facts["real_after_use"] is True
    assert facts["identity_sane"] is True


def test_config_entry_overlapping_explicit_lazy_import(tmp_path: Path) -> None:
    # A config entry that duplicates an explicit lazy import statement
    # is left to native: the pending binding in sys.lazy_modules
    # identifies the reification call, and unwrapt hands native back
    # the real module.

    config = json_config(tmp_path / "lazy.json", {"__main__": ["colorsys"]})

    facts = run_facts(
        SETUP
        + """
        lazy import colorsys

        deferred = "colorsys" not in sys.modules

        value = colorsys.rgb_to_hls(1, 0, 0)

        facts = {
            "deferred": deferred,
            "touch_worked": value == (0.0, 0.5, 1.0),
            "real_after_use": type(colorsys) is types.ModuleType,
            "identity_sane": colorsys is sys.modules["colorsys"],
        }
        print(json.dumps(facts))
        """,
        env={"UNWRAPT_CONFIG": config},
    )

    assert facts["deferred"] is True
    assert facts["touch_worked"] is True
    assert facts["real_after_use"] is True
    assert facts["identity_sane"] is True


def test_debug_states_external_config_only_mode(tmp_path: Path) -> None:
    config = json_config(tmp_path / "lazy.json", {"__main__": ["wave"]})

    process = run_python(
        """
        import unwrapt

        unwrapt.install()
        """,
        env={"UNWRAPT_CONFIG": config, "UNWRAPT_DEBUG": "1"},
    )

    assert "external-config-only mode installed" in process.stderr


def test_never_calls_set_lazy_imports() -> None:
    facts = run_facts(
        SETUP
        + """
        import wave

        facts = {
            "mode": sys.get_lazy_imports(),
            "filter": sys.get_lazy_imports_filter(),
        }
        print(json.dumps(facts))
        """
    )

    assert facts["mode"] == "normal"
    assert facts["filter"] is None
