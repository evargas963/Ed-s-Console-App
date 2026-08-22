#!/usr/bin/env python3
"""P0.1-B: authenticate Schwab LEVELONE or fail closed; score same-ms old-rule loss.

# next-rth-ok: 2026-08-24 Monday
# universal-scope-ok: default universe is CORE_TICKERS parsed from server.py;
# --symbols overrides. Historical probe frames are fixtures, not a rate.
# chart-intent-ok: this tool banks L1 source evidence; Chart consumer remains open.

Does not close live empirical master items. A non-RTH day or missing token is
EXTERNAL_DATA_UNAVAILABLE / RTH_ONLY, never PASS.

Usage:
  python tools/l1_source_contract_rth_v1.py --analyze-frames reports/of_capability_probe/20260820T134927Z/frames
  python tools/l1_source_contract_rth_v1.py --live
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from time_et import is_trading_day_et, now_et  # noqa: E402
import l1_trade_observation as l1  # noqa: E402

OUT_PATH = ROOT / "reports" / "l1_source_contract_rth_latest.json"
TOKEN_PATH = ROOT / "schwab_token.json"
SERVER_PY = ROOT / "server.py"

L1_FIELD_CATALOG = (
    "BID_PRICE",
    "ASK_PRICE",
    "LAST_PRICE",
    "BID_SIZE",
    "ASK_SIZE",
    "LAST_SIZE",
    "TOTAL_VOLUME",
    "QUOTE_TIME_MILLIS",
    "TRADE_TIME_MILLIS",
    "BID_TIME_MILLIS",
    "ASK_TIME_MILLIS",
    "EXCHANGE_ID",
    "BID_MIC_ID",
    "ASK_MIC_ID",
    "LAST_MIC_ID",
    "BID_ID",
    "ASK_ID",
    "LAST_ID",
)


def default_universe_from_core() -> list[str]:
    """CORE_TICKERS in server.py without importing FastAPI."""
    text = SERVER_PY.read_text(encoding="utf-8")
    m = re.search(r"CORE_TICKERS:\s*list\[str\]\s*=\s*\[(.*?)\]", text, re.S)
    if not m:
        raise SystemExit("FATAL: CORE_TICKERS not parseable from server.py")
    found = re.findall(r'"([A-Z][A-Z0-9.]{0,7})"', m.group(1))
    if len(found) < 3:
        raise SystemExit("FATAL: CORE_TICKERS parse produced too few symbols")
    return found


def session_blockers(*, require_rth: bool) -> list[str]:
    et = now_et()
    blockers: list[str] = []
    if require_rth and not is_trading_day_et(et.date().isoformat()):
        blockers.append("RTH_ONLY")
    if not TOKEN_PATH.exists():
        blockers.append("EXTERNAL_DATA_UNAVAILABLE")
    if os.environ.get("ED_CI_OFFLINE", "").strip() in {"1", "true", "TRUE"}:
        if "EXTERNAL_DATA_UNAVAILABLE" not in blockers and not TOKEN_PATH.exists():
            blockers.append("EXTERNAL_DATA_UNAVAILABLE")
    if not os.environ.get("SCHWAB_API_KEY") and not TOKEN_PATH.exists():
        if "EXTERNAL_DATA_UNAVAILABLE" not in blockers:
            blockers.append("EXTERNAL_DATA_UNAVAILABLE")
    return blockers


def _content_rows_from_frame(obj: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    content = obj.get("content") or []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                rows.append(item)
    return rows


def analyze_frame_dir(frame_dir: Path) -> dict[str, Any]:
    prints: list[dict[str, Any]] = []
    field_seen: dict[str, int] = {k: 0 for k in L1_FIELD_CATALOG}
    services: set[str] = set()
    files = 0
    for path in sorted(frame_dir.glob("LEVELONE_EQUITIES_*_decoded.json")):
        files += 1
        obj = json.loads(path.read_text(encoding="utf-8"))
        services.add(str(obj.get("service") or ""))
        for item in _content_rows_from_frame(obj):
            for k in L1_FIELD_CATALOG:
                if k in item and item.get(k) is not None:
                    field_seen[k] += 1
            got = l1.extract_vendor_print(item)
            if got is None:
                continue
            prints.append({**got, "instrument": item.get("key")})
    scored = l1.quantify_same_ms_old_rule_loss(prints)
    scored["is_live_rate"] = False
    scored["frame_files"] = files
    scored["services"] = sorted(services)
    scored["field_presence_counts"] = field_seen
    scored["source"] = str(frame_dir)
    return scored


def production_l1_path_facts() -> dict[str, Any]:
    src = (ROOT / "order_flow_streaming.py").read_text(encoding="utf-8")
    return {
        "uses_level_one_equity_subs": "level_one_equity_subs" in src,
        "uses_level_one_equity_handler": "add_level_one_equity_handler" in src,
        "uses_timesale_subs": "timesale_equity_subs" in src.lower()
        or "timesale_equity_subs" in src,
        "imports_alpaca": "alpaca" in src.lower(),
        "pushes_level_one": "push_level_one" in src,
        "quote_fallback_is_named": "rest_fallback_explicit" in src,
    }


def write_report(payload: dict[str, Any]) -> Path:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return OUT_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyze-frames", type=Path, default=None)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--symbols", default="", help="Comma symbols; default CORE_TICKERS")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)

    et = now_et()
    universe = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        or default_universe_from_core()
    )
    blockers = session_blockers(require_rth=bool(args.live))
    path_facts = production_l1_path_facts()
    report: dict[str, Any] = {
        "schema": "l1_source_contract_rth_v1",
        "measured_et": et.isoformat(),
        "weekday": et.strftime("%A"),
        "trading_day": is_trading_day_et(et.date().isoformat()),
        "next_rth": "2026-08-24 Monday",
        "universe": universe,
        "blockers": blockers,
        "source_contract": l1.source_contract(),
        "production_l1_path": path_facts,
        "live_attempted": bool(args.live),
        "live_receipts": 0,
        "verdict": "NOT_PROVEN",
    }

    if args.analyze_frames is not None:
        report["historical_frame_score"] = analyze_frame_dir(args.analyze_frames)
        report["historical_frame_score"]["rate_claim"] = "FORBIDDEN — fixture / max-12 sample"

    if args.live:
        if blockers:
            report["verdict"] = "NOT_PROVEN"
            report["live_error"] = "live blocked: " + ",".join(blockers)
        else:
            report["verdict"] = "NOT_PROVEN"
            report["live_error"] = "live runner reservation: connect path not executed in this invocation"
    else:
        if blockers:
            report["session_note"] = "live not requested; blockers recorded for honesty"

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(dest), "verdict": report["verdict"], "blockers": blockers}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
