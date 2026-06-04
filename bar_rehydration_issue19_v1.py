"""
Issue 19 — Controlled Schwab 1m bar rehydration into price_bars_1m.

Uses windowed GET /marketdata/v1/pricehistory (minute) + market_data_adapter.schwab_candles_to_bars
+ EdDB.upsert_1m_bars (ticker_storage_key). Targets tickers in repair-scoped pin_neutral cohort.

Phases: baseline JSON → optional backup → fetch/upsert per window → post-audit → optional pin_neutral repair.

CLI:
  python bar_rehydration_issue19_v1.py --db data/ed_console.db --dry-run
  python bar_rehydration_issue19_v1.py --db data/ed_console.db
  python bar_rehydration_issue19_v1.py --db data/ed_console.db --skip-backup --no-repair
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import EdDB, get_snapshot_sql
from distance_option_a_backfill_v1 import copy_db_file_backup
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1, OUTCOME_BAR_SPECS
from market_data_adapter import schwab_candles_to_bars
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME

FLAG_KEY = "bar_rehydration_issue19_v1"
FLAG_COMPLETE = "rehydration_complete"

DEFAULT_START_BUFFER_SEC = 86400.0
FORWARD_PAD_SEC = float(max(s[2] for s in OUTCOME_BAR_SPECS)) * 60.0 + 120.0


def _load_bar_audit_module():
    p = ROOT / "tools" / "bar_history_recovery_audit_v1.py"
    spec = importlib.util.spec_from_file_location("bar_history_recovery_audit_v1", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load audit module from {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cohort_tickers_and_bounds(db: EdDB) -> list[dict]:
    """One row per distinct ticker: ticker, min_ts, max_ts from repair-scoped pin_neutral."""
    with db._connect() as conn:
        rows = conn.execute(
            get_snapshot_sql("bar_rehydration_issue19_v1.py:57"),
            (
                CANONICAL_TIMEFRAME,
                DERIVED_TIMEFRAME,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        ).fetchall()
    return [dict(r) for r in rows]


def _fetch_minute_window(client, symbol: str, start_utc: datetime, end_utc: datetime):
    import schwab as _schwab

    PH = _schwab.client.Client.PriceHistory
    last_err = None
    last_body = None
    for attempt in range(3):
        try:
            resp = client.get_price_history(
                symbol,
                period_type=None,
                period=None,
                frequency_type=PH.FrequencyType.MINUTE,
                frequency=PH.Frequency.EVERY_MINUTE,
                start_datetime=start_utc,
                end_datetime=end_utc,
                need_extended_hours_data=True,
            )
            if resp is not None and getattr(resp, "status_code", None) == 200:
                return resp
            last_err = getattr(resp, "status_code", None)
            try:
                last_body = (resp.text or "")[:800] if resp is not None else None
            except Exception:
                last_body = None
        except Exception as e:
            last_err = str(e)
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(
        f"Schwab price history failed after retries: {last_err} body={last_body!r}"
    )


def run_rehydration(
    db_path: Path,
    *,
    dry_run: bool = False,
    skip_backup: bool = False,
    window_days: int = 7,
    start_buffer_sec: float = DEFAULT_START_BUFFER_SEC,
    run_repair_after: bool = True,
    skip_normalized_refresh: bool = False,
    allow_noncanonical: bool = False,
) -> dict:
    db_path = db_path.resolve()
    audit_mod = _load_bar_audit_module()
    out: dict = {
        "schema": "bar_rehydration_issue19_v1",
        "db_path": str(db_path),
        "dry_run": dry_run,
        "window_days": window_days,
        "forward_pad_sec": FORWARD_PAD_SEC,
        "start_buffer_sec": float(start_buffer_sec),
    }

    conn = audit_mod.connect_bar_audit(db_path)
    try:
        baseline = audit_mod.collect_bar_recovery_audit(conn, db_path)
    finally:
        conn.close()
    out["baseline"] = baseline
    baseline_path = db_path.parent / "bar_rehydration_baseline_issue19_v1.json"
    baseline_path.write_text(json.dumps(baseline, indent=2, default=str) + "\n", encoding="utf-8")
    out["baseline_json"] = str(baseline_path)

    cohort = _cohort_tickers_and_bounds(EdDB(db_path, allow_noncanonical=allow_noncanonical))
    out["cohort_tickers"] = cohort
    if not cohort:
        out["note"] = "no cohort tickers; abort"
        return out

    if dry_run:
        out["status"] = "dry_run_complete"
        return out

    if not skip_backup:
        out["backup_path"] = str(copy_db_file_backup(db_path, label="pre_bar_rehydration_issue19_v1"))

    db = EdDB(db_path)
    client = None
    try:
        from server import get_client

        client = get_client()
    except Exception as e:
        out["error"] = f"Schwab client init failed: {e}"
        return out

    windows_log: list[dict] = []
    total_bars_written = 0

    for spec in cohort:
        sym = (spec["ticker"] or "").strip()
        if not sym:
            continue
        t0 = float(spec["min_snap_ts"]) - float(start_buffer_sec)
        t1 = float(spec["max_snap_ts"]) + FORWARD_PAD_SEC
        start_dt = datetime.fromtimestamp(t0, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(t1, tz=timezone.utc)
        cap = datetime.now(timezone.utc) - timedelta(seconds=60)
        if end_dt > cap:
            end_dt = cap
        if start_dt >= end_dt:
            windows_log.append(
                {
                    "ticker_db": sym,
                    "skipped": True,
                    "reason": "start_dt >= end_dt after capping to now",
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                }
            )
            continue

        span_sec = (end_dt - start_dt).total_seconds()
        # schwab-py docs: ~48d max for minute data; use one request if span fits to avoid 400s on tiny tail windows.
        use_single = span_sec <= float(max(1, window_days) * 86400 * 5)

        def _one_window(cursor: datetime, w_end: datetime) -> None:
            nonlocal total_bars_written
            if w_end <= cursor:
                return
            wl = {
                "ticker_db": sym,
                "schwab_symbol": sym,
                "window_start_utc": cursor.isoformat(),
                "window_end_utc": w_end.isoformat(),
                "http_status": None,
                "n_candles": 0,
                "first_candle_ms": None,
                "last_candle_ms": None,
                "error": None,
            }
            try:
                resp = _fetch_minute_window(client, sym, cursor, w_end)
                wl["http_status"] = resp.status_code
                data = resp.json()
                candles = data.get("candles") or []
                wl["n_candles"] = len(candles)
                if candles:
                    wl["first_candle_ms"] = candles[0].get("datetime")
                    wl["last_candle_ms"] = candles[-1].get("datetime")
                bars = schwab_candles_to_bars(candles)
                total_bars_written += db.upsert_1m_bars(sym, bars)
            except Exception as e:
                wl["error"] = str(e)
                windows_log.append(wl)
                raise
            windows_log.append(wl)

        if use_single:
            _one_window(start_dt, end_dt)
        else:
            cursor = start_dt
            while cursor < end_dt:
                w_end = min(cursor + timedelta(days=window_days), end_dt)
                _one_window(cursor, w_end)
                cursor = w_end
                time.sleep(0.35)
        time.sleep(0.35)

    out["windows"] = windows_log
    out["total_bar_dicts_upserted"] = total_bars_written

    conn2 = audit_mod.connect_bar_audit(db_path)
    try:
        post = audit_mod.collect_bar_recovery_audit(conn2, db_path)
    finally:
        conn2.close()
    out["post_rehydration"] = post
    post_path = db_path.parent / "bar_rehydration_post_issue19_v1.json"
    post_path.write_text(json.dumps(post, indent=2, default=str) + "\n", encoding="utf-8")
    out["post_rehydration_json"] = str(post_path)

    feasible = int(post.get("pin_neutral_anchor_feasible_count") or 0)
    out["pin_neutral_anchor_feasible_after"] = feasible

    if feasible > 0:
        if not dry_run:
            db.set_schema_flag(FLAG_KEY, FLAG_COMPLETE)
        out["schema_flag"] = {FLAG_KEY: FLAG_COMPLETE}
    else:
        out["schema_flag"] = {"skipped": "pin_neutral_anchor_feasible_count still 0"}

    repair_audit: dict | None = None
    if run_repair_after and feasible > 0:
        from pin_neutral_outcome_repair_v1 import run_repair as run_pin_repair

        repair_audit = run_pin_repair(
            db_path, dry_run=False, skip_backup=False, backup_label="pre_pin_neutral_after_bar_rehydration_issue19_v1"
        )
        out["pin_neutral_repair"] = repair_audit
        rp = db_path.parent / "pin_neutral_repair_after_rehydration_issue19_v1.json"
        rp.write_text(json.dumps(repair_audit, indent=2, default=str) + "\n", encoding="utf-8")
        out["pin_neutral_repair_json"] = str(rp)

        updates = int(repair_audit.get("updates_executed") or 0)
        if updates > 0 and not skip_normalized_refresh:
            import subprocess

            r = subprocess.run(
                [sys.executable, str(ROOT / "snapshot_normalizer.py")],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=600,
            )
            out["snapshot_normalizer"] = {
                "returncode": r.returncode,
                "stdout_tail": (r.stdout or "")[-4000:],
                "stderr_tail": (r.stderr or "")[-2000:],
            }

    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-backup", action="store_true")
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument(
        "--start-buffer-sec",
        type=float,
        default=DEFAULT_START_BUFFER_SEC,
        help="Seconds subtracted from cohort min snapshot time for Schwab window start (default 86400). "
        "Increase to close early lead-in gaps (e.g. 172800 or 259200 for $SPX ~24–48h).",
    )
    ap.add_argument("--no-repair", action="store_true")
    ap.add_argument("--no-normalized-refresh", action="store_true")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    if not args.db.is_file():
        raise SystemExit(f"DB not found: {args.db}")
    require_canonical_db_target(args, tool_name="bar_rehydration_issue19_v1", write_capable=True)
    r = run_rehydration(
        args.db,
        dry_run=args.dry_run,
        skip_backup=args.skip_backup,
        window_days=args.window_days,
        start_buffer_sec=args.start_buffer_sec,
        run_repair_after=not args.no_repair,
        skip_normalized_refresh=args.no_normalized_refresh,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    summary_path = args.db.parent / "bar_rehydration_issue19_v1_last_run.json"
    summary_path.write_text(json.dumps(r, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
