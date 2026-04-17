"""
Phase 2 verification: insert N snapshots via build_market_state + EdDB.insert_snapshot,
then validate nearest_*_dist Option A on snapshot_id > cutoff.

Run from repo root: python tools/phase2_forward_write_verify.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import DB_PATH, EdDB, SnapshotRow, build_ts_et, get_snapshot_sql, market_session
from math_exposure_core import ExposureRow
from math_levels import TotalsRow, WallsRow
from market_context import MarketContext, PriceLevels
from market_state import build_market_state
from math_volatility import session_bucket
from timeframe_config import CANONICAL_TIMEFRAME

ET = ZoneInfo("America/New_York")
N_INSERTS = 110
TICKER = "PHASE2VERIFY"


def _make_walls(spot: float) -> list[WallsRow]:
    return [
        WallsRow(
            "CONSENSUS",
            None,
            spot + 8,
            1.0,
            spot - 7,
            1.0,
            "call",
            spot + 8,
            1.0,
            spot + 9,
            1.0,
            spot - 9,
            1.0,
            "call",
            spot + 9,
            1.0,
            spot + 10,
            1.0,
            spot - 10,
            1.0,
            "call",
            spot + 10,
            1.0,
        )
    ]


def _make_consensus(spot: float) -> ExposureRow:
    return ExposureRow(
        "CONSENSUS",
        None,
        1.0,
        1.0,
        spot,
        spot - 1,
        spot + 1,
        spot,
        "Moderate",
        "Neutral",
    )


def main() -> None:
    if not DB_PATH.is_file():
        print(json.dumps({"error": "db_not_found", "path": str(DB_PATH)}))
        sys.exit(2)

    db = EdDB(DB_PATH)
    with db._connect() as conn:
        row = conn.execute(get_snapshot_sql("tools/phase2_forward_write_verify.py:87")).fetchone()
        cutoff = int(row[0])

    totals = TotalsRow(
        "CONSENSUS",
        None,
        1,
        1,
        2,
        1,
        1,
        2,
        100,
        100,
        200,
        1.0,
        0.2,
        None,
    )
    ctx = MarketContext(vix=18.0, session_label="RTH")
    base_ts = time.time()

    for i in range(N_INSERTS):
        spot = 450.0 + i * 0.02
        ts = base_ts + float(i)
        et_dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET)
        eh, em = et_dt.hour, et_dt.minute
        walls = _make_walls(spot)
        consensus = _make_consensus(spot)
        pl = PriceLevels(
            vwap=spot + 2,
            today_open=spot,
            today_high=spot + 3,
            today_low=spot - 3,
            pdc=spot - 1,
        )
        ms = build_market_state(
            ticker=TICKER,
            selected_exp="2026-04-15",
            session_label="RTH",
            spot=spot,
            bid=spot - 0.05,
            ask=spot + 0.05,
            consensus_summary=consensus,
            contracts_use=[],
            walls=walls,
            totals=[totals],
            price_levels=pl,
            mkt_ctx=ctx,
            live_on=False,
            zone_since_bars=1,
            zone_since_bars_5m=1,
            prev_zone=None,
            et_hour=eh,
            et_minute=em,
            db=None,
            refresh_ts_utc=ts,
        )
        snap = SnapshotRow(
            ticker=TICKER,
            timeframe=CANONICAL_TIMEFRAME,
            ts_utc=ts,
            ts_et=build_ts_et(et_dt),
            et_hour=eh,
            et_minute=em,
            market_session=market_session(eh, em),
            spot=float(spot),
            session_bucket=session_bucket(eh, em),
            zone=ms.zone,
            vwap=getattr(pl, "vwap", None),
            vwap_side=getattr(ms, "vwap_side", None),
            nearest_above_name=ms.nearest_above_name,
            nearest_above_val=ms.nearest_above_val,
            nearest_above_dist=ms.nearest_above_dist,
            nearest_below_name=ms.nearest_below_name,
            nearest_below_val=ms.nearest_below_val,
            nearest_below_dist=ms.nearest_below_dist,
        )
        db.insert_snapshot(snap)

    conn = sqlite3.connect(str(DB_PATH))
    def q(sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return conn.execute(sql, params)

    stats = {}
    stats["cutoff_snapshot_id"] = cutoff
    stats["inserts_requested"] = N_INSERTS
    stats["new_max_snapshot_id"] = int(
        q(get_snapshot_sql("tools/phase2_forward_write_verify.py:max_snapshot_id")).fetchone()[0]
    )
    r = q(
        get_snapshot_sql("tools/phase2_forward_write_verify.py:post_cutoff_agg"),
        (cutoff, CANONICAL_TIMEFRAME),
    ).fetchone()
    stats["post_cutoff"] = {
        "row_count": int(r[0]),
        "nad_min": r[1],
        "nad_max": r[2],
        "nbd_min": r[3],
        "nbd_max": r[4],
        "nad_negative_count": int(r[5] or 0),
        "nbd_negative_count": int(r[6] or 0),
    }
    leg = q(
        get_snapshot_sql("tools/phase2_forward_write_verify.py:legacy_nbd_neg"),
        (cutoff, CANONICAL_TIMEFRAME),
    ).fetchone()[0]
    stats["legacy_pre_cutoff_nbd_negative"] = int(leg)
    tot_neg = q(
        get_snapshot_sql("tools/phase2_forward_write_verify.py:total_nbd_neg"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()[0]
    stats["table_total_nbd_negative"] = int(tot_neg)
    conn.close()

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
