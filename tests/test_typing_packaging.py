"""Tests for the packaging promises: py.typed, inert import, version.

The wheel content itself is exercised by the CI build; these check the
source tree invariants that make the promises hold.
"""

import pathlib

import unwrapt


def test_py_typed_ships_with_the_package() -> None:
    package = pathlib.Path(unwrapt.__file__).parent

    assert (package / "py.typed").is_file()


def test_public_api_surface() -> None:
    assert sorted(unwrapt.__all__) == [
        "Config",
        "ConfigError",
        "Deferral",
        "Installed",
        "ProfileOptions",
        "Resolution",
        "__version__",
        "__version_info__",
        "deferred",
        "find_config",
        "install",
        "install_from_env",
        "installed",
        "is_installed",
        "load_config",
        "on_resolve",
        "stop_profile",
        "uninstall",
    ]

    # Every name in __all__ resolves, including the configuration API
    # that loads through the module __getattr__.

    for name in unwrapt.__all__:
        assert getattr(unwrapt, name) is not None

    assert callable(unwrapt.install)
    assert callable(unwrapt.is_installed)
