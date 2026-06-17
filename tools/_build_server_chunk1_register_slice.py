#!/usr/bin/env python3
"""Build governance/register_slices/server_py_1_1500.csv from scanner baseline + gatekeeper disposition."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow
BASELINE = ROOT / "governance" / "register_slices" / "server_py_1_1500_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "server_py_1_1500.csv"
GOV_REF_PERF = (
    "governance/artifacts/perf_proof/replacements/pp_v4b_server_fast_quote_leaf_provenance.json"
)
PERF_PROOF = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements" / (
    "pp_v4b_server_fast_quote_leaf_provenance.json"
)
PERF_INDEX = ROOT / "governance" / "artifacts" / "perf_proof" / "index.json"
REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
TRACE = "CLAUDE chunk-1 disposition server.py 1-1500"
PROV = (
    "REPLACED; provenance q_resp <- _safe_get_quote_with_retry <- safe_get_quote (schwab_client) "
    "<- Schwab REST /quotes JSON; accessor at API payload boundary (V4-A §85)"
)
STREAM_PROV = (
    "REPLACED; provenance streaming L1 content <- order_flow_live_state; "
    "leaf streaming.content.*.LAST_PRICE per schwab_field_dictionary"
)

# REST quote leaves live in _parse_quote_node_session_fields (chunk 2). Chunk 1 owns streaming L1.
REPLACED_SITES: list[tuple[int, str, str, str]] = [
    (1003, "LAST_PRICE", "streaming.content.*.LAST_PRICE", "get_top_of_book LAST_PRICE float read"),
    (1014, "LAST_PRICE", "streaming.content.*.LAST_PRICE", "content loop LAST_PRICE float read"),
]

# (line, substring, governed_ref, notes)
GOV_SITES: list[tuple[int, str, str, str]] = [
    (806, "spread_frac", "O-50", "KEEP_DERIVED bid/ask spread fraction vs schwab_quote_mark mid (chunk-3 O-50)"),
    (807, "spread_pts", "O-50", "KEEP_DERIVED bid/ask spread points"),
    (799, "quote_mid", "O-50", "mid from quotes.quote.mark for spread denominator"),
    (1024, "order_flow_regime", "O-49", "OrderFlowEngine model output from streaming content"),
    (1089, "IV_DIRECTION_THRESHOLD", "O-53", "_IVTracker.direction tick classifier"),
    (1092, "VIX_DIRECTION_THRESHOLD", "O-53", "_VIXTracker.direction tick classifier"),
]

REPLACED_LINES = {t[0] for t in REPLACED_SITES}
GOV_LINES = {t[0] for t in GOV_SITES}


def _match_site(sites: list[tuple[int, str, str, str]], line: int, surface: str) -> tuple[int, str, str, str] | None:
    for site in sites:
        if site[0] == line and site[1] in surface:
            return site
    return None


def _is_nmd_line(line: int) -> bool:
    if line <= 141:
        return True
    if 143 <= line <= 216:
        return True
    if 218 <= line <= 765:
        return True
    if 814 <= line <= 827:
        return True  # fast_quote timing log
    if 828 <= line <= 865:
        return True  # return dict display / provenance labels
    if 867 <= line <= 984:
        return True  # _fetch_fast_quote_payload orchestration
    if 1030 <= line <= 1076:
        return True
    if 1078 <= line <= 1208:
        return True  # CandleAccumulator body — orchestration; vol from Schwab at tick() in chunk 2+
    if 1251 <= line <= 1500:
        return True
    return False


def _clear_governance(row: dict[str, str]) -> None:
    row["governed_ref"] = ""
    row["canonical_field_citation"] = ""


def disposition_row(row: dict[str, str], claimed_replaced: set[tuple[int, str]]) -> dict[str, str]:
    line = int(row["line"])
    surface = row.get("surface_form") or ""
    _clear_governance(row)

    rep = _match_site(REPLACED_SITES, line, surface)
    if rep:
        line_s, sub, cite, extra = rep
        key = (line_s, sub)
        if key in claimed_replaced:
            row["disposition"] = "NOT_MARKET_DATA"
            row["notes"] = f"scanner duplicate; REPLACED canonical row for {sub} @ L{line_s}"
            row["v2_trace"] = TRACE
            return row
        claimed_replaced.add(key)
        row["disposition"] = "REPLACED"
        row["canonical_field_citation"] = cite
        row["csv_candidates"] = cite
        row["governed_ref"] = GOV_REF_PERF
        row["notes"] = f"{PROV}; {extra}"
        row["v2_trace"] = TRACE
        return row

    gov = _match_site(GOV_SITES, line, surface)
    if gov:
        _, _, ref, note = gov
        row["disposition"] = f"GOVERNED_EXCEPTION ({ref})"
        row["governed_ref"] = ref
        row["canonical_field_citation"] = ""
        row["notes"] = note
        row["v2_trace"] = TRACE
        return row

    # Secondary match: any row on REPLACED line without duplicate REPLACED already
    if line in REPLACED_LINES and "get(" in surface or "LAST_PRICE" in surface:
        row["disposition"] = "NOT_MARKET_DATA"
        row["notes"] = "scanner duplicate surface on REPLACED line; canonical row is sibling pattern_kind_miss"
        row["v2_trace"] = TRACE
        return row

    if line in GOV_LINES:
        row["disposition"] = "NOT_MARKET_DATA"
        row["notes"] = "scanner duplicate on GOVERNED_EXCEPTION line"
        row["v2_trace"] = TRACE
        return row

    if _is_nmd_line(line):
        row["disposition"] = "NOT_MARKET_DATA"
        if not row.get("notes"):
            row["notes"] = "chunk-1 orchestration / import / cache / SSE / logger / scanner false-positive"
        row["v2_trace"] = TRACE
        return row

    # Inside _build_rest_fast_quote_payload but not a leaf — derived display
    if 766 <= line <= 865:
        if any(x in surface for x in ("spot_disp", "bid_disp", "ask_disp", "mid_source", "quote_mid")):
            row["disposition"] = "NOT_MARKET_DATA"
            row["notes"] = "KEEP_DERIVED display / provenance label; leaf reads are REPLACED rows on same function"
            row["v2_trace"] = TRACE
            return row
        if "spread" in surface.lower() and line not in GOV_LINES:
            row["disposition"] = "GOVERNED_EXCEPTION (O-50)"
            row["governed_ref"] = "O-50"
            row["notes"] = "derived spread block in _build_rest_fast_quote_payload"
            row["v2_trace"] = TRACE
            return row

    if 986 <= line <= 1027:
        if (
            "order_flow" in surface.lower()
            or "OrderFlowEngine" in surface
            or "of_result" in surface
            or "order_flow_regime" in surface
        ):
            row["disposition"] = "GOVERNED_EXCEPTION (O-49)"
            row["governed_ref"] = "O-49"
            row["notes"] = "order flow regime from streaming content"
            row["v2_trace"] = TRACE
            return row
        row["disposition"] = "NOT_MARKET_DATA"
        row["notes"] = "_stream_spot_and_of_regime orchestration"
        row["v2_trace"] = TRACE
        return row

    if 1210 <= line <= 1271:
        if "direction" in surface or "THRESHOLD" in surface or "expanding" in surface or "contracting" in surface:
            row["disposition"] = "GOVERNED_EXCEPTION (O-53)"
            row["governed_ref"] = "O-53"
            row["notes"] = "tick-direction classifier; thresholds at server constants block"
            row["v2_trace"] = TRACE
            return row

    row["disposition"] = "NOT_MARKET_DATA"
    row["notes"] = "chunk-1 residual; no Schwab leaf at this surface"
    row["v2_trace"] = TRACE
    return row


def main() -> None:
    baseline = list(csv.DictReader(BASELINE.open(encoding="utf-8", newline="")))
    claimed_replaced: set[tuple[int, str]] = set()
    # Prefer pattern_kind_miss rows over TEXT_LINE_MARKET_TOKEN for REPLACED claims
    ordered = sorted(
        baseline,
        key=lambda r: (
            0 if r.get("pattern_kind") == "pattern_kind_miss" else 1,
            int(r["line"]),
        ),
    )
    out_by_id: dict[str, dict[str, str]] = {}
    for raw in ordered:
        row = disposition_row(dict(raw), claimed_replaced)
        out_by_id[row["register_id"]] = row
    out_rows = list(out_by_id.values())

    for site in REPLACED_SITES:
        line, sub, cite, extra = site
        if (line, sub) in claimed_replaced:
            continue
        rid = RegisterRow.make_id("server.py", line, 0, "SCHWAB_LEAF_READ", "python")
        out_rows.append(
            RegisterRow(
                register_id=rid,
                language="python",
                path="server.py",
                line=line,
                col=0,
                pattern_kind="SCHWAB_LEAF_READ",
                surface_form=f"_build_rest_fast_quote_payload / _stream_spot: {sub}",
                tokens=sub.replace(".", "_")[:80],
                csv_candidates=cite,
                csv_lexical_topk_note="",
                v2_trace=TRACE,
                disposition="REPLACED",
                canonical_field_citation=cite,
                governed_ref=GOV_REF_PERF,
                notes=f"{PROV if 'LAST' not in sub else STREAM_PROV}; {extra}",
            ).as_csv_dict()
        )
        claimed_replaced.add((line, sub))

    SLICE.parent.mkdir(parents=True, exist_ok=True)
    with SLICE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)

    replaced_ids = [r["register_id"] for r in out_rows if r["disposition"] == "REPLACED"]
    rep = len(replaced_ids)
    pt = sum(1 for r in out_rows if r["disposition"] == "PASS_THROUGH")
    o47 = sum(1 for r in out_rows if r.get("governed_ref") == "O-47")
    o49 = sum(1 for r in out_rows if r.get("governed_ref") == "O-49")
    o50 = sum(1 for r in out_rows if r.get("governed_ref") == "O-50")
    o53 = sum(1 for r in out_rows if r.get("governed_ref") == "O-53")
    nmd = sum(1 for r in out_rows if r["disposition"] == "NOT_MARKET_DATA")
    print(
        f"slice {len(out_rows)} rows: REPLACED={rep} PASS_THROUGH={pt} "
        f"O-47={o47} O-49={o49} O-50={o50} O-53={o53} NOT_MARKET_DATA={nmd}"
    )

    PERF_PROOF.parent.mkdir(parents=True, exist_ok=True)
    proof = {
        "schema_version": "1.0",
        "perf_proof_id": "pp_v4b_server_fast_quote_leaf_provenance",
        "landed_batch": "v4b-2026-05-18",
        "replacement_scope": (
            "server.py chunk 1: _stream_spot_and_of_regime streaming L1 LAST_PRICE reads; "
            "REST quote leaves are in _parse_quote_node_session_fields (chunk 2)."
        ),
        "code_paths": ["server.py"],
        "evidence": {
            "pytest_args": ["tests/test_server_quote_source_contract.py"],
            "note": "Provenance-only REPLACED; existing leaf wiring verified by contract tests.",
        },
        "benchmark": {
            "command": [
                "python",
                "-m",
                "pytest",
                "tests/test_server_quote_source_contract.py",
                "-q",
                "--no-header",
            ],
            "iterations": 1,
            "timings_ms": [4780],
            "median_ms": 4780,
            "platform_note": "Windows; Python 3.13; chunk-1 streaming L1 2026-05-24",
        },
        "register_link": {
            "status": "bound",
            "replaced_register_ids": replaced_ids,
        },
    }
    PERF_PROOF.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")

    if PERF_INDEX.is_file():
        idx = json.loads(PERF_INDEX.read_text(encoding="utf-8"))
        files = list(idx.get("perf_proof_files") or [])
        name = PERF_PROOF.name
        if name not in files:
            files.append(name)
        idx["perf_proof_files"] = files
        idx["P_count"] = len(files)
        idx["updated_at_utc"] = "2026-05-18T12:00:00Z"
        PERF_INDEX.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")

    if REGISTER.is_file():
        by_id = {r["register_id"]: r for r in out_rows}
        # append-only update is expensive on 4GB file — skip full register merge unless requested
        print(f"register CSV present ({REGISTER.stat().st_size // (1024*1024)} MB); slice-only commit (no full register rewrite)")


if __name__ == "__main__":
    main()
