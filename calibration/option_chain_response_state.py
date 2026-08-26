"""OPTIONS FLOW — retain the REST chain response ENVELOPE at the cadence it arrives.

THE MEASURED LOSS THIS CLOSES. Every chain fetch returns, alongside the contracts, a response
envelope and an underlying-quote block describing the state of the world for THAT response.
Production received 4,209 such responses in the last 24 hours across 58 tickers. It retained the
envelope from roughly 39 of them — the once-per-ticker-per-day morning wide chain. Everything
else was parsed for contracts and discarded.

WHAT WAS BEING THROWN AWAY, specifically, and why it is not incidental:
  * interestRate and dividendYield — the vendor's own r and q. Our greeks currently use r = q = 0.
    Whether that is acceptable is an empirical question, and it is UNANSWERABLE without a history
    of what the vendor actually said r and q were, minute by minute. Keeping only a 09:30 sample
    cannot answer it.
  * underlyingPrice and the 23-field underlying quote block — a NATIVE spot arriving on the same
    response as the chain, i.e. exactly contemporaneous with the greeks computed from it.
  * volatility — the vendor's own underlying-level IV.
  * isChainTruncated — whether the vendor cut the response. A truncated chain silently changes
    what any span or coverage claim means, and RC-491 already showed truncation is real here.
  * daysToExpiration, numberOfContracts, status, isDelayed — response-scoped facts that describe
    the very fetch a snapshot was computed from.

COST, MEASURED RATHER THAN ASSUMED. The envelope plus the underlying block serialises to about
754 bytes. At the measured 4,209 responses per day that is 3.17 MB/day, 67 MB/month, 0.80 GB/year.
So full-cadence retention is affordable outright, and the temporal fidelity of the record is NOT
reduced for convenience: every response that arrives is kept, not a sample of them, and not only
the ones where something changed. A change-only scheme would have been cheaper and would have
destroyed the ability to say "we observed this value at this instant".

DESIGN. Raw-native preservation plus canonical typed projections, the same shape as the rest of
this foundation: the high-value envelope scalars become typed, queryable COLUMNS, and the
underlying block is stored whole as JSON so no field is lost to an omission in today's parser.

NOT A SIGNAL. These are native vendor observations. Nothing here infers dealer ownership,
inventory sign, aggressor side, or intent, and nothing derived from it may enter Decide without
its own validation.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Envelope scalars promoted to typed columns because they are directly queryable facts about
#: the response. Anything not listed stays reachable through the stored underlying JSON or the
#: envelope_extra_json catch-all, so this list is a projection, never a filter.
TYPED_ENVELOPE_COLUMNS = (
    ("status", "TEXT"),
    ("strategy", "TEXT"),
    ("interval_val", "REAL"),
    ("is_delayed", "INTEGER"),
    ("is_index", "INTEGER"),
    ("interest_rate", "REAL"),
    ("dividend_yield", "REAL"),
    ("volatility", "REAL"),
    ("underlying_price", "REAL"),
    ("days_to_expiration", "REAL"),
    ("number_of_contracts", "INTEGER"),
    ("is_chain_truncated", "INTEGER"),
    ("asset_main_type", "TEXT"),
    ("asset_sub_type", "TEXT"),
)

#: Vendor envelope key -> our column. Kept explicit so a vendor rename shows up as a NULL column
#: in the data rather than as a silently-dropped field.
ENVELOPE_KEY_TO_COLUMN = {
    "status": "status",
    "strategy": "strategy",
    "interval": "interval_val",
    "isDelayed": "is_delayed",
    "isIndex": "is_index",
    "interestRate": "interest_rate",
    "dividendYield": "dividend_yield",
    "volatility": "volatility",
    "underlyingPrice": "underlying_price",
    "daysToExpiration": "days_to_expiration",
    "numberOfContracts": "number_of_contracts",
    "isChainTruncated": "is_chain_truncated",
    "assetMainType": "asset_main_type",
    "assetSubType": "asset_sub_type",
}

TABLE_NAME = "option_chain_response_state"


def _create_sql() -> str:
    cols = ",\n    ".join(f"{name} {typ}" for name, typ in TYPED_ENVELOPE_COLUMNS)
    return f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT NOT NULL,
    ts_utc              REAL NOT NULL,   -- when WE received the response
    {cols},
    underlying_json     TEXT,            -- the vendor's underlying quote block, stored whole
    envelope_extra_json TEXT,            -- any envelope key we do not have a typed column for
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ocrs_ticker_ts ON {TABLE_NAME}(ticker, ts_utc);
CREATE INDEX IF NOT EXISTS idx_ocrs_ts ON {TABLE_NAME}(ts_utc);
"""


def ensure_response_state_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_create_sql())
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({TABLE_NAME})")}
    for name, typ in TYPED_ENVELOPE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {name} {typ}")
    conn.commit()


def _as_int_bool(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    try:
        return 1 if int(v) else 0
    except (TypeError, ValueError):
        return None


def project_response_state(ticker: str, ts_utc: float,
                           chain_response: dict | None) -> dict[str, Any] | None:
    """Project one chain response into the stored row shape. None when unusable.

    Everything the vendor sent at the top level is accounted for: known keys become typed
    values, the underlying block is preserved whole, and ANY key we do not recognise lands in
    envelope_extra_json rather than being dropped. That catch-all is the point — it is what
    makes this robust to the vendor adding a field, which is exactly how breakEven and ssid
    survived in the contract store.
    """
    if not isinstance(chain_response, dict):
        return None
    row: dict[str, Any] = {"ticker": str(ticker), "ts_utc": float(ts_utc)}
    for name, _typ in TYPED_ENVELOPE_COLUMNS:
        row[name] = None

    extra: dict[str, Any] = {}
    for k, v in chain_response.items():
        if k in ("callExpDateMap", "putExpDateMap"):
            continue                        # the contracts themselves; persisted elsewhere
        if k == "underlying":
            continue                        # handled below, stored whole
        col = ENVELOPE_KEY_TO_COLUMN.get(k)
        if col is None:
            extra[k] = v
            continue
        if col in ("is_delayed", "is_index", "is_chain_truncated"):
            row[col] = _as_int_bool(v)
        elif col in ("interval_val", "interest_rate", "dividend_yield", "volatility",
                     "underlying_price", "days_to_expiration"):
            try:
                row[col] = float(v) if v is not None else None
            except (TypeError, ValueError):
                row[col] = None
                extra[k] = v                # unparseable value is KEPT, not silently zeroed
        elif col == "number_of_contracts":
            try:
                row[col] = int(v) if v is not None else None
            except (TypeError, ValueError):
                row[col] = None
                extra[k] = v
        else:
            row[col] = str(v) if v is not None else None

    und = chain_response.get("underlying")
    row["underlying_json"] = (json.dumps(und, default=str, separators=(",", ":"))
                              if isinstance(und, dict) else None)
    row["envelope_extra_json"] = (json.dumps(extra, default=str, separators=(",", ":"))
                                  if extra else None)
    return row


def persist_response_state(db_path: Path | str, ticker: str, ts_utc: float,
                           chain_response: dict | None) -> dict[str, Any]:
    """Store one response's envelope state. Fails SOFT — never breaks a snapshot.

    This runs on the snapshot path, so it must be cheap and it must not be able to take a
    request down. A retention failure is logged and reported; the caller carries on.
    """
    row = project_response_state(ticker, ts_utc, chain_response)
    if row is None:
        return {"status": "skipped", "reason": "no usable chain response envelope"}
    cols = list(row)
    sql = (f"INSERT INTO {TABLE_NAME} ({','.join(cols)}) "
           f"VALUES ({','.join('?' * len(cols))})")
    try:
        conn = sqlite3.connect(str(db_path), timeout=30.0)
    except sqlite3.Error as e:
        return {"status": "error", "reason": str(e)}
    try:
        ensure_response_state_schema(conn)
        conn.execute(sql, [row[c] for c in cols])
        conn.commit()
    except sqlite3.Error as e:
        log.debug("option_chain_response_state persist failed for %s: %s", ticker, e)
        return {"status": "error", "reason": str(e)}
    finally:
        conn.close()
    return {"status": "written", "ticker": ticker,
            "interest_rate": row.get("interest_rate"),
            "dividend_yield": row.get("dividend_yield"),
            "is_chain_truncated": row.get("is_chain_truncated")}


def response_state_as_of(db_path: Path | str, ticker: str, at_ts_utc: float) -> dict | None:
    """The envelope state most recently observed at-or-before an instant. No lookahead."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    except sqlite3.Error:
        return None
    try:
        conn.row_factory = sqlite3.Row
        r = conn.execute(
            f"SELECT * FROM {TABLE_NAME} WHERE ticker = ? AND ts_utc <= ? "
            f"ORDER BY ts_utc DESC LIMIT 1", (str(ticker), float(at_ts_utc))).fetchone()
        return dict(r) if r else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()
