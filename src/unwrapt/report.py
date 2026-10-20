"""Render or compare profile reports.

Run as `python -m unwrapt.report REPORT [--compare REPORT]` to
re-render a saved JSON profile report as text, or to diff two of them.
See the unwrapt documentation for what the report contains.
"""

from unwrapt._report import main

if __name__ == "__main__":
    raise SystemExit(main())
