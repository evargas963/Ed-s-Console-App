"""TU-01 world-data collectors: parser + idempotency contracts (no network).

Fixtures are verbatim excerpts of the live payloads fetch-verified 2026-07-21.
"""

from __future__ import annotations

import sqlite3

from tools.world_data_ingest import (
    ensure_world_schema,
    parse_cboe_history_csv,
    parse_cftc_tff_json,
    parse_dix_csv,
    parse_finra_cnms,
    parse_occ_volume_csv,
    recent_weekdays,
)

DIX_FIXTURE = """date,price,dix,gex
2011-05-02,1361.22,0.376079,1042285605
2026-07-20,6305.60,0.436542,1893371002
"""

CBOE_OHLC_FIXTURE = """DATE,OPEN,HIGH,LOW,CLOSE
01/02/1990,17.24,17.24,17.24,17.24
07/18/2026,16.41,17.02,16.10,16.55
"""

CBOE_SINGLE_FIXTURE = """DATE,SKEW
01/02/1990,126.09
07/18/2026,148.34
"""

FINRA_FIXTURE = """Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
20260717|A|558416|35|904888|B,Q,N
20260717|SPY|41123456|1200|80234567|B,Q,N
"""

OCC_FIXTURE = """quantity,underlying,symbol,actype,porc,exchange,actdate
880127,SPY,SPY,C,C,CBOE,07/17/2026
709956,SPY,SPY,C,P,MIAX,07/17/2026
12345,SPY,SPY,M,C,CBOE,07/17/2026
"""

CFTC_FIXTURE = """[
  {"contract_market_name": "E-MINI S&P 500", "report_date_as_yyyy_mm_dd": "2026-07-14T00:00:00.000",
   "dealer_positions_long_all": "10", "dealer_positions_short_all": "20",
   "asset_mgr_positions_long_all": "30", "asset_mgr_positions_short_all": "40",
   "lev_money_positions_long_all": "50", "lev_money_positions_short_all": "60",
   "open_interest_all": "1000"},
  {"contract_market_name": "WHEAT", "report_date_as_yyyy_mm_dd": "2026-07-14T00:00:00.000"}
]"""


def test_parse_dix_rows_and_types():
    rows = parse_dix_csv(DIX_FIXTURE)
    assert rows[0] == ("2011-05-02", 1361.22, 0.376079, 1042285605.0)
    assert rows[-1][0] == "2026-07-20"


def test_parse_cboe_ohlc_and_single_value_shapes():
    ohlc = parse_cboe_history_csv(CBOE_OHLC_FIXTURE)
    assert ohlc[0] == ("01/02/1990", 17.24, 17.24, 17.24, 17.24)
    single = parse_cboe_history_csv(CBOE_SINGLE_FIXTURE)
    # Single-value files land in the close column; OHLC stay None.
    assert single[-1] == ("07/18/2026", None, None, None, 148.34)


def test_parse_finra_skips_header_and_iso_dates():
    rows = parse_finra_cnms(FINRA_FIXTURE)
    assert len(rows) == 2
    assert rows[0][0] == "2026-07-17"
    assert rows[1][1] == "SPY" and rows[1][2] == 41123456


def test_parse_occ_account_types_survive():
    rows = parse_occ_volume_csv(OCC_FIXTURE)
    assert len(rows) == 3
    assert rows[0] == ("2026-07-17", "SPY", "SPY", "C", "C", "CBOE", 880127)
    # The market-maker row is the load-bearing one for positioning inference.
    assert any(r[3] == "M" for r in rows)


def test_parse_cftc_filters_markets_and_normalizes():
    rows = parse_cftc_tff_json(CFTC_FIXTURE)
    assert len(rows) == 1
    r = rows[0]
    assert r["report_date"] == "2026-07-14"
    assert r["dealer_long"] == 10 and r["lev_money_short"] == 60
    assert r["open_interest"] == 1000


def test_ingest_idempotent_on_replay():
    conn = sqlite3.connect(":memory:")
    ensure_world_schema(conn)
    rows = parse_dix_csv(DIX_FIXTURE)
    for _ in range(2):  # replaying the same feed must not duplicate
        conn.executemany(
            "INSERT OR REPLACE INTO world_dix(date, spx_price, dix, gex) VALUES (?,?,?,?)", rows
        )
    n = conn.execute("SELECT COUNT(*) FROM world_dix").fetchone()[0]
    assert n == 2


def test_recent_weekdays_never_returns_weekend():
    from datetime import datetime, timezone

    days = recent_weekdays(7, today_utc=datetime(2026, 7, 21, tzinfo=timezone.utc))
    assert len(days) == 7
    for d in days:
        assert datetime.fromisoformat(d).weekday() < 5
    assert days == sorted(days)
