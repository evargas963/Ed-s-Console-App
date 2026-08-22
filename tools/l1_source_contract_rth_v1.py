#!/usr/bin/env python3
"""P0.1-B: authenticate Schwab LEVELONE or fail closed; score same-ms old-rule loss.

Uses production StreamClient / add_level_one_equity_handler / level_one_equity_subs
via order_flow_streaming.collect_level_one_receipts. Does not invent a second feed.

# next-rth-ok: derived from time_et.next_rth_session_et
# universal-scope-ok: default universe is CORE_TICKERS parsed from server.py
# chart-intent-ok: this tool banks L1 source evidence; Chart consumer remains open.

Exit contract:
  0 = requested live validation proven (receipts collected)
  2 = NOT_PROVEN / required capability unavailable / blocked
  2 = malformed or environment failure

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

from time_et import is_trading_day_et, next_rth_session_et, now_et  # noqa: E402
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


def _token_path() -> Path:
    env = os.environ.get("SCHWAB_TOKEN_PATH", "").strip()
    return Path(env) if env else TOKEN_PATH


def session_blockers(*, require_rth: bool) -> list[str]:
    """Auth authority is schwab_client.inspect_token_file + config.schwab_live_blocked_for.

    A file's absence is not enough if SCHWAB_TOKEN_PATH names a usable token.
    A key's presence is not enough if the token is not refreshable.
    """
    from config import schwab_live_blocked_for
    from schwab_client import auth_is_refreshable, inspect_token_file

    et = now_et()
    blockers: list[str] = []
    iso = et.date().isoformat()
    if require_rth:
        if not is_trading_day_et(iso):
            blockers.append("RTH_ONLY")
        else:
            from time_et import session_close_mins_for_et_date
            close = session_close_mins_for_et_date(iso)
            mins = et.hour * 60 + et.minute
            if close is None or mins >= close:
                blockers.append("RTH_ONLY")

    token = _token_path()
    inv = inspect_token_file(str(token))
    usable = (
        inv.file_exists
        and inv.json_valid
        and inv.has_access_token
        and (auth_is_refreshable(inv) or not inv.is_expired)
    )
    if not usable:
        blockers.append("EXTERNAL_DATA_UNAVAILABLE")

    api_key = os.environ.get("SCHWAB_API_KEY", "").strip()
    secret = os.environ.get("SCHWAB_APP_SECRET", "").strip()
    if schwab_live_blocked_for(api_key=api_key or None, app_secret=secret or None):
        if "EXTERNAL_DATA_UNAVAILABLE" not in blockers:
            blockers.append("EXTERNAL_DATA_UNAVAILABLE")
    elif usable and (not api_key or not secret):
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


def production_l1_wiring_facts(src: str | None = None) -> dict[str, Any]:
    """Static AST wiring. Not authenticated operation / receipts."""
    from tools.hard_law_runtime import production_l1_wiring_facts as _facts
    text = src if src is not None else (ROOT / "order_flow_streaming.py").read_text(encoding="utf-8")
    return _facts(text)


def production_l1_path_facts() -> dict[str, Any]:
    """Backward-compatible name. Proof class is static_wiring, not live capability."""
    return production_l1_wiring_facts()


def resolve_stream_account_id(client: Any) -> Any:
    """Same account-number leaves server.py / schwab_full_field_inventory use."""
    resp = client.get_account_numbers()
    payload = resp.json() if hasattr(resp, "json") else resp
    if not payload:
        return None
    accs = payload if isinstance(payload, list) else [payload]
    first = accs[0] if accs else {}
    if not isinstance(first, dict):
        return None
    raw = first.get("accountNumber") or first.get("hashValue")
    if not raw and first:
        raw = next(iter(first.values()), None)
    if raw is None:
        return None
    return int(raw) if str(raw).isdigit() else raw


def run_live_levelone(
    *,
    symbols: list[str],
    duration_sec: float = 8.0,
    collect_fn: Any | None = None,
    client: Any | None = None,
    account_id: Any | None = None,
) -> dict[str, Any]:
    """Call the production collect path. collect_fn is injectable for tests."""
    from order_flow_streaming import collect_level_one_receipts

    fn = collect_fn or collect_level_one_receipts
    receipts = fn(client, account_id, symbols, duration_sec=duration_sec)
    return {
        "proof_class": "live_receipts",
        "live_receipts": len(receipts),
        "symbols_seen": sorted({str(r.get("symbol") or "") for r in receipts if r.get("symbol")}),
        "receipts": receipts,
    }


def write_report(payload: dict[str, Any]) -> Path:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return OUT_PATH


def _exit_for(report: dict[str, Any]) -> int:
    if report.get("verdict") == "PASS" and int(report.get("live_receipts") or 0) > 0:
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyze-frames", type=Path, default=None)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--symbols", default="", help="Comma symbols; default CORE_TICKERS")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--duration-sec", type=float, default=8.0)
    args = parser.parse_args(argv)

    et = now_et()
    next_iso, next_wd = next_rth_session_et(et)
    universe = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        or default_universe_from_core()
    )
    blockers = session_blockers(require_rth=bool(args.live))
    wiring = production_l1_wiring_facts()
    report: dict[str, Any] = {
        "schema": "l1_source_contract_rth_v1",
        "measured_et": et.isoformat(),
        "weekday": et.strftime("%A"),
        "trading_day": is_trading_day_et(et.date().isoformat()),
        "next_rth": f"{next_iso} {next_wd}",
        "universe": universe,
        "blockers": blockers,
        "source_contract": l1.source_contract(),
        "production_l1_wiring": wiring,
        "production_l1_path": wiring,
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
            try:
                live = run_live_levelone(symbols=universe, duration_sec=float(args.duration_sec))
                report["live_receipts"] = int(live.get("live_receipts") or 0)
                report["live_symbols_seen"] = live.get("symbols_seen") or []
                report["live_proof_class"] = live.get("proof_class")
                if report["live_receipts"] > 0:
                    report["verdict"] = "PASS"
                else:
                    report["verdict"] = "NOT_PROVEN"
                    report["live_error"] = "connected path returned zero receipts"
            except Exception as e:  # noqa: BLE001 — fail closed with the machine error
                report["verdict"] = "NOT_PROVEN"
                report["live_error"] = f"{type(e).__name__}: {e}"
    else:
        if blockers:
            report["session_note"] = "live not requested; blockers recorded for honesty"

    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(dest), "verdict": report["verdict"], "blockers": blockers,
                      "live_receipts": report["live_receipts"]}))
    return _exit_for(report) if args.live else (0 if not blockers or args.analyze_frames else 2)


if __name__ == "__main__":
    raise SystemExit(main())
