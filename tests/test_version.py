"""Tests for the version definition.

The version is defined once, in unwrapt/__init__.py, as a tuple plus a
formatter; pyproject.toml reads it dynamically, and nothing else may
hard-code it, these tests included: every expectation is derived from
the package, so bumping the version touches no test. What is pinned
here is the shape: the string must be exactly what the formatter makes
of the tuple, and a valid PEP 440 version.
"""

import importlib.metadata
import re

import unwrapt


def test_version_string_comes_from_version_info() -> None:
    assert unwrapt.__version__ == unwrapt._format_version(unwrapt.__version_info__)
    assert _PEP440.match(unwrapt.__version__), unwrapt.__version__


def test_format_version_three_parts() -> None:
    assert unwrapt._format_version(("1", "0", "0")) == "1.0.0"


def test_format_version_prerelease_suffix() -> None:
    assert unwrapt._format_version(("1", "0", "0", "b1")) == "1.0.0b1"
    assert unwrapt._format_version(("1", "0", "0", "rc1")) == "1.0.0rc1"
    assert unwrapt._format_version(("1", "0", "0", "a22")) == "1.0.0a22"


def test_format_version_dot_joined_suffix() -> None:
    assert unwrapt._format_version(("1", "0", "0", "dev3")) == "1.0.0.dev3"
    assert unwrapt._format_version(("1", "0", "0", "post1")) == "1.0.0.post1"


# A pre-release of the standard pattern, from PEP 440's grammar: enough
# to confirm the shapes the formatter produces are real versions
# without depending on the packaging library at test time.

_PEP440 = re.compile(
    r"^([1-9][0-9]*|0)(\.([1-9][0-9]*|0))*"
    r"((a|b|rc)[1-9][0-9]*|\.(dev|post)[1-9][0-9]*)?$"
)


def test_versions_are_valid_pep_440() -> None:
    for parts in (
        unwrapt.__version_info__,
        ("1", "0", "0"),
        ("1", "0", "0", "b1"),
        ("1", "0", "0", "rc1"),
        ("1", "0", "0", "a22"),
        ("1", "0", "0", "dev3"),
        ("1", "0", "0", "post1"),
        ("2", "4", "1"),
    ):
        assert _PEP440.match(unwrapt._format_version(parts)), parts


def test_version_matches_installed_metadata() -> None:
    # After a version bump an editable install keeps its old dist-info
    # until it is reinstalled, so a failure here means the environment
    # is stale, not that the version is wrong.

    assert importlib.metadata.version("unwrapt") == unwrapt.__version__, (
        "installed metadata is stale; run: uv sync --reinstall-package unwrapt"
    )


def test_pyproject_reads_version_dynamically() -> None:
    import pathlib

    pyproject = pathlib.Path(__file__).parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    assert 'dynamic = ["version"]' in text
    assert 'version = {attr = "unwrapt.__version__"}' in text

    # No second, static version anywhere: the only version line is
    # the dynamic attr directive.

    assert not re.search(r"^version\s*=\s*\"", text, re.MULTILINE)
