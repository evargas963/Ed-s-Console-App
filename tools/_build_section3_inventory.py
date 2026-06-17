"""Generate governance/section3_derivation_inventory.py — one row per def (all scopes)."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION3_FILES = [
    "market_context.py",
    "market_state.py",
    "math_snapshot_derive.py",
]

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("market_context.py", "_extract_quote"): (
        "quotes.quote|extended|regular.lastPrice,netPercentChange",
        "PASS_THROUGH",
        "Schwab quote hierarchy; pct from netChange when percent leaf absent.",
    ),
    ("market_context.py", "_derive_session"): (
        "—",
        "KEEP_DERIVED",
        "ET session label; no Schwab session_label leaf.",
    ),
    ("market_context.py", "fetch_market_context"): (
        "quotes.*",
        "PASS_THROUGH",
        "Multi-symbol quote fetch via safe_get_quote wrapper.",
    ),
    ("market_context.py", "fetch_market_context._fetch"): (
        "quotes.*",
        "PASS_THROUGH",
        "Nested per-symbol quote fetch inside fetch_market_context.",
    ),
    ("market_context.py", "fetch_market_context._chg_for"): (
        "quotes.quote.netPercentChange",
        "PASS_THROUGH",
        "Nested pct change helper from quote JSON.",
    ),
    ("market_context.py", "_volume_profile_poc_vah_val"): (
        "pricehistory.candles.*",
        "KEEP_DERIVED",
        "Volume profile POC/VAH/VAL; no Schwab profile leaves.",
    ),
    ("market_context.py", "_vwap_bands"): (
        "pricehistory.candles.*",
        "KEEP_DERIVED",
        "VWAP sigma bands from OHLCV bars.",
    ),
    ("market_context.py", "fetch_price_levels"): (
        "pricehistory.candles.datetime,OHLC,volume",
        "REPLACED",
        "Skip candles missing datetime leaf (fail-closed; no .get(datetime,0)).",
    ),
    ("market_context.py", "_build_confluence"): (
        "constituent quote chg_pct",
        "KEEP_DERIVED",
        "Cap-weighted confluence from quote-derived chg_pct inputs.",
    ),
    ("market_context.py", "_build_iwm_confluence"): (
        "sector quote chg_pct",
        "KEEP_DERIVED",
        "IWM sector confluence composite.",
    ),
    ("market_context.py", "proximity_alerts"): (
        "walls/pins levels",
        "KEEP_DERIVED",
        "Distance alerts vs key levels; inputs from upstream math.",
    ),
    ("market_context.py", "proximity_alerts._check"): (
        "level geometry",
        "NONE",
        "Nested distance check helper.",
    ),
    ("market_context.py", "market_context_panel_symbols_excluding_core.add"): (
        "—",
        "NONE",
        "Nested set-add helper for symbol list builder.",
    ),
    ("market_state.py", "derive_zone"): (
        "—",
        "KEEP_DERIVED",
        "Regime taxonomy from bias_signal + net_delta.",
    ),
    ("market_state.py", "_oe_bid_ask_mid"): (
        "chains.*.mark,bid,ask,last",
        "KEEP_DERIVED",
        "OP-006 mark-first mid ladder; bid/ask/2 only when mark+last absent.",
    ),
    ("market_state.py", "_oe_chain_row_snapshot"): (
        "chains.*",
        "PASS_THROUGH",
        "Snapshots Schwab chain contract row fields.",
    ),
    ("market_state.py", "_schwab_days_to_expiration_for_contract"): (
        "chains.*.daysToExpiration",
        "PASS_THROUGH",
        "Reads Schwab DTE leaf when present.",
    ),
    ("market_state.py", "build_market_state"): (
        "ms_dict / price_levels",
        "PASS_THROUGH",
        "Assembles MarketState from server/context outputs.",
    ),
    ("market_state.py", "recommend_option_expression"): (
        "chains.* bid,ask,gamma,delta,OI",
        "KEEP_DERIVED",
        "OE recommendation from chain fields.",
    ),
    ("market_state.py", "_oe_composite_strike_row"): (
        "chains.*",
        "PASS_THROUGH",
        "Aggregates call/put rows at strike from chain JSON.",
    ),
    ("math_snapshot_derive.py", "derive_vwap_side"): (
        "—",
        "KEEP_DERIVED",
        "spot vs vwap side; no Schwab vwap_side leaf.",
    ),
    ("math_snapshot_derive.py", "derive_pressure_trend"): (
        "—",
        "KEEP_DERIVED",
        "DPI trend label; not a Schwab wire field.",
    ),
}

_SCHWAB_API = (
    "safe_get_quote",
    "safe_get_chain",
    "safe_get_price_history",
    "get_price_history",
    "schwab_candles_to_bars",
    "fetch_price_levels",
    "fetch_market_context",
)

_MARKET_KW = (
    "quote",
    "schwab",
    "candle",
    "pricehistory",
    "bid",
    "ask",
    "mark",
    "spot",
    "vwap",
    "chain",
    "volatility",
    "openinterest",
    "strikeprice",
    "datetime",
    "exposure",
    "gamma",
    "gex",
    "net_delta",
    "contracts",
)


def _fn_body(text: str, fn: ast.FunctionDef) -> str:
    end = fn.end_lineno or fn.lineno
    return "\n".join(text.splitlines()[fn.lineno - 1 : end])


def _walk(tree: ast.AST, text: str, class_stack: tuple[str, ...] = (), func_stack: tuple[str, ...] = ()):
    if isinstance(tree, ast.ClassDef):
        for child in tree.body:
            yield from _walk(child, text, class_stack + (tree.name,), func_stack)
    elif isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
        qual = ".".join(class_stack + func_stack + (tree.name,))
        yield qual, tree
        for child in tree.body:
            yield from _walk(child, text, class_stack, func_stack + (tree.name,))
    elif isinstance(tree, ast.Module):
        for child in tree.body:
            yield from _walk(child, text, class_stack, func_stack)


def classify(file: str, qual: str, fn: ast.FunctionDef, body: str) -> tuple[str, str, str]:
    key = (file, qual)
    if key in OVERRIDES:
        return OVERRIDES[key]

    body_l = body.lower()
    if any(api.lower() in body_l for api in _SCHWAB_API):
        return (
            "quotes.*|pricehistory.candles.*|chains.*",
            "PASS_THROUGH",
            "Schwab API or wire JSON ingest path.",
        )
    if any(kw in body_l for kw in _MARKET_KW):
        return (
            "quotes.*|chains.*|pricehistory.candles.*",
            "KEEP_DERIVED",
            "Reads or composes market fields; no single Schwab leaf.",
        )
    if any(x in fn.name.lower() for x in ("color", "style", "badge", "actionable")):
        return ("—", "NONE", "UI presentation helper; no market derivation.")
    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION3_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 3 Schwab-leaf derivation audit inventory (source of truth for tests).

One row per ``def`` (module, class method, nested helper).
Disposition: REPLACED | KEEP_DERIVED | PASS_THROUGH | NONE
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivationRecord:
    file: str
    line: str
    derivation: str
    schwab_leaf: str
    disposition: str
    justification: str


SECTION3_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION3_FILES = frozenset({")
    for f in SECTION3_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section3_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
