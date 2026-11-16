"""Tests for the label scopes the recorder stamps on each edge.

In-process: the scopes are plain process state that nothing installs,
and every test leaves them as it found them. The recorder side, edges
carrying the labels in force, is covered in test_profile.py.
"""

import pytest

import unwrapt
from unwrapt import _labels


def _current() -> dict[str, str]:
    return _labels.label_sets()[_labels.current]


def test_scope_merges_and_restores() -> None:
    before = _current()

    with unwrapt.scope(entrypoint="hooks", app="shop"):
        assert _current() == {**before, "entrypoint": "hooks", "app": "shop"}

        with unwrapt.scope(entrypoint="mount:api"):
            assert _current() == {**before, "entrypoint": "mount:api", "app": "shop"}

        assert _current() == {**before, "entrypoint": "hooks", "app": "shop"}

    assert _current() == before


def test_scope_restores_on_exception() -> None:
    before = _labels.current

    with pytest.raises(RuntimeError), unwrapt.scope(entrypoint="hooks"):
        raise RuntimeError("load failed")

    assert _labels.current == before


def test_each_distinct_set_is_stored_once() -> None:
    with unwrapt.scope(entrypoint="hooks"):
        first = _labels.current

    with unwrapt.scope(entrypoint="hooks"):
        second = _labels.current

    assert first == second
    assert _labels.label_sets()[first] == {"entrypoint": "hooks"}


def test_push_and_pop_pair() -> None:
    before = _labels.current

    outer = unwrapt.push_scope(entrypoint="hooks")
    inner = unwrapt.push_scope(role="inner")

    # Scopes end in reverse order: the outer token is not the latest.

    with pytest.raises(ValueError, match="reverse order"):
        unwrapt.pop_scope(outer)

    unwrapt.pop_scope(inner)
    unwrapt.pop_scope(outer)

    assert _labels.current == before

    with pytest.raises(ValueError, match="push_scope"):
        unwrapt.pop_scope(object())


def test_label_values_must_be_strings() -> None:
    before = _labels.current

    with pytest.raises(TypeError, match="must be a string"):
        unwrapt.push_scope(release=3)  # type: ignore[arg-type]

    assert _labels.current == before
