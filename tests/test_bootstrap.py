"""Tests for the autowrapt bootstrap, end to end.

autowrapt is not a dependency of unwrapt: it is installed in the test
environment only, and these tests skip themselves when it is absent,
which is the arrangement the CI plain install job relies on.
"""

import sys
from pathlib import Path

import pytest
from support import run_facts, run_python


@pytest.fixture
def autowrapt() -> None:
    pytest.importorskip("autowrapt")


def test_bootstrap_defers_listed_import(autowrapt: None) -> None:
    # Zero application changes: AUTOWRAPT_BOOTSTRAP=unwrapt starts the
    # process with the hook installed, before the application's imports.
    # Below 3.15 the deferred import is an unwrapt proxy; on 3.15, where
    # the bootstrap installs nothing without a configuration, native
    # lazy imports handle the declaration instead.

    facts = run_facts(
        """
        import json, sys, types

        __lazy_modules__ = ["wave"]
        import wave

        facts = {
            "deferred": "wave" not in sys.modules,
            "proxy_type": type(wave).__name__,
        }
        print(json.dumps(facts))
        """,
        env={"AUTOWRAPT_BOOTSTRAP": "unwrapt"},
    )

    assert facts["deferred"] is True

    if sys.version_info < (3, 15):
        assert facts["proxy_type"] == "LazyObjectProxy"
    else:
        assert facts["proxy_type"] == "module"


def test_bootstrap_without_declarations_is_eager(autowrapt: None) -> None:
    facts = run_facts(
        """
        import json, sys, types

        import wave

        facts = {
            "loaded": "wave" in sys.modules,
            "real_module": type(wave) is types.ModuleType,
        }
        print(json.dumps(facts))
        """,
        env={"AUTOWRAPT_BOOTSTRAP": "unwrapt"},
    )

    assert facts["loaded"] is True
    assert facts["real_module"] is True


def test_bootstrap_with_profile_mode(autowrapt: None, tmp_path: Path) -> None:
    import json

    output = tmp_path / "report.json"

    result = run_python(
        """
        import wave
        from difflib import SequenceMatcher
        """,
        env={
            "AUTOWRAPT_BOOTSTRAP": "unwrapt",
            "UNWRAPT_PROFILE": "1",
            "UNWRAPT_PROFILE_FORMAT": "json",
            "UNWRAPT_PROFILE_OUTPUT": str(output),
        },
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr

    report = json.loads(output.read_text())

    assert any(edge["imported"] == "wave" for edge in report["edges"])
    assert any(edge["imported"] == "difflib" for edge in report["edges"])


def test_entry_point_registered(autowrapt: None) -> None:
    import importlib.metadata

    entry_points = importlib.metadata.entry_points(group="unwrapt")
    entry = next(iter(entry_points))

    assert entry.name == "os"
    assert entry.value == "unwrapt.bootstrap:bootstrap"
