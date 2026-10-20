"""A module that shares an import with the entry point: the report
flags the module shared, and deferring one importer alone would only
move the cost."""

from xml.dom import Node


def node() -> object:
    """Return the shared Node type."""

    return Node
