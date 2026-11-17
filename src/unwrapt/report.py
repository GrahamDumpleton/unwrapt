"""The profile report: its data, its analysis, and its command line.

A Report is versioned data: Report.to_dict() is the JSON schema, and
load_report() reads a saved JSON report back. The analysis is a set of
functions over a Report, which the text renderer uses and a consumer
can call or skip: summary(), who_pays(), candidates(), chain() and
chains(), heavy_modules(), by_importer(), deferred_used() and
deferred_unused(), and compare_reports() for two reports.

Run as `python -m unwrapt.report REPORT [--compare REPORT]` to
re-render a saved JSON profile report as text, or to diff two of them,
with `--min-ms`, `--packages` and `--rows` overriding the display
filters saved in the report.
See the unwrapt documentation for what the report contains.
"""

from unwrapt._report import (
    SCHEMA,
    ByImporter,
    Candidate,
    Chain,
    Defer,
    DeferredUnused,
    DeferredUsed,
    EdgeRecord,
    Filters,
    HeavyModule,
    Need,
    Payment,
    Report,
    ReportDict,
    Summary,
    by_importer,
    candidates,
    chain,
    chains,
    compare_reports,
    deferred_unused,
    deferred_used,
    heavy_modules,
    load_report,
    main,
    summary,
    who_pays,
)

__all__ = [
    "SCHEMA",
    "ByImporter",
    "Candidate",
    "Chain",
    "Defer",
    "DeferredUnused",
    "DeferredUsed",
    "EdgeRecord",
    "Filters",
    "HeavyModule",
    "Need",
    "Payment",
    "Report",
    "ReportDict",
    "Summary",
    "by_importer",
    "candidates",
    "chain",
    "chains",
    "compare_reports",
    "deferred_unused",
    "deferred_used",
    "heavy_modules",
    "load_report",
    "main",
    "summary",
    "who_pays",
]

if __name__ == "__main__":
    raise SystemExit(main())
