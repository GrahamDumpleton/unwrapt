"""Run the sample application: python -m myapp.

The entry point imports eagerly, the way real applications do: the
profile report shows what that costs, and the strategy guide walks
what to do about it.
"""

import sqlite3
import xml.dom

import myapp.client
import myapp.web


def main() -> None:
    """Touch the imports, the way a real workload would."""

    connection = sqlite3.connect(":memory:")
    connection.close()

    _ = xml.dom.Node

    myapp.client.match("hello", "hallo")
    myapp.web.render({"id": 1})


if __name__ == "__main__":
    main()
