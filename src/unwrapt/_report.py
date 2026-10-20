"""Aggregation of recorded edges into the profile report.

Pure computation and rendering: nothing here reads the environment,
installs anything or imports anything at call time. The report is a
typed structure (a TypedDict, so the JSON schema is checked and
self-documenting) and both renderers are driven by it alone, which is
what lets a saved JSON report be re-rendered as text, and two reports
compared, without re-running the application.

Cost is attributed to the first importer of a module only: later
importers are cache hits and pay nothing, so deferring the first
importer's import moves the cost to the next eager importer unless
every eager importer is deferred. Edge cumulative times nest (A
imports B imports C means cum(A) already contains cum(B) and cum(C)),
so no figure in this module ever sums cumulative times across edges
that are ancestors or descendants of each other.
"""

import argparse
import json
import linecache
import platform
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

from unwrapt import __version__
from unwrapt._config import Settings

# How many heavy modules get an import chain in the report.
_CHAIN_LIMIT = 8

# `import a.b as c` cannot be deferred by the shim on older Pythons:
# the IMPORT_FROM that follows the IMPORT_NAME fetches the attribute
# immediately and resolves the proxy. `import a.b`, which binds the top
# package, can. The bytecode of both is the same IMPORT_NAME call, so
# the report reads the source line to tell them apart.

_DOTTED_AS = re.compile(r"^\s*(?:lazy\s+)?import\s+([\w.]+)\s+as\s+\w+\s*(?:#.*)?$")

_ESTIMATE_NOTE = "conservative; edge times nest and are not additive"


class Deferrability(TypedDict):
    """Whether each route can defer the import: native is Python 3.15+."""

    native: bool
    unwrapt: bool


class EdgeRecord(TypedDict):
    """One import edge, in the JSON report."""

    id: int
    parent_id: int | None
    imported: str
    importer: str | None
    line: int | None
    kind: str
    level: str
    loaded: bool
    cum_ms: float
    self_ms: float
    deferrable: Deferrability
    unwrapt_limit: str | None
    already_lazy: bool
    native_lazy: bool
    other_eager_importers: list[str]


class HeavyModule(TypedDict):
    """An imported module and the self time it cost."""

    module: str
    self_ms: float


class Chain(TypedDict):
    """The path of import calls that loaded a heavy module."""

    module: str
    self_ms: float
    links: list[int]
    best_cut: int | None


class ByImporter(TypedDict):
    """An importing module and the cumulative time of its direct loads."""

    importer: str
    cum_ms: float


class ReportFilters(TypedDict):
    """The display filters the report was built with."""

    min_ms: float
    packages: list[str] | None


class Summary(TypedDict):
    """The summary header figures."""

    modules_loaded: int
    edge_count: int
    best_cut: int | None
    estimated_saving_ms: float
    estimate_note: str
    filters: ReportFilters


class Report(TypedDict):
    """The whole profile report, in the JSON schema."""

    schema: int
    unwrapt: str
    python: str
    total_import_ms: float
    summary: Summary
    edges: list[EdgeRecord]
    heavy_modules: list[HeavyModule]
    chains: list[Chain]
    by_importer: list[ByImporter]


@dataclass(frozen=True)
class Edge:
    """One recorded import call.

    kind is "import" or "from" depending on whether the call had a
    fromlist; level_name is "module", "function" or "class" for where
    the statement sits. already_lazy marks an import that is already
    declared deferred, by __lazy_modules__, by the external
    configuration, or natively on Python 3.15; native_lazy is the
    Python 3.15 case, an import recorded at native reification rather
    than at its statement. file and line locate the statement for the
    dotted-as check and are not part of the JSON report.
    """

    id: int
    parent_id: int | None
    importer: str | None
    imported: str
    kind: Literal["import", "from"]
    level_name: Literal["module", "function", "class"]
    line: int | None
    file: str | None
    loaded: bool
    cum_ms: float
    self_ms: float
    native_lazy: bool
    already_lazy: bool


@dataclass(frozen=True)
class _Classified:
    """An edge with its route columns computed."""

    edge: Edge
    native: bool
    unwrapt: bool
    limit: str | None

    @property
    def both_routes(self) -> bool:
        return self.native and self.unwrapt


def top_level(name: str) -> str:
    """The top-level package of a module name, which is what `import
    a.b` binds and what a plain import loads first."""

    return name.partition(".")[0]


def build_report(edges: Sequence[Edge], settings: Settings) -> Report:
    """Aggregate recorded edges into the report structure."""

    classified = [_classify(edge) for edge in edges]
    by_id = {item.edge.id: item for item in classified}
    children = _children_map(edges)

    heavy = _heavy_modules(classified)
    by_importer = _by_importer(classified)
    total = sum(item.edge.cum_ms for item in classified if item.edge.parent_id is None)

    kept = _kept_edges(classified, children)
    eager = _eager_loaders(classified, children, kept)

    estimated_saving = _estimated_saving(by_id, children, kept, eager)
    chains = _chains(by_id, children, kept, eager, heavy)
    best_cut = _best_cut(chains, by_id)

    edges_out = [
        _edge_record(item, _other_eager_importers(item, classified))
        for item in classified
    ]

    return Report(
        schema=1,
        unwrapt=__version__,
        python=platform.python_version(),
        total_import_ms=total,
        summary=Summary(
            modules_loaded=len(heavy),
            edge_count=len(edges),
            best_cut=best_cut,
            estimated_saving_ms=estimated_saving,
            estimate_note=_ESTIMATE_NOTE,
            filters=ReportFilters(
                min_ms=settings.profile_min_ms,
                packages=list(settings.profile_packages)
                if settings.profile_packages is not None
                else None,
            ),
        ),
        edges=edges_out,
        heavy_modules=heavy,
        chains=chains,
        by_importer=by_importer,
    )


def render_text(report: Report) -> str:
    """Render the report as the text report: a summary header, then
    candidates, heavy modules, by importer, and import chains."""

    edges = report["edges"]
    summary = report["summary"]
    lines: list[str] = []

    # Summary header.

    lines.append(f"unwrapt {report['unwrapt']} profile report")
    lines.append("")

    lines.append(
        f"Summary: {_ms(report['total_import_ms'])} ms total import time,"
        f" {summary['modules_loaded']} modules loaded,"
        f" {summary['edge_count']} edges"
    )
    lines.append(
        f"Estimated saving if every deferrable edge were deferred:"
        f" {_ms(summary['estimated_saving_ms'])} ms"
        f" ({summary['estimate_note']})"
    )

    best = _edge(report, summary["best_cut"])

    if best is not None:
        lines.append(
            f"Best single cut: {_who(best)} -> {best['imported']}"
            f" ({_ms(best['cum_ms'])} ms cumulative)"
        )

    # Native lazy imports (Python 3.15) are recorded at first use, and
    # the reader needs to know which edges those are and what that
    # means for the figures.

    reified = sum(1 for edge in edges if edge["native_lazy"])

    if reified:
        lines.append("")
        lines.append(
            f"Warning: {reified} native lazy imports on Python 3.15"
            " were recorded at first use rather than at their import"
            " statements. Their cost is real, and attributed to the"
            " importing module, but the line is the site of first use"
            " and the timing is the load cost wherever it landed. To"
            " measure an eager run, unset native lazy imports"
            " (PYTHON_LAZY_IMPORTS=normal) and profile again."
        )

    # Candidates: loaded module-level imports, ranked by cumulative
    # time, never dropped because a route cannot defer them.

    filters = summary["filters"]
    min_ms = filters["min_ms"]
    packages = filters["packages"]

    lines.append("")
    lines.append("Candidates: module-level imports, ranked by cumulative time")

    if min_ms > 0.0:
        lines.append(f"(rows under {_ms(min_ms)} ms hidden by UNWRAPT_PROFILE_MIN_MS)")

    if packages is not None:
        names = ", ".join(packages)
        lines.append(f"(rows outside {names} hidden by UNWRAPT_PROFILE_PACKAGES)")

    rows = [
        edge
        for edge in edges
        if edge["level"] == "module"
        and edge["loaded"]
        and edge["cum_ms"] >= min_ms
        and _under_packages(edge["importer"], packages)
    ]
    rows.sort(key=lambda edge: (-edge["cum_ms"], edge["id"]))

    table = [
        ["cum ms", "self ms", "imported", "imported by", "3.15", "unwrapt", "notes"]
    ]

    for edge in rows:
        table.append(
            [
                _ms(edge["cum_ms"]),
                _ms(edge["self_ms"]),
                edge["imported"],
                _who(edge),
                _native_cell(edge),
                _unwrapt_cell(edge),
                _notes(edge),
            ]
        )

    # Numbers and route columns right aligned, names and notes left.

    lines.extend(_table(table, [False, False, True, True, False, False, True]))

    lines.append("")
    lines.append("  (1) unwrapt hands back a lazy proxy, and the attribute")
    lines.append("      fetch in a `from x import y` or `import a.b as c`")
    lines.append("      resolves it immediately. The saving is real on Python")
    lines.append("      3.15+, or after a rewrite to `import x` and attribute")
    lines.append("      access on older Pythons.")
    lines.append("  (2) function level imports are already deferred until the")
    lines.append("      function runs, so there is nothing to decide.")

    # Heavy modules.

    lines.append("")
    lines.append("Heavy modules: by self time")

    for heavy_module in report["heavy_modules"]:
        lines.append(f"  {_ms(heavy_module['self_ms'])} ms  {heavy_module['module']}")

    # By importer.

    lines.append("")
    lines.append("By importer: direct module-level loads, the files to edit first")

    for entry in report["by_importer"]:
        lines.append(f"  {_ms(entry['cum_ms'])} ms  {entry['importer']}")

    # Import chains.

    lines.append("")
    lines.append("Import chains: why each heavy module is loaded")

    for chain in report["chains"]:
        lines.append("")
        lines.append(f"  {chain['module']}  {_ms(chain['self_ms'])} ms self")

        for edge_id in chain["links"]:
            link = _edge(report, edge_id)

            if link is None:
                continue

            parts = [
                f"    {_who(link)} -> {link['imported']}",
                f"cum {_ms(link['cum_ms'])} ms",
                f"3.15 {_native_cell(link)}",
                f"unwrapt {_unwrapt_cell(link)}",
            ]

            if link["id"] == chain["best_cut"]:
                parts.append("<- best cut")

            notes = _notes(link)

            if notes:
                parts.append(notes)

            lines.append("  ".join(parts))

    # Limits.

    lines.append("")
    lines.append("Limits of this report:")
    lines.append("")

    for limit in _LIMITS:
        lines.append(f"- {limit}")

    return "\n".join(lines)


def render_json(report: Report) -> str:
    """Render the report as the JSON form, indented for reading."""

    return json.dumps(report, indent=2)


def compare_reports(before: Report, after: Report) -> str:
    """Compare two JSON reports: totals, per-module self time changes,
    and modules newly loaded or no longer loaded."""

    lines: list[str] = []

    old_total = before["total_import_ms"]
    new_total = after["total_import_ms"]

    change = new_total - old_total
    percent = (change / old_total * 100.0) if old_total else 0.0

    lines.append(
        f"Total import time: {_ms(old_total)} ms -> {_ms(new_total)} ms"
        f" ({_ms(change)} ms, {percent:+.1f}%)"
    )

    old_modules = _loaded_modules(before)
    new_modules = _loaded_modules(after)

    lines.append(f"Modules loaded: {len(old_modules)} -> {len(new_modules)}")

    newly = sorted(new_modules - old_modules)
    gone = sorted(old_modules - new_modules)

    if newly:
        lines.append(f"Newly loaded: {', '.join(newly)}")

    if gone:
        lines.append(f"No longer loaded: {', '.join(gone)}")

    old_self = {entry["module"]: entry["self_ms"] for entry in before["heavy_modules"]}
    new_self = {entry["module"]: entry["self_ms"] for entry in after["heavy_modules"]}

    changes = sorted(
        (
            (module, old_self.get(module, 0.0), new_self.get(module, 0.0))
            for module in old_self.keys() | new_self.keys()
        ),
        key=lambda item: -abs(item[2] - item[1]),
    )

    if changes:
        lines.append("Largest self-time changes:")

        for module, old_ms, new_ms in changes[:10]:
            lines.append(f"  {module}: {_ms(old_ms)} ms -> {_ms(new_ms)} ms")

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """The python -m unwrapt.report command line entry point.

    Re-renders a saved JSON report as text, and with --compare, diffs
    two reports: total import time, per-module self time changes, and
    modules newly loaded or no longer loaded. This supports the verify
    and guard steps of the strategy guide without re-running the
    application.
    """

    parser = argparse.ArgumentParser(
        prog="python -m unwrapt.report",
        description="Render a saved unwrapt profile report, or compare two.",
    )
    parser.add_argument("report", help="path to a JSON profile report")
    parser.add_argument(
        "--compare",
        metavar="REPORT",
        help="a second JSON report to compare against the first",
    )

    args = parser.parse_args(argv)

    try:
        before = _load_report(args.report)
        after = _load_report(args.compare) if args.compare else None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unwrapt: {exc}", file=sys.stderr)

        return 1

    print(render_text(before))

    if after is not None:
        print("")
        print(compare_reports(before, after))

    return 0


def _classify(edge: Edge) -> _Classified:
    """Compute the route columns for one edge.

    A limit of the shim is not a property of the code: on Python 3.15
    a `from x import y` is deferrable natively. The columns therefore
    report each route separately, and no row is ever dropped because a
    route cannot handle it.
    """

    if edge.level_name == "function":
        return _Classified(edge, False, False, "function-level")

    if edge.level_name == "class":
        return _Classified(edge, False, False, "class-level")

    if edge.kind == "from":
        return _Classified(edge, True, False, "from-import")

    if _is_dotted_as(edge):
        return _Classified(edge, True, False, "dotted-as")

    return _Classified(edge, True, True, None)


def _is_dotted_as(edge: Edge) -> bool:
    """Whether the statement is `import a.b as c`, reading its source line.

    `import a.b as c` compiles to IMPORT_NAME a.b followed by
    IMPORT_FROM b, so the proxy is resolved immediately and the import
    stays eager under the shim, while `import a.b`, which binds the top
    package, defers fine. The bytecode of the two is identical from the
    hook's side, so the source line is read to tell them apart. When
    the line cannot be read the edge is treated as deferrable, and the
    dotted names are left for the reader to check.
    """

    if edge.file is None or edge.line is None:
        return False

    source = linecache.getline(edge.file, edge.line)

    match = _DOTTED_AS.match(source)

    if match is None:
        return False

    return "." in match.group(1)


def _children_map(edges: Sequence[Edge]) -> dict[int, list[int]]:
    """Map each edge id to the ids of its direct children."""

    children: dict[int, list[int]] = {}

    for edge in edges:
        if edge.parent_id is not None:
            children.setdefault(edge.parent_id, []).append(edge.id)

    return children


def _descendants(children: dict[int, list[int]], root: int) -> set[int]:
    """The ids of every edge nested below root, excluding root itself."""

    seen: set[int] = set()
    pending = list(children.get(root, ()))

    while pending:
        edge_id = pending.pop()

        if edge_id in seen:
            continue

        seen.add(edge_id)
        pending.extend(children.get(edge_id, ()))

    return seen


def _heavy_modules(classified: Sequence[_Classified]) -> list[HeavyModule]:
    """Self time per imported top-level package, heaviest first.

    Only loaded edges carry cost; self time separates a module's own
    import work from the modules it pulls in, so a thin wrapper that
    drags in a heavy dependency shows near-zero self time while the
    dependency shows the cost.
    """

    heavy: dict[str, float] = {}

    for item in classified:
        edge = item.edge

        if edge.loaded:
            module = top_level(edge.imported)
            heavy[module] = heavy.get(module, 0.0) + edge.self_ms

    return [
        HeavyModule(module=module, self_ms=self_ms)
        for module, self_ms in sorted(heavy.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _by_importer(classified: Sequence[_Classified]) -> list[ByImporter]:
    """Cumulative time of each importer's direct module-level loads.

    These are the files to edit first: the sum counts only edges whose
    statement sits in the module itself, never the imports made by the
    modules it goes on to load.
    """

    by: dict[str, float] = {}

    for item in classified:
        edge = item.edge

        if edge.loaded and edge.level_name == "module" and edge.importer is not None:
            by[edge.importer] = by.get(edge.importer, 0.0) + edge.cum_ms

    return [
        ByImporter(importer=importer, cum_ms=cum_ms)
        for importer, cum_ms in sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _kept_edges(
    classified: Sequence[_Classified], children: dict[int, list[int]]
) -> list[_Classified]:
    """The deferral plan behind the estimated saving.

    Every loaded module-level import that both routes can defer and
    that is not already lazy is a planned deferral, except that an
    edge nested below another planned deferral is not kept: deferring
    the outer one already removes it, and adding its time would double
    count.
    """

    candidates = [
        item
        for item in classified
        if item.both_routes
        and item.edge.loaded
        and item.edge.level_name == "module"
        and not item.edge.already_lazy
    ]

    inside: set[int] = set()

    for item in candidates:
        inside |= _descendants(children, item.edge.id)

    return [item for item in candidates if item.edge.id not in inside]


def _eager_loaders(
    classified: Sequence[_Classified],
    children: dict[int, list[int]],
    kept: Sequence[_Classified],
) -> dict[str, bool]:
    """The modules that eager importers would load anyway after the plan.

    An eager importer is a module-level import that is not already
    lazy and that neither route can defer: a `from x import y`, an
    `import a.b as c`, or an import in a class body. What both routes
    can defer is in the plan (or beneath it), and imports inside the
    plan's subtrees never run once it is deferred, so only the rest can
    still load a module. The result maps each such module's top-level
    package to True.
    """

    kept_ids = {item.edge.id for item in kept}
    inside_kept: set[int] = set()

    for item in kept:
        inside_kept |= _descendants(children, item.edge.id)

    eager: dict[str, bool] = {}

    for item in classified:
        edge = item.edge

        if (
            edge.id not in inside_kept
            and edge.id not in kept_ids
            and edge.level_name == "module"
            and not edge.already_lazy
            and not item.both_routes
        ):
            eager[top_level(edge.imported)] = True

    return eager


def _estimated_saving(
    by_id: dict[int, _Classified],
    children: dict[int, list[int]],
    kept: Sequence[_Classified],
    eager: dict[str, bool],
) -> float:
    """The conservative estimated saving of the deferral plan.

    The saving is the sum of the kept edges' cumulative times, minus
    the cost of any module in their subtrees that an eager importer
    would load anyway: that cost moves to the next eager importer, it
    does not disappear. A module loaded more than once inside the plan
    is counted once, at its most expensive load. The figure is an
    estimate, and labelled as one.
    """

    if not kept:
        return 0.0

    inside_kept: set[int] = set()

    for item in kept:
        inside_kept |= _descendants(children, item.edge.id)

    moved: dict[str, float] = {}

    for edge_id in inside_kept:
        edge = by_id[edge_id].edge
        module = top_level(edge.imported)

        if edge.loaded and eager.get(module):
            moved[module] = max(moved.get(module, 0.0), edge.cum_ms)

    saving = sum(item.edge.cum_ms for item in kept) - sum(moved.values())

    # Timing noise aside, a nest cannot save more than it costs.

    return max(saving, 0.0)


def _chains(
    by_id: dict[int, _Classified],
    children: dict[int, list[int]],
    kept: Sequence[_Classified],
    eager: dict[str, bool],
    heavy: Sequence[HeavyModule],
) -> list[Chain]:
    """For each of the heaviest modules, the chain of imports that
    loaded it, outermost first, with the best cut marked.

    A chain is the list of places the load could be cut. The best cut
    is the outermost link that both routes can defer, that is not
    already lazy, and whose deferral is not undone by an eager
    importer of a module in its subtree. Deferring an outer link
    removes the whole subtree beneath it, so the outermost safe link
    saves the most.
    """

    kept_ids = {item.edge.id for item in kept}

    chains: list[Chain] = []

    for heavy_module in heavy[:_CHAIN_LIMIT]:
        module = heavy_module["module"]
        loading = None

        for item in by_id.values():
            if item.edge.loaded and top_level(item.edge.imported) == module:
                if loading is None or item.edge.id < loading.edge.id:
                    loading = item

        if loading is None:
            continue

        # Walk parents to the outermost import, then emit root first.

        links: list[int] = []
        current: _Classified | None = loading

        while current is not None:
            links.append(current.edge.id)
            parent_id = current.edge.parent_id
            current = by_id.get(parent_id) if parent_id is not None else None

        links.reverse()

        best_cut = _chain_best_cut(links, by_id, children, kept_ids, eager)

        chains.append(
            Chain(
                module=module,
                self_ms=heavy_module["self_ms"],
                links=links,
                best_cut=best_cut,
            )
        )

    return chains


def _chain_best_cut(
    links: Sequence[int],
    by_id: dict[int, _Classified],
    children: dict[int, list[int]],
    kept_ids: set[int],
    eager: dict[str, bool],
) -> int | None:
    """The outermost safe link of a chain, scanning from the root.

    A link is safe when no module loaded in its subtree has an eager
    importer outside the deferral plan: otherwise deferring the link
    only moves that module's cost. The first safe link from the root is
    the best cut, because it removes the most.
    """

    for link_id in links:
        if link_id not in kept_ids:
            continue

        subtree = _descendants(children, link_id)

        undone = any(
            eager.get(top_level(by_id[desc].edge.imported))
            for desc in subtree
            if by_id[desc].edge.loaded
        )

        if not undone:
            return link_id

    return None


def _best_cut(chains: Sequence[Chain], by_id: dict[int, _Classified]) -> int | None:
    """The single best cut overall: the largest best cut across chains."""

    cuts = [
        (by_id[chain["best_cut"]].edge.cum_ms, chain["best_cut"])
        for chain in chains
        if chain["best_cut"] is not None
    ]

    if not cuts:
        return None

    return max(cuts)[1]


def _other_eager_importers(
    item: _Classified, classified: Sequence[_Classified]
) -> list[str]:
    """The other modules that also import this edge's module and are
    not already lazy, loaded or cache hit. Their existence is what the
    shared note reports: a shared module only stays unloaded if every
    eager importer of it is deferred.

    The same module means the same imported name, so `import xml.dom`
    and `from xml.dom import Node` count as importers of the same
    module while `import xml` alone does not: it loads the xml package
    but not xml.dom. The moved-cost correction inside the estimated
    saving is coarser than this and groups by top-level package, see
    _eager_loaders; the note lists what the reader can act on.
    """

    edge = item.edge
    others: set[str] = set()

    for other in classified:
        candidate = other.edge

        if (
            candidate.importer is not None
            and candidate.importer != edge.importer
            and candidate.level_name == "module"
            and not candidate.already_lazy
            and candidate.imported == edge.imported
        ):
            others.add(candidate.importer)

    return sorted(others)


def _edge_record(item: _Classified, other_eager: list[str]) -> EdgeRecord:
    """The JSON form of one edge."""

    edge = item.edge

    return EdgeRecord(
        id=edge.id,
        parent_id=edge.parent_id,
        imported=edge.imported,
        importer=edge.importer,
        line=edge.line,
        kind=edge.kind,
        level=edge.level_name,
        loaded=edge.loaded,
        cum_ms=edge.cum_ms,
        self_ms=edge.self_ms,
        deferrable=Deferrability(native=item.native, unwrapt=item.unwrapt),
        unwrapt_limit=item.limit,
        already_lazy=edge.already_lazy,
        native_lazy=edge.native_lazy,
        other_eager_importers=other_eager,
    )


_LIMITS = [
    "The profile cannot see import-time use of the imported name by the"
    " importing module: class bases, decorators, default arguments,"
    " annotations without `from __future__ import annotations` and"
    " module level calls all force resolution at import time, and none"
    " of them show here.",
    "A `try/except ImportError` around the import is invisible to the"
    " profile: deferring a guarded optional dependency moves its"
    " ImportError to first use.",
    "The report describes the workload that was profiled, not every"
    " workload: an import cheap on one path may be unavoidable on"
    " another.",
    "Imports made through importlib.import_module and the C import API,"
    " and submodule loads inside `from` imports, do not pass through the"
    " hook as edges of their own: their time is included in the"
    " enclosing cumulative figure but gets no row.",
    "Per-import timing overhead inflates every figure. Compare relative"
    " sizes, against `python -X importtime` for example, and never treat"
    " a millisecond figure as a wall-clock promise.",
]


def _edge(report: Report, edge_id: int | None) -> EdgeRecord | None:
    """The edge record with the given id, when the report has one."""

    if edge_id is None:
        return None

    for edge in report["edges"]:
        if edge["id"] == edge_id:
            return edge

    return None


def _who(edge: EdgeRecord) -> str:
    """The importer column: its module name or a placeholder."""

    return edge["importer"] if edge["importer"] is not None else "<unknown>"


def _native_cell(edge: EdgeRecord) -> str:
    """The 3.15 column: deferrable, n/a for function level imports."""

    if edge["level"] == "function":
        return "n/a (2)"

    return "yes" if edge["deferrable"]["native"] else "no"


def _unwrapt_cell(edge: EdgeRecord) -> str:
    """The unwrapt column: deferrable, with the footnote when the form
    is the limit, and n/a for function level imports."""

    if edge["level"] == "function":
        return "n/a (2)"

    return "yes" if edge["deferrable"]["unwrapt"] else "no (1)"


def _notes(edge: EdgeRecord) -> str:
    """The notes column: shared importers and already lazy declarations."""

    notes: list[str] = []

    if edge["already_lazy"]:
        notes.append("already lazy")

    others = edge["other_eager_importers"]

    if others:
        names = ", ".join(others)
        notes.append(f"shared (+{len(others)}: {names})")

    return "; ".join(notes)


def _under_packages(importer: str | None, packages: list[str] | None) -> bool:
    """Whether the importing module is one of the packages named by
    UNWRAPT_PROFILE_PACKAGES, or lives under one of them. Importers
    outside them are treated as not editable and hidden."""

    if packages is None:
        return True

    if importer is None:
        return False

    return any(
        importer == package or importer.startswith(f"{package}.")
        for package in packages
    )


def _loaded_modules(report: Report) -> set[str]:
    """The top-level packages a report's loaded edges brought in."""

    return {top_level(edge["imported"]) for edge in report["edges"] if edge["loaded"]}


def _ms(value: float) -> str:
    """Format a millisecond figure with one decimal place."""

    return f"{value:.1f}"


def _table(rows: Sequence[list[str]], left: Sequence[bool]) -> list[str]:
    """Render rows as an aligned table with a two space gutter.

    The first row is the header. left says, per column, whether it
    aligns left (True) or right (False). Trailing spaces are stripped.
    """

    if len(rows) <= 1:
        return ["  (nothing to show)"]

    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]

    lines = []

    for row in rows:
        cells = [
            cell.ljust(widths[index]) if left[index] else cell.rjust(widths[index])
            for index, cell in enumerate(row)
        ]

        lines.append("  " + "  ".join(cells).rstrip())

    return lines


def _load_report(path: str) -> Report:
    """Load a saved JSON profile report."""

    with open(path, encoding="utf-8") as fp:
        return cast(Report, json.load(fp))
