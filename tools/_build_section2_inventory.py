"""
Generate governance/section2_derivation_inventory.py — one row per def (all scopes).
"""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION2_FILES = [
    "server.py",
    "live_market_plane.py",
    "live_decision_bundle.py",
    "live_pipeline_diag.py",
    "live_vs_replay_validation.py",
]

# Explicit classifications (file, qualified_name) -> (leaf, disposition, justification)
OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("server.py", "_fetch_state"): (
        "quotes.quote.mark,bidPrice,askPrice",
        "REPLACED",
        "spread_frac mark-denom only; removed bid+ask/2 mid fallback.",
    ),
    ("server.py", "_build_rest_fast_quote_payload"): (
        "quotes.quote|extended|regular.*",
        "REPLACED",
        "Fast-lane quote parse; mark-denom spread_frac (not bid+ask/2).",
    ),
    ("server.py", "_build_rest_fast_quote_payload._attempt_hook"): (
        "—",
        "NONE",
        "Nested quote-attempt counter hook.",
    ),
    ("server.py", "_CandleAccumulator.tick"): (
        "quotes.quote.totalVolume",
        "KEEP_DERIVED",
        "Poll-synthesized OHLCV from spot ticks + totalVolume delta.",
    ),
    ("server.py", "_CandleAccumulator.seed"): (
        "pricehistory.candles.*",
        "PASS_THROUGH",
        "Seeds from Schwab pricehistory candles; datetime required.",
    ),
    ("server.py", "_CandleAccumulator.get_bars_source"): (
        "quotes.quote.totalVolume",
        "KEEP_DERIVED",
        "Bar provenance label for VWAP path.",
    ),
    ("server.py", "_compute_vwap_from_bars"): (
        "—",
        "KEEP_DERIVED",
        "Typical-price VWAP; no Schwab VWAP leaf.",
    ),
    ("server.py", "_update_rest_cum_delta"): (
        "quotes.quote.lastPrice,lastSize,bidPrice,askPrice",
        "KEEP_DERIVED",
        "REST tape proxy when stream unavailable.",
    ),
    ("server.py", "_safe_get_quote_with_retry"): (
        "quotes.*",
        "PASS_THROUGH",
        "Schwab get_quote wrapper with token retry.",
    ),
    ("live_market_plane.py", "record_from_level_one_equity"): (
        "streaming.content.*.LAST_PRICE,MARK,BID,ASK",
        "PASS_THROUGH",
        "LEVEL_ONE_EQUITY streaming fields; mark-denom spread.",
    ),
    ("live_market_plane.py", "record_quote"): (
        "quotes.*",
        "PASS_THROUGH",
        "Records REST-shaped quote into plane cache.",
    ),
    ("live_market_plane.py", "get_quote"): (
        "live_market_plane row",
        "PASS_THROUGH",
        "Reads cached plane quote row.",
    ),
    ("live_market_plane.py", "merge_into_state"): (
        "live_market_plane row",
        "PASS_THROUGH",
        "Copies plane fields into ms_dict.",
    ),
    ("live_market_plane.py", "apply_l1_live_quote_overlay"): (
        "streaming L1 payload",
        "PASS_THROUGH",
        "Overlays L1 stream quote onto plane.",
    ),
    ("live_market_plane.py", "take_fresh_sse_quote_payload"): (
        "SSE quote payload",
        "PASS_THROUGH",
        "Returns fresh SSE quote if cursor advanced.",
    ),
    ("live_market_plane.py", "_plane_tuple_sig"): (
        "spot,bid,ask",
        "KEEP_DERIVED",
        "Dedup signature for plane tuple.",
    ),
    ("live_decision_bundle.py", "_live_session_label"): (
        "market_hours",
        "KEEP_DERIVED",
        "Session label via market_context.",
    ),
    ("live_decision_bundle.py", "tick_triggers_coherent_refresh"): (
        "spot,vwap_side,zone,session_label",
        "KEEP_DERIVED",
        "Coherence triggers vs stream spot and cached bundle.",
    ),
    ("live_decision_bundle.py", "recompute_nearest_struct_at_spot"): (
        "key levels geometry",
        "KEEP_DERIVED",
        "Nearest wall recompute at stream spot.",
    ),
    ("live_decision_bundle.py", "_key_levels_from_ms_dict"): (
        "ms_dict key levels",
        "KEEP_DERIVED",
        "Extracts level tuples from cached state.",
    ),
    ("live_vs_replay_validation.py", "run_live_vs_replay_validation"): (
        "snapshots.*",
        "PASS_THROUGH",
        "Compares persisted snapshot rows; no live Schwab ingest.",
    ),
    ("live_vs_replay_validation.py", "_replay_one_row"): (
        "snapshots.*",
        "PASS_THROUGH",
        "Replays one snapshot row through pipeline.",
    ),
    ("live_vs_replay_validation.py", "_live_from_row"): (
        "snapshots.*",
        "PASS_THROUGH",
        "Builds live proof dict from snapshot row.",
    ),
}

_SCHWAB_API = (
    "safe_get_quote",
    "safe_get_chain",
    "safe_get_price_history",
    "_safe_get_quote_with_retry",
    "schwab_candles_to_bars",
    "get_price_history",
    "normalize_bar",
    "record_from_level_one_equity",
    "fetch_price_levels",
    "fetch_option_chain",
)

_MARKET_KW = (
    "quote",
    "schwab",
    "candle",
    "pricehistory",
    "bidprice",
    "askprice",
    "lastprice",
    "mark",
    "spot",
    "vwap",
    "spread",
    "chain",
    "totalvolume",
    "openinterest",
    "strikeprice",
    "volatility",
    "merge_into_state",
    "live_market_plane",
    "cum_delta",
    "level_one",
    "streaming",
    "option_chain",
    "contracts_raw",
    "exposure",
    "gamma",
    "gex",
)


def _fn_body(text: str, fn: ast.FunctionDef) -> str:
    lines = text.splitlines()
    end = fn.end_lineno or fn.lineno
    return "\n".join(lines[fn.lineno - 1 : end])


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
            "Schwab API wrapper or wire JSON ingest path.",
        )
    if any(kw in body_l for kw in _MARKET_KW):
        return (
            "quotes.quote|extended|regular.*|chains.*|snapshots.*",
            "KEEP_DERIVED",
            "Reads or composes market fields; no single Schwab leaf.",
        )
    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION2_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 2 Schwab-leaf derivation audit inventory (source of truth for tests).

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


SECTION2_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION2_FILES = frozenset({")
    for f in SECTION2_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section2_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
