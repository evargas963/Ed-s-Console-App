#!/usr/bin/env python3
"""RC-438 — Order-flow Schwab capability decode / matrix helpers (no live I/O).

Separates **documented / repo-visible** capability from **live entitlement / proof**.
Nested book ``EXCHANGE`` rows are labeled ``exchange_code_raw`` only — never
"per-participant" / MPID / MM until an RTH probe proves identity semantics.
"""
from __future__ import annotations

from typing import Any

# Status vocabulary for the OF-tab design matrix.
PASS = "PASS"
NOT_PROVEN = "NOT_PROVEN"
UNAVAILABLE = "UNAVAILABLE"
DOCUMENTED = "DOCUMENTED"  # library/inventory only — not live proof


def _as_list(x: Any) -> list:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def decode_book_content_item(content: dict[str, Any]) -> dict[str, Any]:
    """Decode one schwab-py-labeled book content row into an analysis structure.

    Expects named keys (post BookFields/BidFields/AskFields/PerExchange* relabel).
    Does **not** assert EXCHANGE identity (MIC vs MPID vs other).
    """
    symbol = content.get("SYMBOL") or content.get("key")
    book_time = content.get("BOOK_TIME")
    levels_out: list[dict[str, Any]] = []

    for side, price_key, agg_key, num_key, nested_key, vol_key in (
        ("BID", "BID_PRICE", "TOTAL_VOLUME", "NUM_BIDS", "BIDS", "BID_VOLUME"),
        ("ASK", "ASK_PRICE", "TOTAL_VOLUME", "NUM_ASKS", "ASKS", "ASK_VOLUME"),
    ):
        for level in _as_list(content.get("BIDS" if side == "BID" else "ASKS")):
            if not isinstance(level, dict):
                continue
            nested = [n for n in _as_list(level.get(nested_key)) if isinstance(n, dict)]
            exchange_rows = []
            for n in nested:
                exchange_rows.append(
                    {
                        "exchange_code_raw": n.get("EXCHANGE"),
                        "size": n.get(vol_key),
                        "sequence": n.get("SEQUENCE"),
                    }
                )
            num_raw = level.get(num_key)
            try:
                num_int = int(num_raw) if num_raw is not None else None
            except (TypeError, ValueError):
                num_int = None
            levels_out.append(
                {
                    "side": side,
                    "price": level.get(price_key),
                    "aggregate_size": level.get(agg_key),  # vendor TOTAL_VOLUME
                    "num_raw": num_raw,
                    "num_int": num_int,
                    "nested_row_count": len(exchange_rows),
                    "exchange_rows": exchange_rows,
                    "num_equals_nested_count": (
                        num_int is not None and num_int == len(exchange_rows)
                    ),
                    "nested_size_sum": _sum_sizes(exchange_rows),
                    "agg_equals_nested_size_sum": _agg_eq_nested(
                        level.get(agg_key), exchange_rows
                    ),
                }
            )

    return {
        "symbol": symbol,
        "book_time": book_time,
        "levels": levels_out,
        "n_levels": len(levels_out),
    }


def _sum_sizes(rows: list[dict[str, Any]]) -> float | None:
    total = 0.0
    any_ok = False
    for r in rows:
        try:
            total += float(r["size"])
            any_ok = True
        except (TypeError, ValueError, KeyError):
            continue
    return total if any_ok else None


def _agg_eq_nested(agg: Any, rows: list[dict[str, Any]]) -> bool | None:
    nested_sum = _sum_sizes(rows)
    if nested_sum is None or agg is None:
        return None
    try:
        return abs(float(agg) - float(nested_sum)) < 1e-9
    except (TypeError, ValueError):
        return None


def analyze_num_semantics(decoded_frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Relate NUM_BIDS/NUM_ASKS to nested row counts and aggregate sizes.

    Does **not** conclude 'order count' or 'market-maker count' — only measurable
    equalities. Live PASS requires operator RTH evidence + human semantic ruling.
    """
    levels = []
    for fr in decoded_frames:
        levels.extend(fr.get("levels") or [])
    n = len(levels)
    eq_nested = sum(1 for lv in levels if lv.get("num_equals_nested_count") is True)
    ne_nested = sum(1 for lv in levels if lv.get("num_equals_nested_count") is False)
    eq_size = sum(1 for lv in levels if lv.get("agg_equals_nested_size_sum") is True)
    ne_size = sum(1 for lv in levels if lv.get("agg_equals_nested_size_sum") is False)
    missing_num = sum(1 for lv in levels if lv.get("num_int") is None)
    return {
        "n_levels": n,
        "num_equals_nested_count": eq_nested,
        "num_ne_nested_count": ne_nested,
        "agg_equals_nested_size_sum": eq_size,
        "agg_ne_nested_size_sum": ne_size,
        "missing_num": missing_num,
        "ruling": NOT_PROVEN,
        "ruling_note": (
            "Measurable equalities only. Do not label NUM_* as order-count or "
            "market-maker-count without Schwab semantic proof."
        ),
    }


def analyze_exchange_semantics(decoded_frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Collect raw EXCHANGE string samples — identity remains NOT_PROVEN."""
    samples: dict[str, int] = {}
    n_rows = 0
    for fr in decoded_frames:
        for lv in fr.get("levels") or []:
            for row in lv.get("exchange_rows") or []:
                n_rows += 1
                code = row.get("exchange_code_raw")
                key = repr(code)
                samples[key] = samples.get(key, 0) + 1
    # Heuristic flags only — never upgrade to PASS alone.
    looks_like_mic = 0
    looks_like_single = 0
    for key in samples:
        # key is repr(code)
        raw = key.strip("'\"")
        if len(raw) == 4 and raw.isalpha():
            looks_like_mic += samples[key]
        elif len(raw) == 1:
            looks_like_single += samples[key]
    return {
        "n_exchange_rows": n_rows,
        "unique_exchange_code_raw": len(samples),
        "top_samples": sorted(samples.items(), key=lambda kv: (-kv[1], kv[0]))[:40],
        "count_len4_alpha": looks_like_mic,
        "count_len1": looks_like_single,
        "ruling": NOT_PROVEN,
        "ruling_note": (
            "Nested EXCHANGE is exchange_code_raw only. Do not call it "
            "per-participant, MPID, or market-maker-id until proven."
        ),
    }


def analyze_book_time_sequence(decoded_frames: list[dict[str, Any]]) -> dict[str, Any]:
    times = [fr.get("book_time") for fr in decoded_frames if fr.get("book_time") is not None]
    seqs: list[Any] = []
    for fr in decoded_frames:
        for lv in fr.get("levels") or []:
            for row in lv.get("exchange_rows") or []:
                if row.get("sequence") is not None:
                    seqs.append(row["sequence"])
    mono_time = None
    if len(times) >= 2:
        try:
            mono_time = all(float(times[i]) <= float(times[i + 1]) for i in range(len(times) - 1))
        except (TypeError, ValueError):
            mono_time = None
    return {
        "n_frames_with_book_time": len(times),
        "book_time_samples": times[:20],
        "book_time_nondecreasing": mono_time,
        "n_sequence_values": len(seqs),
        "sequence_samples": seqs[:40],
        "ruling": NOT_PROVEN if times or seqs else NOT_PROVEN,
        "ruling_note": "Characterize freshness/order only after RTH capture.",
    }


def scan_keys_for_forbidden_concepts(payload: Any) -> dict[str, Any]:
    """Confirm absence of NOII / aggressor-named keys in a payload tree."""
    found_noii: list[str] = []
    found_aggressor: list[str] = []
    needles_noii = ("noii", "imbalance", "auction_imbalance", "opening_imbalance")
    needles_agg = ("aggressor", "buyer_seller", "tick_direction", "condition_code")

    def walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{path}.{k}" if path else str(k)
                kl = str(k).lower()
                if any(n in kl for n in needles_noii):
                    found_noii.append(p)
                if any(n in kl for n in needles_agg):
                    found_aggressor.append(p)
                walk(v, p)
        elif isinstance(obj, list):
            for i, v in enumerate(obj[:50]):
                walk(v, f"{path}[{i}]")

    walk(payload)
    return {
        "noii_like_keys": found_noii[:50],
        "aggressor_like_keys": found_aggressor[:50],
        "noii_ruling": UNAVAILABLE if not found_noii else NOT_PROVEN,
        "aggressor_ruling": UNAVAILABLE if not found_aggressor else NOT_PROVEN,
        "note": (
            "Key-name scan only. UNAVAILABLE means no matching key names in "
            "captured payloads — not a proof Schwab never offers them elsewhere."
        ),
    }


def empty_capability_matrix(*, live_ran: bool = False) -> dict[str, Any]:
    """Design matrix: documented capability vs live proof status."""

    def row(
        concept: str,
        documented: str,
        live: str,
        semantics: str,
        notes: str,
    ) -> dict[str, str]:
        return {
            "concept": concept,
            "documented_repo_visible": documented,
            "live_entitlement_proof": live,
            "semantics": semantics,
            "notes": notes,
        }

    live_default = NOT_PROVEN if not live_ran else NOT_PROVEN
    return {
        "schema_version": 1,
        "live_probe_ran": live_ran,
        "status_vocab": {
            "PASS": "Live RTH evidence captured and semantic ruling recorded",
            "NOT_PROVEN": "Documented and/or partially observed; live proof incomplete",
            "UNAVAILABLE": "Not offered / refused / absent in probed surfaces",
            "DOCUMENTED": "Present in schwab-py enums or field inventory only",
        },
        "corrections": [
            "Do not call nested EXCHANGE depth per-participant until identity proven.",
            "Documented/repo-visible ≠ live entitlement/proof.",
        ],
        "rows": [
            row(
                "LEVELONE_EQUITIES top-of-book",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Subscribed by order_flow_streaming; inventory has leaves; RTH confirms live",
            ),
            row(
                "Quote time (QUOTE_TIME_MILLIS / quoteTime)",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Native field documented; clock skew vs BOOK_TIME needs RTH",
            ),
            row(
                "Book aggregate size (price-level TOTAL_VOLUME)",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Vendor name TOTAL_VOLUME; used by OrderFlowEngine imbalance",
            ),
            row(
                "NUM_BIDS / NUM_ASKS",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Do not call order-count or market-maker-count without proof",
            ),
            row(
                "Nested EXCHANGE + BID_VOLUME/ASK_VOLUME",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "exchange_code_raw only — not per-participant until proven",
            ),
            row(
                "BOOK_TIME",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Characterize monotonicity / lag vs wall clock at RTH",
            ),
            row(
                "Nested SEQUENCE",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Update-order usefulness NOT_PROVEN",
            ),
            row(
                "NYSE_BOOK live frames (SPY/QQQ/IWM)",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Console subscribes; raw+decoded RTH capture required",
            ),
            row(
                "NASDAQ_BOOK live frames (SPY/QQQ/IWM)",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Console subscribes; raw+decoded RTH capture required",
            ),
            row(
                "OPTIONS_BOOK entitlement",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Defined in schwab-py; not subscribed by console",
            ),
            row(
                "LEVELONE_OPTIONS",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Defined; console uses REST chains instead",
            ),
            row(
                "TIMESALE / trade prints (Schwab)",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Not wrapped in schwab-py; prior 2026-07-22 code 11 is historical — re-probe required",
            ),
            row(
                "Native aggressor side",
                UNAVAILABLE,
                live_default,
                UNAVAILABLE,
                "No field in enums; repo proxies are INFERRED",
            ),
            row(
                "NOII / auction imbalance",
                UNAVAILABLE,
                live_default,
                UNAVAILABLE,
                "No field in enums; confirm absence in live payloads",
            ),
            row(
                "Market Maker ID / MPID",
                UNAVAILABLE,
                live_default,
                UNAVAILABLE,
                "ASK/BID/LAST_ID documented as Exchange ID; MIC separate; no MPID",
            ),
            row(
                "True Level-3 order stream",
                UNAVAILABLE,
                live_default,
                UNAVAILABLE,
                "No order-id add/cancel/modify service in schwab-py",
            ),
            row(
                "Vendor 'level two' book = full MM montage",
                DOCUMENTED,
                live_default,
                NOT_PROVEN,
                "Schema is aggregated price levels + nested EXCHANGE sizes",
            ),
        ],
    }


def apply_live_results_to_matrix(
    matrix: dict[str, Any],
    *,
    book_services: dict[str, Any],
    num_analysis: dict[str, Any] | None,
    exchange_analysis: dict[str, Any] | None,
    timesales: dict[str, Any] | None,
    options_book: dict[str, Any] | None,
    levelone_options: dict[str, Any] | None,
    absence_scan: dict[str, Any] | None,
) -> dict[str, Any]:
    """Upgrade matrix live_entitlement_proof cells from probe outputs.

    Semantics cells stay NOT_PROVEN unless an explicit ruling key is PASS
    (operator/human) — this helper never auto-promotes NUM_* or EXCHANGE identity.
    """
    matrix = dict(matrix)
    matrix["live_probe_ran"] = True
    rows = {r["concept"]: dict(r) for r in matrix["rows"]}

    def set_live(concept: str, status: str, note: str | None = None) -> None:
        if concept not in rows:
            return
        rows[concept]["live_entitlement_proof"] = status
        if note:
            rows[concept]["notes"] = f"{rows[concept]['notes']} | LIVE: {note}"

    for svc, info in (book_services or {}).items():
        n = int(info.get("n_frames") or 0)
        ok = bool(info.get("subs_ok"))
        concept = {
            "NYSE_BOOK": "NYSE_BOOK live frames (SPY/QQQ/IWM)",
            "NASDAQ_BOOK": "NASDAQ_BOOK live frames (SPY/QQQ/IWM)",
            "OPTIONS_BOOK": "OPTIONS_BOOK entitlement",
        }.get(svc)
        if not concept:
            continue
        if ok and n > 0:
            set_live(concept, PASS, f"frames={n}")
            if svc in ("NYSE_BOOK", "NASDAQ_BOOK"):
                set_live(
                    "Book aggregate size (price-level TOTAL_VOLUME)",
                    PASS,
                    "observed in decoded levels",
                )
                set_live("NUM_BIDS / NUM_ASKS", PASS, "field present; semantics still NOT_PROVEN")
                set_live(
                    "Nested EXCHANGE + BID_VOLUME/ASK_VOLUME",
                    PASS,
                    "field present; identity still NOT_PROVEN",
                )
                set_live("BOOK_TIME", PASS if (num_analysis or exchange_analysis) else NOT_PROVEN)
                set_live("Nested SEQUENCE", PASS if (exchange_analysis or {}).get("n_exchange_rows") else NOT_PROVEN)
                # vendor L2 claim still semantic NOT_PROVEN
        elif ok and n == 0:
            set_live(concept, NOT_PROVEN, "SUBS ok but no frames in window")
        else:
            set_live(concept, UNAVAILABLE if info.get("refused") else NOT_PROVEN, str(info.get("error") or ""))

    if timesales:
        code = timesales.get("response_code")
        if code == 0 and timesales.get("n_frames"):
            set_live("TIMESALE / trade prints (Schwab)", PASS, "prints received")
            rows["TIMESALE / trade prints (Schwab)"]["semantics"] = NOT_PROVEN
        elif code == 11:
            set_live("TIMESALE / trade prints (Schwab)", UNAVAILABLE, "response code 11")
            rows["TIMESALE / trade prints (Schwab)"]["semantics"] = UNAVAILABLE
        else:
            set_live("TIMESALE / trade prints (Schwab)", NOT_PROVEN, str(timesales))

    if options_book is not None and "OPTIONS_BOOK entitlement" in rows:
        # already handled via book_services if present
        pass

    if levelone_options:
        if levelone_options.get("n_frames"):
            set_live("LEVELONE_OPTIONS", PASS, f"frames={levelone_options['n_frames']}")
        elif levelone_options.get("subs_ok"):
            set_live("LEVELONE_OPTIONS", NOT_PROVEN, "SUBS ok, no frames")
        else:
            set_live("LEVELONE_OPTIONS", NOT_PROVEN, str(levelone_options.get("error") or ""))

    if absence_scan:
        rows["NOII / auction imbalance"]["live_entitlement_proof"] = absence_scan.get(
            "noii_ruling", UNAVAILABLE
        )
        rows["Native aggressor side"]["live_entitlement_proof"] = absence_scan.get(
            "aggressor_ruling", UNAVAILABLE
        )

    # NUM_* / EXCHANGE semantics never auto-PASS
    if num_analysis:
        rows["NUM_BIDS / NUM_ASKS"]["semantics"] = NOT_PROVEN
        rows["NUM_BIDS / NUM_ASKS"]["notes"] += f" | analysis={num_analysis}"
    if exchange_analysis:
        rows["Nested EXCHANGE + BID_VOLUME/ASK_VOLUME"]["semantics"] = NOT_PROVEN
        rows["Nested EXCHANGE + BID_VOLUME/ASK_VOLUME"]["notes"] += (
            f" | samples={exchange_analysis.get('unique_exchange_code_raw')}"
        )

    matrix["rows"] = list(rows.values())
    return matrix
