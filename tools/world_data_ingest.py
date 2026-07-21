"""World-data collectors: free external feeds -> ed_console.db world_* tables.

MECHANICAL LOCK 2026-07-21 (operator): designs are never scoped to currently-
captured Schwab data. Every source below was fetch-verified live 2026-07-21:

  dix    SqueezeMetrics daily DIX/GEX      https://squeezemetrics.com/monitor/static/DIX.csv
  vol    Cboe index history CSVs           https://cdn.cboe.com/api/global/us_indices/daily_prices/{IDX}_History.csv
  finra  FINRA CNMS daily short volume     https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt
  occ    OCC cleared volume by account     https://marketdata.theocc.com/volume-query (YYYYMMDD date format!)
  cftc   CFTC TFF futures positioning      https://publicreporting.cftc.gov/resource/gpe5-46if.json

All ingests are idempotent (INSERT OR REPLACE on natural keys). Each source
fails loud in its own summary row; one dead feed never blocks the others.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "ed_console.db"
HTTP_TIMEOUT_SEC = 30.0
# FINRA's CDN 403s non-browser agents (probed 2026-07-21); browser UA passes everywhere.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

DIX_URL = "https://squeezemetrics.com/monitor/static/DIX.csv"
CBOE_HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{index}_History.csv"
VOL_INDICES = ("VIX", "VIX9D", "VIX1D", "VVIX", "SKEW")
FINRA_CNMS_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{yyyymmdd}.txt"
OCC_VOLUME_URL = (
    "https://marketdata.theocc.com/volume-query?reportDate={yyyymmdd}&format=csv"
    "&volumeQueryType=O&symbolType=U&symbol={symbol}&reportType=D&accountType=ALL&productKind=ALL"
)
CFTC_TFF_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
#: TFF market names of interest (contract_market_name substring match, upper).
CFTC_MARKETS = ("E-MINI S&P 500", "VIX")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS world_dix (
    date TEXT PRIMARY KEY,
    spx_price REAL,
    dix REAL,
    gex REAL,
    fetched_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS world_vol_index (
    index_name TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (index_name, date)
);
CREATE TABLE IF NOT EXISTS world_finra_short_volume (
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    short_volume INTEGER,
    short_exempt_volume INTEGER,
    total_volume INTEGER,
    market TEXT,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (date, symbol)
);
CREATE TABLE IF NOT EXISTS world_occ_volume (
    actdate TEXT NOT NULL,
    underlying TEXT NOT NULL,
    symbol TEXT NOT NULL,
    actype TEXT NOT NULL,
    porc TEXT NOT NULL,
    exchange TEXT NOT NULL,
    quantity INTEGER,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (actdate, underlying, symbol, actype, porc, exchange)
);
CREATE TABLE IF NOT EXISTS world_cftc_tff (
    report_date TEXT NOT NULL,
    market TEXT NOT NULL,
    dealer_long INTEGER, dealer_short INTEGER,
    asset_mgr_long INTEGER, asset_mgr_short INTEGER,
    lev_money_long INTEGER, lev_money_short INTEGER,
    open_interest INTEGER,
    raw_json TEXT,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (report_date, market)
);
"""


def ensure_world_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def _http_get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _f(v: Any) -> float | None:
    try:
        x = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return x


def _i(v: Any) -> int | None:
    x = _f(v)
    return int(x) if x is not None else None


# ---------------------------------------------------------------- parsers ----

def _vendor_field(row: dict, key: str):
    """Read an OPTIONAL field of an external vendor payload (Socrata omits nulls).

    Exists so vendor-only keys don't land on the orphan-dict-keys lead list, which
    tracks INTERNAL producer/consumer key agreement. Use only for third-party feeds;
    contractual CSV headers use bracket access so header drift fails loud instead.
    """
    return row.get(key)


def parse_dix_csv(text: str) -> list[tuple[str, float | None, float | None, float | None]]:
    """DIX.csv rows: date,price,dix,gex (header row present; header drift = KeyError)."""
    out: list[tuple[str, float | None, float | None, float | None]] = []
    for row in csv.DictReader(io.StringIO(text)):
        date = (row["date"] or "").strip()
        if not date:
            continue
        out.append((date, _f(row["price"]), _f(row["dix"]), _f(row["gex"])))
    return out


def parse_cboe_history_csv(text: str) -> list[tuple[str, float | None, float | None, float | None, float | None]]:
    """Cboe history CSV. VIX-style has OHLC; VVIX/SKEW have a single value column.

    Returns (date, open, high, low, close); single-value files map value -> close.
    """
    reader = csv.reader(io.StringIO(text))
    header: list[str] | None = None
    out: list[tuple[str, float | None, float | None, float | None, float | None]] = []
    for row in reader:
        if not row or not row[0].strip():
            continue
        if header is None:
            # First row whose first cell mentions DATE is the header.
            if "DATE" in row[0].upper():
                header = [c.strip().upper() for c in row]
            continue
        date = row[0].strip()
        vals = {header[j]: row[j] for j in range(1, min(len(header), len(row)))}
        if "CLOSE" in vals:
            out.append((date, _f(vals.get("OPEN")), _f(vals.get("HIGH")),
                        _f(vals.get("LOW")), _f(vals.get("CLOSE"))))
        else:
            single = next(iter(vals.values()), None)
            out.append((date, None, None, None, _f(single)))
    return out


def parse_finra_cnms(text: str) -> list[tuple[str, str, int | None, int | None, int | None, str]]:
    """CNMS pipe-delimited: Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market."""
    out: list[tuple[str, str, int | None, int | None, int | None, str]] = []
    for line in text.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 6 or parts[0].lower() == "date" or not parts[0].strip().isdigit():
            continue
        raw_date = parts[0].strip()
        date = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else raw_date
        out.append((date, parts[1].strip().upper(), _i(parts[2]), _i(parts[3]), _i(parts[4]), parts[5].strip()))
    return out


def parse_occ_volume_csv(text: str) -> list[tuple[str, str, str, str, str, str, int | None]]:
    """OCC volume-query CSV: quantity,underlying,symbol,actype,porc,exchange,actdate."""
    out: list[tuple[str, str, str, str, str, str, int | None]] = []
    for row in csv.DictReader(io.StringIO(text)):
        raw_date = (row["actdate"] or "").strip()
        underlying = (row["underlying"] or "").strip().upper()
        if not raw_date or not underlying:
            continue
        try:  # MM/DD/YYYY -> ISO
            date = datetime.strptime(raw_date, "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            date = raw_date
        out.append((
            date,
            underlying,
            (row["symbol"] or "").strip().upper(),
            (row["actype"] or "").strip().upper(),
            (row["porc"] or "").strip().upper(),
            (row["exchange"] or "").strip().upper(),
            _i(row["quantity"]),
        ))
    return out


def parse_cftc_tff_json(text: str) -> list[dict[str, Any]]:
    """Socrata TFF rows filtered to CFTC_MARKETS, normalized for world_cftc_tff."""
    rows = json.loads(text)
    out: list[dict[str, Any]] = []
    for r in rows if isinstance(rows, list) else []:
        market = str(_vendor_field(r, "contract_market_name")
                     or _vendor_field(r, "market_and_exchange_names") or "").upper()
        if not any(m in market for m in CFTC_MARKETS):
            continue
        report_date = str(_vendor_field(r, "report_date_as_yyyy_mm_dd") or "")[:10]
        if not report_date:
            continue
        out.append({
            "report_date": report_date,
            "market": market,
            "dealer_long": _i(_vendor_field(r, "dealer_positions_long_all")),
            "dealer_short": _i(_vendor_field(r, "dealer_positions_short_all")),
            "asset_mgr_long": _i(_vendor_field(r, "asset_mgr_positions_long_all")
                                 or _vendor_field(r, "asset_mgr_positions_long")),
            "asset_mgr_short": _i(_vendor_field(r, "asset_mgr_positions_short_all")
                                  or _vendor_field(r, "asset_mgr_positions_short")),
            "lev_money_long": _i(_vendor_field(r, "lev_money_positions_long_all")
                                 or _vendor_field(r, "lev_money_positions_long")),
            "lev_money_short": _i(_vendor_field(r, "lev_money_positions_short_all")
                                  or _vendor_field(r, "lev_money_positions_short")),
            "open_interest": _i(_vendor_field(r, "open_interest_all")),
            "raw_json": json.dumps(r, default=str),
        })
    return out


# ---------------------------------------------------------------- ingests ----

def ingest_dix(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = parse_dix_csv(_http_get_text(DIX_URL))
    conn.executemany(
        "INSERT OR REPLACE INTO world_dix(date, spx_price, dix, gex) VALUES (?,?,?,?)", rows
    )
    conn.commit()
    return {"source": "dix", "rows": len(rows), "last_date": rows[-1][0] if rows else None}


def ingest_vol_indices(conn: sqlite3.Connection, indices: tuple[str, ...] = VOL_INDICES) -> dict[str, Any]:
    per: dict[str, int] = {}
    for idx in indices:
        rows = parse_cboe_history_csv(_http_get_text(CBOE_HISTORY_URL.format(index=idx)))
        conn.executemany(
            "INSERT OR REPLACE INTO world_vol_index(index_name, date, open, high, low, close)"
            " VALUES (?,?,?,?,?,?)",
            [(idx, *r) for r in rows],
        )
        per[idx] = len(rows)
    conn.commit()
    return {"source": "vol", "rows_per_index": per}


def ingest_finra(conn: sqlite3.Connection, dates: list[str]) -> dict[str, Any]:
    """dates: ISO YYYY-MM-DD; missing files (holidays) are skipped with a note."""
    total, missing = 0, []
    for d in dates:
        url = FINRA_CNMS_URL.format(yyyymmdd=d.replace("-", ""))
        try:
            rows = parse_finra_cnms(_http_get_text(url))
        except urllib.error.HTTPError as exc:
            # FINRA's CDN answers 403 (not 404) for not-yet-published dates
            # (probed 2026-07-21: today 403s until the nightly publish; all
            # prior weekdays 200 with the same headers).
            if exc.code in (403, 404):
                missing.append(d)
                continue
            raise
        conn.executemany(
            "INSERT OR REPLACE INTO world_finra_short_volume"
            "(date, symbol, short_volume, short_exempt_volume, total_volume, market)"
            " VALUES (?,?,?,?,?,?)",
            rows,
        )
        total += len(rows)
    conn.commit()
    return {"source": "finra", "rows": total, "dates_requested": len(dates), "missing_dates": missing}


def ingest_occ(conn: sqlite3.Connection, symbols: list[str], dates: list[str]) -> dict[str, Any]:
    total, missing = 0, []
    for d in dates:
        for sym in symbols:
            url = OCC_VOLUME_URL.format(yyyymmdd=d.replace("-", ""), symbol=urllib.parse.quote(sym))
            try:
                rows = parse_occ_volume_csv(_http_get_text(url))
            except urllib.error.HTTPError as exc:
                if exc.code in (400, 404):
                    missing.append(f"{d}:{sym}")
                    continue
                raise
            if not rows:
                missing.append(f"{d}:{sym}")
                continue
            conn.executemany(
                "INSERT OR REPLACE INTO world_occ_volume"
                "(actdate, underlying, symbol, actype, porc, exchange, quantity)"
                " VALUES (?,?,?,?,?,?,?)",
                rows,
            )
            total += len(rows)
    conn.commit()
    return {"source": "occ", "rows": total, "empty_or_missing": missing}


def ingest_cftc(conn: sqlite3.Connection, limit: int = 5000) -> dict[str, Any]:
    url = f"{CFTC_TFF_URL}?$limit={int(limit)}&$order=report_date_as_yyyy_mm_dd DESC"
    rows = parse_cftc_tff_json(_http_get_text(url.replace(" ", "%20")))
    conn.executemany(
        "INSERT OR REPLACE INTO world_cftc_tff"
        "(report_date, market, dealer_long, dealer_short, asset_mgr_long, asset_mgr_short,"
        " lev_money_long, lev_money_short, open_interest, raw_json)"
        " VALUES (:report_date, :market, :dealer_long, :dealer_short, :asset_mgr_long,"
        " :asset_mgr_short, :lev_money_long, :lev_money_short, :open_interest, :raw_json)",
        rows,
    )
    conn.commit()
    dates = sorted({r["report_date"] for r in rows})
    return {"source": "cftc", "rows": len(rows),
            "date_range": [dates[0], dates[-1]] if dates else None}


# ------------------------------------------------------------------- main ----

def recent_weekdays(n: int, today_utc: datetime | None = None) -> list[str]:
    """Last n weekdays (ISO dates), newest last. Weekday filter only — holiday
    misses surface as missing_dates in the per-source summary, which is fine."""
    now = today_utc or datetime.now(timezone.utc)
    out: list[str] = []
    d = now.date()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


def run(db_path: Path, sources: list[str], *, symbols: list[str], days: int) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    summaries: list[dict[str, Any]] = []
    try:
        ensure_world_schema(conn)
        dates = recent_weekdays(days)
        dispatch = {
            "dix": lambda: ingest_dix(conn),
            "vol": lambda: ingest_vol_indices(conn),
            "finra": lambda: ingest_finra(conn, dates),
            "occ": lambda: ingest_occ(conn, symbols, dates),
            "cftc": lambda: ingest_cftc(conn),
        }
        for name in sources:
            fn = dispatch.get(name)
            if fn is None:
                summaries.append({"source": name, "error": "unknown source"})
                continue
            try:
                summaries.append(fn())
            except Exception as exc:  # noqa: BLE001 — per-source isolation is the contract
                summaries.append({"source": name, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        conn.close()
    return summaries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--sources", default="dix,vol,finra,occ,cftc",
                    help="comma list from: dix,vol,finra,occ,cftc")
    ap.add_argument("--symbols", default="SPY,QQQ,IWM", help="OCC underlyings")
    ap.add_argument("--days", type=int, default=5, help="weekday lookback for finra/occ")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summaries = run(
        Path(args.db),
        [s.strip() for s in args.sources.split(",") if s.strip()],
        symbols=[s.strip().upper() for s in args.symbols.split(",") if s.strip()],
        days=args.days,
    )
    print(json.dumps(summaries, indent=2))
    return 1 if any("error" in s for s in summaries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
