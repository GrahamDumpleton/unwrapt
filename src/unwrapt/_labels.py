"""Labels scoped to the code being loaded, for the profile report.

A caller brackets work with scope() or push_scope() and pop_scope(),
and each edge the recorder records stores the index of the label set
in force, so the cost per edge is one integer. The sets themselves
live once, in a table the report carries.

The scopes are process wide, not per thread: a host labels the entry
point it is loading, and whatever thread an import happens in during
that, it is part of the load. Nested scopes merge, the inner value
winning for a key both set.

This module imports nothing beyond the standard library's _thread, so
scoping works, and costs next to nothing, before anything is
installed.
"""

import _thread

# The table of label sets, indexed by the edges. Index 0 is the empty
# set, in force outside any scope. _index maps a set's sorted items to
# its index, so each distinct set is stored once.

_lock = _thread.allocate_lock()
_sets: list[dict[str, str]] = [{}]
_index: dict[tuple[tuple[str, str], ...], int] = {(): 0}

# The index of the label set in force, read by the recorder for every
# edge, and the stack of the indexes the pushes replaced.

current = 0
_stack: list[int] = []


class ScopeToken:
    """What push_scope() returns, for pop_scope() to check and undo."""

    __slots__ = ("depth", "previous")

    def __init__(self, depth: int, previous: int) -> None:
        self.depth = depth
        self.previous = previous


def push(labels: dict[str, str]) -> ScopeToken:
    """Bring labels into force over the current ones, until popped."""

    global current

    for name, value in labels.items():
        if not isinstance(value, str):
            raise TypeError(f"label {name!r} must be a string, not {value!r}")

    with _lock:
        merged = {**_sets[current], **labels}
        key = tuple(sorted(merged.items()))
        index = _index.get(key)

        if index is None:
            index = len(_sets)
            _sets.append(merged)
            _index[key] = index

        token = ScopeToken(len(_stack), current)
        _stack.append(current)
        current = index

    return token


def pop(token: ScopeToken) -> None:
    """Undo the push that returned token, which must be the latest."""

    global current

    with _lock:
        if token.depth != len(_stack) - 1:
            raise ValueError("label scopes must be popped in the reverse order pushed")

        _stack.pop()
        current = token.previous


def label_sets() -> list[dict[str, str]]:
    """A copy of the table of label sets, by index."""

    with _lock:
        return [dict(item) for item in _sets]


class Scope:
    """The context manager scope() returns: push on entry, pop on exit."""

    __slots__ = ("labels", "token")

    def __init__(self, labels: dict[str, str]) -> None:
        self.labels = labels
        self.token: ScopeToken | None = None

    def __enter__(self) -> "Scope":
        self.token = push(self.labels)

        return self

    def __exit__(self, *exc_info: object) -> None:
        if self.token is not None:
            pop(self.token)
            self.token = None
