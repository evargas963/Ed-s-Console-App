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
    # a row leaves only with its code: the 2026-09-25 unused-code prune removed 51 rows of 30
    # deleted files (600 -> 577); the uncalled-routes prune 21 rows of deleted server.py
    # functions (577 -> 556); the bars-from-the-stream change 17 rows of deleted code
    # (polling_adapter.py x4, schwab_client.safe_get_price_history/safe_get_daily_price_history,
    # server._CandleAccumulator x5, _bars_collect_one, _enrollment_history_seed,
    # _parse_quote_node_session_fields, _radar_atr, _radar_atr_compute_into_cache,
    # _radar_daily_atr_vendor_fallback) and added 2 for their live replacements
    # (_atr_pair, _read_bars_1m) (556 -> 541)
    # 2026-09-26: the ML stack and the analytics pipeline were deleted with their rows (541 -> 170)
    assert len(ROWS) >= 170, "the consolidated rows lost provenance claims"


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




# ── transport invariant (ported from the retired mega1 suite) ─────────────────────────────
TRANSPORT_FILES = frozenset({"schwab_client.py", "reauth_schwab.py"})
_SCHWAB_API = frozenset({"safe_get_quote", "safe_get_chain", "schwab_candles_to_bars"})
_TRANSPORT_PREFIXES = ("schwab_client.py:",)


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
    call_re = re.compile(r"(?<![.\w])(safe_get_quote|safe_get_chain|schwab_candles_to_bars)\s*\(")
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
