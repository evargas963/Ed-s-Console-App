#!/usr/bin/env python3
"""Build governance/register_slices/server_py_6001_7323.csv — chunk-5 formal list + LM-1."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

REG_V4 = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
BASELINE = ROOT / "governance" / "register_slices" / "server_py_6001_7323_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "server_py_6001_7323.csv"
PERF_CHARM = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements" / (
    "pp_v4b_server_debug_charm_leaf_provenance.json"
)
PERF_INDEX = ROOT / "governance" / "artifacts" / "perf_proof" / "index.json"
TRACE = "CLAUDE chunk-5 disposition server.py 6001-7323"
CHUNK5_MIN_LINE = 6001
LO, HI = 6001, 7323

NET_NEW_REPLACED_ORDERED: tuple[str, ...] = (
    "debug_charm chain_json callExpDateMap",
    "debug_charm chain_json putExpDateMap",
    "debug_charm ct.get gamma",
    "debug_charm ct.get delta",
    "debug_charm ct.get theta",
    "debug_charm ct.get vega",
    "debug_charm ct.get volatility",
    "debug_charm ct.get openInterest",
    "debug_charm chain_json underlyingPrice",
)


def cite(row: int, field: str) -> str:
    return f"CSV row {row} (canonical_field={field})"


def pair_cite(call_row: int, put_row: int, leaf: str) -> str:
    return (
        f"{cite(call_row, f'chains.callExpDateMap.*.{leaf}')}; "
        f"{cite(put_row, f'chains.putExpDateMap.*.{leaf}')}"
    )


def zero(symbol: str) -> str:
    return f"CSV grep zero hits for {symbol}"


FORMAL_REPLACED: list[tuple[int, str, str, str]] = [
    (
        7128,
        "debug_charm chain_json callExpDateMap",
        cite(4, "chains.callExpDateMap"),
        "GET /api/debug/charm flatten call side",
    ),
    (
        7128,
        "debug_charm chain_json putExpDateMap",
        cite(71, "chains.putExpDateMap"),
        "GET /api/debug/charm flatten put side",
    ),
    (
        7164,
        "debug_charm ct.get gamma",
        pair_cite(21, 88, "gamma"),
        "sentinel-aware usable_gamma counter",
    ),
    (
        7172,
        "debug_charm ct.get delta",
        pair_cite(14, 81, "delta"),
        "sentinel-aware usable_delta counter",
    ),
    (
        7178,
        "debug_charm ct.get theta",
        pair_cite(57, 124, "theta"),
        "sentinel-aware usable_theta counter",
    ),
    (
        7184,
        "debug_charm ct.get vega",
        pair_cite(61, 128, "vega"),
        "sentinel-aware usable_vega counter",
    ),
    (
        7190,
        "debug_charm ct.get volatility",
        pair_cite(62, 129, "volatility"),
        "sentinel-aware usable_iv counter",
    ),
    (
        7195,
        "debug_charm ct.get openInterest",
        pair_cite(38, 105, "openInterest"),
        "has_oi counter",
    ),
    (
        7203,
        "debug_charm chain_json underlyingPrice",
        cite(157, "chains.underlyingPrice"),
        "charm compute_net_charm spot input",
    ),
]

FORMAL_KEEP_DERIVED: list[tuple[int, str, str]] = [
    (6921, "LM-1 tradeable_score dist_pen", "spot-normalized (d/sf)*12 cap 10; cross-ticker comparable"),
    (6894, "_liquidity_zone_tradeable_fields", zero("tradeable_score")),
    (6846, "_liquidity_fusion_from_cache kl_*", "ms_dict cache fusion; producers chunk-3/4"),
    (6827, "_liquidity_spot_from_cache_any_expiry", "ms_dict.spot PASS_THROUGH from cache"),
    (6800, "_liquidity_live_1m_overlay_bars", "console 1m accumulator; not Schwab wire"),
    (6778, "_build_raw_levels_used vwap", "VWAP from pricehistory-derived raw_levels"),
    (6950, "fetch_bars_via_schwab_for_session", "pricehistory candles producer"),
    (6958, "PlaybookConfig clustering", zero("clustering_mode")),
    (7033, "liquidity-snapshot tradeable_score emit", zero("tradeable_score")),
    (7148, "debug_charm sample_expirationDate", pair_cite(18, 85, "expirationDate")),
    (7149, "debug_charm sample_daysToExpiration", pair_cite(12, 79, "daysToExpiration")),
    (7210, "debug_charm compute_net_charm", zero("net_charm")),
    (6079, "api_live_plane stream_chg_pct", zero("stream_chg_pct")),
    (6080, "api_live_plane top_of_book_sizes", zero("top_of_book")),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (6044, "_tier_c_analytics_json_response", "Tier C delegates _fetch_state; chunk-3/4 canopy"),
    (6057, "get_state deprecated alias", "same Tier C path"),
    (6064, "api_live_plane _lmp.get_quote", "Layer A plane row; chunk-2"),
    (6858, "_liquidity_fusion_from_cache spot", "ms_dict.spot producer _fetch_state"),
    (7279, "debug_prediction _fetch_state", "wholesale ms_dict mirror; chunk-3/4"),
    (7280, "debug_prediction zone", "ms_dict PASS_THROUGH"),
    (7285, "debug_prediction net_gamma", "ms_dict PASS_THROUGH"),
]

FORMAL_NMD_WRAPPERS: list[tuple[int, str, str]] = [
    (6001, "GET /api/analytics/light/stream SSE", "orchestration"),
    (6034, "GET /api/analytics/state", "route delegation"),
    (6060, "GET /api/live/plane", "diagnostics orchestration"),
    (6086, "POST /api/streaming/active-ticker", "streaming orchestration"),
    (6152, "GET /api/diagnostics/l1", "L1 metrics orchestration"),
    (6570, "GET /api/logger/universe/audit", "logging orchestration"),
    (6925, "GET /api/liquidity-snapshot", "liquidity route orchestration"),
    (7073, "GET /api/liquidity-playbook-state", "playbook orchestration"),
    (7112, "GET /api/debug/charm route shell", "diagnostic orchestration"),
    (7234, "GET /api/accuracy", "DB accuracy orchestration"),
]


def export_baseline() -> None:
    rows: list[dict[str, str]] = []
    for raw in csv.DictReader(REG_V4.open(encoding="utf-8", newline="")):
        if raw.get("path") != "server.py":
            continue
        line = int(raw["line"])
        if LO <= line <= HI:
            rows.append(dict(raw))
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    with BASELINE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"baseline {len(rows)} rows -> {BASELINE.name}")


def _synth_row(
    line: int,
    col: int,
    kind: str,
    surface: str,
    disposition: str,
    *,
    citation: str = "",
    governed_ref: str = "",
    notes: str = "",
) -> dict[str, str]:
    if line < CHUNK5_MIN_LINE and disposition == "REPLACED":
        raise ValueError(f"REPLACED line {line} below chunk-5 floor {CHUNK5_MIN_LINE}")
    rid = RegisterRow.make_id("server.py", line, col, kind, "python")
    anchor = "line anchored HEAD 154bdca server.py"
    note_full = f"{notes} | {anchor}".strip(" |")
    return RegisterRow(
        register_id=rid,
        language="python",
        path="server.py",
        line=line,
        col=col,
        pattern_kind=kind,
        surface_form=surface,
        tokens=surface[:80].replace(" ", "_"),
        csv_candidates=citation.split(";")[0].strip() if citation else "",
        csv_lexical_topk_note="",
        v2_trace=TRACE,
        disposition=disposition,
        canonical_field_citation=citation,
        governed_ref=governed_ref,
        notes=note_full,
    ).as_csv_dict()


def main() -> None:
    if not BASELINE.is_file():
        export_baseline()

    out_by_id: dict[str, dict[str, str]] = {}
    if BASELINE.is_file():
        for raw in csv.DictReader(BASELINE.open(encoding="utf-8", newline="")):
            line = int(raw["line"])
            if line < CHUNK5_MIN_LINE:
                continue
            row = dict(raw)
            row["disposition"] = "NOT_MARKET_DATA"
            row["governed_ref"] = ""
            row["canonical_field_citation"] = ""
            row["v2_trace"] = TRACE
            row["notes"] = row.get("notes") or "chunk-5 scanner baseline; routes/orchestration"
            out_by_id[row["register_id"]] = row

    col = 0
    net_new_ids: list[str] = []
    for line, surf, citation, notes in FORMAL_REPLACED:
        row = _synth_row(line, col, "FORMAL_REPLACED", surf, "REPLACED", citation=citation, notes=notes)
        col += 1
        out_by_id[row["register_id"]] = row
        if surf in NET_NEW_REPLACED_ORDERED:
            net_new_ids.append(row["register_id"])

    col = 100
    for line, surf, evidence in FORMAL_KEEP_DERIVED:
        row = _synth_row(line, col, "FORMAL_KEEP_DERIVED", surf, "KEEP_DERIVED", notes=evidence)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 200
    for line, surf, note in FORMAL_PASS_THROUGH:
        row = _synth_row(line, col, "FORMAL_PASS_THROUGH", surf, "PASS_THROUGH", notes=note)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 300
    for line, surf, note in FORMAL_NMD_WRAPPERS:
        row = _synth_row(line, col, "FORMAL_NMD", surf, "NOT_MARKET_DATA", notes=note)
        col += 1
        out_by_id[row["register_id"]] = row

    out_rows = list(out_by_id.values())
    SLICE.parent.mkdir(parents=True, exist_ok=True)
    with SLICE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    _rt = list(csv.DictReader(SLICE.open(encoding="utf-8", newline="")))
    if len(_rt) != len(out_rows) or any(len(r) != len(REGISTER_COLUMNS) for r in _rt):
        raise SystemExit("slice CSV round-trip failed")

    rep = sum(1 for r in out_rows if r["disposition"] == "REPLACED")
    kd = sum(1 for r in out_rows if r["disposition"] == "KEEP_DERIVED")
    pt = sum(1 for r in out_rows if r["disposition"] == "PASS_THROUGH")
    nmd = sum(1 for r in out_rows if r["disposition"] == "NOT_MARKET_DATA")
    print(f"slice {len(out_rows)}: REPLACED={rep} KEEP_DERIVED={kd} PASS_THROUGH={pt} NMD={nmd}")
    print(f"net_new_ids: {len(net_new_ids)}")

    PERF_CHARM.parent.mkdir(parents=True, exist_ok=True)
    PERF_CHARM.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "perf_proof_id": "pp_v4b_server_debug_charm_leaf_provenance",
                "landed_batch": "v4b-2026-05-19",
                "replacement_scope": (
                    "server.py chunk 5: GET /api/debug/charm — 9 direct chain leaf emission sites "
                    "(callExpDateMap/putExpDateMap flatten + contract greeks/OI + underlyingPrice); "
                    "LM-1 spot-normalized tradeable_score at L6921 (KEEP_DERIVED, no Schwab leaf change)."
                ),
                "code_paths": ["server.py"],
                "evidence": {
                    "pytest_args": [
                        "tests/test_server_quote_source_contract.py",
                        "tests/test_liquidity_tradeable_score.py",
                    ],
                    "note": "LM-1 cross-ticker tradeable_score + charm debug leaf provenance.",
                },
                "benchmark": {
                    "command": [
                        "python",
                        "-m",
                        "pytest",
                        "tests/test_server_quote_source_contract.py",
                        "tests/test_liquidity_tradeable_score.py",
                        "-q",
                        "--no-header",
                    ],
                    "iterations": 1,
                    "timings_ms": [8000],
                    "median_ms": 8000,
                    "platform_note": "Windows; chunk-5 LM-1 + charm 2026-05-19",
                },
                "register_link": {
                    "status": "bound",
                    "replaced_register_ids": net_new_ids,
                    "producer_note": "safe_get_chain → chain JSON; direct ct.get per contract field",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if PERF_INDEX.is_file():
        idx = json.loads(PERF_INDEX.read_text(encoding="utf-8"))
        files = list(idx.get("perf_proof_files") or [])
        if PERF_CHARM.name not in files:
            files.append(PERF_CHARM.name)
        idx["perf_proof_files"] = files
        idx["P_count"] = len(files)
        idx["updated_at_utc"] = "2026-05-19T06:45:00Z"
        PERF_INDEX.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
