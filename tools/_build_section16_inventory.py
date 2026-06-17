"""Generate governance/section16_derivation_inventory.py — external signals."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION16_FILES = sorted(
    [
        "news_sentiment.py",
        "api_pressure.py",
        "event_risk.py",
    ]
)

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("news_sentiment.py", "get_sentiment_features_for_snapshot"): (
        "Finnhub|AlphaVantage",
        "KEEP_DERIVED",
        "Merges external sentiment into snapshot feature dict.",
    ),
    ("news_sentiment.py", "refresh_and_context"): (
        "Finnhub|AlphaVantage",
        "KEEP_DERIVED",
        "Refreshes news/sentiment cache and builds MarketState context.",
    ),
    ("news_sentiment.py", "refresh_and_context_for_ui"): (
        "Finnhub|AlphaVantage",
        "KEEP_DERIVED",
        "UI-bounded refresh path for news/sentiment context.",
    ),
    ("news_sentiment.py", "fetch_finnhub_sentiment"): (
        "Finnhub API",
        "PASS_THROUGH",
        "Finnhub REST sentiment endpoint wrapper.",
    ),
    ("news_sentiment.py", "fetch_finnhub_recent_company_news"): (
        "Finnhub API",
        "PASS_THROUGH",
        "Finnhub company-news REST wrapper.",
    ),
    ("news_sentiment.py", "fetch_alpha_vantage_sentiment"): (
        "AlphaVantage API",
        "PASS_THROUGH",
        "Alpha Vantage sentiment REST wrapper.",
    ),
    ("news_sentiment.py", "_parse_article_datetime"): (
        "Finnhub article datetime",
        "KEEP_DERIVED",
        "Parses external article timestamp; not Schwab pricehistory.",
    ),
    ("api_pressure.py", "record_schwab_http_response"): (
        "HTTP 429 observability",
        "NONE",
        "Records Schwab rate-limit events for UI; no quote field derivation.",
    ),
    ("api_pressure.py", "throttle_ui_payload"): (
        "HTTP 429 observability",
        "NONE",
        "UI payload for recent 429 events; no market-field derivation.",
    ),
    ("event_risk.py", "assess_event_risk"): (
        "macro/earnings calendar",
        "NONE",
        "Static macro/earnings calendar gating; no Schwab ingest.",
    ),
    ("event_risk.py", "session_date_et"): (
        "clock ET",
        "NONE",
        "ET session date helper.",
    ),
}


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
    name_l = fn.name.lower()

    if file == "event_risk.py":
        return ("macro/earnings calendar", "NONE", "Event risk policy hook; no Schwab derivation.")

    if file == "api_pressure.py":
        return ("HTTP observability", "NONE", "Schwab HTTP pressure telemetry only.")

    if name_l.startswith("fetch_"):
        return ("external API", "PASS_THROUGH", "External REST fetch wrapper.")

    if "finnhub" in name_l or "alpha_vantage" in name_l or "av_" in name_l:
        return ("external API", "PASS_THROUGH", "External sentiment/news API call.")

    if name_l.startswith("_http") or name_l.startswith("_load") or "token" in name_l:
        return ("—", "NONE", "HTTP/env helper for external APIs.")

    if "sentiment" in name_l or "headline" in name_l or "merge" in name_l:
        return (
            "Finnhub|AlphaVantage",
            "KEEP_DERIVED",
            "External sentiment/headline derivation for snapshots.",
        )

    if name_l.startswith("_"):
        return ("—", "NONE", "Internal helper; no Schwab market-field derivation.")

    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION16_FILES:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 16 Schwab-leaf derivation audit inventory (external signals).

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


SECTION16_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION16_FILES = frozenset({")
    for f in SECTION16_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section16_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
