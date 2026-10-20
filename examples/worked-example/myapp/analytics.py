"""The analytics module: imports xml.dom, which the entry point
imports too, so the report flags it shared."""

import xml.dom


def analyse() -> None:
    """Pretend to analyse an XML document."""

    _ = xml.dom.Node
