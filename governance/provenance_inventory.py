"""THE provenance authority: one row type, one resolver, one root rule (RC-532, 2026-09-07).

THE REQUIREMENT (operator-approved, dual-signed Claude + ChatGPT): every material market-data
and decision-path truth has end-to-end canonical source/derivation provenance. No inventory
or allowlist is required by name; only mechanisms that uniquely and correctly enforce that
requirement survive.

WHAT THIS REPLACES. Four "mega" inventories (2,041 rows in 135 files), a cross-inventory
resolver, a separate allowlist module, a schema module and an every-function section gate.
MEASURED 2026-09-07 before the repair: 1,421 of the rows were NONE bookkeeping (a row per
function saying "no lineage claim"); of the 29 card-contract fields the operator reads, ONE
resolved to a row whose chain closed; the three decision modules the inventories "covered"
(call_engine, prediction_engine, liquidity_value_engine) carried no provenance row at all; no
non-test code read any of it. The machinery proved chain closure for internal Schwab-
derivation helpers and nothing about what the operator sees or decides on.

THE ROOT RULE (dual-signed text, verbatim in substance):
  ROOTS.  A value is a material provenance root iff it crosses B1 or B2.
          B1: it is an argument of a decision-engine entry (ENGINE_ENTRIES).
          B2: it is a field of MarketState, or a payload of a route classified PRODUCER in the
              one route-classification table covering every served route; an unclassified
              route FAILS.
  EXCLUSIONS. A B1/B2 value is excluded only when it cannot change material semantics:
          presentation-only session/transport labels, debug output, formatting, presentation.
          Session/time state, source identity, freshness, admission, policy, vetoes, or any
          state that can alter TRADE/WAIT/AVOID, exposure, a material computed truth, or the
          operator's interpretation is NOT excluded (category CONTROL).
  OWNER.  A root's provenance owner is the function that computes the value. Assemblers,
          serializers, routes, DOM elements and flags that merely carry it are chain members
          or nothing.
  CHAIN.  Every direct or transitive dependency that can determine a root's value, or
          determine which computation / configuration / model release / calibration /
          admission state / artifact is authoritative, is a required chain member. A chain
          closes only at a validated canonical EXTERNAL leaf (Schwab where Schwab is the
          source, or another explicitly approved external source) or at an explicit
          allowlisted INTERNAL source with a stated reason. Allowlisting is a legitimate leaf
          classification, never a shortcut past a traversable dependency.
  ONE FAUCET. A second computation of a root's truth anywhere, client included, is a defect
          at the owner, not a classification.
  LIMITS. Category assignment is reviewed human judgment from a closed vocabulary, and whether
          a DERIVED row's declared dependencies are semantically truthful is not mechanically
          provable. Neither limitation is hidden by pretending enforcement exists.

WHAT IS ENFORCED vs REPORTED (tests/test_provenance_v1.py):
  enforced — the population is complete (every served route classified, every MarketState
             field categorised, every engine entry's arguments listed), every row is
             schema-valid and every producer_ref names a real function and a real row, every
             DERIVED chain closes, every root that declares a producer closes to a leaf, no
             NONE row exists, the transport invariant holds (no direct Schwab call outside a
             transport chain), and the OPEN root list is exact (a root with no producer is
             listed as OPEN by name; an unlisted one fails).
  reported — how many roots are still OPEN (NOT_PROVEN). Structural closure is never
             represented as semantic truth.

Data lives in governance/provenance_rows.py (rows) and governance/provenance_roots.py
(route classes, MarketState field categories and producers, engine-entry arguments).
This module is test-time governance: nothing on the application runtime path imports it.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO = Path(__file__).resolve().parent.parent

# ── rows ───────────────────────────────────────────────────────────────────────────────────
Disposition = Literal["SCHWAB_LEAF", "REPLACED", "DERIVED", "ALLOWLISTED"]
CLOSING = frozenset({"SCHWAB_LEAF", "REPLACED", "ALLOWLISTED"})
DISPOSITIONS = CLOSING | {"DERIVED"}

#: Schwab dictionary path prefixes (the wire JSON families).
SCHWAB_LEAF_PREFIXES = ("chains.", "quotes.", "pricehistory.")
#: Categorical hand-waves that are not leaves.
FORBIDDEN_LEAF_SUBSTRINGS = ("upstream", "ms_dict", "signalinput", "signal_input", "inference",
                             "snapshots.*", "—")
_LEAF_RE = re.compile(r"^(chains\.|quotes\.|pricehistory\.)[a-zA-Z0-9_.*\[\]]+$")


@dataclass(frozen=True)
class Row:
    """One provenance claim about one function: what it IS in the lineage.

    SCHWAB_LEAF  — reads a validated Schwab dictionary path (`schwab_leaf`).
    REPLACED     — a former proxy replaced by the Schwab-native field (leaf).
    DERIVED      — computed from `producer_refs` (each `file:qualified_name`, each a row).
    ALLOWLISTED  — reads an explicitly approved non-Schwab source (`allowlist_id`).
    """

    file: str
    derivation: str
    disposition: str
    schwab_leaf: str | None = None
    producer_refs: tuple[str, ...] = ()
    allowlist_id: str | None = None
    justification: str = ""

    @property
    def ref(self) -> str:
        return f"{self.file}:{self.derivation}"


@dataclass(frozen=True)
class AllowlistEntry:
    """An approved non-Schwab leaf. `kind` EXTERNAL = a canonical external source (vendor,
    exchange/calendar feed); INTERNAL = this system's own clock, config, persistence, auth,
    transport counters or state, with the reason it is a legitimate leaf."""

    id: str
    kind: Literal["EXTERNAL", "INTERNAL"]
    category: str
    reason: str


#: Every allowlisted leaf a row may cite. Ported 2026-09-07 from the retired allowlist module:
#: the 15 entries rows actually cite; the 7 entries no row cited were bookkeeping and are gone.
#: No EXTERNAL leaf is claimed today — the kind exists so an approved external source is
#: represented as a validated leaf, never mislabeled as an internal exception.
ALLOWLIST: tuple[AllowlistEntry, ...] = (
    AllowlistEntry("mega1_schwab_py_client", "INTERNAL", "transport",
                   "constructs the schwab-py HTTP client from the token; wire calls happen in the transport chain"),
    AllowlistEntry("mega1_env_config", "INTERNAL", "config",
                   "reads environment / config values (base URL, timeouts, flags); no market field produced"),
    AllowlistEntry("mega1_session_calendar", "INTERNAL", "clock",
                   "ET clock and session calendar (RTH windows, trading days); the only source of time"),
    AllowlistEntry("mega1_sqlite_internal", "INTERNAL", "internal_state",
                   "reads persisted snapshot / bar rows from the console database, not Schwab wire JSON"),
    AllowlistEntry("mega1_internal_helper", "INTERNAL", "internal_state",
                   "pure helper over already-typed inputs; produces no market field of its own"),
    AllowlistEntry("mega1_live_plane_state", "INTERNAL", "internal_state",
                   "in-process live-plane cache state (last quote, freshness, sequence)"),
    AllowlistEntry("mega1_l1_sse_counters", "INTERNAL", "counter",
                   "SSE / L1 delivery counters and latency observability"),
    AllowlistEntry("mega1_diagnostic_log", "INTERNAL", "internal_state",
                   "diagnostic logging and error capture; not a market field"),
    AllowlistEntry("mega1_filesystem", "INTERNAL", "filesystem",
                   "reads or writes local files (token, diagnostics, reports)"),
    AllowlistEntry("mega2_display_formatter", "INTERNAL", "internal_state",
                   "formats an already-derived value for display; changes no semantics"),
    AllowlistEntry("mega2_internal_helper", "INTERNAL", "internal_state",
                   "pure helper over already-typed inputs; produces no market field of its own"),
    AllowlistEntry("mega2_schwab_stream_l1", "INTERNAL", "transport",
                   "Schwab streaming L1 frame decoder; the streamed fields close at the stream leaf rows"),
    AllowlistEntry("mega2_test_fixture", "INTERNAL", "internal_state",
                   "test-only fixture path; never on the runtime path"),
    AllowlistEntry("mega3_internal_helper", "INTERNAL", "internal_state",
                   "pure helper over already-typed inputs; produces no market field of its own"),
    AllowlistEntry("mega4_governed_stack_contract", "INTERNAL", "config",
                   "reads the governed model-stack contract (feature contract, release identity)"),
    AllowlistEntry("analytics_cache_state", "INTERNAL", "internal_state",
                   "in-process analytics cache freshness (stale / pending-shell / refresh-in-progress): "
                   "a CONTROL truth whose source is the server's own cache clock, not a market field"),
)
ALLOWLIST_IDS = frozenset(e.id for e in ALLOWLIST)


def is_valid_schwab_leaf(path: str | None) -> bool:
    if not path:
        return False
    s = path.strip()
    low = s.lower()
    if any(f in low for f in FORBIDDEN_LEAF_SUBSTRINGS):
        return False
    return bool(_LEAF_RE.match(s)) and s.startswith(SCHWAB_LEAF_PREFIXES)


def row_schema_errors(row: Row) -> list[str]:
    out = []
    if row.disposition not in DISPOSITIONS:
        out.append(f"{row.ref}: disposition {row.disposition!r} is not one of {sorted(DISPOSITIONS)}")
    if row.disposition in ("SCHWAB_LEAF", "REPLACED") and not is_valid_schwab_leaf(row.schwab_leaf):
        out.append(f"{row.ref}: {row.disposition} needs a validated Schwab leaf, got {row.schwab_leaf!r}")
    if row.disposition == "DERIVED" and not row.producer_refs:
        out.append(f"{row.ref}: DERIVED with no producer_refs")
    if row.disposition == "ALLOWLISTED" and row.allowlist_id not in ALLOWLIST_IDS:
        out.append(f"{row.ref}: allowlist_id {row.allowlist_id!r} is not an ALLOWLIST entry")
    for ref in row.producer_refs:
        if ":" not in ref:
            out.append(f"{row.ref}: producer_ref {ref!r} is not file:qualified_name")
    return out


def index(rows) -> dict[tuple[str, str], Row]:
    idx: dict[tuple[str, str], Row] = {}
    for r in rows:
        key = (r.file, r.derivation)
        if key in idx:
            raise ValueError(f"duplicate row {r.ref}")
        idx[key] = r
    return idx


def resolve_chain(ref: str, idx: dict[tuple[str, str], Row], *, stack: tuple[str, ...] = ()) -> None:
    """Raise AssertionError unless `ref` closes at a leaf through DERIVED rows only."""
    if ref in stack:
        raise AssertionError(f"cycle: {' -> '.join(stack + (ref,))}")
    if ":" not in ref:
        raise AssertionError(f"invalid producer_ref (expected file:fn): {ref!r}")
    file, qual = ref.split(":", 1)
    row = idx.get((file, qual))
    if row is None:
        raise AssertionError(f"producer_ref has no row: {ref}")
    if row.disposition in CLOSING:
        return
    if row.disposition != "DERIVED":
        raise AssertionError(f"unexpected disposition {row.disposition!r} at {ref}")
    if not row.producer_refs:
        raise AssertionError(f"DERIVED row has empty producer_refs: {ref}")
    for child in row.producer_refs:
        resolve_chain(child, idx, stack=stack + (ref,))


def closes(ref: str, idx) -> tuple[bool, str]:
    try:
        resolve_chain(ref, idx)
        return True, ""
    except AssertionError as exc:
        return False, str(exc)


# ── the code, read structurally ────────────────────────────────────────────────────────────
def all_functions_in_file(rel: str) -> set[str]:
    """Qualified names of every def / async def in `rel` (Class.method, outer.inner)."""
    src = (REPO / rel).read_text(encoding="utf-8", errors="replace")
    out: set[str] = set()

    def walk(node, classes=(), funcs=()):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, classes + (child.name,), funcs)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.add(".".join(classes + funcs + (child.name,)))
                walk(child, classes, funcs + (child.name,))
            else:
                walk(child, classes, funcs)

    walk(ast.parse(src))
    return out


def served_routes(rel: str = "server.py") -> list[tuple[str, str, str]]:
    """(method, route, handler) for every @app.get/@app.post in `rel`."""
    src = (REPO / rel).read_text(encoding="utf-8", errors="replace")
    out = []
    for n in ast.parse(src).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and d.func.attr in ("get", "post") and d.args
                        and isinstance(d.args[0], ast.Constant)):
                    out.append((d.func.attr, d.args[0].value, n.name))
    return out


def market_state_fields(rel: str = "market_state.py") -> list[str]:
    src = (REPO / rel).read_text(encoding="utf-8", errors="replace")
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "MarketState")
    return [b.target.id for b in cls.body if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name)]


def function_args(rel: str, name: str) -> list[str]:
    src = (REPO / rel).read_text(encoding="utf-8", errors="replace")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return [a.arg for a in n.args.posonlyargs + n.args.args + n.args.kwonlyargs]
    raise LookupError(f"{rel}:{name} not found")


# ── the root rule ──────────────────────────────────────────────────────────────────────────
#: B1 — decision-engine entries. An argument of any of these is a material root.
ENGINE_ENTRIES: tuple[tuple[str, str], ...] = (
    ("call_engine.py", "compute_call"),
    ("call_engine.py", "compute_position_size"),
    ("multi_horizon_decision.py", "compute_multi_horizon_synthesis"),
    ("prediction_engine.py", "compute_prediction"),
    ("decision_gate.py", "evaluate_decision_path_admission"),
)

#: Route classes. PRODUCER routes carry roots of their own (a payload not drawn from
#: MarketState); CARRIER routes serialize MarketState or another producer's payload.
ROUTE_CLASSES = frozenset({"PRODUCER", "CARRIER", "OPERATOR_INPUT", "OPS", "DIAGNOSTIC",
                           "GOVERNANCE", "LOGGER", "PAGE", "STREAM"})
#: Route classes whose payload fields are roots.
ROOT_ROUTE_CLASSES = frozenset({"PRODUCER"})

#: MarketState field categories (closed vocabulary; reviewed human judgment).
FIELD_CATEGORIES = frozenset({
    "MARKET",         # a market-data truth (price, greeks, levels, exposure, vol)
    "DECISION",       # a decision-path truth (bias, call, plan, probabilities, sizing)
    "CONTROL",        # freshness / admission / policy / veto / session state that can change
                      # a decision or the operator's interpretation
    "IDENTITY",       # what is selected (ticker, expiry) — material when it keys a computation
    "PRESENTATION",   # colours, css classes, display strings, labels of an underlying truth
    "DEBUG",          # diagnostics never read by a decision or shown as a truth
})
ROOT_CATEGORIES = frozenset({"MARKET", "DECISION", "CONTROL", "IDENTITY"})


@dataclass(frozen=True)
class Root:
    """A material provenance root and the producer (row ref) that owns it, or OPEN."""

    kind: str          # "field" | "engine_arg" | "route"
    name: str          # MarketState field, engine "file:fn/arg", or route
    category: str
    producer: str | None   # row ref that computes it; None = OPEN (NOT_PROVEN)


def roots(roots_data, idx) -> list[Root]:
    """Assemble every root from governance/provenance_roots.py under the rule."""
    out: list[Root] = []
    for field, (category, producer) in roots_data.MARKET_STATE.items():
        if category in ROOT_CATEGORIES:
            out.append(Root("field", field, category, producer))
    # B2 also covers keys the serializer ADDS to a carried payload outside MarketState (the
    # card's expected-move bands and analytics freshness flags live in server.py, not on the
    # dataclass); they are roots exactly like fields.
    for key, (category, producer) in getattr(roots_data, "PAYLOAD_EXTRAS", {}).items():
        if category in ROOT_CATEGORIES:
            out.append(Root("payload", key, category, producer))
    for (file, fn), args in roots_data.ENGINE_INPUTS.items():
        for arg, producer in args.items():
            out.append(Root("engine_arg", f"{file}:{fn}/{arg}", "DECISION", producer))
    for route, (cls, producer) in roots_data.ROUTES.items():
        if cls in ROOT_ROUTE_CLASSES:
            out.append(Root("route", route, "MARKET", producer))
    return out


def report(rows, roots_data) -> dict:
    idx = index(rows)
    rs = roots(roots_data, idx)
    closed, open_, broken = [], [], []
    for r in rs:
        if r.producer is None:
            open_.append(r.name)
            continue
        ok, why = closes(r.producer, idx)
        (closed if ok else broken).append(r.name if ok else f"{r.name}: {why}")
    return {
        "rows": len(rows),
        "roots": len(rs),
        "closed": len(closed),
        "open": sorted(open_),
        "broken": sorted(broken),
    }
