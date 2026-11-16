"""The profile report: recorded facts as versioned data, and their analysis.

A Report holds what the recorder saw, one record per import call (with
repeated already-loaded hits folded into one record with a count),
plus the labels the caller attached and the table of label sets the
edges refer to. Its dictionary form is the JSON schema, versioned by
its "schema" field, and holds facts only: the analysis (who pays for
each module, the candidates and their savings, the chains leading to a
module, the deferral outcomes) is a set of functions over a Report,
which the text renderer uses and a consumer can call or skip.

Pure computation and rendering: nothing here reads the environment,
installs anything or imports anything at call time, which is what lets
a saved JSON report be re-rendered as text, and two reports compared,
without re-running the application.

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from unwrapt import __version__
from unwrapt._config import ProfileOptions

# The version of the dictionary form. Bumped whenever a field changes
# incompatibly.

SCHEMA = 2

# How many heavy modules get an import chain in the text report.
_CHAIN_LIMIT = 8

# `import a.b as c` cannot be deferred by the shim on older Pythons:
# the IMPORT_FROM that follows the IMPORT_NAME fetches the attribute
# immediately and resolves the proxy. `import a.b`, which binds the top
# package, can. The bytecode of both is the same IMPORT_NAME call, so
# the report reads the source line to tell them apart.

_DOTTED_AS = re.compile(r"^\s*(?:lazy\s+)?import\s+([\w.]+)\s+as\s+\w+\s*(?:#.*)?$")

_ESTIMATE_NOTE = "conservative; edge times nest and are not additive"


# The dictionary form, which is the JSON schema.


class Defer(TypedDict):
    """Whether the import can be deferred, and if not by the shim, why.

    native is whether native lazy imports (Python 3.15 and later) could
    defer the statement's form. unwrapt is whether the shim would defer
    this call if the import were listed, by the shim's own rules, and
    reason is the first of those rules it fails: function-level,
    class-level, relative, from-import, dotted-as or already-loaded.
    """

    native: bool
    unwrapt: bool
    reason: str | None


class EdgeRecord(TypedDict):
    """One import call, or one folded run of already-loaded hits."""

    id: int
    parent_id: int | None
    importer: str | None
    imported: str
    file: str | None
    line: int | None
    kind: str
    level: str
    relative: bool
    loaded: bool
    count: int
    cum_ms: float
    self_ms: float
    defer: Defer
    already_lazy: bool
    native_lazy: bool
    deferred: bool
    resolution: int | None
    resolves: int | None
    used_in: str | None
    labels: int


class Filters(TypedDict):
    """The display filters a text rendering uses unless told otherwise."""

    min_ms: float
    packages: list[str] | None


class ReportDict(TypedDict):
    """The whole report, in the JSON schema."""

    schema: int
    unwrapt: str
    python: str
    labels: dict[str, str]
    label_sets: list[dict[str, str]]
    filters: Filters
    edges: list[EdgeRecord]


# The analysis results.


class Summary(TypedDict):
    """The headline figures of a report."""

    total_import_ms: float
    modules_loaded: int
    edge_count: int
    import_calls: int
    estimated_saving_ms: float
    estimate_note: str
    best_cut: int | None


class Need(TypedDict):
    """An importer that needed a module someone else had already loaded."""

    importer: str | None
    labels: dict[str, str]
    count: int


class Payment(TypedDict):
    """Who paid to load a module, and who else needed it afterwards."""

    module: str
    edge: int
    importer: str | None
    labels: dict[str, str]
    cum_ms: float
    self_ms: float
    also_needed_by: list[Need]


class Candidate(TypedDict):
    """A module-level import that loaded a module, as a deferral candidate.

    saving_ms is what deferring this one import alone would save: its
    cumulative time, less the cost of any module it loads that another
    eager importer would load anyway, and zero when the shim cannot
    defer it, it is already lazy, or its own module is shared.
    """

    edge: int
    imported: str
    importer: str | None
    cum_ms: float
    self_ms: float
    native: bool
    unwrapt: bool
    reason: str | None
    already_lazy: bool
    shared: list[str]
    saving_ms: float


class Chain(TypedDict):
    """The path of import calls that loaded a module, outermost first."""

    module: str
    self_ms: float
    links: list[int]
    best_cut: int | None


class HeavyModule(TypedDict):
    """A top-level package and the self time its loads cost."""

    module: str
    self_ms: float


class ByImporter(TypedDict):
    """An importing module and the cumulative time of its direct loads."""

    importer: str
    cum_ms: float


class DeferredUnused(TypedDict):
    """A deferred import the profiled run never used."""

    edge: int
    module: str
    importer: str | None


class DeferredUsed(TypedDict):
    """A deferred import the profiled run used, and so loaded anyway."""

    edge: int | None
    resolution: int
    module: str
    importer: str | None
    used_in: str | None
    line: int | None
    load_ms: float
    loaded: bool


# The recorder's in-memory form.


@dataclass(frozen=True)
class Edge:
    """One recorded import call, as the recorder holds it.

    kind is "import" or "from" depending on whether the call had a
    fromlist, or "resolve" for a deferred import being resolved at
    first use, in a run with deferral on; level_name is "module",
    "function" or "class" for where the statement sits, and relative
    whether the import was relative. already_lazy marks an import that
    is already declared deferred, by __lazy_modules__, by the external
    configuration, or natively on Python 3.15; native_lazy is the
    Python 3.15 case, an import recorded at native reification rather
    than at its statement. deferred marks an import the shim below the
    recorder handed back as a lazy proxy, in a run with deferral on. A
    resolve edge carries in resolves the id of the deferred edge it
    resolves, when the recorder saw that deferral, and in used_in the
    module that used the proxy first; its line is the line of that
    first use. labels is the index of the label set in force, and count
    the number of already-loaded hits a folded edge stands for, with
    their times summed.
    """

    id: int
    parent_id: int | None
    importer: str | None
    imported: str
    kind: Literal["import", "from", "resolve"]
    level_name: Literal["module", "function", "class"]
    line: int | None
    file: str | None
    loaded: bool
    cum_ms: float
    self_ms: float
    native_lazy: bool
    already_lazy: bool
    deferred: bool = False
    resolves: int | None = None
    used_in: str | None = None
    relative: bool = False
    labels: int = 0
    count: int = 1


class Report:
    """A profile report, as versioned data.

    labels is the caller's own description of what the report is of,
    a dict to update freely, for example with app, release, role and
    outcome. label_sets is the table of the label sets in force when
    edges were recorded, which each edge's labels field indexes, and
    edges the import calls. filters holds the display filters a text
    rendering uses unless told otherwise. to_dict() is the JSON schema.
    """

    SCHEMA = SCHEMA

    def __init__(
        self,
        *,
        edges: list[EdgeRecord],
        label_sets: list[dict[str, str]],
        filters: Filters,
        labels: dict[str, str] | None = None,
        unwrapt: str = __version__,
        python: str | None = None,
    ) -> None:
        self.unwrapt = unwrapt
        self.python = python if python is not None else platform.python_version()
        self.labels: dict[str, str] = dict(labels or {})
        self.label_sets = label_sets
        self.filters = filters
        self.edges = edges
        self._graph: _Graph | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Report":
        """Build a Report from its dictionary form, as loaded from JSON.

        Raises ValueError for a report of another schema version.
        """

        schema = data.get("schema")

        if schema != SCHEMA:
            raise ValueError(
                f"report schema {schema!r} is not supported: this unwrapt reads"
                f" schema {SCHEMA}, so profile the application again"
            )

        return cls(
            edges=list(data["edges"]),
            label_sets=[dict(item) for item in data["label_sets"]],
            filters=Filters(
                min_ms=float(data["filters"]["min_ms"]),
                packages=data["filters"]["packages"],
            ),
            labels=dict(data["labels"]),
            unwrapt=str(data["unwrapt"]),
            python=str(data["python"]),
        )

    def to_dict(self) -> ReportDict:
        """The dictionary form: the JSON schema, with a "schema" version."""

        return ReportDict(
            schema=SCHEMA,
            unwrapt=self.unwrapt,
            python=self.python,
            labels=dict(self.labels),
            label_sets=[dict(item) for item in self.label_sets],
            filters=Filters(
                min_ms=self.filters["min_ms"],
                packages=list(self.filters["packages"])
                if self.filters["packages"] is not None
                else None,
            ),
            edges=list(self.edges),
        )

    def render_json(self) -> str:
        """The dictionary form as JSON, indented for reading."""

        return json.dumps(self.to_dict(), indent=2)

    def render_text(
        self,
        *,
        min_ms: float | None = None,
        packages: Sequence[str] | None = None,
    ) -> str:
        """The text report.

        A summary header, the deferral sections for a run with deferral
        on, then candidates, heavy modules, by importer and import
        chains. min_ms and packages filter the candidate rows, and
        default to the report's own filters.
        """

        return _render_text(self, min_ms, packages)

    def edge(self, edge_id: int | None) -> EdgeRecord | None:
        """The edge record with the given id, when the report has one."""

        if edge_id is None:
            return None

        return self.graph().by_id.get(edge_id)

    def label_set(self, index: int) -> dict[str, str]:
        """The labels an edge's labels index refers to."""

        if 0 <= index < len(self.label_sets):
            return dict(self.label_sets[index])

        return {}

    def graph(self) -> "_Graph":
        """The edge lookup tables, built once."""

        if self._graph is None:
            self._graph = _Graph(self.edges)

        return self._graph


class _Graph:
    """The lookup tables over a report's edges: by id, and children."""

    def __init__(self, edges: Sequence[EdgeRecord]) -> None:
        self.by_id: dict[int, EdgeRecord] = {edge["id"]: edge for edge in edges}
        self.children: dict[int, list[int]] = {}

        for edge in edges:
            if edge["parent_id"] is not None:
                self.children.setdefault(edge["parent_id"], []).append(edge["id"])

    def descendants(self, root: int) -> set[int]:
        """The ids of every edge nested below root, excluding root itself."""

        seen: set[int] = set()
        pending = list(self.children.get(root, ()))

        while pending:
            edge_id = pending.pop()

            if edge_id in seen:
                continue

            seen.add(edge_id)
            pending.extend(self.children.get(edge_id, ()))

        return seen


def top_level(name: str) -> str:
    """The top-level package of a module name, which is what `import
    a.b` binds and what a plain import loads first."""

    return name.partition(".")[0]


def build_report(
    edges: Sequence[Edge],
    options: ProfileOptions,
    label_sets: Sequence[Mapping[str, str]] = ({},),
) -> Report:
    """Turn recorded edges into a Report.

    options supplies the display filters, stored in the report for the
    text renderer, and never drops an edge. label_sets is the table the
    edges' label indexes refer to.
    """

    resolutions = {
        edge.resolves: edge.id for edge in edges if edge.resolves is not None
    }

    records = [
        _edge_record(edge, resolutions.get(edge.id))
        for edge in sorted(edges, key=lambda edge: edge.id)
    ]

    return Report(
        edges=records,
        label_sets=[dict(item) for item in label_sets],
        filters=Filters(
            min_ms=options.min_ms,
            packages=list(options.packages) if options.packages is not None else None,
        ),
    )


def load_report(path: str) -> Report:
    """Load a saved JSON profile report.

    Raises OSError or json.JSONDecodeError for a file that cannot be
    read, and ValueError for a report of another schema version.
    """

    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)

    if not isinstance(data, dict):
        raise ValueError(f"{path} is not an unwrapt profile report")

    return Report.from_dict(data)


# The analysis.


def summary(report: Report) -> Summary:
    """The headline figures: the totals, and the deferral plan's saving.

    The total is the sum of the outermost import calls, so a nest
    counts once. The estimated saving is for deferring every
    module-level import both routes can defer, net of the cost that
    would only move to another eager importer, and the best cut is the
    single link that removes the most.
    """

    plan = _Plan(report)

    return Summary(
        total_import_ms=sum(
            edge["cum_ms"] for edge in report.edges if edge["parent_id"] is None
        ),
        modules_loaded=len(heavy_modules(report)),
        edge_count=len(report.edges),
        import_calls=sum(edge["count"] for edge in report.edges),
        estimated_saving_ms=plan.estimated_saving(),
        estimate_note=_ESTIMATE_NOTE,
        best_cut=_best_cut(report, chains(report)),
    )


def who_pays(report: Report) -> list[Payment]:
    """For each module loaded, the import that paid for it and who else
    needed it, costliest first.

    The cost of a module stays with its first load. Every other import
    of the same name that found it loaded, under whatever labels were
    in force, is listed as also needing it, grouped by importer and
    label set with a count: that is how a later entry point shows that
    it needs a module an earlier one paid for.
    """

    needs: dict[str, dict[tuple[str | None, int], int]] = {}

    for edge in report.edges:
        if not edge["loaded"] and edge["kind"] != "resolve" and not edge["deferred"]:
            key = (edge["importer"], edge["labels"])
            by_need = needs.setdefault(edge["imported"], {})
            by_need[key] = by_need.get(key, 0) + edge["count"]

    payments: list[Payment] = []
    seen: set[str] = set()

    for edge in sorted(report.edges, key=lambda edge: edge["id"]):
        module = edge["imported"]

        if not edge["loaded"] or module in seen:
            continue

        seen.add(module)

        also = [
            Need(importer=importer, labels=report.label_set(labels), count=count)
            for (importer, labels), count in needs.get(module, {}).items()
            if not (importer == edge["importer"] and labels == edge["labels"])
        ]

        payments.append(
            Payment(
                module=module,
                edge=edge["id"],
                importer=edge["importer"],
                labels=report.label_set(edge["labels"]),
                cum_ms=edge["cum_ms"],
                self_ms=edge["self_ms"],
                also_needed_by=also,
            )
        )

    payments.sort(key=lambda payment: (-payment["cum_ms"], payment["edge"]))

    return payments


def candidates(
    report: Report,
    *,
    min_ms: float | None = None,
    packages: Sequence[str] | None = None,
) -> list[Candidate]:
    """The module-level imports that loaded a module, ranked by
    cumulative time, with what deferring each alone would save.

    No row is dropped because a route cannot defer it: the native and
    unwrapt columns say which can. min_ms and packages default to the
    report's filters; packages keeps only importers under the named
    top-level packages.
    """

    if min_ms is None:
        min_ms = report.filters["min_ms"]

    if packages is None and report.filters["packages"] is not None:
        packages = report.filters["packages"]

    graph = report.graph()
    eager = _eager_importers(report)

    rows: list[Candidate] = []

    for edge in report.edges:
        if (
            edge["level"] != "module"
            or edge["kind"] == "resolve"
            or not edge["loaded"]
            or edge["cum_ms"] < min_ms
            or not _under_packages(edge["importer"], packages)
        ):
            continue

        rows.append(
            Candidate(
                edge=edge["id"],
                imported=edge["imported"],
                importer=edge["importer"],
                cum_ms=edge["cum_ms"],
                self_ms=edge["self_ms"],
                native=edge["defer"]["native"],
                unwrapt=edge["defer"]["unwrapt"],
                reason=edge["defer"]["reason"],
                already_lazy=edge["already_lazy"],
                shared=_shared(report, edge),
                saving_ms=_single_saving(graph, edge, eager),
            )
        )

    rows.sort(key=lambda row: (-row["cum_ms"], row["edge"]))

    return rows


def chain(report: Report, module: str) -> Chain | None:
    """The chain of import calls that loaded module, outermost first.

    module is matched by top-level package, against the first edge that
    loaded it. A chain is the list of places the load could be cut. Its
    best cut is the outermost link that both routes can defer, that is
    not already lazy, and whose deferral is not undone by an eager
    importer of a module in its subtree. Deferring an outer link
    removes the whole subtree beneath it, so the outermost safe link
    saves the most. Returns None when nothing loaded the module.
    """

    graph = report.graph()
    target = top_level(module)

    loading = [
        edge
        for edge in report.edges
        if edge["loaded"] and top_level(edge["imported"]) == target
    ]

    if not loading:
        return None

    first = min(loading, key=lambda edge: edge["id"])

    # Walk parents to the outermost import, then emit root first.

    links: list[int] = []
    current: EdgeRecord | None = first

    while current is not None:
        links.append(current["id"])
        parent_id = current["parent_id"]
        current = graph.by_id.get(parent_id) if parent_id is not None else None

    links.reverse()

    self_ms = sum(edge["self_ms"] for edge in loading)

    return Chain(
        module=target,
        self_ms=self_ms,
        links=links,
        best_cut=_Plan(report).best_cut(links),
    )


def chains(report: Report, limit: int = _CHAIN_LIMIT) -> list[Chain]:
    """The chains of the heaviest modules, heaviest first."""

    result: list[Chain] = []

    for heavy in heavy_modules(report)[:limit]:
        found = chain(report, heavy["module"])

        if found is not None:
            result.append(found)

    return result


def heavy_modules(report: Report) -> list[HeavyModule]:
    """Self time per loaded top-level package, heaviest first.

    Self time separates a module's own import work from the modules it
    pulls in, so a thin wrapper that drags in a heavy dependency shows
    near-zero self time while the dependency shows the cost.
    """

    heavy: dict[str, float] = {}

    for edge in report.edges:
        if edge["loaded"]:
            module = top_level(edge["imported"])
            heavy[module] = heavy.get(module, 0.0) + edge["self_ms"]

    return [
        HeavyModule(module=module, self_ms=self_ms)
        for module, self_ms in sorted(heavy.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def by_importer(report: Report) -> list[ByImporter]:
    """Cumulative time of each importer's direct module-level loads.

    These are the files to edit first: the sum counts only edges whose
    statement sits in the module itself, never the imports made by the
    modules it goes on to load, and never the resolve of an import that
    is already deferred.
    """

    by: dict[str, float] = {}

    for edge in report.edges:
        if (
            edge["loaded"]
            and edge["level"] == "module"
            and edge["kind"] != "resolve"
            and edge["importer"] is not None
        ):
            by[edge["importer"]] = by.get(edge["importer"], 0.0) + edge["cum_ms"]

    return [
        ByImporter(importer=importer, cum_ms=cum_ms)
        for importer, cum_ms in sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def deferred_unused(report: Report) -> list[DeferredUnused]:
    """The deferred imports the run never used, in recorded order."""

    return [
        DeferredUnused(
            edge=edge["id"], module=edge["imported"], importer=edge["importer"]
        )
        for edge in report.edges
        if edge["deferred"] and edge["resolution"] is None
    ]


def deferred_used(report: Report) -> list[DeferredUsed]:
    """The deferred imports the run used anyway, costliest first, with
    where each was first used and what its load cost."""

    resolves = [edge for edge in report.edges if edge["kind"] == "resolve"]
    resolves.sort(key=lambda edge: (-edge["cum_ms"], edge["id"]))

    return [
        DeferredUsed(
            edge=edge["resolves"],
            resolution=edge["id"],
            module=edge["imported"],
            importer=edge["importer"],
            used_in=edge["used_in"],
            line=edge["line"],
            load_ms=edge["cum_ms"],
            loaded=edge["loaded"],
        )
        for edge in resolves
    ]


def compare_reports(before: Report, after: Report) -> str:
    """Compare two reports: totals, per-module self time changes, and
    modules newly loaded or no longer loaded."""

    lines: list[str] = []

    old_total = summary(before)["total_import_ms"]
    new_total = summary(after)["total_import_ms"]

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

    old_self = {entry["module"]: entry["self_ms"] for entry in heavy_modules(before)}
    new_self = {entry["module"]: entry["self_ms"] for entry in heavy_modules(after)}

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
        before = load_report(args.report)
        after = load_report(args.compare) if args.compare else None
    except (OSError, ValueError) as exc:
        print(f"unwrapt: {exc}", file=sys.stderr)

        return 1

    print(before.render_text())

    if after is not None:
        print("")
        print(compare_reports(before, after))

    return 0


# Classification of the recorded edges.


def _edge_record(edge: Edge, resolution: int | None) -> EdgeRecord:
    """The dictionary form of one edge."""

    return EdgeRecord(
        id=edge.id,
        parent_id=edge.parent_id,
        importer=edge.importer,
        imported=edge.imported,
        file=edge.file,
        line=edge.line,
        kind=edge.kind,
        level=edge.level_name,
        relative=edge.relative,
        loaded=edge.loaded,
        count=edge.count,
        cum_ms=edge.cum_ms,
        self_ms=edge.self_ms,
        defer=_defer(edge),
        already_lazy=edge.already_lazy,
        native_lazy=edge.native_lazy,
        deferred=edge.deferred,
        resolution=resolution,
        resolves=edge.resolves,
        used_in=edge.used_in,
        labels=edge.labels,
    )


def _defer(edge: Edge) -> Defer:
    """Whether each route can defer the import, by the shim's own rules.

    The shim's rules, in the order the reason reports them: a
    module-level statement (not a function or class body), absolute,
    whole-module (no fromlist), not `import a.b as c`, and the module
    not already loaded. The native route defers any form at module
    level, relative and from-imports included, so a limit of the shim
    is not a property of the code: the two routes are reported
    separately, and no edge is ever dropped because one cannot defer
    it. A resolve edge is a statement that was deferred, and a
    deferred edge one the shim did defer.
    """

    if edge.level_name == "function":
        return Defer(native=False, unwrapt=False, reason="function-level")

    if edge.level_name == "class":
        return Defer(native=False, unwrapt=False, reason="class-level")

    if edge.relative:
        return Defer(native=True, unwrapt=False, reason="relative")

    if edge.kind == "from":
        return Defer(native=True, unwrapt=False, reason="from-import")

    if edge.kind == "import" and not edge.loaded and not edge.deferred:
        return Defer(native=False, unwrapt=False, reason="already-loaded")

    if edge.kind == "import" and _is_dotted_as(edge):
        return Defer(native=True, unwrapt=False, reason="dotted-as")

    return Defer(native=True, unwrapt=True, reason=None)


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


def _both_routes(edge: EdgeRecord) -> bool:
    """Whether both routes can defer the statement's form.

    An already-loaded hit counts: the shim would pass that one call
    through, but the statement is one the plan can defer, and does, so
    it never stands as an eager importer.
    """

    defer = edge["defer"]

    return (defer["native"] and defer["unwrapt"]) or defer["reason"] == "already-loaded"


class _Plan:
    """The deferral plan behind the estimated saving and the best cuts.

    Every loaded module-level import that both routes can defer and
    that is not already lazy is a planned deferral, except that an edge
    nested below another planned deferral is not kept: deferring the
    outer one already removes it, and adding its time would double
    count. The eager importers are the module-level imports outside the
    plan that are not already lazy and that a route cannot defer: they
    would load their modules anyway.
    """

    def __init__(self, report: Report) -> None:
        self.graph = report.graph()

        planned = [
            edge
            for edge in report.edges
            if _both_routes(edge)
            and edge["loaded"]
            and edge["level"] == "module"
            and not edge["already_lazy"]
        ]

        inside: set[int] = set()

        for edge in planned:
            inside |= self.graph.descendants(edge["id"])

        self.kept = [edge for edge in planned if edge["id"] not in inside]
        self.kept_ids = {edge["id"] for edge in self.kept}

        self.inside_kept: set[int] = set()

        for edge in self.kept:
            self.inside_kept |= self.graph.descendants(edge["id"])

        self.eager: set[str] = set()

        for edge in report.edges:
            if (
                edge["id"] not in self.inside_kept
                and edge["id"] not in self.kept_ids
                and edge["level"] == "module"
                and not edge["already_lazy"]
                and not _both_routes(edge)
            ):
                self.eager.add(top_level(edge["imported"]))

    def estimated_saving(self) -> float:
        """The conservative estimated saving of the plan.

        The kept edges' cumulative times, minus the cost of any module
        in their subtrees that an eager importer would load anyway: that
        cost moves, it does not disappear. A module loaded more than
        once inside the plan is counted once, at its most expensive
        load.
        """

        if not self.kept:
            return 0.0

        moved: dict[str, float] = {}

        for edge_id in self.inside_kept:
            edge = self.graph.by_id[edge_id]
            module = top_level(edge["imported"])

            if edge["loaded"] and module in self.eager:
                moved[module] = max(moved.get(module, 0.0), edge["cum_ms"])

        saving = sum(edge["cum_ms"] for edge in self.kept) - sum(moved.values())

        # Timing noise aside, a nest cannot save more than it costs.

        return max(saving, 0.0)

    def best_cut(self, links: Sequence[int]) -> int | None:
        """The outermost safe link of a chain, scanning from the root.

        A link is safe when no module loaded in its subtree has an eager
        importer outside the plan: otherwise deferring the link only
        moves that module's cost.
        """

        for link_id in links:
            if link_id not in self.kept_ids:
                continue

            undone = any(
                top_level(self.graph.by_id[desc]["imported"]) in self.eager
                for desc in self.graph.descendants(link_id)
                if self.graph.by_id[desc]["loaded"]
            )

            if not undone:
                return link_id

        return None


def _best_cut(report: Report, found: Sequence[Chain]) -> int | None:
    """The single best cut overall: the largest best cut across chains."""

    cuts: list[tuple[float, int]] = []

    for item in found:
        cut = item["best_cut"]
        edge = report.edge(cut)

        if cut is not None and edge is not None:
            cuts.append((edge["cum_ms"], cut))

    if not cuts:
        return None

    return max(cuts)[1]


def _eager_importers(report: Report) -> dict[str, set[int]]:
    """For each top-level package, the module-level edges importing it
    that are not already lazy, loaded or cache hit."""

    eager: dict[str, set[int]] = {}

    for edge in report.edges:
        if (
            edge["level"] == "module"
            and edge["kind"] != "resolve"
            and not edge["already_lazy"]
            and not edge["deferred"]
        ):
            eager.setdefault(top_level(edge["imported"]), set()).add(edge["id"])

    return eager


def _single_saving(
    graph: _Graph, edge: EdgeRecord, eager: Mapping[str, set[int]]
) -> float:
    """What deferring this one import, and nothing else, would save.

    Every module it loads, itself included, whose top-level package has
    another eager importer outside its subtree would be loaded there
    anyway, so that load's cost moves rather than disappearing.
    """

    if not edge["defer"]["unwrapt"] or edge["already_lazy"]:
        return 0.0

    subtree = graph.descendants(edge["id"])
    inside = subtree | {edge["id"]}

    moved: dict[str, float] = {}

    for edge_id in inside:
        loaded = graph.by_id[edge_id]
        module = top_level(loaded["imported"])

        if loaded["loaded"] and eager.get(module, set()) - inside:
            moved[module] = max(moved.get(module, 0.0), loaded["cum_ms"])

    return max(edge["cum_ms"] - sum(moved.values()), 0.0)


def _shared(report: Report, edge: EdgeRecord) -> list[str]:
    """The other modules that also import this edge's module and are not
    already lazy, loaded or cache hit. A shared module only stays
    unloaded if every eager importer of it is deferred.

    The same module means the same imported name, so `import xml.dom`
    and `from xml.dom import Node` count as importers of the same
    module while `import xml` alone does not.
    """

    others: set[str] = set()

    for candidate in report.edges:
        if (
            candidate["importer"] is not None
            and candidate["importer"] != edge["importer"]
            and candidate["level"] == "module"
            and candidate["kind"] != "resolve"
            and not candidate["already_lazy"]
            and candidate["imported"] == edge["imported"]
        ):
            others.add(candidate["importer"])

    return sorted(others)


def _under_packages(importer: str | None, packages: Sequence[str] | None) -> bool:
    """Whether the importing module is one of the packages named by the
    packages filter, or lives under one of them. Importers outside them
    are treated as not editable and hidden."""

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

    return {top_level(edge["imported"]) for edge in report.edges if edge["loaded"]}


# The text renderer.


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


def _render_text(
    report: Report,
    min_ms: float | None,
    packages: Sequence[str] | None,
) -> str:
    """Render the text report, from the analysis functions alone."""

    if min_ms is None:
        min_ms = report.filters["min_ms"]

    if packages is None and report.filters["packages"] is not None:
        packages = report.filters["packages"]

    headline = summary(report)
    lines: list[str] = []

    # Summary header.

    lines.append(f"unwrapt {report.unwrapt} profile report")

    if report.labels:
        names = ", ".join(f"{key}={value}" for key, value in report.labels.items())
        lines.append(f"Labels: {names}")

    lines.append("")

    lines.append(
        f"Summary: {_ms(headline['total_import_ms'])} ms total import time,"
        f" {headline['modules_loaded']} modules loaded,"
        f" {headline['edge_count']} edges ({headline['import_calls']} import calls)"
    )
    lines.append(
        f"Estimated saving if every deferrable edge were deferred:"
        f" {_ms(headline['estimated_saving_ms'])} ms"
        f" ({headline['estimate_note']})"
    )

    best = report.edge(headline["best_cut"])

    if best is not None:
        lines.append(
            f"Best single cut: {_who(best)} -> {best['imported']}"
            f" ({_ms(best['cum_ms'])} ms cumulative)"
        )

    # Native lazy imports (Python 3.15) are recorded at first use, and
    # the reader needs to know which edges those are and what that
    # means for the figures.

    reified = sum(1 for edge in report.edges if edge["native_lazy"])

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

    # The deferral sections, for a run with deferral on.

    lines.extend(_render_deferrals(report))

    # Candidates: loaded module-level imports, ranked by cumulative
    # time, never dropped because a route cannot defer them. A resolve
    # edge is not a statement to change, and has its own section.

    lines.append("")
    lines.append("Candidates: module-level imports, ranked by cumulative time")

    if min_ms > 0.0:
        lines.append(f"(rows under {_ms(min_ms)} ms hidden by the min_ms filter)")

    if packages is not None:
        names = ", ".join(packages)
        lines.append(f"(rows outside {names} hidden by the packages filter)")

    table = [
        ["cum ms", "self ms", "imported", "imported by", "3.15", "unwrapt", "notes"]
    ]

    for row in candidates(report, min_ms=min_ms, packages=packages):
        edge = report.edge(row["edge"])

        assert edge is not None

        table.append(
            [
                _ms(row["cum_ms"]),
                _ms(row["self_ms"]),
                row["imported"],
                _who(edge),
                _native_cell(edge),
                _unwrapt_cell(edge),
                _notes(edge, row["shared"]),
            ]
        )

    # Numbers and route columns right aligned, names and notes left.

    lines.extend(_table(table, [False, False, True, True, False, False, True]))

    lines.append("")
    lines.append("  (1) unwrapt hands back a lazy proxy, and the attribute")
    lines.append("      fetch in a `from x import y` or `import a.b as c`")
    lines.append("      resolves it immediately, and it never defers a")
    lines.append("      relative import. The saving is real on Python")
    lines.append("      3.15+, or after a rewrite to `import x` and attribute")
    lines.append("      access on older Pythons.")
    lines.append("  (2) function level imports are already deferred until the")
    lines.append("      function runs, so there is nothing to decide.")

    # Heavy modules.

    lines.append("")
    lines.append("Heavy modules: by self time")

    for heavy in heavy_modules(report):
        lines.append(f"  {_ms(heavy['self_ms'])} ms  {heavy['module']}")

    # By importer.

    lines.append("")
    lines.append("By importer: direct module-level loads, the files to edit first")

    for entry in by_importer(report):
        lines.append(f"  {_ms(entry['cum_ms'])} ms  {entry['importer']}")

    # Import chains.

    lines.append("")
    lines.append("Import chains: why each heavy module is loaded")

    for item in chains(report):
        lines.append("")
        lines.append(f"  {item['module']}  {_ms(item['self_ms'])} ms self")

        for edge_id in item["links"]:
            link = report.edge(edge_id)

            if link is None:
                continue

            parts = [
                f"    {_who(link)} -> {link['imported']}",
                f"cum {_ms(link['cum_ms'])} ms",
                f"3.15 {_native_cell(link)}",
                f"unwrapt {_unwrapt_cell(link)}",
            ]

            if link["id"] == item["best_cut"]:
                parts.append("<- best cut")

            notes = _notes(link, _shared(report, link))

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


def _render_deferrals(report: Report) -> list[str]:
    """The two deferral sections, shown only for a run that deferred."""

    unused = deferred_unused(report)
    used = deferred_used(report)

    if not unused and not used:
        return []

    lines = [""]
    lines.append("Deferred but used anyway: loaded during the run, so not a saving")

    table = [["load ms", "module", "deferred in", "first used in", "line"]]

    for entry in used:
        table.append(
            [
                _ms(entry["load_ms"]) if entry["loaded"] else "(loaded)",
                entry["module"],
                _name(entry["importer"]),
                _name(entry["used_in"]),
                str(entry["line"]) if entry["line"] is not None else "",
            ]
        )

    lines.extend(_table(table, [False, True, True, True, False]))

    lines.append("")
    lines.append("  (loaded) means something else had already loaded the module.")

    lines.append("")
    lines.append("Deferred and never used: deferred for the whole run")

    table = [["module", "deferred in"]]

    for unused_entry in unused:
        table.append([unused_entry["module"], _name(unused_entry["importer"])])

    lines.extend(_table(table, [True, True]))

    lines.append("")
    lines.append("  What each would have cost is known only from a profile with")
    lines.append("  nothing deferred. To see the saving, compare against one:")
    lines.append("  python -m unwrapt.report EAGER.json --compare THIS.json")

    return lines


def _who(edge: EdgeRecord) -> str:
    """The importer column: its module name or a placeholder."""

    return _name(edge["importer"])


def _name(module: str | None) -> str:
    """A module name for display, or a placeholder when it is unknown."""

    return module if module is not None else "<unknown>"


def _native_cell(edge: EdgeRecord) -> str:
    """The 3.15 column: deferrable, n/a for function level imports."""

    if edge["level"] == "function":
        return "n/a (2)"

    return "yes" if edge["defer"]["native"] else "no"


def _unwrapt_cell(edge: EdgeRecord) -> str:
    """The unwrapt column: deferrable, with the footnote when the form
    is the limit, and n/a for function level imports."""

    if edge["level"] == "function":
        return "n/a (2)"

    return "yes" if edge["defer"]["unwrapt"] else "no (1)"


def _notes(edge: EdgeRecord, shared: Sequence[str]) -> str:
    """The notes column: shared importers and already lazy declarations."""

    notes: list[str] = []

    if edge["already_lazy"]:
        notes.append("already lazy")

    if shared:
        names = ", ".join(shared)
        notes.append(f"shared (+{len(shared)}: {names})")

    return "; ".join(notes)


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
