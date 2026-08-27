#!/usr/bin/env python3
"""ISOLATED Alpaca IEX research collector — NOT part of canonical Schwab Collect.

WHY THIS IS A SEPARATE, ISOLATED MODULE. The Alpaca free-tier IEX websocket is an UNPROVEN
research feed for the (still-QUEUED) CR-02 trade-signing / CVD study: a ~5% IEX sample, quote
sizes in ROUND LOTS, distinct vendor semantics from Schwab consolidated. The dependency trace
found it has NO current consumer — nothing reads its rows except a liveness heartbeat, no CR-02
study code exists, no research artifact has ever been produced, and the canonical capture db has
never held an Alpaca row. So the capability is PRESERVED here, isolated, rather than co-mingled
into the canonical Schwab Collect daemon (tools/run_stream_capture.py):

  * it writes its OWN database (data/alpaca_capture.db) and its OWN tables (alpaca_prints_raw,
    alpaca_quotes_raw) — it can NEVER write stream_capture.db (the Schwab Collect db) or
    ed_console.db (the operational db). The store guards that at construction, not by convention.
  * it is UNSCHEDULED. It is a standalone research collector to be run by hand (or scheduled by
    CR-02 when that study actually starts). The canonical Schwab capture job is unaffected.
  * it stays RAW: it records prints and NBBO quotes as the vendor sends them. No signing, no
    aggressor side, no CVD is computed here — that is the CR-02 study's job, and it does not exist
    yet. Nothing here enters Decide.

This is the SAME capture code that used to live inside the daemon (auth, subscribe, half-open
reconnect guard, field maps) — MOVED, not duplicated: the only thing that changed is the sink,
which is now this module's own small sqlite store instead of the shared Schwab bus/writer.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

#: The collector's OWN database — never the Schwab capture db, never the operational db.
ALPACA_DB_DEFAULT = ROOT / "data" / "alpaca_capture.db"
ALPACA_WS_URL = "wss://stream.data.alpaca.markets/v2/iex"
ALPACA_ENV_PATH = ROOT / ".env"
#: IEX slice scale, MEASURED on-roster 2026-07-22: SPY IEX daily volume 1,223,790 vs Schwab
#: consolidated TOTAL_VOLUME 24,067,157 (~5.1%). Coverage is a SAMPLE, not the tape — the
#: pre-registered CR-02 study decides whether the sample is trustworthy.
ALPACA_SRC = "alpaca_iex"
ALPACA_STALE_RECONNECT_SEC = 120.0   #: no frames this long -> recycle the socket (half-open guard)

#: Alpaca stream field dictionary (schema verified live 2026-07-22). NAMED once.
ALPACA_TYPE_KEY = "T"      #: message type: "t" trade, "q" NBBO quote, control/bars other
ALPACA_SYMBOL_KEY = "S"
ALPACA_STAMP_KEY = "t"     #: RFC-3339 with NANOSECOND fraction
ALPACA_TRADE_FIELDS = {"p": "price", "s": "size", "x": "exchange", "c": "conditions",
                       "i": "trade_id", "z": "tape"}
#: `bs`/`as` are ROUND LOTS per Alpaca's schema — recorded AS GIVEN (no raw-layer conversion).
ALPACA_QUOTE_FIELDS = {"bp": "bid", "ap": "ask", "bs": "bid_size", "as": "ask_size",
                       "bx": "bid_exchange", "ax": "ask_exchange", "z": "tape"}

#: The collector's own schema — DISTINCT tables in a DISTINCT db, so Alpaca rows can never be
#: mistaken for or blended with Schwab's stream_quotes_raw/stream_prints_raw.
ALPACA_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS alpaca_prints_raw (
    ts_recv REAL NOT NULL, symbol TEXT NOT NULL,
    price REAL, size INTEGER, exchange TEXT, conditions TEXT,
    trade_ts_ms INTEGER, src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_apr_sym_ts ON alpaca_prints_raw(symbol, ts_recv);
CREATE TABLE IF NOT EXISTS alpaca_quotes_raw (
    ts_recv REAL NOT NULL, symbol TEXT NOT NULL,
    bid REAL, ask REAL, bid_size INTEGER, ask_size INTEGER,
    quote_time_ms INTEGER, src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aqr_sym_ts ON alpaca_quotes_raw(symbol, ts_recv);
"""

#: Databases this research collector is FORBIDDEN to write — the two canonical stores. Resolved,
#: not basename-only, so `data/x/../stream_capture.db` and symlinks collapse to the real name.
_FORBIDDEN_DB_NAMES = frozenset({"stream_capture.db", "ed_console.db"})


def alpaca_keys_from_env() -> tuple[str, str] | None:
    """Paper keys from .env (ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY) or process env.

    Values are never logged. Missing keys are a SKIP, not an error — the collector simply does
    nothing without them."""
    kv: dict[str, str] = {}
    try:
        for line in ALPACA_ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            kv[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    import os
    kid = kv.get("ALPACA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY_ID")
    sec = kv.get("ALPACA_API_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET_KEY")
    return (kid, sec) if kid and sec else None


def alpaca_rfc3339_to_ms(t) -> int | None:
    """Alpaca timestamps are RFC-3339 with NANOSECOND fractions (9 digits) — datetime.fromisoformat
    accepts at most 6, so the fraction is trimmed. Stored as epoch milliseconds."""
    if not t or not isinstance(t, str):
        return None
    from datetime import datetime
    s = t.rstrip("Z")
    if "." in s:
        head, frac = s.split(".", 1)
        s = f"{head}.{frac[:6]}"
    try:
        return int(datetime.fromisoformat(s + "+00:00").timestamp() * 1000)
    except ValueError:
        return None


def _parse_item(item: dict, field_map: dict[str, str], sym: str) -> dict:
    out: dict = {"symbol": sym}
    for k, name in field_map.items():
        if k in item:
            out[name] = item[k]
    return out


def alpaca_item_to_row(item: dict, *, received_ts: float) -> tuple[str, tuple] | None:
    """One Alpaca stream item -> ('print'|'quote', row tuple) for this module's own tables, or None
    for bars/status/control frames. Prints and NBBO quotes only; bars are Schwab's authority."""
    if not isinstance(item, dict):
        return None
    kind = item.get(ALPACA_TYPE_KEY)
    sym = str(item.get(ALPACA_SYMBOL_KEY) or "").upper()
    if not sym:
        return None
    if kind == "t":
        f = _parse_item(item, ALPACA_TRADE_FIELDS, sym)
        conds = f.get("conditions")
        return ("print", (received_ts, sym, f.get("price"), f.get("size"), f.get("exchange"),
                          ",".join(str(x) for x in conds) if isinstance(conds, list) else conds,
                          alpaca_rfc3339_to_ms(item.get(ALPACA_STAMP_KEY)), ALPACA_SRC))
    if kind == "q":
        f = _parse_item(item, ALPACA_QUOTE_FIELDS, sym)
        return ("quote", (received_ts, sym, f.get("bid"), f.get("ask"), f.get("bid_size"),
                          f.get("ask_size"), alpaca_rfc3339_to_ms(item.get(ALPACA_STAMP_KEY)),
                          ALPACA_SRC))
    return None


class AlpacaCaptureStore:
    """Tiny batched sqlite sink for the isolated collector. NOT the Schwab spine — its own db, its
    own tables. Refuses the canonical databases at construction so a research feed can never write
    them."""

    def __init__(self, db_path: Path | str = ALPACA_DB_DEFAULT, *, batch_max: int = 200) -> None:
        p = Path(db_path).resolve()
        if p.name in _FORBIDDEN_DB_NAMES:
            raise ValueError(
                f"the isolated Alpaca research collector must NEVER write {p.name} — it writes only "
                f"its own alpaca_capture.db (got {p})")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = p
        self.batch_max = int(batch_max)
        self.written = 0
        self._batch: list[tuple[str, tuple]] = []
        self._conn = sqlite3.connect(str(p), timeout=30.0)
        self._conn.executescript(
            "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=30000;")
        self._conn.executescript(ALPACA_SCHEMA_SQL)
        self._conn.commit()

    def write(self, kind: str, row: tuple) -> None:
        self._batch.append((kind, row))
        if len(self._batch) >= self.batch_max:
            self.flush()

    def flush(self) -> None:
        if not self._batch:
            return
        prints = [r for k, r in self._batch if k == "print"]
        quotes = [r for k, r in self._batch if k == "quote"]
        try:
            if prints:
                self._conn.executemany(
                    "INSERT INTO alpaca_prints_raw(ts_recv,symbol,price,size,exchange,conditions,"
                    "trade_ts_ms,src) VALUES(?,?,?,?,?,?,?,?)", prints)
            if quotes:
                self._conn.executemany(
                    "INSERT INTO alpaca_quotes_raw(ts_recv,symbol,bid,ask,bid_size,ask_size,"
                    "quote_time_ms,src) VALUES(?,?,?,?,?,?,?,?)", quotes)
            self._conn.commit()
            self.written += len(prints) + len(quotes)
        except sqlite3.Error as e:
            print(f"alpaca collector: write failed ({len(self._batch)} rows): {e}")
        finally:
            self._batch = []

    def close(self) -> None:
        try:
            self.flush()
        finally:
            self._conn.close()


async def _alpaca_session(ws, symbols: list[str], kid: str, sec: str,
                          store: AlpacaCaptureStore, stop: asyncio.Event) -> bool:
    """Auth + subscribe + receive loop on an open socket. Returns False on auth refusal (permanent
    for this run), True when the loop ends via `stop` or the half-open guard."""
    await asyncio.wait_for(ws.recv(), 10)              # {"T":"success","msg":"connected"}
    await ws.send(json.dumps({"action": "auth", "key": kid, "secret": sec}))
    auth = json.loads(await asyncio.wait_for(ws.recv(), 10))
    a0 = auth[0] if isinstance(auth, list) and auth else auth
    if not (isinstance(a0, dict) and a0.get(ALPACA_TYPE_KEY) == "success"):
        print(f"alpaca: auth REFUSED: {a0} — collector stopped for this run")
        return False
    await ws.send(json.dumps({"action": "subscribe", "trades": symbols, "quotes": symbols}))
    print(f"alpaca: subscribed trades+quotes for {len(symbols)} symbols (free tier cap 30)")
    last_rx = time.monotonic()
    while not stop.is_set():
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            # half-open guard: a dead socket raises NOTHING — quiet past the bar means recycle.
            if time.monotonic() - last_rx > ALPACA_STALE_RECONNECT_SEC:
                print("alpaca: no frames past the stale bar — recycling socket (half-open guard)")
                store.flush()
                return True
            continue
        last_rx = time.monotonic()
        rx = time.time()
        frame = json.loads(raw)
        for item in (frame if isinstance(frame, list) else [frame]):
            if isinstance(item, dict) and item.get(ALPACA_TYPE_KEY) == "error":
                print(f"alpaca: stream error frame: {item}")
                continue
            out = alpaca_item_to_row(item, received_ts=rx)
            if out is not None:
                store.write(out[0], out[1])
        store.flush()
    return True


async def alpaca_pump(symbols: list[str], store: AlpacaCaptureStore, stop: asyncio.Event) -> None:
    """Hold the Alpaca IEX socket open; write prints/quotes to the isolated store. Reconnects with
    bounded backoff (5s..60s) until `stop`. No keys -> a printed no-op; the collector never raises
    into the caller."""
    keys = alpaca_keys_from_env()
    if keys is None:
        print("alpaca: no ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY in .env — collector idle (no-op)")
        return
    import websockets
    kid, sec = keys
    backoff = 5.0
    while not stop.is_set():
        try:
            async with websockets.connect(ALPACA_WS_URL, open_timeout=15) as ws:
                backoff = 5.0
                if not await _alpaca_session(ws, symbols, kid, sec, store, stop):
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — reconnect loop; every drop is printed
            if stop.is_set():
                return
            print(f"alpaca: connection lost ({type(exc).__name__}: {exc}) — reconnect in "
                  f"{backoff:.0f}s")
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
                return
            except asyncio.TimeoutError:
                backoff = min(backoff * 2, 60.0)


async def run(symbols: list[str], duration_min: float, db_path: str | None) -> int:
    store = AlpacaCaptureStore(db_path or ALPACA_DB_DEFAULT)
    stop = asyncio.Event()
    task = asyncio.create_task(alpaca_pump(symbols, store, stop))
    try:
        if duration_min > 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=duration_min * 60.0)
            except asyncio.TimeoutError:
                pass
        else:
            await task
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        stop.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 — bounded shutdown
            pass
        store.close()
        print(json.dumps({"alpaca_rows_written": store.written, "db": str(store.db_path)}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="SPY,QQQ,IWM")
    ap.add_argument("--duration-min", type=float, default=0.0, help="0 = until Ctrl+C")
    ap.add_argument("--db", default=None, help="override alpaca_capture.db path (tests)")
    a = ap.parse_args()
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    return asyncio.run(run(syms, a.duration_min, a.db))


if __name__ == "__main__":
    raise SystemExit(main())
