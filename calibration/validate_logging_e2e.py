"""
Controlled end-to-end check: ED_CALIBRATION_LOG + compute_signals + calibration_decision_log row count.

Run from repo root:
  ED_CALIBRATION_LOG=1 python -m calibration.validate_logging_e2e

Does not replace production monitoring; proves one row per successful compute_signals call.
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("ED_CALIBRATION_LOG", "1")

from db import DB_PATH, EdDB  # noqa: E402
from signal_types import SignalInput  # noqa: E402


def _inp(*, refresh_ts_utc: float | None = None) -> SignalInput:
    return SignalInput(
        ticker="SPY",
        timeframe="1m",
        expiry=None,
        dte=None,
        spot=450.0,
        candle_open=449.5,
        candle_high=450.2,
        candle_low=449.3,
        candle_close=450.0,
        candle_direction="up",
        candle_body_pts=0.5,
        candle_range_pts=0.9,
        vwap=449.8,
        vwap_side="above",
        vwap_dist_pts=0.2,
        zone="pin_bull",
        prev_zone="pin_bull",
        zone_since_bars=5,
        zone_since_bars_1m=5,
        zone_since_bars_5m=1,
        call_gamma_wall=452.0,
        put_gamma_wall=448.0,
        call_delta_wall=None,
        put_delta_wall=None,
        gamma_inflection=None,
        delta_inflection=None,
        call_oi_wall=None,
        put_oi_wall=None,
        call_vanna_wall=None,
        put_vanna_wall=None,
        pin_width_pts=2.0,
        dist_call_gamma_wall=2.0,
        dist_put_gamma_wall=-2.0,
        dist_call_delta_wall=None,
        dist_put_delta_wall=None,
        dist_gamma_inflection=None,
        dist_delta_inflection=None,
        dist_call_oi_wall=None,
        dist_put_oi_wall=None,
        dist_call_vanna_wall=None,
        dist_put_vanna_wall=None,
        nearest_above_name="CGW",
        nearest_above_val=452.0,
        nearest_above_dist=2.0,
        nearest_below_name="PGW",
        nearest_below_val=448.0,
        nearest_below_dist=2.0,
        net_gamma=1000.0,
        net_delta=500.0,
        net_vanna=None,
        charm_net=None,
        charm_direction="buying",
        charm_drift_toward=450.0,
        charm_magnitude="moderate",
        dex_magnitude="moderate",
        iv_level=0.15,
        iv_direction="flat",
        realized_vol=None,
        atr=1.5,
        put_call_oi_ratio=0.9,
        oi_center=None,
        recent_crosses=[],
        ceiling_tests_today=0,
        floor_tests_today=0,
        spy_chg_pct=0.3,
        qqq_chg_pct=0.35,
        iwm_chg_pct=0.25,
        vix_level=18.0,
        mins_to_close=120.0,
        em_upper=452.0,
        em_lower=448.0,
        order_flow_score=0.2,
        order_flow_direction="bullish",
        order_flow_readiness="yellow",
        refresh_ts_utc=refresh_ts_utc,
    )


def main() -> int:
    import argparse
    import sqlite3

    from calibration.schema import ensure_calibration_schema
    from calibration.v2_live_logging import append_live_v2_calibration_decision
    from db import (
        CANONICAL_TIMEFRAME,
        SnapshotRow,
        build_ts_et,
        configure_sqlite_connection,
        market_session,
        now_et,
        utc_ts,
    )
    from signals import compute_signals
    from v2_decision import build_module_a_a1_decision

    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=3, help="Number of compute_signals invocations")
    args = ap.parse_args()
    n_calls = max(1, args.calls)
    conn = sqlite3.connect(str(DB_PATH))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    before = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    conn.close()

    db = EdDB(DB_PATH)
    _et = now_et()
    for i in range(n_calls):
        t0 = time.time()
        rts = float(utc_ts())
        inp = _inp(refresh_ts_utc=rts)
        out = compute_signals(inp, db=db)
        canonical = out.canonical_forecast
        v2_decision = build_module_a_a1_decision(
            {
                "ticker": inp.ticker,
                "fusion_available": True,
                "fusion_dominant_direction": canonical.direction,
                "fusion_dominant_prob": max(
                    float(canonical.probability_up),
                    float(canonical.probability_down),
                    float(canonical.probability_flat),
                ),
                "execution_mode": getattr(out.call, "execution_mode", None),
            }
        )
        append_live_v2_calibration_decision(
            db_path=DB_PATH,
            calibration_payload=out.calibration_payload,
            v2_decision=v2_decision,
            colocated_snapshot_ts_utc=float(rts),
        )
        t1 = time.time()
        snap = SnapshotRow(
            ticker="SPY",
            timeframe=CANONICAL_TIMEFRAME,
            ts_utc=rts,
            ts_et=build_ts_et(_et),
            et_hour=_et.hour,
            et_minute=_et.minute,
            market_session=market_session(_et.hour, _et.minute,
                                          et_date=_et.strftime("%Y-%m-%d")),  # RC-278
            spot=450.0,
        )
        db.insert_snapshot(snap)
        print(f"call {i} signal={out.call.signal} refresh_ts_utc={rts:.3f} wall_s=[{t0:.3f},{t1:.3f}]")
        time.sleep(0.15)

    conn = sqlite3.connect(str(DB_PATH))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    after = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    conn.close()
    delta = after - before
    print(f"rows_before={before} rows_after={after} delta={delta} expected={n_calls}")
    return 0 if delta == n_calls else 1


if __name__ == "__main__":
    sys.exit(main())
