# unwrapt — Specification

**Status:** design specification, ready for implementation
**Audience:** an AI coding assistant (or developer) implementing the package from scratch
**Package name:** `unwrapt` (PyPI), import name `unwrapt`
**Revision:** 6 (initial version `1.0.0b1`, version defined as in wrapture; section 12.1). Revision 5 set the minimum Python to 3.12 (aligned with wrapture) and required type hints throughout. Revision 4: Adds import chains and a non-additive summary to the profile report (sections 8.4, 8.7) and a documentation strategy guide for turning the report into decisions (section 19.4). Earlier revisions added external-config-only mode as the behaviour on Python 3.15+ (no force switch), a Read the Docs documentation tree, and repository and AI-steering-file conventions taken from the wrapture project (sections 18 to 20).

> Tagline: *Don't open it until you need it.*

---

## 0. How to use this document

This spec was produced from a design conversation. It separates:

- **Normative requirements** (MUST / SHOULD / MAY): what the package has to do.
- **Informative sketches**: example code that illustrates intent. Do not treat them as final; they were written from memory without being run.
- **Items to verify** (section 15): facts about third-party APIs (wrapt, autowrapt, CPython 3.15 / PEP 810) that the design relies on but that have **not** been confirmed. Verify each against the actual library source, docs or interpreter before depending on it. Do not invent API names. If something in section 15 turns out to be false, adjust the design and note the deviation.

Suggested build order: (1) repository scaffolding, AGENTS.md/CLAUDE.md and TESTING.md following wrapture (sections 18 and 20), (2) core hook and proxy, (3) config handling and autowrapt bootstrap, (4) test suite, (5) profile mode and report, (6) documentation tree (section 19), packaging and README.

---

## 1. Purpose and background

### 1.1 Problem

Python 3.15 adds explicit lazy imports (PEP 810): a `lazy import x` statement, plus a syntax-free compatibility mechanism, a module-level `__lazy_modules__` list, that makes listed top-level imports lazy while remaining ordinary valid code on older Pythons (where it is an unused list and imports are eager).

Code bases that must still run on older Pythons therefore get no laziness from `__lazy_modules__` there. Developers also lack a good way to discover *which* imports are worth deferring.

### 1.2 What unwrapt is

`unwrapt` is a Python package built on [wrapt](https://github.com/GrahamDumpleton/wrapt) and designed to be injected using [autowrapt](https://github.com/GrahamDumpleton/autowrapt) so that **no application code changes are needed**. It provides:

1. **Shim mode (default):** on Python versions before 3.15, emulate PEP 810 lazy behaviour for **whole-module imports** (`import x`, `import x as y`) by replacing `builtins.__import__` with a hook that returns a wrapt lazy proxy instead of the module. Candidates come from the importing module's own `__lazy_modules__` and/or an external JSON config.
2. **Profile mode (`UNWRAPT_PROFILE`):** record import edges and timings for a real run and produce a report that guides a human or an AI to the imports worth making lazy, with clear flags for what can be deferred on which route (native 3.15 vs unwrapt on older Pythons).

### 1.3 Name rationale (for README tone)

"unwrapt" plays on gift-wrapping: an import is a present your program unwraps immediately; unwrapt leaves the wrapping on until first use. README copy should keep this light but accurate. A draft README is outlined in section 13.

---

## 2. Goals and non-goals

### Goals

- G1. Emulate PEP 810 `__lazy_modules__` semantics for whole-module imports on Python < 3.15.
- G2. Activate with zero application changes via autowrapt (`AUTOWRAPT_BOOTSTRAP`).
- G3. Allow an external JSON config to mark imports lazy in modules the user cannot edit.
- G4. Reify: after first use, replace the proxy in the importing module's namespace with the real module, to match PEP 810's "no residual overhead" behaviour.
- G5. Provide a profile mode whose report is useful on its own, **including for Python 3.15+ users**, and is explicit about which imports are deferrable on which route.
- G6. Report output usable by humans (text) and by scripts/AI (JSON).
- G7. On Python 3.15+, unwrapt runs in an **external-config-only** mode: only imports listed in the external config are deferred by unwrapt, while native 3.15 lazy imports continue to handle everything the code declares (section 5.7). There is no force switch in v1.
- G8. A documentation tree under `docs/` published on Read the Docs, and AI steering files, following the conventions of the wrapture project (sections 18 to 20).

### Non-goals

- N1. Making `from x import y` lazy in shim mode. This is a fundamental limitation of the approach (section 5.4). It is **reported, not hidden**.
- N2. Making `import a.b as c` lazy in shim mode (same reason; the hook cannot see the `as`).
- N3. Source rewriting or AST transformation. (A possible future alternative design, section 14.)
- N4. Replacing, disabling or competing with native 3.15 lazy imports. On 3.15+ unwrapt never reads `__lazy_modules__` and does not switch native laziness off. A force mode that would do so was considered and deliberately dropped for v1 (section 14).
- N5. Automatically editing user source code. Profile mode only reports.
- N6. Python versions before 3.12. The minimum supported Python is **3.12**, aligned with wrapture. The shim therefore covers Python 3.12 to 3.14; on 3.15+ only the external-config-only mode applies. (wrapt itself supports older versions, but unwrapt deliberately does not.)

---

## 3. Terminology

- **Importer:** the module whose namespace executes an `import` statement (identified by `globals["__name__"]`).
- **Imported:** the module name passed to `__import__`.
- **Edge:** one (importer, imported) import event.
- **Deferral / lazy:** returning a proxy so the real import happens on first use.
- **Reification:** replacing the proxy object in the importer's namespace with the real module once resolved.
- **Cumulative time:** wall time for an import call including all nested imports.
- **Self time:** cumulative time minus time spent in nested import calls made through the hook.
- **Native route:** Python 3.15+ lazy imports. **unwrapt route:** shim mode on older Pythons.

---

## 4. Architecture overview

```
src/unwrapt/
    __init__.py      # __version__ (single source of the version, 12.1); public API: install(), is_installed();
                     # imports stay inert: no hook installed on import (see 6.1)
                     # (only when used as an autowrapt bootstrap, see 6.1)
    _config.py       # env var parsing, JSON config loading
    _hook.py         # shim mode __import__ replacement, proxy creation, reification
    _profile.py      # profile mode __import__ replacement, edge recording
    _report.py       # aggregation, status computation, text and JSON rendering
    _compat.py       # Python version gating, 3.15 behaviour switches
    bootstrap.py     # autowrapt entry: installs the hook on import (6.1)
    py.typed
tests/
pyproject.toml
README.md
```

### 4.1 Typing (required)

All code MUST have type hints, as the AI steering files (`AGENTS.md`, section 20) also require:

- Every function, method and public or private module-level name that a checker cannot infer is annotated; the package ships a `py.typed` marker and works for downstream users of a type checker.
- The package MUST pass the type checker, with the same strictness and configuration that wrapture uses (read wrapture's `pyproject.toml`, section 18.3), and CI runs it.
- Use modern Python 3.12 syntax: `X | None`, built-in generics (`list[str]`, `dict[str, frozenset[str]]`), `collections.abc` types, and PEP 695 `type` aliases where they help. No `from typing import List, Optional` style.
- Avoid `Any` unless unavoidable, and comment why where used. The one expected exception is the lazy proxy returned from the `__import__` hook, which is not a real `ModuleType`: confine the `typing.cast` to a single, commented place.
- The hook signature is typed to mirror `builtins.__import__`, for example `(name: str, globals: Mapping[str, object] | None = None, locals: Mapping[str, object] | None = None, fromlist: Sequence[str] | None = (), level: int = 0) -> ModuleType`.
- The report and JSON schema (8.8) are described with `TypedDict` (or dataclasses with a serialiser) so the structure is checked and self-documenting; the docs' `ai-assisted-tuning` page references the same definitions.
- Tests are typed to whatever extent wrapture's tests are; follow its convention.

Mode selection happens once, in `install()`:

| Condition | Result |
| --- | --- |
| `UNWRAPT_PROFILE` set | Profile hook installed. Deferral disabled (section 8.1). |
| Python >= 3.15, external config present | Shim hook installed in **external-config-only** mode (5.7). |
| Python >= 3.15, no external config | Nothing installed (silent no-op; one debug line if `UNWRAPT_DEBUG`). Native handles `__lazy_modules__`. |
| Python < 3.15 | Shim hook installed; candidates from `__lazy_modules__` and the external config (or the config only, if `UNWRAPT_CONFIG_ONLY` is set). |

Profile mode and shim mode are **mutually exclusive in one process** by design (profiling an already-deferred program measures something different).

---

## 5. Shim mode — normative behaviour

### 5.1 Hook installation

- `install()` MUST be idempotent.
- It MUST capture the current `builtins.__import__` at install time and chain to it, so other installed import wrappers (APM agents, etc.) keep working.
- It MUST replace `builtins.__import__` with a plain function, not a `wrapt` function wrapper, to minimise per-import overhead (every import statement in the process passes through it).
- The replacement MUST accept the standard signature `(name, globals=None, locals=None, fromlist=(), level=0)` and be safe when called with keyword arguments.

### 5.2 When an import is deferred

An import call is deferred only if **all** of the following hold:

1. `level == 0` (absolute import).
2. `fromlist` is empty/falsy (plain `import x`, not `from x import ...`).
3. `globals` is not `None`.
4. `locals is globals` (module-level statement; function bodies pass `None`, class bodies pass the class namespace). **Verify on 3.13+** (PEP 667 changed frame locals).
5. `name not in sys.modules` (already-loaded modules are returned normally; nothing to defer).
6. The module is a candidate (5.3).

Otherwise the call MUST be passed through to the original `__import__` unchanged.

### 5.3 Candidate determination

A name is a candidate for importer `globals` if either:

- `globals.get("__lazy_modules__")` is a non-string container that contains `name` (exact match by default; **never consulted on Python 3.15+**, 5.7), or
- the external config (section 7) lists `name` for `globals["__name__"]`.

Notes:

- `__lazy_modules__` is read **at call time** from the importer's globals, so, as in PEP 810, it must be assigned before the imports it governs.
- `__lazy_modules__` may be a list, tuple, set or frozenset; membership via `in` works for all. If profiling shows linear scans matter, cache a frozenset keyed on the list's identity.
- **Matching rule:** the exact matching semantics of PEP 810 (exact name vs. parent-package matching) are **unverified** (section 15). Mirror whatever the PEP specifies so source behaves identically on 3.15 and older versions. Until verified, use exact match and document it.

### 5.4 Returned object and what cannot be deferred

The hook returns a `wrapt.LazyObjectProxy` (or equivalent lazy proxy; see section 15 for API) that on first use:

1. Calls `importlib.import_module(name)` (full dotted name).
2. Obtains the object `import name` would have bound: `sys.modules[name.partition(".")[0]]` (CPython's `__import__` returns the top-level package when `fromlist` is empty).
3. Reifies (5.5).
4. Returns that module as the proxy target.

Consequences (MUST be documented, not hidden):

- **`from x import y`** is never deferred: `IMPORT_FROM` does `getattr` on the returned object immediately, which would force resolution.
- **`import a.b as c`**: CPython 3.7+ compiles this to `IMPORT_NAME a.b` followed by `IMPORT_FROM b`; the `getattr` forces resolution, so it is effectively eager. The hook cannot distinguish `import a.b` from `import a.b as c`.
- **`import a.b.c`** binds `a`; the proxy therefore stands in for the top-level package while the resolve step imports the full dotted name.
- **`try/except ImportError`** context is invisible to the hook. Listing a guarded optional dependency moves its `ImportError` to first use. Documented as "don't list those".
- Strict C-level module checks on the proxy may fail; `isinstance(x, types.ModuleType)` works via `__class__`. `x is sys.modules["x"]` is false before reification.

### 5.5 Reification

On first resolve, the implementation SHOULD scan the importer's globals dict and replace every entry whose value `is` the proxy with the real module:

```python
for key, value in list(caller_globals.items()):
    if value is proxy:
        caller_globals[key] = module
```

- Cost is one scan per proxy, at first use.
- Only the namespace where the import statement ran is fixed. Proxies copied elsewhere before first use (for example `from mod import json` in another module, or `x = json`) remain proxies and still work, with small overhead.
- Resolve MUST be idempotent and safe if two threads trigger it concurrently (verify wrapt's behaviour, section 15).
- README MUST NOT claim namespace rewriting unless implemented as above.

### 5.6 Informative sketch

```python
import builtins, importlib, json, os, sys
import wrapt

_original_import = builtins.__import__

def _make_proxy(name, caller_globals):
    def resolve():
        importlib.import_module(name)
        module = sys.modules[name.partition(".")[0]]
        for key, value in list(caller_globals.items()):
            if value is proxy:
                caller_globals[key] = module
        return module
    proxy = wrapt.LazyObjectProxy(resolve)   # verify API
    return proxy

def _lazy_aware_import(name, globals=None, locals=None, fromlist=(), level=0):
    if (level == 0 and not fromlist and globals is not None
            and locals is globals and name not in sys.modules
            and _is_candidate(name, globals)):
        return _make_proxy(name, globals)
    return _original_import(name, globals, locals, fromlist, level)
```

### 5.7 External-config-only mode (Python 3.15+)

Purpose: on Python 3.15+ native lazy imports already handle `lazy import` statements and `__lazy_modules__`. unwrapt's job there is narrower: let a user defer **additional** imports, listed in the external config file, in modules that are not declared lazy. This allows trying candidate lists (for example from profile mode) without editing source, while native keeps handling everything the code declares.

Rules:

1. On Python >= 3.15 the **only** candidate source is the external config file (`UNWRAPT_CONFIG`). The importer's `__lazy_modules__` is **never consulted**, because native handles it. Supplying the config is itself the opt-in; there is no force variable.
2. If no config file is given, or it is empty or unreadable, unwrapt installs nothing on 3.15+ (no hook, no overhead). With `UNWRAPT_DEBUG` it logs one line saying why. It MUST NOT warn otherwise, because running the bootstrap on 3.15 with no config is a normal, harmless setup.
3. If a config entry names an import that the importer already makes lazy natively (listed in its `__lazy_modules__`), unwrapt MUST leave it to native and SHOULD report the overlap in debug output. Entries covered by an explicit `lazy import` statement leave no trace in the module globals and cannot be detected this way; whether they are a problem depends on how native reification interacts with `__import__` (unverified, section 15.8). Until verified, document that config entries should not duplicate names the code already imports with `lazy import`.
4. All other shim rules apply unchanged (5.1 to 5.5): same eligibility checks, same proxy, same reification, same limits (`from` imports and `import a.b as c` remain eager under unwrapt).
5. Debug output (`UNWRAPT_DEBUG`) SHOULD state the active mode once at start-up, for example `unwrapt: external-config-only mode (Python 3.15)`.
6. unwrapt does not call `sys.set_lazy_imports` or otherwise change native behaviour.

`UNWRAPT_CONFIG_ONLY=1` MAY also be offered on Python < 3.15 to ignore `__lazy_modules__` and use only the config file. It gives an A/B switch for experiments on any version. On 3.15+ the behaviour is always config-only.

Interaction with native lazy imports (hook calls on reification, filters) is unverified; see section 15.

---

## 6. Activation

### 6.1 Autowrapt bootstrap

Usage to support:

```
AUTOWRAPT_BOOTSTRAP=unwrapt python app.py
```

- `AUTOWRAPT_BOOTSTRAP=unwrapt` MUST result in `install()` running, **without** importing the `unwrapt` package having that side effect: the version is read from `unwrapt/__init__.py` at build time (12.1) and `import unwrapt` must stay inert. Put the install-on-import code in a separate module (for example `unwrapt/bootstrap.py`) and have autowrapt reach it by whichever mechanism applies: an entry point in the group autowrapt uses (so the short name `unwrapt` works), or a dotted module name (`unwrapt.bootstrap`). The exact autowrapt loading mechanism was described from memory; **verify against the autowrapt README/source**, and look at how wrapture arranges for `AUTOWRAPT_BOOTSTRAP=wrapture` to work, then mirror it where it does not conflict with the inert-`__init__` rule. Support the short name `unwrapt` for users if at all possible.
- `install` SHOULD accept an ignored positional argument so it can double as a wrapt post-import-hook callable (for example keyed on `builtins`) if that route is used.
- The hook should be in place before application imports. `site` processes autowrapt's `.pth` early; anything already in `sys.modules` by then is eager by definition.

### 6.2 Environment variables

| Variable | Mode | Meaning |
| --- | --- | --- |
| `UNWRAPT_CONFIG=path` | shim | JSON file of extra lazy candidates (section 7). On Python >= 3.15 this is what activates unwrapt |
| `UNWRAPT_DEBUG=1` | shim | Log each deferred import to stderr: `unwrapt: deferring 'json' in myapp.web` |
| `UNWRAPT_CONFIG_ONLY=1` | shim | Ignore `__lazy_modules__`; use only the external config (always the behaviour on Python >= 3.15) |
| `UNWRAPT_PROFILE=1` | profile | Enable profile mode (section 8) |
| `UNWRAPT_PROFILE_OUTPUT=path` | profile | Report destination; `%p` expands to PID |
| `UNWRAPT_PROFILE_FORMAT=text\|json` | profile | Default `text` |
| `UNWRAPT_PROFILE_MIN_MS=n` | profile | Hide edges with cumulative time below n ms |
| `UNWRAPT_PROFILE_PACKAGES=a,b` | profile (optional) | Restrict candidate rows to importers under these top-level packages (treat other importers as "not editable") |

Invalid values SHOULD produce a single clear warning on stderr and fall back to defaults; unwrapt MUST NOT crash the host application at start-up.

---

## 7. External configuration

JSON mapping importer module name to a list of module names to defer:

```json
{"thirdparty.pkg.client": ["numpy", "pandas"]}
```

- Loaded once at `install()`; converted to `{str: frozenset}`.
- Unioned with `__lazy_modules__` from the importer (either source makes a name a candidate).
- A missing or unreadable file: warn once, continue without it.
- Out of scope for v1 but worth leaving room for: wildcard importer names, a config schema version key.

---

## 8. Profile mode — normative behaviour

### 8.1 Mode behaviour

- Installs a recording `__import__` hook **instead of** the shim hook. No deferral occurs.
- On Python 3.15+, the profiler MUST also ensure native lazy imports are disabled for the run (otherwise it measures an already-lazy program), or detect and clearly warn that they are active. The mechanism (`-X lazy_imports=...`, `PYTHON_LAZY_IMPORTS`, `sys.set_lazy_imports(...)`) is **unverified** (section 15).
- The report is written at process exit (`atexit`). Worker-process setups (e.g. mod_wsgi daemon processes) may not run `atexit` reliably; `UNWRAPT_PROFILE_OUTPUT` with `%p` is the recommended route.

### 8.2 What is recorded

For **every** import call through the hook (including `sys.modules` cache hits), record an edge:

| Field | Source |
| --- | --- |
| `id` | sequential edge number |
| `parent_id` | `id` of the import call in progress when this one was made (top of the call stack), or null for an outermost import; this is what lets the report build import chains and the import tree |
| `importer` | `globals["__name__"]` (None if unavailable) |
| `imported` | `name` |
| `kind` | `"from"` if `fromlist` non-empty, else `"import"` |
| `level` | `"module"` if `locals is globals`; `"function"` if `locals is None`; else `"class"` (verify on 3.13+) |
| `line` | caller frame line number (profile mode only; adjust frame depth for hook wrapper layers) |
| `loaded` | whether `len(sys.modules)` grew during the call |
| `cum_ms` | wall time of the call |
| `self_ms` | `cum_ms` minus time in nested hook calls (maintain a stack of child-time accumulators) |
| `eager_importers` | derived at report time (see 8.4) |

Cache-hit edges are needed to compute "shared" status, but only edges with `loaded=True` carry cost.

Optional enhancement: use `linecache` on the recorded line to detect `import a.b as c` and annotate dotted-`as` edges precisely; otherwise mark dotted edges with a "check source" note.

### 8.3 Why cost is attributed to the first importer only

Only the first import of a module pays the load cost; later importers get cache hits. Deferring the first importer's import therefore **moves** the cost to the next eager importer unless all eager importers are deferred. This is why "shared" status matters and why rows must show the other eager importers.

### 8.4 Derived data

- **Per candidate edge:** cumulative and self time; the other modules that also import the same module (any edge, loaded or cache hit) and are not already lazy.
- **Heavy modules:** per imported module, self time (sum if imported via multiple loads, though normally one).
- **By importer:** per importer, sum of `cum_ms` of its `loaded` module-level edges.
- **Total import time:** sum of top-level (outermost) hook call elapsed times.
- **Import tree and chains:** edges linked by `parent_id` form a tree. For each heavy module, the **chain** is the path of loaded edges from an outermost import down to the edge that loaded it. A chain is a list of places where the load could be cut.
- **Best cut per chain:** the outermost link on the chain that is deferrable on the route(s) being considered and whose deferral is not undone by other eager importers of modules in its subtree (see "Non-additivity" below). Deferring an outer link removes the whole subtree beneath it, so the outermost safe link saves the most.
- **Summary figures:** total import time, number of modules loaded, number of edges, the single best cut overall, and a conservative estimated saving (below).

**Non-additivity (MUST be respected by every figure the report derives):** edge cumulative times **nest**. If A imports B imports C, `cum(A)` already contains `cum(B)` and `cum(C)`. The report MUST NOT sum `cum_ms` across edges that are ancestors/descendants of each other. The estimated saving for a set of deferred edges is the sum of `cum_ms` of the *outermost* selected edges only, minus the time of any module in their subtrees that other, non-deferred eager importers would load anyway (that cost moves, it does not disappear; section 8.3). Label the figure an estimate.

### 8.5 Ranking

Primary ranking for candidates: **cumulative time**, descending. Self time is shown alongside to explain cost and is the sort key only for the separate "heavy modules" section. Rationale: the saving from deferring one import line is its cumulative time; a thin wrapper that pulls in a heavy dependency has near-zero self time but is the best candidate.

### 8.6 Deferrability columns (route-aware status)

Do **not** use a single "blocked" status. A limit of the shim is not a property of the code; on 3.15 those imports are fine. Report two columns:

| Import form | Native (3.15+) | unwrapt (older Python) |
| --- | --- | --- |
| `import x`, `import x as y` | yes | yes |
| `import a.b` | yes | yes |
| `import a.b as c` | yes | **no** (footnote 1) |
| `from x import y` | yes | **no** (footnote 1) |
| function-level import | n/a (footnote 2) | n/a |
| class-level import | not eligible | not eligible |

Footnote 1: unwrapt hands back a lazy proxy; `from x import y` and `import a.b as c` fetch an attribute immediately, forcing resolution. Saving is real on older Pythons only after a code rewrite (for example `import x` then `x.y`).
Footnote 2: function-level imports are already deferred until the function runs.

Per-row notes: `shared (+N)` (list the N other eager importers) and `already lazy` (listed in `__lazy_modules__` or config).

Rows MUST NOT be dropped because unwrapt cannot handle them. The estimated saving is identical on every route; the columns tell the user which routes are open.

### 8.7 Text report

A summary header followed by four sections, in order:

0. **Summary header:** total import time, modules loaded, edge count, the single best cut, and the conservative estimated saving if every deferrable edge were deferred (non-additive, 8.4).
1. **Candidates:** columns `cum ms`, `self ms`, `imported`, `imported by`, `3.15`, `unwrapt`, `notes`; sorted by `cum ms` descending; rows under `UNWRAPT_PROFILE_MIN_MS` hidden. Footnotes printed beneath.
2. **Heavy modules:** by self time.
3. **By importer:** summed cumulative time of the importer's direct module-level loads; these are the files to edit first.
4. **Import chains:** for each of the heaviest modules (by self time, top N), the chain of imports that loaded it, one link per line with that link's cumulative time and route columns, the best cut marked, and any other eager importers listed. This answers "why is this loaded at start-up, and where is the right place to cut it?", which a flat ranking cannot.

Example summary header and chain:

```
Summary: 1240.5 ms total import time, 187 modules, 412 edges
Estimated saving if every deferrable edge were deferred: 640 ms (conservative, not additive)
Best single cut: mypkg.web -> mypkg.analytics (412.3 ms)

numpy  388.0 ms self
  app.main -> mypkg.web           cum 640.2   3.15 yes  unwrapt yes
  mypkg.web -> mypkg.analytics    cum 412.3   3.15 yes  unwrapt yes   <- best cut
  mypkg.analytics -> numpy        cum 398.1   3.15 yes  unwrapt yes   shared (+2)
```

Example candidates section:

```
 cum ms  self ms  imported         imported by       3.15   unwrapt  notes
  412.3     0.4   mypkg.analytics  mypkg.web          yes     yes
  398.1   388.0   numpy            mypkg.analytics    yes     yes     shared (+2)
  151.0     2.1   requests         mypkg.client       yes     yes
   96.4     0.2   yaml             mypkg.config       yes     no (1)
```

A short "limits of this report" block SHOULD be printed (or documented): the profile cannot see import-time use of the name by the importer (class bases, decorators, default args, annotations without `from __future__ import annotations`), `try/except ImportError` guards, whether code paths run on other workloads, attribution for `importlib.import_module()` and submodule loads inside `from` imports (time is included in the enclosing cumulative figure but gets no row), and per-import timing overhead (compare relative sizes against `python -X importtime`, not absolutely).

### 8.8 JSON report

```json
{
  "schema": 1,
  "unwrapt": "1.0.0b1",
  "python": "3.12.4",
  "total_import_ms": 1240.5,
  "summary": {
    "modules_loaded": 187,
    "edge_count": 412,
    "best_cut": 17,
    "estimated_saving_ms": 640.0,
    "estimate_note": "conservative; edge times nest and are not additive"
  },
  "edges": [
    {
      "id": 17,
      "parent_id": 3,
      "imported": "yaml",
      "importer": "mypkg.config",
      "line": 7,
      "kind": "from",
      "level": "module",
      "loaded": true,
      "cum_ms": 96.4,
      "self_ms": 0.2,
      "deferrable": {"native": true, "unwrapt": false},
      "unwrapt_limit": "from-import",
      "already_lazy": false,
      "other_eager_importers": []
    }
  ],
  "heavy_modules": [{"module": "numpy", "self_ms": 388.0}],
  "chains": [{"module": "numpy", "self_ms": 388.0, "links": [3, 9, 17], "best_cut": 9}],
  "by_importer": [{"importer": "mypkg.web", "cum_ms": 412.3}]
}
```

Field names above are a proposal; keep them stable once released, and bump `"schema"` if the structure changes incompatibly.

### 8.9 Informative sketch of the recording hook

```python
_stack = []     # one [child_time] cell per in-progress import call

def _profiling_import(name, globals=None, locals=None, fromlist=(), level=0):
    before = len(sys.modules)
    cell = [0.0]
    _stack.append(cell)
    start = time.perf_counter()
    try:
        return _original_import(name, globals, locals, fromlist, level)
    finally:
        elapsed = time.perf_counter() - start
        _stack.pop()
        if _stack:
            _stack[-1][0] += elapsed
        _record(name, globals, locals, fromlist, level,
                loaded=len(sys.modules) != before,
                cum=elapsed, self_=elapsed - cell[0])
```

The sketch omits edge ids: assign `id` from a counter and take `parent_id` from the id of the enclosing in-progress call (keep it on the stack alongside the child-time cell) so chains can be built (8.4).

Recording MUST NOT itself trigger imports in a way that recurses into the hook (guard against re-entrancy, and import `time`/`linecache` etc. before installing).

### 8.10 Suggested consumption procedure (for README / AI assistants)

1. Ask the target Python version(s) the code base must support.
2. Take rows deferrable on the required routes, in descending `cum_ms`. For 3.15-only projects use `deferrable.native`; for mixed support take rows true for both and treat `unwrapt_limit` rows as optional rewrites judged on size of saving.
3. For `shared` rows, proceed only if every module in `other_eager_importers` can also be deferred.
4. Before editing, read the importing module's source and check for import-time use of the name and for `try/except ImportError`.
5. Add the module to `__lazy_modules__` (or config file for code you do not own).
6. Re-profile after each batch and compare `total_import_ms`.

This is the short form. The full strategy (goals, workloads, cut-point selection, triage, verification, iteration) is specified in section 19.4 and is the primary documentation of the profile feature.

### 8.11 Comparing runs (MAY for v1)

A small command, for example `python -m unwrapt.report before.json [--compare after.json]`, that re-renders a JSON report as text and diffs two reports (total import time, per-module change, modules newly loaded or no longer loaded). It supports the verify and guard steps of the strategy (19.4) without re-running the application. If omitted from v1, the strategy guide shows the same comparison with a short script over the JSON.
---

## 9. Python version behaviour

| Python | Shim mode | Profile mode |
| --- | --- | --- |
| 3.12 to 3.14 | Active; candidates from `__lazy_modules__` plus config | Active |
| >= 3.15 | External-config-only mode when a config is supplied, otherwise nothing installed (5.7) | Active; must neutralise native laziness (8.1) |

Supported versions: **Python 3.12 and later**, the same floor as wrapture. `requires-python = ">=3.12"`. CI covers 3.12, 3.13, 3.14 and a 3.15 pre-release build, mirroring wrapture's matrix (including any free-threaded entries it has; if unwrapt is tested on free-threaded builds, the first-resolve and reification scan (5.5) need explicit thread-safety tests). The wrapt minimum is wrapture's (2.4.0+) unless the lazy proxy API needs a newer release (section 15.1).

---

## 10. Error handling and safety

- unwrapt MUST NOT prevent the host application starting because of its own configuration errors: warn once to stderr and continue.
- Hook code MUST NOT raise from its own bookkeeping; only the underlying import's exceptions propagate.
- Resolve errors (the real import failing at first use) propagate to the code that touched the proxy, as `ImportError`. The proxy should not cache a failure permanently unless wrapt does; document actual behaviour.
- Thread safety: concurrent first-use of the same proxy must not corrupt state or double-import with inconsistent results (importlib already serialises module imports; verify the proxy layer).
- No network access, no writing files other than the optional report path.

---

## 11. Known limitations (to appear in README)

- `from x import y` and `import a.b as c` stay eager in shim mode.
- Only module-level imports are considered.
- `try/except ImportError` guards are invisible; do not list guarded optional dependencies.
- Already-imported modules are returned as-is.
- Older Pythons import eagerly without unwrapt; never rely on laziness for correctness (import side effects, circular imports that only work lazily, error timing differ).
- `importlib.import_module`, C-API imports and modules imported before bootstrap are unaffected.
- Per-import hook overhead exists for every import statement in the process (small, early exits keep it low).
- Proxies copied elsewhere before first use remain proxies.

---

## 12. Packaging

- `pyproject.toml` with `src/` layout, `py.typed`, `requires-python = ">=3.12"`, and type-check configuration matching wrapture's.
- Dependencies: `wrapt` (default minimum 2.4.0, as wrapture; raise it only if the lazy proxy API needs a newer release, verified per section 15) and autowrapt as a documented companion (runtime dependency decision: autowrapt is only needed for injection, so consider an extra, for example `unwrapt[autowrapt]`, versus a hard dependency).
- Entry point registration for autowrapt discovery if applicable (section 6.1).
- Licence: BSD-2-Clause, as wrapture and wrapt (author to confirm).
- Classifiers, project URLs, and a README suitable for PyPI rendering (Markdown, no features PyPI cannot render).
- Version and release naming: see 12.1.
- Reserve/check the name on PyPI/TestPyPI before release; PyPI also normalises `-`, `_`, `.` and rejects near-duplicate names.

### 12.1 Versioning

- **Initial version: `1.0.0b1`** (a PEP 440 beta pre-release), as the first published release. Later pre-releases continue in the same style (`1.0.0b2`, then `1.0.0rc1` if used, then `1.0.0`), matching how wrapture's pre-releases were numbered (`1.0.0a22`, `1.0.0b1`, `1.0.0b4`). Git tags use the bare version with no `v` prefix (`1.0.0b1`), as wrapture's tags do.
- **Single source of truth:** the version is defined once, in `src/unwrapt/__init__.py`, using the **same two-level structure as wrapture** (supplied by the author from wrapture's source):

```python
def _format_version(parts: tuple[str, ...]) -> str:
    base = ".".join(parts[:3])

    if len(parts) == 3:
        return base

    suffix = parts[3]
    return (
        f"{base}.{suffix}" if suffix.startswith(("dev", "post")) else f"{base}{suffix}"
    )


__version_info__ = ("1", "0", "0", "b1")
__version__ = _format_version(__version_info__)
```

  - `__version_info__` is a tuple of strings: three numeric parts plus an optional fourth. A fourth part starting with `dev` or `post` is joined with a dot (`1.0.0.dev3`, `1.0.0.post1`); any other suffix is appended directly (`1.0.0b1`, `1.0.0rc1`). With three parts the version is just `1.0.0`. This gives valid PEP 440 strings and matches wrapture's tags (`1.0.0.dev3`, `1.0.0a22`, `1.0.0b4`).
  - To release, change only `__version_info__`; `__version__` is derived.
  - Both are typed: `__version_info__: tuple[str, ...]` and `__version__: str` (the helper is already annotated). `unwrapt.__version__` is part of the public API; `python -c "import unwrapt; print(unwrapt.__version__)"` works and installs nothing (see 6.1).
  - `pyproject.toml` takes the project version from this file (the `version` field is declared dynamic). **The `pyproject.toml` side was not supplied and must be copied from wrapture's `pyproject.toml`** (section 18.3): the `dynamic = ["version"]` declaration and the backend table that reads the version. Note the constraint this creates: because `__version__` is computed by a function rather than a literal string, the backend must be one that can read it by evaluating or importing the module (for example setuptools' `attr` mechanism) and not one that only pattern-matches a literal `__version__ = "..."` line. Use whatever wrapture uses; do not substitute another scheme (`importlib.metadata`, VCS-derived versions, a separate `_version.py`) unless wrapture does.
  - **Build-time import hazard:** if the backend imports `unwrapt` to read the version, any side effects in `__init__.py` run at build time, when wrapt may not be installed. Therefore importing `unwrapt` MUST NOT install the hook or import wrapt at module level (see 6.1). Keep `__init__.py` free of side effects beyond defining the version and the lightweight public names (import heavier submodules inside functions), or confirm how wrapture avoids this.
- The profile report's JSON includes `"unwrapt": "<__version__>"` so a report can be tied to the version that produced it (8.8).
- Release process: bumping `__version__`, tagging, and the `build-test-release.yml` flow follow wrapture's (18.2). If wrapture's workflow verifies that the tag equals the package version, do the same.
- While at `1.0.0bN`, the README carries a status note modelled on wrapture's (pre-releases are published to PyPI, a plain `pip install unwrapt` picks up the latest pre-release, and small API changes are still possible before `1.0.0`), and the docs `release-notes` page opens with the `1.0.0` section that accumulates until the final release.

---

## 13. README outline

1. Title and tagline: *Don't open it until you need it.* Gift-wrapping framing: every `import` is a present your program unwraps immediately; unwrapt leaves the wrapping on until first use.
2. Relationship to PEP 810 and wrapt/autowrapt; "works without changing your application code".
3. How it works: `__lazy_modules__` example; first use unwraps; proxy swapped for the real module (only if implemented per 5.5); on 3.15+ the interpreter handles `__lazy_modules__` natively and unwrapt only applies the external config.
4. Installation and use: `pip install unwrapt`; `AUTOWRAPT_BOOTSTRAP=unwrapt python app.py`.
5. Wrapping things you can't edit: JSON config, `UNWRAPT_CONFIG`.
6. Peeking at the label: `UNWRAPT_DEBUG`.
7. What it can't unwrap early: section 11.
8. Finding what is worth wrapping: `UNWRAPT_PROFILE`, in a few lines, with a prominent link to the strategy guide (`choosing-what-to-defer`) as the way to turn the report into decisions; ranking by cumulative time, self time explained; the two route columns and footnotes; JSON output and the AI consumption procedure (8.10); limits of the report.
9. Licence.

Wording must stay accurate over cleverness: every limitation stated in section 11 appears in the README. Mirror the structure of wrapture's README (section 18.4). The README also notes that on Python 3.15+ unwrapt applies only the external config (section 5.7).

---

## 14. Possible future work (out of scope for v1)

- **AST-rewrite variant:** a `sys.meta_path` finder that rewrites only configured importer modules, turning `import x` into a lazy-proxy assignment. Advantages: no process-wide `__import__` overhead, exact `as` handling, awareness of `try/except` and module-level context, possible `from x import y` support via an attribute-level lazy helper. Cost: `.pyc` cache handling (bypass or key by config), more complexity.
- Static pre-check integration (flake8-lazy, Lifeguard) to validate config and flag unsafe candidates.
- Honouring the external config on 3.15+ via `sys.set_lazy_imports` with a filter (API shape unverified).
- `--by-importer` grouping and filtering options in the report.
- Config wildcards and schema versioning.
- **Force mode:** a switch to run the full shim (including `__lazy_modules__`) on 3.15+ by first disabling native lazy imports (for example via `sys.set_lazy_imports`), mainly so the same test suite can exercise the shim there. Dropped for v1 because it is unclear whether native can be fully disabled and how native reification interacts with `__import__`. Revisit after the checks in section 15.

---

## 15. Items to verify before relying on them

These were stated from memory during design and are **not confirmed**:

1. **wrapt lazy API:** exact name and signature of `wrapt.LazyObjectProxy` and `wrapt.lazy_import`; whether the proxy takes a resolve callback as in the sketch; behaviour on repeated resolve and on resolve failure; thread-safety of first resolve; minimum wrapt version providing it. If the callback form does not exist, implement the proxy differently (for example subclass `wrapt.ObjectProxy` with a lazy target) while keeping reification.
2. **autowrapt loading:** whether `AUTOWRAPT_BOOTSTRAP` names an importable module, an entry-point name in an `autowrapt.bootstrap` group, or both; adapt section 6.1.
3. **PEP 810 matching rule for `__lazy_modules__`:** exact name versus parent-package matching, and scope rules; align the shim.
4. **3.15 controls:** exact spelling and semantics of `-X lazy_imports=...`, `PYTHON_LAZY_IMPORTS`, `sys.set_lazy_imports(...)`, and whether reification on 3.15 calls `__import__` in a way that would confuse the profiler.
5. **`locals is globals` test** for "module-level only" on all supported versions, in particular 3.13+ (PEP 667) and class-body behaviour.
6. **Bytecode for `import a.b as c`** on each supported version, 3.12 to 3.15 (assumed `IMPORT_NAME a.b` then `IMPORT_FROM b`).
7. **Licence** and the final package name availability on PyPI.
8. **Hook interaction with native lazy imports (3.15+):** whether reification of a native lazy import calls `builtins.__import__` (and with what `globals`/`locals`), whether native lazy imports bypass the hook entirely until reified, and whether `sys.set_lazy_imports` filters interact. This decides whether external-config-only mode (5.7) needs extra overlap handling beyond skipping names declared in `__lazy_modules__`. Also check whether native lazy imports can be switched off (`-X lazy_imports=...`, `PYTHON_LAZY_IMPORTS`, `sys.set_lazy_imports(...)`, a possible "none" mode and whether it affects explicit `lazy import`): profile mode needs this (8.1), and it is the prerequisite for any future force mode (section 14).
9. **wrapture conventions (including the `pyproject.toml` side of version handling and how `AUTOWRAPT_BOOTSTRAP=wrapture` is arranged, 12.1 and 6.1):** the contents of wrapture's `AGENTS.md`, `CLAUDE.md`, `TESTING.md`, `Justfile`, `.readthedocs.yaml`, `pyproject.toml`, CI workflow and `docs/conf.py` were **not readable** when this spec was written (only the repository listing and README were). Section 18 to 20 are inferences from that; read the real files and follow them where they differ.

---

## 16. Test plan

Use `pytest`. Where subprocesses are needed (hook installation is process-global), run them in subprocesses with controlled env vars.

### Shim mode

- `__lazy_modules__ = ["json"]; import json` leaves `"json" not in sys.modules` until first attribute access (use a module guaranteed not to be preloaded, or a purpose-built temp module recording its import).
- After first use, the importer's global is the real module (`type(json) is types.ModuleType`).
- `import x as y` stays lazy and reifies under alias `y`.
- `import a.b.c` binds the top package lazily; resolve imports the full dotted name.
- `import a.b as c` and `from x import y` are eager (documented behaviour).
- Function-level and class-level imports are never deferred.
- Name already in `sys.modules` is returned unchanged.
- Name not in `__lazy_modules__` and not in config is eager.
- `__lazy_modules__` defined *after* the import has no effect (ordering).
- External config adds candidates; union with `__lazy_modules__`.
- Missing/invalid config file warns and continues.
- Chaining: a previously installed `__import__` wrapper is still called for non-deferred imports.
- Idempotent `install()`.
- Reification does not replace unrelated globals; copies elsewhere still work.
- Concurrent first-use from multiple threads resolves once, consistently.
- Failing import (nonexistent module in the list) raises `ImportError` at first use, not at import statement.
- On Python >= 3.15 with no config file, nothing is installed and nothing is warned (debug line only).
- On Python >= 3.15 with a config file: only config entries are deferred; a module's own `__lazy_modules__` entries are not touched by the hook (native handles them).
- A config entry that is also in the importer's `__lazy_modules__` is left to native on 3.15+.
- Debug output states external-config-only mode once.
- unwrapt never calls `sys.set_lazy_imports` or alters native behaviour.
- `UNWRAPT_CONFIG_ONLY` on Python < 3.15 ignores `__lazy_modules__` and uses only the config file.

### Profile mode

- Edges recorded for loaded and cache-hit imports; `loaded` flag correct.
- `self_ms <= cum_ms`; nested imports' time excluded from parent's self time.
- `kind`, `level` (module/function/class) classified correctly.
- Cost attributed to first importer only; `shared` computed from all eager importers; `already lazy` edges flagged.
- Report ordering: candidates by `cum_ms`; heavy modules by `self_ms`; by-importer sums correct.
- `parent_id` links form a correct tree for nested imports; chains for a heavy module list every link from the outermost import down; `best_cut` is the outermost deferrable link not undone by other eager importers.
- Non-additivity: the summary's estimated saving never exceeds total import time and never double-counts nested edges (test with a three-level nest and with a shared module).
- Comparing runs (if implemented): diff of two JSON reports lists changed totals and newly loaded or no longer loaded modules.
- Route columns: `from` edges show native yes / unwrapt no with footnote; rows never dropped.
- `UNWRAPT_PROFILE_MIN_MS` filter; `%p` output path; JSON schema validity.
- Re-entrancy: the recorder does not recurse into the hook.
- Profile mode disables deferral even if `__lazy_modules__` is present.

### Typing

- The configured type checker passes on the package (and tests, to the extent wrapture does) in CI.
- `py.typed` is present in the built wheel.
- A small downstream-style check (a file that imports the public API and is type-checked) passes, so the exported types are usable.

### Versioning

- `_format_version` unit tests: three parts give `1.0.0`; a `b1` suffix gives `1.0.0b1`; `rc1` gives `1.0.0rc1`; `dev3` gives `1.0.0.dev3`; `post1` gives `1.0.0.post1`; the result always parses as a valid PEP 440 version.
- `unwrapt.__version__` equals the installed distribution's metadata version, and both equal `1.0.0b1` for the first release (`__version_info__ == ("1", "0", "0", "b1")`).
- `pyproject.toml` declares the version as dynamic and takes it from `__init__.py` (no second hard-coded version anywhere).
- The version is a valid PEP 440 pre-release; a tag-versus-version check runs in the release workflow if wrapture's does.
- The JSON report carries the producing `unwrapt` version.

### Packaging

- Wheel installs and `python -c "import unwrapt"` works with **no side effects**: it does not install the hook and does not import wrapt (checked in a subprocess by confirming `builtins.__import__` is unchanged). The bootstrap route installs the hook; `unwrapt.install()` is the explicit API for non-bootstrap use.
- End-to-end: `AUTOWRAPT_BOOTSTRAP=unwrapt python sample_app.py` defers a sample import.

---

## 17. Acceptance criteria

1. On Python < 3.15, a sample app with `__lazy_modules__` defers its listed whole-module imports and reifies them on first use, activated only via `AUTOWRAPT_BOOTSTRAP=unwrapt`.
2. `from` imports and `import a.b as c` behave eagerly, and the profile report explicitly flags such edges as not deferrable by unwrapt but deferrable natively on 3.15.
3. Profile mode produces text and JSON reports ranked by cumulative time, with self-time, shared-importer and route columns, and the documented footnotes.
4. All items in section 15 have been verified or the design adjusted and the deviation recorded.
5. README accurately lists every limitation in section 11.
6. The test plan in section 16 passes on the supported Python matrix, including a 3.15 pre-release job.
7. On Python 3.15+, `UNWRAPT_CONFIG=lazy.json` (with the bootstrap) defers only the config-listed imports while the program's own `lazy import` statements and `__lazy_modules__` lists keep native behaviour, and with no config unwrapt installs nothing.
8. The documentation includes the strategy guide (`choosing-what-to-defer`) covering every item in 19.4, a worked example on a sample application that runs in CI, and an AI-assistant page with the prompt template, and the profile report provides the import chains and non-additive summary the guide relies on (8.4, 8.7).
9. All code is type-hinted per section 4.1 and passes the type checker in CI; Python 3.12 is the minimum supported version.
10. The first release is version `1.0.0b1`, defined once in `unwrapt/__init__.py` and read by `pyproject.toml` exactly as wrapture does it (12.1).
11. `import unwrapt` is side-effect free (so the build can read the version from it) and the autowrapt bootstrap works as described in 6.1.
12. The repository has the layout, AI steering files, `Justfile`, `TESTING.md` and Read the Docs configuration described in sections 18 to 20, matching wrapture's conventions, and the docs build cleanly with warnings treated as errors.


---

## 18. Repository layout and conventions (follow wrapture)

### 18.1 Reference projects

The style reference is the author's wrapture project (`https://github.com/GrahamDumpleton/wrapture`, default branch `develop`) and its siblings: wrapt, wrapture-instrumentation (and its aws, postgresql, mysql companions) and the workshop repositories. unwrapt is a sibling of wrapt, autowrapt and wrapture and should read as part of that family.

### 18.2 What was observable when this spec was written

From the public repository listing and README only (file contents were not readable, see 15.9):

| Item | Observed |
| --- | --- |
| `src/wrapture/` | src-layout package |
| `tests/` | test suite directory |
| `docs/` and `.readthedocs.yaml` | documentation on Read the Docs |
| `examples/` and `scratch/` | worked examples; a scratch area |
| `AGENTS.md` and `CLAUDE.md` | AI steering files at the repo root |
| `TESTING.md` | testing guide (wrapt's README describes it as covering Python version-specific test conventions and available test commands) |
| `Justfile` | common tasks, run `just` to list them |
| `pyproject.toml`, `uv.lock`, `.python-version` | uv-managed project (the README shows `uv add`) |
| `.github/` with a `build-test-release.yml` workflow | one workflow for build, test and release; PyPI files carry attestations |
| `LICENSE` | BSD-2-Clause |
| Version | defined once in the package `__init__.py` and read by `pyproject.toml` (the exact mechanism is for the implementer to copy from wrapture, 12.1) |
| Releases | pre-releases tagged like `1.0.0a22`, `1.0.0b4`; GitHub Releases include wheel, sdist and a `SHA256SUMS` file and a standard preview-release note; PyPI receives the pre-releases |
| Default branch | `develop` |

### 18.3 Required first step

Before scaffolding, the implementing session MUST read the following from wrapture (and `TESTING.md`/`Justfile` from wrapt if useful) and mirror their structure, tooling and tone, without copying project-specific content:

- `AGENTS.md`, `CLAUDE.md`, `TESTING.md`, `Justfile`
- `.readthedocs.yaml`, `docs/conf.py`, and the layout of `docs/`
- `src/wrapture/__init__.py` and `pyproject.toml` (how the version is defined and read, build backend, dependency groups, lint and type-check configuration, entry points)
- `.github/workflows/build-test-release.yml` (test matrix, build, release and publish steps)
- `.gitignore`, `.python-version`

Where those files differ from sections 18 to 20 of this spec, **the real files win** and the deviation should be noted in `AGENTS.md`.

### 18.4 README structure (mirror wrapture's)

Bold tagline; Tests and Documentation badges; a short statement of what the package is and that it is a sibling to wrapt, autowrapt and wrapture; a status note while pre-1.0; Installation (`pip install unwrapt` and `uv add unwrapt`); Documentation (link to Read the Docs, start with the getting-started page); At a glance (a short runnable example); What it does; Why; What it is not; How it was built (an honest note that the code and docs were written by an AI assistant under the author's direction, linking the docs page); Requirements (Python 3.12+, wrapt 2.4.0+ or as verified); Issues; License.

"What it is not" for unwrapt: not a replacement for PEP 810 (on 3.15+ it only applies the external config), not a source rewriter, not able to defer `from x import y`.

### 18.5 Deviations that must not be copied blindly

- **Python floor and wrapt minimum: aligned, not deviating.** unwrapt uses wrapture's minimums: Python 3.12+ and wrapt 2.4.0+ (raise the wrapt minimum only if section 15.1 requires it). Confirm both against wrapture's current `pyproject.toml` and README, since they may have changed.
- **Test isolation.** unwrapt installs a process-global `__import__` hook, so tests need subprocess isolation (section 16); `TESTING.md` must say so.
- **CI matrix.** Add a 3.15 pre-release job; mirror wrapture's approach to optional or experimental matrix entries.

---

## 19. Documentation (docs/ for Read the Docs)

### 19.1 Build and hosting

- `.readthedocs.yaml` at the repo root and sources in `docs/`, using the same toolchain as wrapture. wrapt's docs sources are reStructuredText, which suggests Sphinx; confirm from wrapture's `docs/conf.py`.
- The docs build runs in CI with warnings treated as errors.
- Version anchors in a release-notes page (wrapture links to `release-notes.html#version-1-0-0`); GitHub Release notes point at it.
- README carries a Documentation badge.

### 19.2 Page plan

| Page | Content |
| --- | --- |
| `index` | What unwrapt is, the gift-wrapping framing kept brief, links to the rest |
| `getting-started` | Everything on it is pasteable into a Python interpreter (wrapture's convention): a temp module, `__lazy_modules__`, first-use unwrapping, reification |
| `how-it-works` | The `__import__` hook, eligibility rules (5.2), proxy, reification (5.5) |
| `configuration` | Every environment variable once (6.2), including the config-only behaviour on 3.15+ |
| `external-config` | JSON format, union with `__lazy_modules__`, errors |
| `python-3-15` | Relationship to native lazy imports; what unwrapt does and does not do there; **external-config-only mode** with a worked example of testing extra lazy imports while native handles the rest |
| `autowrapt` | `AUTOWRAPT_BOOTSTRAP=unwrapt`, how injection works, ordering relative to `site` |
| `choosing-what-to-defer` | **The strategy guide (19.4)**: a step-by-step method for using the profile report to decide what to convert to lazy imports. This is the main entry point for the profile feature; README and `index` link here first |
| `worked-example` | A complete run of the strategy on a sample application under `examples/`: baseline report, decisions, resulting `__lazy_modules__` and config, re-profile, before and after |
| `profile-mode` | `UNWRAPT_PROFILE`, variables, what is recorded (reference) |
| `reading-the-report` | Column-by-column reference: summary header, candidates, heavy modules, by importer, import chains, the route columns and footnotes (8.6), `shared` and `already lazy` notes (reference; the strategy guide links into it) |
| `ai-assisted-tuning` | The strategy for an AI assistant: the JSON schema (8.8), the procedure (8.10), and a ready-to-use prompt template (19.4.9) |
| `limitations` | Section 11 in full, with the reasons |
| `api` | `install()` and any other public names |
| `faq` | Common questions, for example why `from x import y` stays eager |
| `how-unwrapt-was-built` | Honest account of the AI-assisted process, in the style of wrapture's equivalent page |
| `release-notes` | Per-version notes with stable anchors |

### 19.3 Documentation rules

- Every limitation in section 11 appears in the docs, and the docs never claim behaviour the code lacks (for example namespace reification only if implemented, 5.5).
- Each environment variable is documented in one place (`configuration`) and linked from elsewhere.
- Code examples are tested (doctest or an equivalent harness) so they cannot drift.
- The strategy guide is the primary way into the profile feature. Reference pages explain fields; the guide explains what to **do** with them. Neither is sufficient alone, and the reference pages link back to the relevant guide step.
- The worked example runs in CI against the sample application in `examples/`. The test asserts on report structure and decisions (for example that the expected module appears in a chain and is flagged deferrable), never on absolute millisecond values.
- `examples/` holds small runnable programs: shim demo, external-config demo, profile-mode demo, and a 3.15 external-config-only demo.

### 19.4 The strategy guide (`choosing-what-to-defer`) — required content

The guide MUST teach a method, not just describe output. It is written for a human first, and is also the basis of the AI-assistant page. Required sections:

**19.4.1 When laziness is worth pursuing.** Start-up dominated workloads benefit most: command-line tools, serverless cold starts, test suites, short-lived workers. For long-running servers the cost moves to first use, so judge whether first-request latency matters. Pre-forking servers that import before forking share the imported code across workers, so deferring can trade shared start-up work for per-worker first-use work; say this plainly and tell the reader to measure. Distinguish **application owners** (control the entry point; use `__lazy_modules__` in their own modules and the external config for third-party code) from **library authors** (should defer their own heavy, optional imports and must not rely on laziness for correctness).

**19.4.2 Set the goal first.** Decide the target Python versions (this selects the route columns: 3.15-only, or mixed with older), the workloads to profile (pure start-up, a typical command or request, the slowest `--help` or health-check path), and a stopping rule (for example stop when remaining candidates each save less than a few percent of baseline).

**19.4.3 Take a baseline.** Run profile mode on each workload several times and keep the JSON of a representative run. Note run-to-run noise so small differences are not mistaken for wins. Remind the reader that timing overhead makes absolute figures run high, so only compare like with like.

**19.4.4 Read the report top-down.** Order of attention: the summary header (how big is the prize), then **heavy modules** (what is expensive in itself), then **import chains** (why it is loaded and where it can be cut), and only then the flat candidate list. Explain why self time identifies the culprit while cumulative time on a chain link identifies the cut, and that edge times nest and are never added together (8.4).

**19.4.5 Choose cut points.** Principles, each with a small diagram or table:
1. Cut as close to the root as is safe: deferring an outer link removes the whole subtree beneath it.
2. Cut in code you control where possible; use the external config for code you do not own.
3. A module only stays unloaded if **every** eager path to it is cut. For `shared (+N)` rows, either defer all the listed importers or accept that the cost moves rather than disappears.
4. Prefer links where the imported name is only used inside functions or methods.
5. Take the largest estimated saving first; re-profile between batches because the next-largest item often changes.

**19.4.6 Triage each candidate (decision table).** For every edge the reader intends to change, answer in order:

| Question | If yes | If no |
| --- | --- | --- |
| Is it a module-level `import x` / `import x as y` (ready on both routes)? | continue | `from x import y` or `import a.b as c`: on 3.15+ continue; on older Pythons either rewrite to `import x` and use `x.y`, or accept the cost, depending on size of saving |
| Is the name used while the importing module itself is being imported (class bases, decorators, default arguments, annotations without `from __future__ import annotations`, module-level calls)? | **leave eager**, or move the use inside a function first | continue |
| Is the import inside `try/except ImportError` (optional dependency)? | **leave eager**: laziness would move the error to first use | continue |
| Does the module have import-time side effects that must happen at start-up (registering handlers or plugins, patching, configuring logging, signal handlers)? | **leave eager** | continue |
| Is the first-use latency acceptable on the path that touches it (a request handler, a latency-critical loop)? | continue | consider warming it explicitly at a chosen point, or leave eager |
| Do all other eager importers (`shared`) also qualify? | **defer** | defer only if the remaining importers can be changed too |

Outcomes are exactly four: **defer**, **rewrite then defer**, **leave eager**, **move into a function instead** (the classic alternative, still valid when the whole feature is optional). The guide explains how to spot each condition in source quickly (what to grep for), and tells the reader the profile cannot see these conditions itself (8.7 limits block).

**19.4.7 Apply.** Code you own: declare the module names in `__lazy_modules__` before the imports they govern (mixed-version projects) or write `lazy import` directly (3.15-only projects). Code you do not own: list entries in the external config (section 7). Explain the route differences once, including that on 3.15+ unwrapt applies only the config (5.7) and native handles `__lazy_modules__`.

**19.4.8 Verify, iterate, guard.**
- Verify: re-profile the same workloads; compare totals (8.11); confirm the target module is no longer loaded at start-up; run the test suite on an older Python (shim) and on 3.15 (native).
- Watch for the cost reappearing: it may now be paid at first use somewhere surprising; profile the first request or command, not just start-up.
- Iterate: second-order effects are normal (another path to the same heavy module appears). Stop at the stopping rule from 19.4.2.
- Guard: keep the baseline JSON (or an import-time budget) in CI so a new eager import of a heavy module is noticed; tie to the compare tool (8.11).
- Anti-patterns to name: deferring everything; deferring cheap imports for no measurable gain; deferring where correctness depends on import order or side effects; adding laziness to silence a circular import.

**19.4.9 AI-assistant prompt template (on `ai-assisted-tuning`).** A ready-to-use prompt and procedure for giving an assistant the JSON report, the target Python versions, the source of the top importing modules, and the triage table above. The assistant MUST be asked to return, per edge: the decision (one of the four outcomes), the evidence from the source that justifies it, and the exact edit (a `__lazy_modules__` line or config entry, or the rewrite). It MUST be told not to recommend deferral where the triage table says leave eager, and that a human reviews and re-profiles after each batch.

---

## 20. AI steering files

### 20.1 Files

- `AGENTS.md` at the repo root as the primary guidance file for AI coding agents.
- `CLAUDE.md` at the repo root for Claude Code. Mirror whatever relationship wrapture uses between the two (a common pattern is a `CLAUDE.md` that imports `AGENTS.md` with `@AGENTS.md` and adds Claude-specific notes); read wrapture's files to see which it uses.
- `TESTING.md` for how to run tests (18.3, 20.3).

### 20.2 Proposed AGENTS.md contents

Adapt to wrapture's format; keep it accurate for the repository as it actually is:

1. What unwrapt is, in a few lines, and where the design spec lives (keep this spec in the repo, for example `docs/` or a top-level design file, and say it is a design record: once code and docs exist they win, and deviations should be noted).
2. Repository layout (section 18.2 style) and common commands via `just`.
3. Tooling and conventions taken from wrapture: dependency management, lint, type-check, test runner, formatting, commit and branch conventions (default branch `develop`). State the supported Python floor (3.12+).
3a. **Type hints are mandatory** on all code (section 4.1): new and changed code must be fully annotated, ship `py.typed`, and pass the project's type check before it is considered done. Prefer modern 3.12 syntax and avoid `Any` without a comment.
4. **unwrapt-specific hard rules:**
   - Never document behaviour that is not implemented; the README, docs and limitations must match the code.
   - Verify any third-party API (wrapt lazy proxy, autowrapt loading, PEP 810 and 3.15 switches) against the real source or interpreter before using it; do not guess names (section 15).
   - The hook must never raise from its own bookkeeping, must chain to any previously installed `__import__`, and must stay cheap on the non-deferred path.
   - Shim mode and profile mode are mutually exclusive in one process.
   - On Python 3.15+, unwrapt never reads `__lazy_modules__` and never alters native behaviour; it applies only the external config, and installs nothing when there is none.
   - Whole-module imports only; `from` imports and `import a.b as c` stay eager and are documented as such.
5. Testing rules: global hook means subprocess isolation, version-specific conventions, the 3.15 pre-release job.
6. Documentation rules (19.3), the requirement to keep the strategy guide (19.4) and worked example in step with the report format, and the requirement to update docs and release notes with behaviour changes.
7. Release process: pre-release tags, GitHub Release, PyPI publishing as wrapture does it.
8. A reminder to update `AGENTS.md` itself when the repository structure or commands change.

### 20.3 Proposed TESTING.md contents

How to run the suite (`just` tasks), the Python version matrix including 3.15 pre-release, which tests need subprocess isolation and why, how external-config-only mode (3.15+) and profile mode are exercised, how to run docs example tests, and any Python version-specific conventions, modelled on wrapt's and wrapture's `TESTING.md`.
