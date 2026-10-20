"""A thin wrapper around a heavy dependency: near-zero self time, and
a large cumulative time in the report."""

import difflib


def ratio(left: str, right: str) -> float:
    """Compare two strings."""

    return difflib.SequenceMatcher(None, left, right).ratio()
