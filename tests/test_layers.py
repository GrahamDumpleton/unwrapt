"""Tests for the two layers, deferral and recording, and their API.

install(config, defer=..., profile=...) installs the shim, the
recorder, or both with the recorder above the shim; stop_profile()
takes out only the recorder, uninstall() both, and installed() says
which are in. Each scenario runs in its own subprocess, since the
layers replace builtins.__import__ for the whole process.

The scenarios pass an explicit Config, so they read no configuration
file and no environment. wave is deferred by the configuration and
plistlib by the module's own __lazy_modules__: below 3.15 the shim
handles both, and from 3.15 native lazy imports handle plistlib.
"""

import json
import sys
from pathlib import Path

from support import run_facts, run_python

BELOW_315 = sys.version_info < (3, 15)

SETUP = """
        import builtins, json, sys, types

        import unwrapt

        config = unwrapt.Config(
            lazy_modules={"__main__": ["wave", "difflib"]},
            profile=unwrapt.ProfileOptions(format="json"),
        )

        def layers():
            state = unwrapt.installed()

            if state is None:
                return None

            return {"defer": state.defer, "profile": state.profile}
        """


def _edges(report: dict[str, object], name: str) -> list[dict[str, object]]:
    edges = report["edges"]

    assert isinstance(edges, list)

    return [edge for edge in edges if edge["imported"] == name]


def test_defer_on_profile_off(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        installed = unwrapt.install(config, defer=True, profile=False)

        __lazy_modules__ = ["plistlib"]
        import plistlib
        import wave

        print(json.dumps({
            "installed": installed,
            "layers": layers(),
            "wave_deferred": "wave" not in sys.modules,
            "plistlib_deferred": "plistlib" not in sys.modules,
        }))
        """,
        cwd=tmp_path,
    )

    assert facts["installed"] is True
    assert facts["layers"] == {"defer": True, "profile": False}
    assert facts["wave_deferred"] is True
    assert facts["plistlib_deferred"] is True


def test_defer_on_without_entries_on_315_installs_nothing(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        installed = unwrapt.install(unwrapt.Config(), defer=True)

        print(json.dumps({"installed": installed, "layers": layers()}))
        """,
        cwd=tmp_path,
    )

    if BELOW_315:
        assert facts == {
            "installed": True,
            "layers": {"defer": True, "profile": False},
        }
    else:
        assert facts == {"installed": False, "layers": None}


def test_defer_off_profile_on(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        installed = unwrapt.install(config, defer=False, profile=True)

        __lazy_modules__ = ["plistlib"]
        import plistlib
        import wave

        state = layers()
        wrapt_loaded = "wrapt" in sys.modules
        wave_loaded = "wave" in sys.modules
        plistlib_loaded = "plistlib" in sys.modules

        report = unwrapt.stop_profile(write=False)

        print(json.dumps({
            "installed": installed,
            "layers": state,
            "wrapt_loaded": wrapt_loaded,
            "wave_loaded": wave_loaded,
            "plistlib_loaded": plistlib_loaded,
            "report": report.to_dict(),
        }))
        """,
        cwd=tmp_path,
    )

    assert facts["installed"] is True
    assert facts["layers"] == {"defer": False, "profile": True}

    # The recorder alone never loads wrapt, and defers nothing: below
    # 3.15 the module's own declaration is not applied either, while
    # from 3.15 native lazy imports still handle it.

    assert facts["wrapt_loaded"] is False
    assert facts["wave_loaded"] is True
    assert facts["plistlib_loaded"] is BELOW_315

    wave = _edges(facts["report"], "wave")

    assert wave and wave[0]["loaded"] is True
    assert wave[0]["deferred"] is False


def test_defer_on_profile_on(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        installed = unwrapt.install(config, defer=True, profile=True)

        import wave

        state = layers()
        deferred = "wave" not in sys.modules

        report = unwrapt.stop_profile(write=False)

        print(json.dumps({
            "installed": installed,
            "layers": state,
            "deferred": deferred,
            "report": report.to_dict(),
        }))
        """,
        cwd=tmp_path,
    )

    assert facts["installed"] is True
    assert facts["layers"] == {"defer": True, "profile": True}
    assert facts["deferred"] is True

    # The recorder sits above the shim and marks the edge as deferred
    # from the shim's own flag.

    wave = _edges(facts["report"], "wave")

    assert len(wave) == 1
    assert wave[0]["deferred"] is True
    assert wave[0]["loaded"] is False
    assert wave[0]["already_lazy"] is True


def test_defer_off_profile_off(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        before = builtins.__import__

        installed = unwrapt.install(config, defer=False, profile=False)

        print(json.dumps({
            "installed": installed,
            "layers": layers(),
            "unchanged": builtins.__import__ is before,
        }))
        """,
        cwd=tmp_path,
    )

    assert facts == {"installed": False, "layers": None, "unchanged": True}


def test_install_again_changes_nothing(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        first = unwrapt.install(config, defer=True)
        hook = builtins.__import__

        second = unwrapt.install(config, defer=True, profile=True)

        print(json.dumps({
            "first": first,
            "second": second,
            "same_hook": builtins.__import__ is hook,
            "layers": layers(),
        }))
        """,
        cwd=tmp_path,
    )

    assert facts == {
        "first": True,
        "second": False,
        "same_hook": True,
        "layers": {"defer": True, "profile": False},
    }


def test_install_reads_no_environment(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        installed = unwrapt.install(unwrapt.Config(lazy_modules={"x": ["y"]}))

        print(json.dumps({"installed": installed, "layers": layers()}))
        """,
        env={"UNWRAPT_PROFILE": "1", "UNWRAPT_DEFER": "0"},
        cwd=tmp_path,
    )

    assert facts == {"installed": True, "layers": {"defer": True, "profile": False}}


def test_stop_profile_leaves_deferral_in_place(tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    result = run_python(
        SETUP
        + f"""
        config = unwrapt.Config(
            lazy_modules={{"__main__": ["wave", "difflib"]}},
            profile=unwrapt.ProfileOptions(format="json", output={str(output)!r}),
        )

        unwrapt.install(config, defer=True, profile=True)

        import wave

        report = unwrapt.stop_profile(write=False)

        state = layers()
        top_is_shim = builtins.__import__.__name__ == "_lazy_aware_import"
        again = unwrapt.stop_profile()

        import difflib

        print(json.dumps({{
            "layers": state,
            "top_is_shim": top_is_shim,
            "again": again,
            "difflib_deferred": "difflib" not in sys.modules,
            "recorded_difflib": any(
                edge["imported"] == "difflib" for edge in report.edges
            ),
            "recorded_wave": any(
                edge["imported"] == "wave" for edge in report.edges
            ),
        }}))
        """,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr

    facts = json.loads(result.stdout.strip().splitlines()[-1])

    assert facts["layers"] == {"defer": True, "profile": False}
    assert facts["top_is_shim"] is True
    assert facts["again"] is None
    assert facts["difflib_deferred"] is True
    assert facts["recorded_wave"] is True
    assert facts["recorded_difflib"] is False

    # The exit handler was unregistered: no report at exit, in the file
    # or on stderr.

    assert not output.exists()
    assert "profile report" not in result.stderr


def test_stop_profile_writes_where_the_options_say(tmp_path: Path) -> None:
    output = tmp_path / "report-%p.json"

    facts = run_facts(
        SETUP
        + f"""
        config = unwrapt.Config(
            profile=unwrapt.ProfileOptions(format="json", output={str(output)!r}),
        )

        unwrapt.install(config, defer=False, profile=True)

        import wave

        report = unwrapt.stop_profile()

        print(json.dumps({{"schema": report.to_dict()["schema"]}}))
        """,
        cwd=tmp_path,
    )

    assert facts == {"schema": 2}

    written = list(tmp_path.glob("report-*.json"))

    assert len(written) == 1
    assert any(
        edge["imported"] == "wave"
        for edge in json.loads(written[0].read_text())["edges"]
    )


def test_uninstall_with_a_wrapper_installed_over_unwrapt(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        calls = []

        unwrapt.install(config, defer=True, profile=True)

        import wave

        below = builtins.__import__

        def wrapper(name, globals=None, locals=None, fromlist=(), level=0):
            calls.append(name)

            return below(name, globals, locals, fromlist, level)

        builtins.__import__ = wrapper

        removed = unwrapt.uninstall()

        state = layers()
        wrapper_kept = builtins.__import__ is wrapper

        # Both layers stay in the chain as pass-through: nothing more is
        # deferred, and the proxy handed out before still resolves.

        import difflib

        difflib_loaded = "difflib" in sys.modules
        wave_works = wave.Wave_read.__name__ == "Wave_read"

        # A second install goes in over the wrapper and the pass-through
        # layers, and defers again without recursing through them.

        reinstalled = unwrapt.install(
            unwrapt.Config(lazy_modules={"__main__": ["plistlib"]}), defer=True
        )

        import plistlib

        print(json.dumps({
            "removed": removed,
            "layers": state,
            "wrapper_kept": wrapper_kept,
            "wrapper_saw_difflib": "difflib" in calls,
            "difflib_loaded": difflib_loaded,
            "wave_works": wave_works,
            "reinstalled": reinstalled,
            "plistlib_deferred": "plistlib" not in sys.modules,
            "again": unwrapt.uninstall(),
            "none_left": unwrapt.uninstall(),
        }))
        """,
        cwd=tmp_path,
    )

    assert facts == {
        "removed": True,
        "layers": None,
        "wrapper_kept": True,
        "wrapper_saw_difflib": True,
        "difflib_loaded": True,
        "wave_works": True,
        "reinstalled": True,
        "plistlib_deferred": True,
        "again": True,
        "none_left": False,
    }


def test_uninstall_restores_the_original_import(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        original = builtins.__import__

        unwrapt.install(config, defer=True, profile=True)
        unwrapt.uninstall()

        print(json.dumps({"restored": builtins.__import__ is original}))
        """,
        cwd=tmp_path,
    )

    assert facts == {"restored": True}


def test_stop_profile_with_a_wrapper_over_the_recorder(tmp_path: Path) -> None:
    facts = run_facts(
        SETUP
        + """
        unwrapt.install(config, defer=False, profile=True)

        below = builtins.__import__

        def wrapper(name, globals=None, locals=None, fromlist=(), level=0):
            return below(name, globals, locals, fromlist, level)

        builtins.__import__ = wrapper

        report = unwrapt.stop_profile(write=False)

        import plistlib

        print(json.dumps({
            "wrapper_kept": builtins.__import__ is wrapper,
            "layers": layers(),
            "plistlib_loaded": "plistlib" in sys.modules,
            "edges": len(report.edges),
        }))
        """,
        cwd=tmp_path,
    )

    assert facts["wrapper_kept"] is True
    assert facts["layers"] is None
    assert facts["plistlib_loaded"] is True


# install_from_env: the environment's switches.


def _env_layers(tmp_path: Path, env: dict[str, str]) -> dict[str, object]:
    return run_facts(
        """
        import json, sys

        import unwrapt

        installed = unwrapt.install_from_env()

        __lazy_modules__ = ["plistlib"]
        import plistlib

        state = unwrapt.installed()

        print(json.dumps({
            "installed": installed,
            "layers": None if state is None else [state.defer, state.profile],
            "plistlib_deferred": "plistlib" not in sys.modules,
        }))
        """,
        env=env,
        cwd=tmp_path,
    )


def test_install_from_env_defers_by_default(tmp_path: Path) -> None:
    facts = _env_layers(tmp_path, {})

    # On 3.15 with no configuration there is nothing for unwrapt to do,
    # and native lazy imports handle the declaration.

    assert facts["plistlib_deferred"] is True

    if BELOW_315:
        assert facts["layers"] == [True, False]
    else:
        assert facts["layers"] is None


def test_install_from_env_profile_alone_is_eager(tmp_path: Path) -> None:
    facts = _env_layers(
        tmp_path, {"UNWRAPT_PROFILE": "1", "UNWRAPT_PROFILE_OUTPUT": "r.txt"}
    )

    assert facts["layers"] == [False, True]
    assert facts["plistlib_deferred"] is not BELOW_315


def test_install_from_env_profile_with_defer(tmp_path: Path) -> None:
    facts = _env_layers(
        tmp_path,
        {
            "UNWRAPT_PROFILE": "1",
            "UNWRAPT_DEFER": "1",
            "UNWRAPT_PROFILE_OUTPUT": "r.txt",
        },
    )

    assert facts["plistlib_deferred"] is True

    if BELOW_315:
        assert facts["layers"] == [True, True]
    else:
        assert facts["layers"] == [False, True]


def test_install_from_env_defer_off(tmp_path: Path) -> None:
    facts = _env_layers(tmp_path, {"UNWRAPT_DEFER": "0"})

    assert facts["installed"] is False
    assert facts["layers"] is None
    assert facts["plistlib_deferred"] is not BELOW_315
