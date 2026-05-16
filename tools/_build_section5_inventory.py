"""Generate governance/section5_derivation_inventory.py — one row per def (all scopes)."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION5_FILES = [
    "order_flow_engine.py",
    "order_flow_live_state.py",
    "order_flow_streaming.py",
    "debug_flow_snapshot.py",
]

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("order_flow_engine.py", "_compute_spread"): (
        "quotes.quote.mark,streaming.MARK",
        "REPLACED",
        "spread_frac mark-denom only; removed bid+ask/2 mid synthesis.",
    ),
    ("order_flow_engine.py", "_resolve_quote_mark"): (
        "quotes.quote.mark,streaming.MARK",
        "PASS_THROUGH",
        "Mark leaf for spread denominator.",
    ),
    ("order_flow_engine.py", "_resolve_bid_ask_prices"): (
        "streaming.BID/ASK,quotes.quote.bidPrice,askPrice",
        "PASS_THROUGH",
        "Bid/ask from stream or REST quote JSON.",
    ),
    ("order_flow_engine.py", "_compute_book_imbalance"): (
        "streaming.book levels",
        "KEEP_DERIVED",
        "Depth imbalance from bid/ask level sizes.",
    ),
    ("order_flow_engine.py", "_compute_top_book_pressure"): (
        "streaming.book,quotes",
        "KEEP_DERIVED",
        "Top-of-book pressure composite.",
    ),
    ("order_flow_engine.py", "_compute_tape_pressure"): (
        "streaming.LAST_PRICE,SIZE",
        "KEEP_DERIVED",
        "Tape pressure from print stream.",
    ),
    ("order_flow_engine.py", "_compute_cum_delta_proxy"): (
        "streaming prints,quotes",
        "KEEP_DERIVED",
        "Cumulative delta proxy when stream partial.",
    ),
    ("order_flow_engine.py", "_compute_options_flow"): (
        "chains.* volume,bidSize,askSize",
        "KEEP_DERIVED",
        "Options flow from chain/stream maps.",
    ),
    ("order_flow_engine.py", "OrderFlowEngine.compute"): (
        "aggregated OF metrics",
        "KEEP_DERIVED",
        "Public OF engine entry; composes sub-metrics.",
    ),
    ("order_flow_live_state.py", "push_level_one"): (
        "streaming.content.* LEVEL_ONE",
        "PASS_THROUGH",
        "Ingests Schwab LEVEL_ONE_EQUITY content item.",
    ),
    ("order_flow_live_state.py", "push_book"): (
        "streaming.book bid/ask levels",
        "PASS_THROUGH",
        "Ingests book level updates into deque.",
    ),
    ("order_flow_live_state.py", "get_stream_volume"): (
        "streaming.TOTAL_VOLUME",
        "PASS_THROUGH",
        "Latest stream totalVolume for symbol.",
    ),
    ("order_flow_live_state.py", "get_stream_chg_pct"): (
        "streaming net change fields",
        "PASS_THROUGH",
        "Stream-derived change percent when present.",
    ),
    ("order_flow_live_state.py", "get_content_for_symbol"): (
        "streaming content deque",
        "PASS_THROUGH",
        "Returns merged stream content for engine.",
    ),
    ("order_flow_live_state.py", "get_top_of_book_sizes._to_int"): (
        "—",
        "NONE",
        "Nested int parse inside get_top_of_book_sizes.",
    ),
    ("order_flow_streaming.py", "_run_stream_loop._async_run._book_handler"): (
        "streaming book events",
        "PASS_THROUGH",
        "Async handler pushes book to live_state.",
    ),
    ("order_flow_streaming.py", "_run_stream_loop._async_run._level_one_handler"): (
        "streaming LEVEL_ONE",
        "PASS_THROUGH",
        "Async handler pushes L1 to live_state.",
    ),
    ("order_flow_streaming.py", "start_order_flow_stream"): (
        "Schwab stream client",
        "PASS_THROUGH",
        "Starts schwab-py stream subscription thread.",
    ),
    ("debug_flow_snapshot.py", "_contracts_from_chain_json"): (
        "chains.*",
        "PASS_THROUGH",
        "Parses option chain JSON for debug snapshot.",
    ),
    ("debug_flow_snapshot.py", "main"): (
        "—",
        "NONE",
        "CLI debug entry; reads persisted snapshots.",
    ),
}

_SCHWAB_API = (
    "safe_get_quote",
    "get_option_chain",
    "stream",
    "push_level_one",
    "push_book",
    "schwab",
)

_MARKET_KW = (
    "quote",
    "bid",
    "ask",
    "mark",
    "spread",
    "book",
    "tape",
    "delta",
    "volume",
    "chain",
    "option",
    "streaming",
    "level_one",
    "last_price",
    "totalvolume",
    "content",
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
    if any(api in body_l for api in _SCHWAB_API):
        return (
            "quotes.*|streaming.*|chains.*",
            "PASS_THROUGH",
            "Schwab stream or API wire path.",
        )
    if any(kw in body_l for kw in _MARKET_KW):
        return (
            "streaming.*|quotes.*|chains.*",
            "KEEP_DERIVED",
            "Order-flow metric from Schwab stream/quote fields.",
        )
    if fn.name in ("_main", "main", "_mock_data", "_log_stream", "_empty_result"):
        return ("—", "NONE", "CLI/mock/diagnostic; no production derivation.")
    if qual.startswith("_run_stream_loop") and "handler" not in qual:
        return ("—", "NONE", "Stream thread lifecycle; no field derivation.")
    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION5_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 5 Schwab-leaf derivation audit inventory (order flow).

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


SECTION5_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION5_FILES = frozenset({")
    for f in SECTION5_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section5_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
