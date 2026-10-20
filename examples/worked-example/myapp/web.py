"""The web module: imports decimal at module level, the classic case
for a thin wrapper around a heavy dependency that the report flags
with near-zero self time and a large cumulative time."""

import decimal
import myapp.analytics


def render(row: dict[str, int]) -> str:
    """Render a row, using decimal only inside the function."""

    cents = decimal.Decimal(row["id"]) / 100

    return f"{cents:.2f}"
