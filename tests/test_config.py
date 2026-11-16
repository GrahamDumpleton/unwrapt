"""Tests for the configuration: the file, its search, the environment.

In-process where nothing global is touched: finding and loading a file
has no side effects beyond warnings, so those tests change directory
with monkeypatch and run directly. The byte check that keeps tomllib
out of a process is asserted in a subprocess, since the test process
may already have imported it. The shim's candidate check is exercised
here too, with the Python 3.15 branch forced through monkeypatching so
the version rules can be tested on any interpreter.
"""

import json
import sys
import textwrap
import warnings
from pathlib import Path

import pytest
from support import run_facts

import unwrapt
from unwrapt._config import (
    Config,
    ConfigError,
    ConfigWarning,
    ProfileOptions,
    config_from_env,
    find_config,
    is_candidate,
    is_native_pending,
    load_config,
)

_VARIABLES = (
    "UNWRAPT_DEBUG",
    "UNWRAPT_CONFIG",
    "UNWRAPT_CONFIG_ONLY",
    "UNWRAPT_PROFILE",
    "UNWRAPT_PROFILE_OUTPUT",
    "UNWRAPT_PROFILE_FORMAT",
    "UNWRAPT_PROFILE_MIN_MS",
    "UNWRAPT_PROFILE_PACKAGES",
)


@pytest.fixture
def clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An empty working directory and no UNWRAPT_* variables."""

    for name in _VARIABLES:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.chdir(tmp_path)

    return tmp_path


def _write(path: Path, source: str) -> Path:
    path.write_text(textwrap.dedent(source))

    return path


def _config_warnings(caught: list[warnings.WarningMessage]) -> list[str]:
    return [
        str(item.message) for item in caught if issubclass(item.category, ConfigWarning)
    ]


# The public names load through the package's module __getattr__.


def test_public_names_are_the_config_module_names() -> None:
    assert unwrapt.Config is Config
    assert unwrapt.ConfigError is ConfigError
    assert unwrapt.ProfileOptions is ProfileOptions
    assert unwrapt.find_config is find_config
    assert unwrapt.load_config is load_config

    with pytest.raises(AttributeError):
        getattr(unwrapt, "no_such_name")  # noqa: B009


# find_config: the precedence chain.


def test_find_config_nothing_found(clean: Path) -> None:
    assert find_config() is None


def test_find_config_prefers_the_environment(
    clean: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(clean / "unwrapt.toml", "debug = true\n")
    _write(clean / "pyproject.toml", "[tool.unwrapt]\ndebug = true\n")

    monkeypatch.setenv("UNWRAPT_CONFIG", "elsewhere.toml")

    # Returned even though it does not exist, so loading fails loudly.

    assert find_config() == "elsewhere.toml"


def test_find_config_unwrapt_toml_before_pyproject(clean: Path) -> None:
    _write(clean / "unwrapt.toml", "debug = true\n")
    _write(clean / "pyproject.toml", "[tool.unwrapt]\ndebug = true\n")

    assert find_config() == "unwrapt.toml"


def test_find_config_pyproject_with_table(clean: Path) -> None:
    _write(clean / "pyproject.toml", "[tool.unwrapt.lazy_modules]\nx = ['y']\n")

    assert find_config() == "pyproject.toml"


def test_find_config_pyproject_without_table(clean: Path) -> None:
    _write(clean / "pyproject.toml", "[project]\nname = 'x'\n")

    assert find_config() is None


def test_find_config_pyproject_header_only_in_a_comment(clean: Path) -> None:
    # The byte check matches, and the parse then says there is no table.

    _write(clean / "pyproject.toml", "# [tool.unwrapt] goes here one day\n")

    assert find_config() is None


def test_find_config_dotted_key_form_is_not_found(clean: Path) -> None:
    # The documented rule: the table form is required.

    _write(clean / "pyproject.toml", "[tool]\nunwrapt.debug = true\n")

    assert find_config() is None


def test_find_config_invalid_pyproject_raises(clean: Path) -> None:
    _write(clean / "pyproject.toml", "[tool.unwrapt\n")

    with pytest.raises(ConfigError, match="not valid TOML"):
        find_config()


def test_byte_check_keeps_tomllib_out(tmp_path: Path) -> None:
    code = """
        import json, sys

        import unwrapt

        found = unwrapt.find_config()

        print(json.dumps({"found": found, "tomllib": "tomllib" in sys.modules}))
        """

    _write(tmp_path / "pyproject.toml", "[project]\nname = 'x'\n")

    facts = run_facts(code, cwd=tmp_path)

    assert facts == {"found": None, "tomllib": False}

    _write(tmp_path / "pyproject.toml", "[tool.unwrapt]\ndebug = true\n")

    facts = run_facts(code, cwd=tmp_path)

    assert facts == {"found": "pyproject.toml", "tomllib": True}


# load_config: the file forms.


def test_load_config_defaults_when_nothing_found(clean: Path) -> None:
    config = load_config()

    assert config == Config()
    assert config.lazy_modules == {}
    assert config.config_only is False
    assert config.debug is False
    assert config.path is None
    assert config.profile.output is None
    assert config.profile.format == "text"
    assert config.profile.min_ms == 0.0
    assert config.profile.packages is None


def test_load_config_unwrapt_toml(clean: Path) -> None:
    _write(
        clean / "unwrapt.toml",
        """
        config_only = true
        debug = true

        [lazy_modules]
        "thirdparty.pkg.client" = ["numpy", "pandas"]

        [profile]
        output = "reports/unwrapt-%p.txt"
        format = "json"
        min_ms = 1
        packages = ["shop"]
        """,
    )

    config = load_config()

    assert config.path == "unwrapt.toml"
    assert config.config_only is True
    assert config.debug is True
    assert config.lazy_modules == {
        "thirdparty.pkg.client": frozenset({"numpy", "pandas"})
    }

    # A relative output is relative to the file's directory.

    assert config.profile.output == str(clean / "reports" / "unwrapt-%p.txt")
    assert config.profile.format == "json"
    assert config.profile.min_ms == 1.0
    assert config.profile.packages == ("shop",)


def test_load_config_pyproject_table(clean: Path) -> None:
    _write(
        clean / "pyproject.toml",
        """
        [project]
        name = "shop"

        [tool.unwrapt]
        debug = true

        [tool.unwrapt.lazy_modules]
        "shop.web" = ["decimal"]
        """,
    )

    config = load_config()

    assert config.path == "pyproject.toml"
    assert config.debug is True
    assert config.lazy_modules == {"shop.web": frozenset({"decimal"})}


def test_load_config_explicit_path(tmp_path: Path) -> None:
    path = _write(tmp_path / "other.toml", "[lazy_modules]\na = ['b']\n")

    assert load_config(path).lazy_modules == {"a": frozenset({"b"})}
    assert load_config(str(path)).path == str(path)


def test_load_config_absolute_output_kept(tmp_path: Path) -> None:
    output = tmp_path / "abs" / "report.json"
    path = _write(tmp_path / "unwrapt.toml", f"[profile]\noutput = {str(output)!r}\n")

    assert load_config(path).profile.output == str(output)


def test_load_config_json_form(tmp_path: Path) -> None:
    path = tmp_path / "lazy.json"
    path.write_text(json.dumps({"myapp.web": ["csv", "wave"]}))

    config = load_config(path)

    assert config.lazy_modules == {"myapp.web": frozenset({"csv", "wave"})}
    assert config.path == str(path)
    assert config.profile == ProfileOptions()


def test_load_config_json_named_by_environment(
    clean: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = clean / "lazy.json"
    path.write_text(json.dumps({"__main__": ["wave"]}))

    monkeypatch.setenv("UNWRAPT_CONFIG", str(path))

    assert load_config().lazy_modules == {"__main__": frozenset({"wave"})}


# load_config: ConfigError.


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    for name in ("nope.toml", "nope.json"):
        with pytest.raises(ConfigError, match="does not exist"):
            load_config(tmp_path / name)


def test_load_config_invalid_toml_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "unwrapt.toml", "debug = \n")

    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(path)


def test_load_config_invalid_json_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "lazy.json", "{not json")

    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(path)


def test_load_config_json_wrong_shape_raises(tmp_path: Path) -> None:
    path = tmp_path / "lazy.json"
    path.write_text(json.dumps(["csv"]))

    with pytest.raises(ConfigError, match="must be a JSON object"):
        load_config(path)

    path.write_text(json.dumps({"myapp.web": ["csv"], "myapp.mixed": ["csv", 5]}))

    with pytest.raises(ConfigError, match="'myapp.mixed' must be a list"):
        load_config(path)


def test_load_config_pyproject_without_table_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "pyproject.toml", "[project]\nname = 'x'\n")

    with pytest.raises(ConfigError, match=r"no \[tool.unwrapt\] table"):
        load_config(path)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("profile = 1\n", "profile must be a table"),
        ("debgu = true\n", "unknown key 'debgu'"),
        ("[profile]\nouptut = 'x'\n", "unknown key 'ouptut' in the profile table"),
        ("debug = 'yes'\n", "debug must be true or false"),
        ("config_only = 1\n", "config_only must be true or false"),
        ("lazy_modules = ['x']\n", "lazy_modules must map"),
        ("[lazy_modules]\na = 'numpy'\n", "'a' must be a list of module names"),
        ("[lazy_modules]\na = [1]\n", "'a' must be a list of module names"),
        ("[profile]\nformat = 'xml'\n", "format must be 'text' or 'json'"),
        ("[profile]\nmin_ms = 'soon'\n", "min_ms must be a number"),
        ("[profile]\nmin_ms = -1\n", "min_ms must not be negative"),
        ("[profile]\noutput = 5\n", "output must be a path string"),
        ("[profile]\npackages = 'shop'\n", "packages must be a list"),
    ],
)
def test_load_config_invalid_values_raise(
    tmp_path: Path, source: str, message: str
) -> None:
    path = _write(tmp_path / "unwrapt.toml", source)

    with pytest.raises(ConfigError, match=message) as info:
        load_config(path)

    # The message names the file.

    assert str(path) in str(info.value)


def test_config_built_in_code_is_normalised() -> None:
    config = Config(lazy_modules={"shop.web": ["decimal", "wave"]})

    assert config.lazy_modules == {"shop.web": frozenset({"decimal", "wave"})}

    options = ProfileOptions(packages=[], min_ms=2)

    assert options.packages is None
    assert options.min_ms == 2.0

    with pytest.raises(ConfigError):
        Config(lazy_modules={"shop.web": "decimal"})


# config_from_env: the environment overrides the file.


def test_env_defaults(clean: Path) -> None:
    assert config_from_env() == Config()


def test_env_overrides_file(clean: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(
        clean / "unwrapt.toml",
        """
        config_only = false
        debug = true

        [lazy_modules]
        a = ["b"]

        [profile]
        output = "file.txt"
        format = "text"
        min_ms = 1.0
        packages = ["shop"]
        """,
    )

    monkeypatch.setenv("UNWRAPT_CONFIG_ONLY", "1")
    monkeypatch.setenv("UNWRAPT_DEBUG", "0")
    monkeypatch.setenv("UNWRAPT_PROFILE_OUTPUT", "env.json")
    monkeypatch.setenv("UNWRAPT_PROFILE_FORMAT", "JSON")
    monkeypatch.setenv("UNWRAPT_PROFILE_MIN_MS", "2.5")
    monkeypatch.setenv("UNWRAPT_PROFILE_PACKAGES", " mypkg , other ")

    config = config_from_env()

    assert config.lazy_modules == {"a": frozenset({"b"})}
    assert config.config_only is True
    assert config.debug is False
    assert config.profile.output == "env.json"
    assert config.profile.format == "json"
    assert config.profile.min_ms == 2.5
    assert config.profile.packages == ("mypkg", "other")


def test_env_unset_or_empty_keeps_file_values(
    clean: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(
        clean / "unwrapt.toml",
        "debug = true\n[profile]\nformat = 'json'\npackages = ['shop']\n",
    )

    monkeypatch.setenv("UNWRAPT_PROFILE_FORMAT", "")
    monkeypatch.setenv("UNWRAPT_PROFILE_PACKAGES", " , ")

    config = config_from_env()

    assert config.debug is True
    assert config.profile.format == "json"
    assert config.profile.packages == ("shop",)


def test_env_flags_accept_truthy_and_falsy_values(
    clean: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for value in ("1", "true", "YES", "On"):
        monkeypatch.setenv("UNWRAPT_DEBUG", value)

        assert config_from_env().debug is True

    for value in ("", "0", "false", "NO", "off"):
        monkeypatch.setenv("UNWRAPT_DEBUG", value)

        assert config_from_env().debug is False


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("UNWRAPT_DEBUG", "perhaps"),
        ("UNWRAPT_PROFILE_FORMAT", "xml"),
        ("UNWRAPT_PROFILE_MIN_MS", "soon"),
        ("UNWRAPT_PROFILE_MIN_MS", "-1"),
    ],
)
def test_env_invalid_value_warns_and_keeps_file_value(
    clean: Path, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    _write(
        clean / "unwrapt.toml",
        "debug = true\n[profile]\nformat = 'json'\nmin_ms = 3.0\n",
    )

    monkeypatch.setenv(name, value)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = config_from_env()

    assert config.debug is True
    assert config.profile.format == "json"
    assert config.profile.min_ms == 3.0

    assert any(name in message for message in _config_warnings(caught))


def test_env_unusable_file_warns_and_continues(
    clean: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNWRAPT_CONFIG", str(clean / "nope.toml"))
    monkeypatch.setenv("UNWRAPT_DEBUG", "1")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = config_from_env()

    # The file is left out, and the environment still applies.

    assert config.lazy_modules == {}
    assert config.debug is True

    messages = _config_warnings(caught)

    assert any("does not exist" in message for message in messages)
    assert any("continuing without the configuration file" in m for m in messages)


def test_install_from_env_reads_pyproject(tmp_path: Path) -> None:
    # End to end: a [tool.unwrapt] table in the working directory is
    # found and applied with no environment variable at all.

    _write(
        tmp_path / "pyproject.toml",
        """
        [tool.unwrapt.lazy_modules]
        "__main__" = ["wave"]
        """,
    )

    facts = run_facts(
        """
        import json, sys

        import unwrapt

        installed = unwrapt.install_from_env()

        import wave

        deferred = "wave" not in sys.modules

        print(json.dumps({"installed": installed, "deferred": deferred}))
        """,
        cwd=tmp_path,
    )

    assert facts == {"installed": True, "deferred": True}


def test_profile_table_never_switches_profiling_on(tmp_path: Path) -> None:
    # A [profile] table only says how a report is written: with no
    # UNWRAPT_PROFILE, nothing is recorded and nothing is written.

    _write(tmp_path / "unwrapt.toml", "[profile]\noutput = 'report.txt'\n")

    facts = run_facts(
        """
        import json

        import unwrapt

        unwrapt.install_from_env()

        import wave

        print(json.dumps({"done": True}))
        """,
        cwd=tmp_path,
    )

    assert facts == {"done": True}
    assert not (tmp_path / "report.txt").exists()


# The candidate check.


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

    config = Config()

    assert is_candidate("csv", _globals(lazy_modules=["csv", "wave"]), config)
    assert not is_candidate("json", _globals(lazy_modules=["csv"]), config)


def test_is_candidate_from_any_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("unwrapt._config.has_native_lazy_imports", lambda: False)

    config = Config()

    for lazy_modules in (
        ["csv"],
        ("csv",),
        {"csv"},
        frozenset({"csv"}),
        {"csv": None},
    ):
        assert is_candidate("csv", _globals(lazy_modules=lazy_modules), config)


def test_is_candidate_string_is_not_a_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("unwrapt._config.has_native_lazy_imports", lambda: False)

    assert not is_candidate("csv", _globals(lazy_modules="csv"), Config())


def test_is_candidate_from_config() -> None:
    config = Config(lazy_modules={"myapp.web": ["csv"]})

    assert is_candidate("csv", _globals(), config)
    assert not is_candidate("wave", _globals(), config)
    assert not is_candidate("csv", _globals(name="myapp.other"), config)


def test_is_candidate_config_only_ignores_lazy_modules() -> None:
    config = Config(config_only=True, lazy_modules={"myapp.web": ["wave"]})

    namespace = _globals(lazy_modules=["csv"])

    assert not is_candidate("csv", namespace, config)
    assert is_candidate("wave", namespace, config)


def test_is_candidate_never_reads_lazy_modules_on_315(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the Python 3.15 branch: the interpreter handles
    # __lazy_modules__ there, so the candidate check must ignore it.

    monkeypatch.setattr("unwrapt._config.has_native_lazy_imports", lambda: True)

    namespace = _globals(lazy_modules=["csv"])

    assert not is_candidate("csv", namespace, Config())

    with_entries = Config(lazy_modules={"myapp.web": ["csv"]})

    assert is_candidate("csv", namespace, with_entries)


def test_is_native_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    assert is_native_pending("csv") is False

    monkeypatch.setattr(sys, "lazy_modules", {"csv"}, raising=False)

    try:
        assert is_native_pending("csv") is True
        assert is_native_pending("wave") is False
    finally:
        monkeypatch.delattr(sys, "lazy_modules", raising=False)
