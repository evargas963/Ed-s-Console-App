"""Index confluence retired: no weighted_push producer; /api/state keys stay withheld."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_PREFIXES = ("tests/", "archive/")
SKIP_PARTS = frozenset({"archive"})


def test_f39_no_weighted_push_producer_remains(repo_index):
    """T-12/T-13/T-14: no function may assign weighted_push or construct ConfluenceRead with one."""
    found: set[str] = set()
    for relpath, _text, tree in repo_index.items():
        rel = relpath.as_posix()
        if rel.startswith(SKIP_PREFIXES):
            continue
        if any(part in SKIP_PARTS for part in relpath.parts):
            continue
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for t in child.targets:
                        if isinstance(t, ast.Name) and t.id == "weighted_push":
                            found.add(f"{rel}:{node.name}")
                if isinstance(child, ast.Return) and isinstance(child.value, ast.Call):
                    fn = child.value.func
                    name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                    if name == "ConfluenceRead":
                        found.add(f"{rel}:{node.name}")
    assert found == set(), (
        f"retired weighted_push / ConfluenceRead producers reappeared: {sorted(found)}"
    )


def test_f39_no_confluence_key_literal_anywhere_in_server_ast():
    keys = {
        "cf_weighted_push", "cf_label", "cf_color", "cf_dot_green", "cf_dot_total",
        "qqq_cf_weighted_push", "iwm_cf_push", "iwm_holdings_cf_push",
        "iwm_participation_push",
    }
    tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
    hits = [
        (n.lineno, n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in keys
    ]
    assert hits == [], (
        f"server.py names a confluence display key outside the typed mapper: {hits} — "
        "stamp_confluence_display_fields must stay the ONLY faucet (F39/RC-365)")


def test_f39_stamp_is_withheld_not_substituted():
    from market_context import (
        INDEX_CONFLUENCE_RETIRED_REASON,
        MarketContext,
        stamp_confluence_display_fields,
    )

    stamped = stamp_confluence_display_fields(MarketContext())
    assert stamped["cf_weighted_push"] is None
    assert stamped["cf_label"] == "—"
    assert stamped["cf_dot_green"] is None
    assert stamped["cf_dot_total"] is None
    assert stamped["iwm_participation_push"] is None
    assert stamped["cf_unavailable_reason"] == INDEX_CONFLUENCE_RETIRED_REASON
    assert stamp_confluence_display_fields(None)["cf_weighted_push"] is None

    server = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "ms_dict.update(stamp_confluence_display_fields(mkt_ctx))" in server
    import re as _re
    for key in ("cf_weighted_push", "cf_label", "cf_color", "cf_dot_green",
                "cf_dot_total", "qqq_cf_weighted_push", "iwm_cf_push",
                "iwm_holdings_cf_push", "iwm_participation_push"):
        direct = _re.findall(rf'ms_dict\[\s*[\'"]{key}[\'"]\s*\]\s*=', server)
        assert direct == [], (
            f"a second /api/state confluence stamp writes {key!r} directly — the "
            "typed mapper must stay the ONLY faucet (F39/RC-365)")
        dict_form = _re.findall(rf'ms_dict\.update\(\s*\{{[^)]*[\'"]{key}[\'"]', server)
        assert dict_form == [], (
            f"a dict-literal ms_dict.update writes {key!r} outside the typed mapper "
            "(F39/RC-365)")


def test_retired_roster_tables_are_gone():
    import market_context as mc

    for name in (
        "SPY_TOP",
        "QQQ_TOP",
        "IWM_TOP_HOLDINGS",
        "IWM_SECTORS",
        "_build_confluence",
        "_build_iwm_confluence",
        "weighted_push_from_constituents",
        "blend_iwm_weighted_push",
    ):
        assert not hasattr(mc, name), name
