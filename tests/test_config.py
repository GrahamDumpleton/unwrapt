"""Tests for environment variable parsing and the external config.

In-process: reading settings has no side effects beyond warnings, so
these run directly. The shim's candidate check is exercised here too,
with the Python 3.15 branch forced through monkeypatching so the
version rules can be tested on any interpreter.
"""

import json
import sys
import warnings
from pathlib import Path

import pytest

from unwrapt._config import (
    ConfigWarning,
    Settings,
    is_candidate,
    is_native_pending,
    load_config,
    read_settings,
)


def test_read_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "UNWRAPT_DEBUG",
        "UNWRAPT_CONFIG",
        "UNWRAPT_CONFIG_ONLY",
        "UNWRAPT_PROFILE",
        "UNWRAPT_PROFILE_OUTPUT",
        "UNWRAPT_PROFILE_FORMAT",
        "UNWRAPT_PROFILE_MIN_MS",
        "UNWRAPT_PROFILE_PACKAGES",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = read_settings()

    assert settings.debug is False
    assert settings.config_only is False
    assert settings.profile is False
    assert settings.config_path is None
    assert settings.config == {}
    assert settings.profile_output is None
    assert settings.profile_format == "text"
    assert settings.profile_min_ms == 0.0
    assert settings.profile_packages is None


def test_flags_accept_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "YES", "On"):
        monkeypatch.setenv("UNWRAPT_DEBUG", value)

        assert read_settings().debug is True


def test_flags_accept_falsy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("", "0", "false", "NO", "off"):
        monkeypatch.setenv("UNWRAPT_DEBUG", value)

        assert read_settings().debug is False


def test_invalid_flag_warns_and_reads_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNWRAPT_DEBUG", "perhaps")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings = read_settings()

    assert settings.debug is False

    messages = [
        str(item.message) for item in caught if issubclass(item.category, ConfigWarning)
    ]
    assert any("UNWRAPT_DEBUG" in message for message in messages)


def test_profile_format_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNWRAPT_PROFILE_FORMAT", "JSON")

    assert read_settings().profile_format == "json"

    monkeypatch.setenv("UNWRAPT_PROFILE_FORMAT", "xml")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert read_settings().profile_format == "text"

    assert any("UNWRAPT_PROFILE_FORMAT" in str(item.message) for item in caught)


def test_profile_min_ms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNWRAPT_PROFILE_MIN_MS", "2.5")

    assert read_settings().profile_min_ms == 2.5

    monkeypatch.setenv("UNWRAPT_PROFILE_MIN_MS", "soon")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert read_settings().profile_min_ms == 0.0

    assert any("UNWRAPT_PROFILE_MIN_MS" in str(item.message) for item in caught)


def test_profile_min_ms_negative_reads_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNWRAPT_PROFILE_MIN_MS", "-1")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert read_settings().profile_min_ms == 0.0

    assert any("UNWRAPT_PROFILE_MIN_MS" in str(item.message) for item in caught)


def test_profile_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNWRAPT_PROFILE_PACKAGES", " mypkg , other ")

    assert read_settings().profile_packages == ("mypkg", "other")

    monkeypatch.setenv("UNWRAPT_PROFILE_PACKAGES", " , ")

    assert read_settings().profile_packages is None


def test_load_config_reads_mapping(tmp_path: Path) -> None:
    path = tmp_path / "lazy.json"
    path.write_text(json.dumps({"myapp.web": ["csv", "wave"]}))

    assert load_config(str(path)) == {"myapp.web": frozenset({"csv", "wave"})}


def test_load_config_missing_file_warns(tmp_path: Path) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = load_config(str(tmp_path / "nope.json"))

    assert config == {}
    assert any("does not exist" in str(item.message) for item in caught)


def test_load_config_invalid_json_warns(tmp_path: Path) -> None:
    path = tmp_path / "lazy.json"
    path.write_text("{not json")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = load_config(str(path))

    assert config == {}
    assert any("not valid JSON" in str(item.message) for item in caught)


def test_load_config_wrong_shape_warns(tmp_path: Path) -> None:
    path = tmp_path / "lazy.json"
    path.write_text(json.dumps(["csv"]))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = load_config(str(path))

    assert config == {}
    assert any("must be a JSON object" in str(item.message) for item in caught)


def test_load_config_skips_invalid_entries(tmp_path: Path) -> None:
    path = tmp_path / "lazy.json"
    path.write_text(
        json.dumps(
            {
                "myapp.web": ["csv"],
                "myapp.scalar": "csv",
                "myapp.mixed": ["csv", 5],
            }
        )
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = load_config(str(path))

    assert config == {"myapp.web": frozenset({"csv"})}
    assert any("ignored UNWRAPT_CONFIG entries" in str(item.message) for item in caught)


def _globals(
    name: str = "myapp.web",
    lazy_modules: object = None,
) -> dict[str, object]:
    namespace: dict[str, object] = {"__name__": name}

    if lazy_modules is not None:
        namespace["__lazy_modules__"] = lazy_modules

    return namespace


def test_is_candidate_from_lazy_modules_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the below-3.15 branch: on any interpreter, the emulation
    # must read the importing module's own list.

    monkeypatch.setattr("unwrapt._config.has_native_lazy_imports", lambda: False)

    settings = read_settings()

    assert is_candidate("csv", _globals(lazy_modules=["csv", "wave"]), settings)
    assert not is_candidate("json", _globals(lazy_modules=["csv"]), settings)


def test_is_candidate_from_any_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("unwrapt._config.has_native_lazy_imports", lambda: False)

    settings = read_settings()

    for lazy_modules in (
        ["csv"],
        ("csv",),
        {"csv"},
        frozenset({"csv"}),
        {"csv": None},
    ):
        assert is_candidate("csv", _globals(lazy_modules=lazy_modules), settings)


def test_is_candidate_string_is_not_a_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("unwrapt._config.has_native_lazy_imports", lambda: False)

    settings = read_settings()

    assert not is_candidate("csv", _globals(lazy_modules="csv"), settings)


def test_is_candidate_from_config() -> None:
    settings = Settings(config={"myapp.web": frozenset({"csv"})})

    assert is_candidate("csv", _globals(), settings)
    assert not is_candidate("wave", _globals(), settings)
    assert not is_candidate("csv", _globals(name="myapp.other"), settings)


def test_is_candidate_config_only_ignores_lazy_modules() -> None:
    settings = Settings(
        config_only=True,
        config={"myapp.web": frozenset({"wave"})},
    )

    namespace = _globals(lazy_modules=["csv"])

    assert not is_candidate("csv", namespace, settings)
    assert is_candidate("wave", namespace, settings)


def test_is_candidate_never_reads_lazy_modules_on_315(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the Python 3.15 branch: the interpreter handles
    # __lazy_modules__ there, so the candidate check must ignore it.

    monkeypatch.setattr("unwrapt._config.has_native_lazy_imports", lambda: True)

    settings = read_settings()
    namespace = _globals(lazy_modules=["csv"])

    assert not is_candidate("csv", namespace, settings)

    settings_with_config = Settings(config={"myapp.web": frozenset({"csv"})})

    assert is_candidate("csv", namespace, settings_with_config)


def test_is_native_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    assert is_native_pending("csv") is False

    monkeypatch.setattr(sys, "lazy_modules", {"csv"}, raising=False)

    try:
        assert is_native_pending("csv") is True
        assert is_native_pending("wave") is False
    finally:
        monkeypatch.delattr(sys, "lazy_modules", raising=False)
