#!/usr/bin/env python3
"""
Schwab Field Dictionary Builder — Normalize and classify raw field inventory.

Reads schwab_all_fields_master.txt and schwab_field_inventory_summary.csv,
normalizes field paths (removes symbol prefixes, array indexes, noise),
categorizes fields, and produces a canonical field dictionary.

Run: python schwab_field_dictionary_builder.py
"""

from __future__ import annotations

import csv
import os
import re
from collections import defaultdict
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

INPUT_DIR = Path(
    os.getenv("SCHWAB_INVENTORY_DIR", "schwab_field_inventory")
).resolve()

OUTPUT_DIR = INPUT_DIR  # Same directory for outputs

MASTER_FILE = INPUT_DIR / "schwab_all_fields_master.txt"
SUMMARY_CSV = INPUT_DIR / "schwab_field_inventory_summary.csv"

# Known ticker symbols (from inventory) — strip these prefixes
KNOWN_TICKERS = {"SPY", "QQQ", "AAPL", "NVDA", "IWM", "TSLA", "$VIX"}

# Categories for classification
CATEGORIES = [
    "price", "bid_ask", "size_depth", "volume", "time", "volatility", "greeks",
    "options_chain", "market_hours", "movers", "instrument_fundamentals",
    "streaming_quote", "streaming_book", "chart_bar", "unknown",
]

# Likely use values
LIKELY_USES = [
    "direct_order_flow", "order_flow_proxy", "regime_detection", "key_levels",
    "risk_model", "prediction_model", "ui_only", "unknown",
]

# Field → category mapping (keyword-based)
CATEGORY_PATTERNS = [
    (r"\.(bid|ask|bidPrice|askPrice|bidSize|askSize|lastPrice|mark|closePrice|openPrice|highPrice|lowPrice)\b", "bid_ask"),
    (r"\.(52WeekHigh|52WeekLow|high52Week|low52Week|structureSupport|structureResist)\b", "key_levels"),
    (r"\.(totalVolume|volume|lastSize|regularMarketLastSize)\b", "volume"),
    (r"\.(quoteTime|tradeTime|datetime|tradeTimeInLong|quoteTimeInLong|CHART_TIME_MILLIS|QUOTE_TIME_MILLIS|TRADE_TIME_MILLIS)\b", "time"),
    (r"\.(volatility|theoreticalVolatility|impliedVol)\b", "volatility"),
    (r"\.(delta|gamma|vega|theta|rho)\b", "greeks"),
    (r"\.(callExpDateMap|putExpDateMap|strikePrice|expirationDate|openInterest|putCall)\b", "options_chain"),
    (r"\.(marketHours|session|isOpen|open|close)\b", "market_hours"),
    (r"\.(movers|percentChange|netChange)\b", "movers"),
    (r"\.(peRatio|eps|divYield|divAmount|sharesOutstanding|avg10DaysVolume|avg1YearVolume)\b", "instrument_fundamentals"),
    (r"\.(BID_PRICE|ASK_PRICE|LAST_PRICE|BID_SIZE|ASK_SIZE|TOTAL_VOLUME|LEVELONE)\b", "streaming_quote"),
    (r"\.(bids|asks|book|depth|level)\b", "streaming_book"),
    (r"\.(candles|open|high|low|close|OHLC)\b", "chart_bar"),
    (r"content\.\d+\.(BID_|ASK_|LAST_|TOTAL_|QUOTE_|TRADE_)", "streaming_quote"),
    # M3 (RC-439): BOOK_TIME and the top-level book SEQUENCE are BOOK-stream fields
    # (NASDAQ_BOOK/NYSE_BOOK/OPTIONS_BOOK), proven absent from LEVELONE. They carry no
    # BID_/ASK_/QUOTE_ token, so without this rule they fall through to the `^streaming.`
    # fallback and are mislabeled `streaming_quote`. Classify them as `streaming_book`
    # BEFORE the fallback. (Nested per-exchange SEQUENCE already matches `.asks/.bids`.)
    (r"\.BOOK_TIME\b", "streaming_book"),
    (r"\.SEQUENCE\b", "streaming_book"),
    (r"^streaming\.", "streaming_quote"),  # fallback for streaming
    (r"callExpDateMap\.|putExpDateMap\.", "options_chain"),
    (r"candles\.\d+\.", "chart_bar"),
]

# Field → likely_use mapping
LIKELY_USE_PATTERNS = [
    (r"\.(bidSize|askSize|BID_SIZE|ASK_SIZE|bids|asks|depth)\b", "direct_order_flow"),
    (r"\.(totalVolume|volume|openInterest)\b", "order_flow_proxy"),
    (r"\.(volatility|regime|session)\b", "regime_detection"),
    (r"\.(52WeekHigh|52WeekLow|high52Week|low52Week|structureSupport)\b", "key_levels"),
    (r"\.(delta|gamma|vega|theta|rho|theoreticalVolatility)\b", "risk_model"),
    (r"\.(peRatio|eps|divYield|fundamental)\b", "prediction_model"),
    (r"\.(description|exchangeName|cusip|assetMainType)\b", "ui_only"),
]

# Field → priority mapping (high = order flow, risk, key levels; medium = most; low = metadata)
PRIORITY_PATTERNS = [
    (r"\.(bidPrice|askPrice|bidSize|askSize|lastPrice|mark|BID_PRICE|ASK_PRICE)\b", "high"),
    (r"\.(delta|gamma|vega|theta|volatility|openInterest)\b", "high"),
    (r"\.(52WeekHigh|52WeekLow|structureSupport|structureResist)\b", "high"),
    (r"\.(totalVolume|volume|candles\.\*\.(open|high|low|close))\b", "high"),
    (r"\.(description|cusip|assetMainType|assetSubType|exchange)\b", "low"),
]


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def is_ticker(seg: str) -> bool:
    """Check if segment looks like a ticker symbol."""
    if not seg or len(seg) > 10:
        return False
    if seg in KNOWN_TICKERS:
        return True
    if seg.startswith("$") and seg[1:].isalpha():
        return True
    if seg.isupper() and 1 <= len(seg) <= 5:
        return True
    return False


def is_numeric_index(seg: str) -> bool:
    return seg.isdigit()


def is_expiry_like(seg: str) -> bool:
    """e.g. 2026-03-12:0 or 2026-01-17:7"""
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}:\d+$", seg))


def is_strike_like(seg: str) -> bool:
    """e.g. 601.0 or 600.5"""
    return bool(re.match(r"^\d+\.\d+$", seg))


def normalize_path(raw: str, endpoint: str | None = None) -> str:
    """
    Normalize a raw field path into canonical form.
    - Strip symbol prefixes
    - Replace numeric indexes with *
    - Replace expiry/strike segments with *
    - Add endpoint prefix where appropriate
    """
    parts = raw.split(".")
    out: list[str] = []

    # Detect and skip leading ticker
    i = 0
    if parts and is_ticker(parts[0]):
        i = 1
    # Also skip symbol in batch quotes: symbol is first part
    if i < len(parts) and is_ticker(parts[i]):
        i += 1

    # Map endpoint to prefix
    ep_prefix = ""
    if endpoint:
        if endpoint == "streaming":
            ep_prefix = "streaming."
        elif endpoint == "chains":
            ep_prefix = "chains."
        elif endpoint == "pricehistory":
            ep_prefix = "pricehistory."
        elif endpoint == "market_hours":
            ep_prefix = "market_hours."
        elif endpoint == "movers":
            ep_prefix = "movers."
        elif endpoint == "instruments":
            ep_prefix = "instruments."
        elif endpoint == "quotes":
            ep_prefix = "quotes."

    while i < len(parts):
        seg = parts[i]
        if is_numeric_index(seg):
            # Use * for array index
            if out and out[-1] != "*":
                out.append("*")
        elif is_expiry_like(seg) or is_strike_like(seg):
            if out and out[-1] != "*":
                out.append("*")
        elif seg in ("extended", "regular", "reference") and "quote" not in ".".join(parts[:i]):
            # Keep extended/regular/reference as context
            out.append(seg)
        else:
            out.append(seg)
        i += 1

    # Collapse consecutive *
    normalized = []
    for p in out:
        if p == "*" and normalized and normalized[-1] == "*":
            continue
        normalized.append(p)

    # Remove trailing standalone object names (no leaf)
    if normalized and normalized[-1] in ("quote", "extended", "regular", "reference", "fundamental", "content"):
        normalized.pop()

    result = ".".join(normalized)
    if ep_prefix and not result.startswith(ep_prefix):
        result = ep_prefix + result
    return result if result else raw


def categorize(canonical: str) -> str:
    for pat, cat in CATEGORY_PATTERNS:
        if re.search(pat, canonical, re.IGNORECASE):
            return cat
    return "unknown"


def likely_use(canonical: str) -> str:
    for pat, use in LIKELY_USE_PATTERNS:
        if re.search(pat, canonical, re.IGNORECASE):
            return use
    return "unknown"


def priority(canonical: str) -> str:
    for pat, pri in PRIORITY_PATTERNS:
        if re.search(pat, canonical, re.IGNORECASE):
            return pri
    return "medium"


def load_raw_fields_and_endpoints() -> tuple[list[str], dict[str, set[str]]]:
    """Load raw field list and build raw_path -> set of endpoints from CSV."""
    raw_fields: list[str] = []
    path_to_endpoints: dict[str, set[str]] = defaultdict(set)

    if MASTER_FILE.exists():
        with open(MASTER_FILE, encoding="utf-8") as f:
            raw_fields = [line.strip() for line in f if line.strip()]

    if SUMMARY_CSV.exists():
        with open(SUMMARY_CSV, encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                fp = row.get("field_path", "").strip()
                ep = row.get("endpoint", "").strip()
                if fp and ep:
                    path_to_endpoints[fp].add(ep)

    return raw_fields, dict(path_to_endpoints)


def infer_endpoint_from_path(raw: str) -> str:
    """Infer endpoint when not in CSV."""
    raw_lower = raw.lower()
    if "callexpdatemap" in raw_lower or "putexpdatemap" in raw_lower:
        return "chains"
    if raw.startswith("candles.") or "candles." in raw:
        return "pricehistory"
    if "market" in raw_lower and ("hour" in raw_lower or "session" in raw_lower):
        return "market_hours"
    if any(t in raw for t in KNOWN_TICKERS) and (".quote." in raw or ".extended." in raw or ".fundamental." in raw):
        return "quotes"
    if "content." in raw or "service" in raw:
        return "streaming"
    if "symbol" in raw_lower and ("search" in raw_lower or "fundamental" in raw_lower):
        return "instruments"
    return ""


def build_canonical_dictionary(
    raw_fields: list[str],
    path_to_endpoints: dict[str, set[str]],
) -> dict[str, dict]:
    """
    Build canonical field -> {source_endpoints, example_raw_field, category, likely_use, priority}.
    """
    canon: dict[str, dict] = {}

    for raw in raw_fields:
        eps = path_to_endpoints.get(raw, set())
        if not eps:
            inferred = infer_endpoint_from_path(raw)
            if inferred:
                eps = {inferred}
            else:
                eps = set()
        ep_for_norm = list(eps)[0] if eps else ""
        norm = normalize_path(raw, ep_for_norm)
        if not norm:
            continue
        if norm not in canon:
            canon[norm] = {
                "source_endpoints": set(),
                "example_raw_field": raw,
                "category": categorize(norm),
                "likely_use": likely_use(norm),
                "priority": priority(norm),
            }
        canon[norm]["source_endpoints"].update(eps)
        canon[norm]["example_raw_field"] = raw

    return canon


def main() -> int:
    ensure_dir(OUTPUT_DIR)

    if not MASTER_FILE.exists():
        print(f"ERROR: {MASTER_FILE} not found. Run schwab_full_field_inventory.py first.")
        return 1

    print("Loading raw field inventory...")
    raw_fields, path_to_endpoint = load_raw_fields_and_endpoints()
    raw_count = len(raw_fields)
    print(f"  Raw fields: {raw_count}")

    print("Building canonical dictionary...")
    canon = build_canonical_dictionary(raw_fields, path_to_endpoint)
    canon_count = len(canon)
    print(f"  Canonical fields: {canon_count}")

    # A. schwab_canonical_fields.txt
    canon_file = OUTPUT_DIR / "schwab_canonical_fields.txt"
    with open(canon_file, "w", encoding="utf-8") as f:
        for k in sorted(canon.keys()):
            f.write(k + "\n")

    # B. schwab_field_dictionary.csv
    dict_file = OUTPUT_DIR / "schwab_field_dictionary.csv"
    with open(dict_file, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["canonical_field", "source_endpoints", "example_raw_field", "category", "likely_use", "priority"])
        for k in sorted(canon.keys()):
            v = canon[k]
            eps = ";".join(sorted(v["source_endpoints"])) if v["source_endpoints"] else "unknown"
            w.writerow([
                k,
                eps,
                v["example_raw_field"],
                v["category"],
                v["likely_use"],
                v["priority"],
            ])

    # C. schwab_field_dictionary_grouped.csv
    grouped_file = OUTPUT_DIR / "schwab_field_dictionary_grouped.csv"
    rows_by_cat: dict[str, list] = defaultdict(list)
    for k in sorted(canon.keys()):
        v = canon[k]
        rows_by_cat[v["category"]].append({
            "canonical_field": k,
            "source_endpoints": ";".join(sorted(v["source_endpoints"])) if v["source_endpoints"] else "unknown",
            "likely_use": v["likely_use"],
            "priority": v["priority"],
        })
    with open(grouped_file, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "canonical_field", "source_endpoints", "likely_use", "priority"])
        for cat in sorted(rows_by_cat.keys()):
            for row in sorted(rows_by_cat[cat], key=lambda x: (x["canonical_field"],)):
                w.writerow([cat, row["canonical_field"], row["source_endpoints"], row["likely_use"], row["priority"]])

    # Counts by category, likely_use, priority
    by_cat = defaultdict(int)
    by_use = defaultdict(int)
    by_pri = defaultdict(int)
    for v in canon.values():
        by_cat[v["category"]] += 1
        by_use[v["likely_use"]] += 1
        by_pri[v["priority"]] += 1

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Raw field count:       {raw_count:,}")
    print(f"  Canonical field count:  {canon_count:,}")
    print()
    print("  Counts by category:")
    for cat in sorted(by_cat.keys()):
        print(f"    {cat}: {by_cat[cat]:,}")
    print()
    print("  Counts by likely_use:")
    for use in sorted(by_use.keys()):
        print(f"    {use}: {by_use[use]:,}")
    print()
    print("  Counts by priority:")
    for pri in sorted(by_pri.keys(), key=lambda x: ("high", "medium", "low").index(x) if x in ("high", "medium", "low") else 3):
        print(f"    {pri}: {by_pri[pri]:,}")
    print()
    print("  Output files:")
    print(f"    {canon_file}")
    print(f"    {dict_file}")
    print(f"    {grouped_file}")
    print("=" * 60)
    print()
    print("FIELD DICTIONARY COMPLETE")
    print()
    print("Output directory:")
    print(f"  {OUTPUT_DIR}\\")
    print()
    print("Canonical fields file:")
    print(f"  {canon_file}")
    print()
    print("Field dictionary CSV:")
    print(f"  {dict_file}")
    print()
    print("Field dictionary grouped CSV:")
    print(f"  {grouped_file}")
    print()
    print(f"Total canonical fields: {canon_count:,}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
