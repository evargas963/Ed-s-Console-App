"""RC-532 — ONE provenance authority; the root population is complete and every claim is real.

What is ENFORCED here (a red test is a defect, never a number to tune):
  * population: every served route is classified; every MarketState field is categorised; every
    decision-engine entry's arguments are listed and match the code — so "every material truth"
    is a demonstrated set, not an assumed one;
  * rows: schema-valid; every producer_ref names a real function and a real row; no NONE row;
  * closure: every DERIVED row's chain closes at a leaf; every root that declares a producer
    closes; a root with no producer is OPEN by name (the exact list is pinned as data, so an
    OPEN root can neither hide nor silently appear);
  * the transport invariant: no direct Schwab API call outside a chain that reaches transport.
What is REPORTED (printed, never asserted): how many roots are OPEN. Structural closure is not
semantic truth, and the suite never says otherwise.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance import provenance_inventory as P  # noqa: E402
from governance import provenance_roots as R  # noqa: E402
from governance.provenance_rows import ROWS  # noqa: E402

IDX = P.index(ROWS)


# ── rows ───────────────────────────────────────────────────────────────────────────────────
def test_every_row_is_schema_valid_and_none_is_bookkeeping():
    errs = [e for r in ROWS for e in P.row_schema_errors(r)]
    assert errs == [], "\n".join(errs[:20])
    assert all(r.disposition != "NONE" for r in ROWS)
    assert len(ROWS) >= 600, "the consolidated rows lost provenance claims"


def _qualified_defs(tree: ast.AST) -> set[str]:
    out: set[str] = set()

    def _descend(node, classes=(), funcs=()):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                _descend(child,classes + (child.name,), funcs)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.add(".".join(classes + funcs + (child.name,)))
                _descend(child,classes, funcs + (child.name,))
            else:
                _descend(child,classes, funcs)

    _descend(tree)
    return out


def test_every_producer_ref_names_a_real_function_and_a_real_row(repo_index):
    """Sourced from the shared `repo_index` corpus (the one current-tree observation)."""
    trees = {rel.as_posix(): tree for rel, _text, tree in repo_index.items()}
    funcs: dict[str, set[str]] = {}
    missing_fn, missing_row = [], []
    for r in ROWS:
        for ref in list(r.producer_refs) + [r.ref]:
            file, qual = ref.split(":", 1)
            if file not in funcs:
                funcs[file] = _qualified_defs(trees[file]) if file in trees else set()
            if qual not in funcs[file]:
                missing_fn.append(ref)
        for ref in r.producer_refs:
            if tuple(ref.split(":", 1)) not in IDX:
                missing_row.append(ref)
    assert missing_row == [], f"producer_refs with no row: {missing_row[:15]}"
    assert missing_fn == [], f"refs naming no function in the tree: {missing_fn[:15]}"


def test_every_derived_chain_closes_at_a_leaf():
    broken = []
    for r in ROWS:
        if r.disposition != "DERIVED":
            continue
        for ref in r.producer_refs:
            ok, why = P.closes(ref, IDX)
            if not ok:
                broken.append(f"{r.ref} -> {why}")
    assert broken == [], "\n".join(broken[:20])


def test_allowlist_entries_are_used_and_kinds_are_explicit():
    used = {r.allowlist_id for r in ROWS if r.disposition == "ALLOWLISTED"}
    assert used <= P.ALLOWLIST_IDS, sorted(used - P.ALLOWLIST_IDS)
    unused = sorted(P.ALLOWLIST_IDS - used)
    assert unused == [], f"allowlist entries no row cites are bookkeeping: {unused}"
    for e in P.ALLOWLIST:
        assert e.kind in ("EXTERNAL", "INTERNAL") and e.reason.strip(), e


# ── population ─────────────────────────────────────────────────────────────────────────────
def test_every_served_route_is_classified_and_no_ghost_route_is_listed():
    served = {route for _m, route, _h in P.served_routes()}
    listed = set(R.ROUTES)
    assert served - listed == set(), f"served but unclassified: {sorted(served - listed)}"
    assert listed - served == set(), f"classified but not served: {sorted(listed - served)}"
    bad = {r: c for r, (c, _p) in R.ROUTES.items() if c not in P.ROUTE_CLASSES}
    assert bad == {}, bad


def test_every_market_state_field_is_categorised_and_no_ghost_field_is_listed():
    fields = set(P.market_state_fields())
    listed = set(R.MARKET_STATE)
    assert fields - listed == set(), f"MarketState fields without a category: {sorted(fields - listed)}"
    assert listed - fields == set(), f"categorised fields MarketState no longer has: {sorted(listed - fields)}"
    bad = {f: c for f, (c, _p) in R.MARKET_STATE.items() if c not in P.FIELD_CATEGORIES}
    assert bad == {}, bad


def test_every_engine_entry_argument_is_listed_and_matches_the_code():
    for file, fn in P.ENGINE_ENTRIES:
        code = P.function_args(file, fn)
        listed = list(R.ENGINE_INPUTS[(file, fn)])
        assert listed == code, f"{file}:{fn} arguments drifted: code={code} listed={listed}"
    assert set(R.ENGINE_INPUTS) == set(P.ENGINE_ENTRIES)


# ── closure of the roots ───────────────────────────────────────────────────────────────────
def test_every_root_with_a_producer_closes_and_the_open_list_is_exact():
    rep = P.report(ROWS, R)
    assert rep["broken"] == [], "\n".join(rep["broken"][:20])
    # A root without a producer is OPEN (NOT_PROVEN). The exact set is pinned as data in
    # provenance_roots.OPEN_ROOTS so a root cannot go OPEN, or be forgotten, silently.
    assert sorted(rep["open"]) == sorted(R.OPEN_ROOTS), (
        f"OPEN roots changed — newly open: {sorted(set(rep['open']) - set(R.OPEN_ROOTS))[:10]}; "
        f"listed but no longer open: {sorted(set(R.OPEN_ROOTS) - set(rep['open']))[:10]}")
    print(f"\nPROVENANCE: {rep['roots']} roots, {rep['closed']} closed, {len(rep['open'])} OPEN (NOT_PROVEN)")


def test_the_card_contract_fields_are_roots_or_declared_exclusions():
    """The card contract is a CONSUMER contract. Each emitted field points at a MarketState
    root (its api_key); it never becomes a provenance authority of its own."""
    card = json.loads((ROOT / "reports/artifacts/CARD_CONSUMER_CONTRACT_V1.json").read_text(encoding="utf-8"))
    bad = []
    for f in card["fields"]:
        key = f.get("provenance_root")
        if key == "not_emitted" or key == "client_state":
            continue
        if key not in R.MARKET_STATE and key not in R.PAYLOAD_EXTRAS:
            bad.append((f["field_name"], key))
    assert bad == [], f"card fields whose provenance_root is not a root: {bad}"


# ── transport invariant (ported from the retired mega1 suite) ─────────────────────────────
TRANSPORT_FILES = frozenset({"schwab_client.py", "reauth_schwab.py", "polling_adapter.py",
                             "websocket_adapter.py", "sse_adapter.py"})
_SCHWAB_API = frozenset({"safe_get_quote", "safe_get_chain", "safe_get_price_history", "schwab_candles_to_bars"})
_TRANSPORT_PREFIXES = ("schwab_client.py:", "polling_adapter.py:", "websocket_adapter.py:", "sse_adapter.py:")


def _function_at_line(tree: ast.AST, lineno: int) -> str:
    best = ""

    def _descend(node, classes=(), funcs=()):
        nonlocal best
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                _descend(child,classes + (child.name,), funcs)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if child.lineno <= lineno <= child.end_lineno:
                    best = ".".join(classes + funcs + (child.name,))
                    _descend(child,classes, funcs + (child.name,))
            else:
                _descend(child,classes, funcs)

    _descend(tree)
    return best


def _reaches_transport(ref: str, stack=()) -> bool:
    if ref in stack or ":" not in ref:
        return False
    row = IDX.get(tuple(ref.split(":", 1)))
    if row is None:
        return False
    if ref.startswith(_TRANSPORT_PREFIXES):
        return True
    if row.disposition in ("SCHWAB_LEAF", "REPLACED") and row.file in TRANSPORT_FILES:
        return True
    if row.disposition != "DERIVED":
        return False
    return any(_reaches_transport(p, stack + (ref,)) for p in row.producer_refs)


def test_no_direct_schwab_api_call_outside_a_transport_chain(repo_index):
    """Sourced from the shared `repo_index` corpus; scoped to the files that carry rows."""
    corpus = {rel.as_posix(): (text, tree) for rel, text, tree in repo_index.items()}
    files = sorted({r.file for r in ROWS if r.file in corpus})
    call_re = re.compile(r"(?<![.\w])(safe_get_quote|safe_get_chain|safe_get_price_history|schwab_candles_to_bars)\s*\(")
    violations = []
    for rel in files:
        if rel in TRANSPORT_FILES:
            continue
        text, tree = corpus[rel]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
            if name not in _SCHWAB_API or not call_re.search(ast.get_source_segment(text, node) or ""):
                continue
            qual = _function_at_line(tree, node.lineno)
            # A nested helper with no row of its own is judged under its enclosing function's
            # row (the retired suite's parent fallback, minus the NONE row it used to walk).
            while qual and (rel, qual) not in IDX and "." in qual:
                qual = qual.rsplit(".", 1)[0]
            ref = f"{rel}:{qual}"
            if not qual or not _reaches_transport(ref):
                violations.append(f"{rel}:{node.lineno} in {ref} — no chain to Schwab transport")
    assert violations == [], "\n".join(violations)
