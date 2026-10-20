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
        "__version__",
        "__version_info__",
        "install",
        "is_installed",
    ]

    assert callable(unwrapt.install)
    assert callable(unwrapt.is_installed)
