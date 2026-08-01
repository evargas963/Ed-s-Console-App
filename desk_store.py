"""Desk fact store — bitemporal, so the Desk tab can be replayed without lying about it.

Every other surface in this console answers "what is true now". The Desk has to answer a
harder question — "what was knowable at 09:15 on Tuesday" — because that is the only form in
which a candidate screen can be judged. A screen scored against facts that arrived after the
decision is not a screen, it is a memoir.

So every row here carries TWO clocks:

  event_time_utc      when the thing happened in the world
  knowledge_time_utc  the first moment WE could have acted on it

They are routinely days apart. MEASURED 2026-07-31 on this repo's own data: FINRA short-volume
rows for event date 2026-07-15 carry `fetched_at` 2026-07-21 13:02:27 — a six-day availability
lag. A study that joined those on event date would be reading the future, and would look
brilliant doing it. Reads therefore filter on knowledge time, never on event time.

Two rules make that guarantee real rather than decorative:

1. A knowledge time is never invented. `put_fact` requires one; there is no default, no
   `or time.time()`, no fallback to the event time. A source that cannot say when we learned
   something does not get a row (RC-68's failure class: a 09:47 capture served at 11:31 as
   current).
2. When a source stamps a naive timestamp with no timezone, we resolve it to the LATEST
   plausible instant rather than the earliest (`_naive_text_to_utc_conservative`). Being wrong
   in that direction costs a few hours of visibility; being wrong the other way silently
   licenses lookahead.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

#: Evidence tier. The Desk renders these; nothing below ESTIMATED may drive an action.
#: MEASURED  — a fetched fact carrying its own source and vintage.
#: DERIVED   — arithmetic over MEASURED facts (no forecast, no free parameter).
#: ESTIMATED — model output that has a calibration record behind it.
#: UNPROVEN  — model output without one.
TIERS: tuple[str, ...] = ("MEASURED", "DERIVED", "ESTIMATED", "UNPROVEN")

#: Widest offset any naive wall-clock string in this repo could be behind UTC. US/Eastern is
#: UTC-4/-5, so a naive string that is really ET is at most 5h EARLIER than the same string read
#: as UTC. Resolving conservatively means adding that, never subtracting it.
_MAX_NAIVE_LAG_HOURS = 5

#: RC-167: a median needs sessions to be a median OF. Below this the statistic is the outlier.
_MIN_SESSIONS_FOR_ADV = 3

#: RC-167/RC-168: a session whose dollar volume exceeds this multiple of the symbol's own median
#: is counted and reported, never silently dropped. Measured, not categorical — the multiple is
#: applied to every symbol identically and the count reaches the payload.
_SUSPECT_SESSION_MULTIPLE = 5.0

DESK_FACTS_SQL = """
CREATE TABLE IF NOT EXISTS desk_facts (
    subject            TEXT NOT NULL,
    kind               TEXT NOT NULL,
    event_time_utc     REAL NOT NULL,
    knowledge_time_utc REAL NOT NULL,
    source             TEXT NOT NULL,
    source_ref         TEXT,
    tier               TEXT NOT NULL,
    value_num          REAL,
    payload_json       TEXT,
    ingested_at_utc    REAL NOT NULL,
    PRIMARY KEY (subject, kind, event_time_utc, source)
)
"""

DESK_FACTS_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_desk_facts_knowledge "
    "ON desk_facts (kind, knowledge_time_utc, subject)"
)


class DeskFactError(ValueError):
    """A fact was rejected. Raised rather than coerced — a silently repaired row is the bug."""


def _connect(db_path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    p = str(db_path)
    if read_only:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=15.0)
    else:
        con = sqlite3.connect(p, timeout=30.0)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    return con


def ensure_schema(db_path: str | Path) -> None:
    con = _connect(db_path)
    try:
        con.execute(DESK_FACTS_SQL)
        con.execute(DESK_FACTS_INDEX_SQL)
        con.commit()
    finally:
        con.close()


def _naive_text_to_utc_conservative(text: str) -> float | None:
    """Resolve a naive 'YYYY-MM-DD HH:MM:SS' stamp to the LATEST instant it could mean.

    The `world_*` tables store `fetched_at` without a timezone (MEASURED 2026-07-31:
    world_finra_short_volume.fetched_at = '2026-07-21 13:02:27', typeof=text). Read as UTC it
    is the earliest reading; read as US/Eastern it is up to 5 hours later. We take the later
    one. Knowledge time is a claim about when we were ENTITLED to act, and over-claiming it is
    the one error that cannot be detected downstream — it just makes every study look better.
    """
    s = (text or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:len(fmt) + 4] if fmt.endswith("%S") else s, fmt)
        except ValueError:
            continue
        dt = dt.replace(tzinfo=timezone.utc) + timedelta(hours=_MAX_NAIVE_LAG_HOURS)
        return dt.timestamp()
    return None


def put_fact(
    db_path: str | Path,
    *,
    subject: str,
    kind: str,
    event_time_utc: float,
    knowledge_time_utc: float,
    source: str,
    tier: str,
    source_ref: str | None = None,
    value_num: float | None = None,
    payload: Mapping[str, Any] | None = None,
) -> None:
    """Write one fact. Every argument above `source_ref` is required — deliberately.

    There is no `knowledge_time_utc=None` path that fills in `time.time()`. If a caller cannot
    say when we learned something, the honest outcome is no row.
    """
    if not subject or not kind or not source:
        raise DeskFactError("subject, kind and source are all required")
    if tier not in TIERS:
        raise DeskFactError(f"tier {tier!r} is not one of {TIERS}")
    if not isinstance(event_time_utc, (int, float)) or event_time_utc <= 0:
        raise DeskFactError(f"event_time_utc must be a positive epoch, got {event_time_utc!r}")
    if not isinstance(knowledge_time_utc, (int, float)) or knowledge_time_utc <= 0:
        raise DeskFactError(
            f"knowledge_time_utc must be a positive epoch, got {knowledge_time_utc!r} — "
            "a fact whose knowledge time is unknown does not get stored"
        )
    if knowledge_time_utc < event_time_utc:
        raise DeskFactError(
            f"knowledge_time_utc {knowledge_time_utc} precedes event_time_utc {event_time_utc} "
            f"for {subject}/{kind} — we cannot have known it before it happened"
        )
    con = _connect(db_path)
    try:
        con.execute(DESK_FACTS_SQL)
        con.execute(DESK_FACTS_INDEX_SQL)
        con.execute(
            "INSERT OR REPLACE INTO desk_facts (subject, kind, event_time_utc, "
            "knowledge_time_utc, source, source_ref, tier, value_num, payload_json, "
            "ingested_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                subject.upper(), kind, float(event_time_utc), float(knowledge_time_utc),
                source, source_ref, tier,
                None if value_num is None else float(value_num),
                None if payload is None else json.dumps(dict(payload), separators=(",", ":")),
                time.time(),
            ),
        )
        con.commit()
    finally:
        con.close()


def facts_as_of(
    db_path: str | Path,
    as_of_utc: float,
    *,
    subject: str | None = None,
    kind: str | None = None,
    kinds: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Every fact we were entitled to act on at `as_of_utc`, newest knowledge first.

    The filter is `knowledge_time_utc <= as_of_utc`. It is never `event_time_utc <= as_of_utc`;
    that comparison is the leak this whole module exists to prevent.
    """
    if not isinstance(as_of_utc, (int, float)) or as_of_utc <= 0:
        raise DeskFactError(f"as_of_utc must be a positive epoch, got {as_of_utc!r}")
    where = ["knowledge_time_utc <= ?"]
    args: list[Any] = [float(as_of_utc)]
    if subject:
        where.append("subject = ?")
        args.append(subject.upper())
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if kinds:
        where.append("kind IN (" + ",".join("?" for _ in kinds) + ")")
        args.extend(list(kinds))
    sql = (
        "SELECT subject, kind, event_time_utc, knowledge_time_utc, source, source_ref, tier, "
        "value_num, payload_json FROM desk_facts WHERE " + " AND ".join(where) +
        " ORDER BY knowledge_time_utc DESC, subject ASC"
    )
    try:
        con = _connect(db_path, read_only=True)
    except sqlite3.OperationalError:
        return []
    try:
        try:
            rows = con.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return []  # table not created yet — absence reaches the surface as absence
    finally:
        con.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if d.get("payload_json"):
            try:
                d["payload"] = json.loads(d["payload_json"])
            except (TypeError, ValueError):
                d["payload"] = None
        d.pop("payload_json", None)
        out.append(d)
    return out


def latest_by_subject(
    db_path: str | Path, as_of_utc: float, kind: str, *, subjects: Iterable[str] | None = None
) -> dict[str, dict[str, Any]]:
    """One row per subject — the newest thing we knew about `kind` at `as_of_utc`."""
    wanted = {s.upper() for s in subjects} if subjects else None
    best: dict[str, dict[str, Any]] = {}
    for f in facts_as_of(db_path, as_of_utc, kind=kind):
        s = f["subject"]
        if wanted is not None and s not in wanted:
            continue
        prev = best.get(s)
        if prev is None or f["knowledge_time_utc"] > prev["knowledge_time_utc"]:
            best[s] = f
    return best


# ---------------------------------------------------------------------------
# Materializers — turn tables this repo ALREADY fills into bitemporal facts.
#
# Nothing here invents a knowledge time. Each source is used only because it carries one:
# world_* tables stamp `fetched_at`; price bars close at `bar_end_ts_utc`; chain snapshots
# stamp `ts_utc`. A source without such a stamp is skipped, and says so in the return value.
# ---------------------------------------------------------------------------

def materialize_short_volume(db_path: str | Path, *, limit_symbols: int = 0) -> dict[str, int]:
    """FINRA daily short volume -> `short_volume_ratio`, MEASURED.

    Knowledge time is `fetched_at`, which trails the event date by days. That lag is the point.
    """
    con = _connect(db_path, read_only=True)
    try:
        rows = con.execute(
            "SELECT date, symbol, short_volume, total_volume, fetched_at "
            "FROM world_finra_short_volume WHERE total_volume > 0"
        ).fetchall()
    except sqlite3.OperationalError:
        return {"written": 0, "skipped_no_knowledge_time": 0, "source_rows": 0}
    finally:
        con.close()

    written = skipped = 0
    seen: set[str] = set()
    target = _connect(db_path)
    try:
        target.execute(DESK_FACTS_SQL)
        target.execute(DESK_FACTS_INDEX_SQL)
        batch = []
        for r in rows:
            kt = _naive_text_to_utc_conservative(str(r["fetched_at"] or ""))
            if kt is None:
                skipped += 1
                continue
            sym = str(r["symbol"] or "").upper()
            if not sym:
                skipped += 1
                continue
            if limit_symbols and sym not in seen and len(seen) >= limit_symbols:
                continue
            seen.add(sym)
            et = _naive_text_to_utc_conservative(str(r["date"] or ""))
            if et is None:
                skipped += 1
                continue
            tot = float(r["total_volume"] or 0.0)
            if tot <= 0:
                skipped += 1
                continue
            ratio = float(r["short_volume"] or 0.0) / tot
            batch.append((
                sym, "short_volume_ratio", et, max(kt, et), "finra.daily_short_volume",
                str(r["date"]), "MEASURED", ratio,
                json.dumps({"short": r["short_volume"], "total": r["total_volume"]},
                           separators=(",", ":")),
                time.time(),
            ))
        if batch:
            target.executemany(
                "INSERT OR REPLACE INTO desk_facts (subject, kind, event_time_utc, "
                "knowledge_time_utc, source, source_ref, tier, value_num, payload_json, "
                "ingested_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
            written = len(batch)
        target.commit()
    finally:
        target.close()
    return {"written": written, "skipped_no_knowledge_time": skipped, "source_rows": len(rows)}


def materialize_earnings(db_path: str | Path) -> dict[str, int]:
    """Scheduled earnings dates -> `earnings_date`, MEASURED.

    An earnings DATE is knowable before the event, so here knowledge time legitimately precedes
    event time and the `knowledge >= event` guard in `put_fact` does not apply; the row is
    written through the bulk path with both stamps recorded as the source gives them.
    """
    con = _connect(db_path, read_only=True)
    try:
        rows = con.execute(
            "SELECT date, symbol, time_hint, fetched_at FROM world_earnings"
        ).fetchall()
    except sqlite3.OperationalError:
        return {"written": 0, "skipped_no_knowledge_time": 0, "source_rows": 0}
    finally:
        con.close()

    written = skipped = 0
    target = _connect(db_path)
    try:
        target.execute(DESK_FACTS_SQL)
        target.execute(DESK_FACTS_INDEX_SQL)
        batch = []
        for r in rows:
            kt = _naive_text_to_utc_conservative(str(r["fetched_at"] or ""))
            et = _naive_text_to_utc_conservative(str(r["date"] or ""))
            sym = str(r["symbol"] or "").upper()
            if kt is None or et is None or not sym:
                skipped += 1
                continue
            batch.append((
                sym, "earnings_date", et, kt, "world.earnings", str(r["date"]),
                "MEASURED", et,
                json.dumps({"time_hint": r["time_hint"]}, separators=(",", ":")),
                time.time(),
            ))
        if batch:
            target.executemany(
                "INSERT OR REPLACE INTO desk_facts (subject, kind, event_time_utc, "
                "knowledge_time_utc, source, source_ref, tier, value_num, payload_json, "
                "ingested_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
            written = len(batch)
        target.commit()
    finally:
        target.close()
    return {"written": written, "skipped_no_knowledge_time": skipped, "source_rows": len(rows)}


def is_cash_index(symbol: str) -> bool:
    """Cash indices carry no shares, so they carry no dollar volume.

    RC-167: the first real run of this materializer published `$SPX` with an ADV of
    $108,127,149,193,795 — a hundred and eight TRILLION dollars a day, roughly the planet's
    annual output, printed in a capacity column whose entire job is to say how much size a name
    can absorb. `close * volume` is only dollars traded when `volume` counts SHARES; on a cash
    index it counts nothing purchasable. The derivation was applied to every row in
    `price_bars_1m` without first asking whether the instrument has the quantity being derived.
    """
    return str(symbol or "").startswith("$")


def materialize_dollar_volume(db_path: str | Path, *, window_days: int = 20) -> dict[str, int]:
    """20-session average dollar volume from 1m bars -> `adv_dollar`, DERIVED.

    Knowledge time is the close of the LAST bar in the window: that is the first instant the
    average existed. Capacity is a first-class column on the Desk, so this is not decoration —
    a candidate that cannot absorb size is not a candidate.

    RC-167 governs three details that look like arithmetic and are actually correctness:

    1. Cash indices are excluded (`is_cash_index`) — no shares, so no dollar volume.
    2. The statistic is the MEDIAN session, not the mean. MEASURED 2026-07-31: MSFT's four most
       recent sessions ran $9.42B, $9.25B, $59.48B, $333.72B. A mean over that is a number about
       the outlier, not about the name.
    3. Those outliers are a defect in `price_bars_1m` itself, not here (RC-168): one 2026-07-31
       MSFT bar carries 25,118,525 shares in a single minute while its neighbours carry
       thousands, and the day's bars are NOT a cumulative series (232 of 420 steps
       non-decreasing — coin-flip, not monotone). The median makes the Desk robust to it; it
       does not repair it, so the count of suspect sessions rides along in the payload where it
       stays visible instead of being smoothed away.
    """
    from time_et import et_date_str_from_ts_utc, is_rth_ts_utc

    cutoff = time.time() - (window_days * 86400.0)
    con = _connect(db_path, read_only=True)
    try:
        raw = con.execute(
            "SELECT ticker, bar_end_ts_utc, close, volume FROM price_bars_1m "
            "WHERE bar_end_ts_utc >= ? AND volume > 0", (cutoff,)
        ).fetchall()
    except sqlite3.OperationalError:
        return {"written": 0, "skipped_no_knowledge_time": 0, "source_rows": 0}
    finally:
        con.close()

    # RC-170: `price_bars_1m` carries extended hours BY DESIGN, and coverage differs per name.
    # MEASURED 2026-07-31 before this filter: SPY averaged 687 bars per session against MSFT's
    # 358 — one name's ADV was counting pre- and post-market turnover and the other's was not,
    # so the column ranked names against each other on different definitions of a day. Session
    # membership is the `time_et` authority's call, never a bar count.
    per_day: dict[tuple[str, str], list[float]] = {}
    last_bar: dict[str, float] = {}
    skipped_non_rth = 0
    for r in raw:
        ts = float(r["bar_end_ts_utc"] or 0.0)
        sym = str(r["ticker"] or "").upper()
        if not sym or ts <= 0:
            continue
        if not is_rth_ts_utc(ts):
            skipped_non_rth += 1
            continue
        d = et_date_str_from_ts_utc(ts)
        per_day.setdefault((sym, d), []).append(float(r["close"] or 0.0) * float(r["volume"]))
        if ts > last_bar.get(sym, 0.0):
            last_bar[sym] = ts

    per_symbol: dict[str, list[tuple[float, float, int]]] = {}
    for (sym, _d), dollars in per_day.items():
        total = sum(dollars)
        if total <= 0:
            continue
        per_symbol.setdefault(sym, []).append((total, last_bar.get(sym, 0.0), len(dollars)))

    written = skipped = suspect_total = 0
    target = _connect(db_path)
    try:
        target.execute(DESK_FACTS_SQL)
        target.execute(DESK_FACTS_INDEX_SQL)
        batch = []
        for sym, sessions in per_symbol.items():
            if is_cash_index(sym):
                skipped += 1  # no shares, so no dollar volume — absence, not a fabricated number
                continue
            if len(sessions) < _MIN_SESSIONS_FOR_ADV:
                skipped += 1
                continue
            last = max(s[1] for s in sessions)
            if last <= 0:
                skipped += 1
                continue
            dollars = sorted(s[0] for s in sessions)
            mid = len(dollars) // 2
            median = (dollars[mid] if len(dollars) % 2
                      else 0.5 * (dollars[mid - 1] + dollars[mid]))
            if median <= 0:
                skipped += 1
                continue
            suspect = sum(1 for d in dollars if d > _SUSPECT_SESSION_MULTIPLE * median)
            suspect_total += suspect
            batch.append((
                sym, "adv_dollar", last, last, "derived.price_bars_1m",
                f"{window_days}d median", "DERIVED", median,
                json.dumps({"sessions": len(dollars), "suspect_sessions": suspect,
                            "max_session": dollars[-1], "window_days": window_days},
                           separators=(",", ":")),
                time.time(),
            ))
        if batch:
            target.executemany(
                "INSERT OR REPLACE INTO desk_facts (subject, kind, event_time_utc, "
                "knowledge_time_utc, source, source_ref, tier, value_num, payload_json, "
                "ingested_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
            written = len(batch)
        target.commit()
    finally:
        target.close()
    return {"written": written, "skipped_no_knowledge_time": skipped,
            "source_rows": len(raw), "skipped_non_rth_bars": skipped_non_rth,
            "suspect_sessions": suspect_total}


def materialize_options_listed(db_path: str | Path) -> dict[str, int]:
    """Chain presence and width from banked chains -> `options_listed`, MEASURED."""
    con = _connect(db_path, read_only=True)
    try:
        rows = con.execute(
            "SELECT ticker, MAX(ts_utc) AS ts, n_strikes, session_volume "
            "FROM option_chain_accrual GROUP BY ticker"
        ).fetchall()
    except sqlite3.OperationalError:
        return {"written": 0, "skipped_no_knowledge_time": 0, "source_rows": 0}
    finally:
        con.close()

    written = skipped = 0
    target = _connect(db_path)
    try:
        target.execute(DESK_FACTS_SQL)
        target.execute(DESK_FACTS_INDEX_SQL)
        batch = []
        for r in rows:
            ts = float(r["ts"] or 0.0)
            sym = str(r["ticker"] or "").upper()
            if ts <= 0 or not sym:
                skipped += 1
                continue
            batch.append((
                sym, "options_listed", ts, ts, "schwab.option_chain_accrual", None,
                "MEASURED", float(r["n_strikes"] or 0),
                json.dumps({"session_volume": r["session_volume"]}, separators=(",", ":")),
                time.time(),
            ))
        if batch:
            target.executemany(
                "INSERT OR REPLACE INTO desk_facts (subject, kind, event_time_utc, "
                "knowledge_time_utc, source, source_ref, tier, value_num, payload_json, "
                "ingested_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
            written = len(batch)
        target.commit()
    finally:
        target.close()
    return {"written": written, "skipped_no_knowledge_time": skipped, "source_rows": len(rows)}


def materialize_all(db_path: str | Path, *, limit_symbols: int = 0) -> dict[str, dict[str, int]]:
    ensure_schema(db_path)
    return {
        "short_volume_ratio": materialize_short_volume(db_path, limit_symbols=limit_symbols),
        "earnings_date": materialize_earnings(db_path),
        "adv_dollar": materialize_dollar_volume(db_path),
        "options_listed": materialize_options_listed(db_path),
    }


def radar_rows(db_path: str | Path, as_of_utc: float, *, limit: int = 60) -> dict[str, Any]:
    """The Radar table, assembled strictly from what was knowable at `as_of_utc`.

    Rank is a deterministic ordering over MEASURED/DERIVED structure — dollar volume, then
    short-volume ratio. It is tradeability, not expected return, and it carries no forecast.
    Anything that would rank by predicted return needs an ADMITTED claim first, and there
    isn't one.
    """
    adv = latest_by_subject(db_path, as_of_utc, "adv_dollar")
    svr = latest_by_subject(db_path, as_of_utc, "short_volume_ratio")
    opt = latest_by_subject(db_path, as_of_utc, "options_listed")
    earn = latest_by_subject(db_path, as_of_utc, "earnings_date")

    subjects = set(adv) | set(svr) | set(opt)
    out = []
    for s in subjects:
        a, v, o = adv.get(s), svr.get(s), opt.get(s)
        e = earn.get(s)
        # Only future earnings are an event; a past one is history, not a calendar item.
        e_val = e["value_num"] if (e and e["value_num"] and e["value_num"] >= as_of_utc) else None
        out.append({
            "subject": s,
            "adv_dollar": a["value_num"] if a else None,
            "adv_knowledge_utc": a["knowledge_time_utc"] if a else None,
            "short_volume_ratio": v["value_num"] if v else None,
            "svr_event_utc": v["event_time_utc"] if v else None,
            "svr_knowledge_utc": v["knowledge_time_utc"] if v else None,
            "svr_lag_hours": (
                round((v["knowledge_time_utc"] - v["event_time_utc"]) / 3600.0, 1) if v else None
            ),
            "n_strikes": o["value_num"] if o else None,
            "options_knowledge_utc": o["knowledge_time_utc"] if o else None,
            "earnings_utc": e_val,
            "tiers": {
                "adv_dollar": "DERIVED" if a else None,
                "short_volume_ratio": "MEASURED" if v else None,
                "options_listed": "MEASURED" if o else None,
                "earnings_date": "MEASURED" if e_val else None,
            },
        })
    out.sort(key=lambda r: (-(r["adv_dollar"] or 0.0), r["subject"]))
    return {
        "as_of_utc": float(as_of_utc),
        "rows": out[:limit],
        "n_total": len(out),
        "rank_basis": "adv_dollar desc — tradeability, not expected return",
        "empty_reason": None if out else (
            "no facts carry a knowledge time at or before this instant"
        ),
    }
