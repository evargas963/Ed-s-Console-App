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

# RC-274: every read of a nullable column goes through these. `float(x or 0.0)` turns an absent
# measurement into the number zero, and a fact table cannot tell the two apart afterwards.
from app.domain.numeric_contract import (
    float_finite_or_none,
    float_nonnegative_or_none,
    float_positive_or_none,
)

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

#: A median spread formed from a handful of quotes is a quote, not a spread.
_MIN_QUOTES_FOR_SPREAD = 30

#: Capacity is quoted at a stated impact budget rather than as an unqualified "max size".
#: The number is meaningless without the budget it was computed against, so both travel together.
_CAPACITY_IMPACT_BPS = 25.0

#: RC-171: square-root impact coefficient, impact = Y * sigma * sqrt(Q/ADV). Published in every
#: payload that uses it. Literature puts Y near 0.5-1.5; 1.0 is the neutral choice and this
#: number is a stated assumption, which is why the capacity field is ESTIMATED and not DERIVED.
_IMPACT_COEFFICIENT = 1.0

#: Hard ceiling on participation. A cap is not a model — when it binds, the payload says so
#: rather than letting a ceiling masquerade as an answer.
_MAX_PARTICIPATION = 0.25

#: A two-session sigma is a coin flip dressed as a volatility.
_MIN_SESSIONS_FOR_SIGMA = 5

#: Minutes in a regular session, 09:30-16:00 ET. Used to convert a horizon in SESSIONS into a
#: number of 1m steps — never to infer how many sessions a pile of bars represents (RC-167).
_BARS_PER_RTH_SESSION = 390

#: Below this the bootstrap is resampling noise. One session of bars is not a return series.
_MIN_RETURNS_FOR_BOOTSTRAP = 600

#: Block length. Long enough to carry a volatility cluster through into the sampled path;
#: independent draws would destroy the very autocorrelation that makes a real tape dangerous.
_BOOTSTRAP_BLOCK_BARS = 30

_DENSITY_BINS = 48

#: Stated once, so every surface refuses for the same reason in the same words.
_RISK_NEUTRAL_UNAVAILABLE = (
    "option_chain_accrual banks [strike, net_gex, volume] triples and no option PRICES, so the "
    "risk-neutral density (second derivative of call price across strikes) cannot be formed "
    "from anything this repo currently stores"
)

#: A research block older than this is shown greyed. Catalysts and analyst scorecards perish;
#: a brief that ages silently is worse than no brief.
_BRIEF_BLOCK_SHELF_LIFE_SEC = 36 * 3600.0

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


def _iso_utc_to_epoch(text: str) -> float | None:
    """Parse an explicitly-UTC ISO stamp such as `2026-07-17T14:10:43Z`.

    Separate from `_naive_text_to_utc_conservative` on purpose: this input DECLARES its zone, so
    there is nothing to be conservative about and adding a safety margin would be wrong.
    """
    s = (text or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.timestamp()


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
    """One row per subject — the newest thing we knew about `kind` at `as_of_utc`.

    RC-172: this used to call `facts_as_of` and reduce in Python, which MEASURED 2026-07-31
    pulled 48,564 short-volume rows across the wire to keep 12,617 of them, on every Radar
    request, against a database already under enough write contention to have its own open root
    cause (RC-166). The reduction belongs in SQL, where the index can do it.
    """
    wanted = {s.upper() for s in subjects} if subjects else None
    if not isinstance(as_of_utc, (int, float)) or as_of_utc <= 0:
        raise DeskFactError(f"as_of_utc must be a positive epoch, got {as_of_utc!r}")
    sql = (
        "SELECT subject, kind, event_time_utc, knowledge_time_utc, source, source_ref, tier, "
        "value_num, payload_json FROM ("
        "  SELECT *, ROW_NUMBER() OVER ("
        "    PARTITION BY subject ORDER BY knowledge_time_utc DESC, event_time_utc DESC"
        "  ) AS rn FROM desk_facts WHERE kind = ? AND knowledge_time_utc <= ?"
        ") WHERE rn = 1"
    )
    args: list[Any] = [kind, float(as_of_utc)]
    if wanted:
        sql += " AND subject IN (" + ",".join("?" for _ in wanted) + ")"
        args.extend(sorted(wanted))
    try:
        con = _connect(db_path, read_only=True)
    except sqlite3.OperationalError:
        return {}
    try:
        rows = con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return {}  # table absent — absence reaches the surface as absence
    finally:
        con.close()
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = dict(r)
        if d.get("payload_json"):
            try:
                d["payload"] = json.loads(d["payload_json"])
            except (TypeError, ValueError):
                d["payload"] = None
        d.pop("payload_json", None)
        best[d["subject"]] = d
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
            tot = float_positive_or_none(r["total_volume"])
            if tot is None:
                skipped += 1
                continue
            # RC-274: a NULL short_volume is FINRA not reporting, which is not the same fact as
            # zero shares sold short. Divided into total it used to publish a 0.0 ratio under
            # tier "MEASURED" — a number no one measured.
            short = float_nonnegative_or_none(r["short_volume"])
            if short is None:
                skipped += 1
                continue
            ratio = short / tot
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
    from app.domain.time_et import et_date_str_from_ts_utc

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
    now = time.time()
    per_day: dict[tuple[str, str], list[float]] = {}
    last_bar: dict[str, float] = {}
    skipped_non_rth = skipped_incomplete = 0
    complete: dict[str, bool] = {}
    for r in raw:
        ts = float_positive_or_none(r["bar_end_ts_utc"])
        sym = str(r["ticker"] or "").upper()
        if not sym or ts is None:
            continue
        # RC-176: both clock AND calendar. `price_bars_1m` really does carry weekend/holiday
        # rows (2026-07-03/04/05/11/18 measured), and the clock-only filter counted them as
        # sessions.
        if not is_rth_trading_ts(ts):
            skipped_non_rth += 1
            continue
        d = et_date_str_from_ts_utc(ts)
        # RC-173: a session in progress contributes a FRACTION of a session's turnover. Letting
        # it into the sample drags the median down for as long as the market is open.
        if d not in complete:
            complete[d] = session_is_complete(d, now)
        if not complete[d]:
            skipped_incomplete += 1
            continue
        # RC-274: a NULL close used to contribute 0 dollars, quietly deflating the very turnover
        # ADV ranks names on — while a NULL volume raised TypeError two characters later. Same
        # absence, two behaviours. A bar we cannot price is a bar we do not count.
        close = float_positive_or_none(r["close"])
        vol = float_nonnegative_or_none(r["volume"])
        if close is None or vol is None:
            skipped_incomplete += 1
            continue
        per_day.setdefault((sym, d), []).append(close * vol)
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
            "skipped_incomplete_session_bars": skipped_incomplete,
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
            ts = float_positive_or_none(r["ts"])
            sym = str(r["ticker"] or "").upper()
            if ts is None or not sym:
                skipped += 1
                continue
            # RC-274: tier "MEASURED" is a claim about provenance. A NULL n_strikes written as
            # 0 makes that claim about a number nobody produced.
            n_strikes = float_nonnegative_or_none(r["n_strikes"])
            if n_strikes is None:
                skipped += 1
                continue
            batch.append((
                sym, "options_listed", ts, ts, "schwab.option_chain_accrual", None,
                "MEASURED", n_strikes,
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


def effective_spread_bps(
    db_path: str | Path, subject: str, as_of_utc: float, *, window_days: int = 20
) -> dict[str, Any] | None:
    """Median quoted spread in basis points over the regular session.

    `snapshots.spread` is an absolute price, so it is normalised by the spot recorded on the
    same row rather than by a later one — a spread divided by a price from a different instant
    is not a spread. RTH membership comes from `time_et`, not from the denormalised
    `market_session` column, for the same reason RC-170 exists: one authority per question.
    """
    lo = as_of_utc - (window_days * 86400.0)
    try:
        con = _connect(db_path, read_only=True)
    except sqlite3.OperationalError:
        return None
    try:
        rows = con.execute(
            "SELECT ts_utc, spot, spread FROM snapshots WHERE ticker = ? AND ts_utc >= ? "
            "AND ts_utc <= ? AND spread IS NOT NULL AND spot > 0",
            (subject.upper(), lo, as_of_utc),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()

    bps: list[float] = []
    for r in rows:
        # RC-274: the SQL already excludes NULL spread and non-positive spot, so a row failing
        # here is a row the SELECT could not have returned — which is exactly why it is checked.
        ts = float_positive_or_none(r["ts_utc"])
        spread = float_nonnegative_or_none(r["spread"])
        spot = float_positive_or_none(r["spot"])
        if ts is None or spread is None or spot is None:
            continue
        if not is_rth_trading_ts(ts):
            continue
        bps.append((spread / spot) * 10_000.0)
    bps.sort()
    if len(bps) < _MIN_QUOTES_FOR_SPREAD:
        return None
    mid = len(bps) // 2
    median = bps[mid] if len(bps) % 2 else 0.5 * (bps[mid - 1] + bps[mid])
    return {
        "median_bps": round(median, 2),
        "p90_bps": round(bps[min(len(bps) - 1, int(0.90 * len(bps)))], 2),
        "n_quotes": len(bps),
        "window_days": window_days,
        "tier": "DERIVED",
    }


def is_rth_trading_ts(ts_utc: float) -> bool:
    """RTH means BOTH clock and calendar — 09:30–16:00 ET on an actual trading day.

    RC-176: `time_et.is_rth_ts_utc` answers only the CLOCK question (its docstring says so), and
    every Desk reader used it alone, so Saturday 11:00 passed as regular session. That is not
    hypothetical: MEASURED 2026-08-01, `price_bars_1m` carries bars on 2026-07-03/04/05/11/18 —
    a holiday and four weekend dates — which the ADV, sigma and bootstrap readers all counted as
    sessions. The calendar question belongs to `is_trading_day_et`; this helper asks both.
    """
    from app.domain.time_et import et_date_str_from_ts_utc, is_rth_ts_utc, is_trading_day_et

    return is_rth_ts_utc(ts_utc) and is_trading_day_et(et_date_str_from_ts_utc(ts_utc))


def session_is_complete(et_date: str, as_of_utc: float) -> bool:
    """Has the regular session for `et_date` already closed as of `as_of_utc`?

    RC-173: every daily statistic here — sigma, and the ADV median — was built by taking the
    last regular-session bar of each ET date as that date's close. At 21:15 CT with the market
    shut that is the close. At 11:00 ET it is an intraday print being treated as one, so the
    newest "daily return" is a partial-day move and the newest "session volume" is a fraction of
    a session. Both quietly distort the number, and only ever while the market is open — which
    is precisely when the operator is looking at it.
    """
    from app.domain.time_et import (
        et_date_str_from_ts_utc,
        et_minute_total_from_ts_utc,
        is_trading_day_et,
        session_close_mins_for_et_date,
    )

    # RC-176: a non-trading date has no session, so nothing can be in progress. Without this
    # guard, `session_close_mins_for_et_date` supplies a close time for any non-holiday date in
    # a covered year (it does not ask the weekday), so a Saturday judged before 16:00 ET read as
    # "session still open" — and Desk statistics froze out the day's data on weekend runs.
    # Callers that COUNT sessions must separately exclude non-trading dates (is_rth_trading_ts);
    # this function only answers "is anything still in progress", and on a Saturday the answer
    # is no.
    if not is_trading_day_et(et_date):
        return True
    if et_date != et_date_str_from_ts_utc(as_of_utc):
        return True  # a past date's session is closed by construction
    close_mins = session_close_mins_for_et_date(et_date)
    if not close_mins:
        return True  # no session that day — nothing incomplete about it
    return et_minute_total_from_ts_utc(as_of_utc) >= float(close_mins)


def daily_sigma_bps(db_path: str | Path, subject: str, as_of_utc: float, *,
                    window_days: int = 20) -> dict[str, Any] | None:
    """Daily volatility in basis points, measured on this name's own regular-session closes.

    RC-171: capacity used to be computed from a ratio of impact budget to quoted SPREAD, which
    is not a volatility and carries no units that make the square-root law true — it produced a
    $5,601,230,345 capacity for SPY, a quarter of its entire daily turnover, because the
    participation cap was the only thing still binding. Impact scales with VOLATILITY; the
    spread is the cost of one crossing, not the cost of size.
    """
    import math

    from app.domain.time_et import et_date_str_from_ts_utc

    lo = as_of_utc - (window_days * 86400.0)
    try:
        con = _connect(db_path, read_only=True)
    except sqlite3.OperationalError:
        return None
    try:
        rows = con.execute(
            "SELECT bar_end_ts_utc, close FROM price_bars_1m WHERE ticker = ? "
            "AND bar_end_ts_utc >= ? AND bar_end_ts_utc <= ? AND close > 0 "
            "ORDER BY bar_end_ts_utc", (subject.upper(), lo, as_of_utc)).fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()

    closes: dict[str, float] = {}
    for r in rows:
        ts = float_positive_or_none(r["bar_end_ts_utc"])
        if ts is None or not is_rth_trading_ts(ts):  # RC-176: clock AND calendar
            continue
        close = float_positive_or_none(r["close"])  # RC-274
        if close is None:
            continue
        closes[et_date_str_from_ts_utc(ts)] = close
    # RC-173: a session still in progress has no close. Including it turns the newest daily
    # return into a partial-day move.
    series = [closes[d] for d in sorted(closes) if session_is_complete(d, as_of_utc)]
    if len(series) < _MIN_SESSIONS_FOR_SIGMA:
        return None
    # strict=False is deliberate and correct: `series[1:]` is one shorter by construction, which
    # is exactly the pairing wanted. Stated rather than defaulted so the next reader does not
    # have to work out whether the length mismatch is intended.
    rets = [math.log(b / a) for a, b in zip(series, series[1:], strict=False) if a > 0 and b > 0]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    sigma = math.sqrt(var)
    if sigma <= 0:
        return None
    return {"sigma_bps": round(sigma * 10_000.0, 1), "n_sessions": len(series),
            "window_days": window_days, "tier": "DERIVED"}


def dossier(db_path: str | Path, subject: str, as_of_utc: float) -> dict[str, Any]:
    """One name, assembled only from facts knowable at `as_of_utc`.

    Every field is nullable and every null is reported as a null with a reason. There is no
    branch here that substitutes a plausible number for a missing one.
    """
    s = subject.upper()
    adv = latest_by_subject(db_path, as_of_utc, "adv_dollar", subjects=[s]).get(s)
    svr = latest_by_subject(db_path, as_of_utc, "short_volume_ratio", subjects=[s]).get(s)
    opt = latest_by_subject(db_path, as_of_utc, "options_listed", subjects=[s]).get(s)
    spread = effective_spread_bps(db_path, s, as_of_utc)

    earnings = [
        f for f in facts_as_of(db_path, as_of_utc, subject=s, kind="earnings_date")
        if f["value_num"] and f["value_num"] >= as_of_utc
    ]
    earnings.sort(key=lambda f: f["value_num"])

    capacity = None
    capacity_inputs: dict[str, Any] | None = None
    sigma_bps = daily_sigma_bps(db_path, s, as_of_utc)
    if adv and adv["value_num"] and sigma_bps:
        # RC-171: square-root market impact, impact_bps = Y * sigma_daily_bps * sqrt(Q / ADV),
        # solved for Q. Sigma is MEASURED on this name's own regular-session closes; Y is a
        # literature coefficient and is published alongside the answer rather than buried, so
        # the number can be re-derived and argued with. The participation cap is a hard ceiling,
        # not the operative term — when it binds, the payload says so.
        q_frac = (_CAPACITY_IMPACT_BPS / (_IMPACT_COEFFICIENT * sigma_bps["sigma_bps"])) ** 2
        capped = q_frac >= _MAX_PARTICIPATION
        capacity = float(adv["value_num"]) * min(_MAX_PARTICIPATION, q_frac)
        capacity_inputs = {
            "model": "square_root_impact",
            "impact_budget_bps": _CAPACITY_IMPACT_BPS,
            "coefficient_Y": _IMPACT_COEFFICIENT,
            "sigma_daily_bps": sigma_bps["sigma_bps"],
            "sigma_sessions": sigma_bps["n_sessions"],
            "participation": round(min(_MAX_PARTICIPATION, q_frac), 4),
            "participation_capped": capped,
        }

    missing: list[str] = []
    if adv is None:
        missing.append("adv_dollar — fewer than 3 regular sessions of bars in the window")
    if spread is None:
        missing.append(
            f"effective_spread — fewer than {_MIN_QUOTES_FOR_SPREAD} regular-session quotes")
    if opt is None:
        missing.append("options_listed — this name has no banked chain")
    if svr is None:
        missing.append("short_volume_ratio — not present in the FINRA file for this symbol")

    return {
        "subject": s,
        "as_of_utc": float(as_of_utc),
        "adv_dollar": adv["value_num"] if adv else None,
        "adv_payload": adv.get("payload") if adv else None,
        "short_volume_ratio": svr["value_num"] if svr else None,
        "short_volume_lag_hours": (
            round((svr["knowledge_time_utc"] - svr["event_time_utc"]) / 3600.0, 1)
            if svr else None
        ),
        "n_strikes": opt["value_num"] if opt else None,
        "spread": spread,
        "capacity_usd": capacity,
        "capacity_inputs": capacity_inputs,
        "capacity_impact_bps": _CAPACITY_IMPACT_BPS if capacity is not None else None,
        "next_earnings_utc": earnings[0]["value_num"] if earnings else None,
        "missing": missing,
        "tiers": {"adv_dollar": "DERIVED", "short_volume_ratio": "MEASURED",
                  "options_listed": "MEASURED", "spread": "DERIVED",
                  "capacity_usd": "ESTIMATED" if capacity is not None else None},
    }


def evidence_rows(repo_root: str | Path | None = None,
                  as_of_utc: float | None = None) -> dict[str, Any]:
    """The study scoreboard, READ from `reports/` rather than retyped.

    Retyping is how a scoreboard drifts from the studies it claims to summarise, and a drifted
    scoreboard is worse than none: it is the one surface the rest of the Desk defers to when it
    refuses to make a claim.

    RC-172: this ignored the replay clock entirely, so dragging the Desk back to a past instant
    still rendered whatever scoreboard exists on disk NOW. On a tab whose whole premise is that
    a screen can be judged against what was knowable, the one surface that adjudicates claims
    was the surface reading the future. It now refuses a scoreboard generated after `as_of_utc`.
    """
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parent
    p = root / "reports" / "fp_scoreboard_latest.json"
    # RC-174: the absolute path is the operator's home directory. This value is handed to a
    # browser, and this repo already forbids operator-home paths in tracked evidence for the
    # same reason — a path is an environment disclosure that tells a reader who is running the
    # process and where. The repo-relative form names the file just as usefully.
    rel = "reports/fp_scoreboard_latest.json"
    if not p.exists():
        return {"rows": [], "source": rel, "empty_reason": "no scoreboard has been written"}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"rows": [], "source": rel, "empty_reason": f"{type(e).__name__}: {e}"}

    gen_raw = str(doc.get("generated_utc") or "")
    if as_of_utc is not None:
        gen_ts = _iso_utc_to_epoch(gen_raw)
        if gen_ts is None:
            return {"rows": [], "source": rel, "generated_utc": gen_raw,
                    "empty_reason": ("the scoreboard carries no readable generated_utc, so it "
                                     "cannot be placed on the replay clock")}
        if gen_ts > float(as_of_utc):
            return {"rows": [], "source": rel, "generated_utc": gen_raw,
                    "empty_reason": (f"this scoreboard was generated {gen_raw}, after the "
                                     "instant being replayed — it was not knowable yet")}

    rows = []
    # external-key-ok: `studies` and `totals.existence_pass_cells_sum` are keys of the
    # fp_scoreboard_v1 JSON document written by the Find & Prove scoreboard tool, not of any
    # dict literal in this repo, so the orphan-key check cannot see their producer. They are
    # read defensively — a missing key yields an empty mapping and an empty Evidence tab with a
    # stated reason, never a silent None presented as a result.
    for name, st in sorted((doc.get("studies") or {}).items()):  # external-key-ok: fp_scoreboard_v1 JSON
        status = str(st.get("status") or st.get("verdict") or "UNKNOWN")
        n_pass = st.get("n_pass")
        n_fail = st.get("n_fail")
        rows.append({
            "study": name,
            "verdict": status,
            "n_pass": n_pass,
            "n_fail": n_fail,
            # Nothing is ESTIMATED until it passes. The scoreboard is the promotion authority.
            "tier": "ESTIMATED" if (isinstance(n_pass, int) and n_pass > 0) else "UNPROVEN",
        })
    totals = doc.get("totals") or {}
    return {
        "rows": rows,
        "source": rel,
        "generated_utc": doc.get("generated_utc"),
        "money_path": doc.get("money_path"),
        "existence_pass_cells": totals.get("existence_pass_cells_sum"),  # external-key-ok: fp_scoreboard_v1 JSON
        "empty_reason": None if rows else "the scoreboard names no studies",
    }


def _rth_log_returns(db_path: str | Path, subject: str, as_of_utc: float,
                     window_days: int) -> list[float]:
    lo = as_of_utc - (window_days * 86400.0)
    try:
        con = _connect(db_path, read_only=True)
    except sqlite3.OperationalError:
        return []
    try:
        rows = con.execute(
            "SELECT bar_end_ts_utc, close FROM price_bars_1m WHERE ticker = ? "
            "AND bar_end_ts_utc >= ? AND bar_end_ts_utc <= ? AND close > 0 "
            "ORDER BY bar_end_ts_utc", (subject.upper(), lo, as_of_utc)
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    # RC-176: clock AND calendar — a weekend bar in the return series injects a fake flat (or
    # blown) minute into the bootstrap's block distribution.
    closes: list[float] = []
    for r in rows:
        ts = float_positive_or_none(r["bar_end_ts_utc"])  # RC-274
        close = float_positive_or_none(r["close"])
        if ts is None or close is None or not is_rth_trading_ts(ts):
            continue
        closes.append(close)
    import math
    return [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False)
            if a > 0 and b > 0]


def terminal_distribution(
    db_path: str | Path, subject: str, as_of_utc: float, *,
    horizon_sessions: int = 5, spot: float | None = None,
    n_paths: int = 4000, window_days: int = 20,
) -> dict[str, Any]:
    """Block bootstrap of the name's OWN one-minute returns to a terminal price distribution.

    Blocks rather than independent draws, because independent draws destroy exactly what makes
    a real tape dangerous: volatility clusters and autocorrelation. A lognormal Monte Carlo with
    one sigma would produce a prettier curve and a thinner tail than this name actually has.

    This is the PHYSICAL measure. The risk-neutral one is not available: `option_chain_accrual`
    banks `[strike, net_gex, volume]` triples and no option prices, so the second derivative of
    call price across strikes — the density the market itself is quoting — cannot be formed from
    anything this repo currently stores. That absence is reported, not approximated.

    The seed is derived from the DATA, not the clock, so the same underlying series returns the
    same answer however often it is asked. RC-175: it used to include `int(as_of_utc)`, and on
    the live path `as_of` is NOW — so two calls a second apart produced different quantiles
    (p50 745.3444 then 744.9982, MEASURED 2026-07-31) while this docstring claimed they could
    not. A desk number that changes on refresh cannot be checked, and a number that cannot be
    checked is not evidence; a docstring promising otherwise is worse than no promise at all.
    """
    import math
    import random

    rets = _rth_log_returns(db_path, subject, as_of_utc, window_days)
    steps = int(horizon_sessions) * _BARS_PER_RTH_SESSION
    if len(rets) < _MIN_RETURNS_FOR_BOOTSTRAP or steps <= 0:
        return {
            "subject": subject.upper(), "available": False,
            "reason": (f"only {len(rets)} regular-session 1m returns in the window; "
                       f"{_MIN_RETURNS_FOR_BOOTSTRAP} required"),
            "risk_neutral_available": False,
            "risk_neutral_reason": _RISK_NEUTRAL_UNAVAILABLE,
        }

    if spot is None or spot <= 0:
        try:
            con = _connect(db_path, read_only=True)
            row = con.execute(
                "SELECT close FROM price_bars_1m WHERE ticker = ? AND bar_end_ts_utc <= ? "
                "AND close > 0 ORDER BY bar_end_ts_utc DESC LIMIT 1",
                (subject.upper(), as_of_utc)).fetchone()
            con.close()
            spot = float(row["close"]) if row else None
        except sqlite3.OperationalError:
            spot = None
    if not spot or spot <= 0:
        return {"subject": subject.upper(), "available": False,
                "reason": "no regular-session close at or before this instant",
                "risk_neutral_available": False,
                "risk_neutral_reason": _RISK_NEUTRAL_UNAVAILABLE}

    blk = _BOOTSTRAP_BLOCK_BARS
    block_sums = [sum(rets[i:i + blk]) for i in range(len(rets) - blk + 1)]
    if not block_sums:
        return {"subject": subject.upper(), "available": False,
                "reason": "return series shorter than one bootstrap block",
                "risk_neutral_available": False,
                "risk_neutral_reason": _RISK_NEUTRAL_UNAVAILABLE}

    n_blocks = max(1, steps // blk)
    # RC-175: seeded on the SERIES, never on the wall clock. Two calls against the same bars
    # must agree; two calls after a new bar arrives are entitled to differ, and do.
    seed = (f"{subject.upper()}|{len(rets)}|{blk}|{len(block_sums)}|"
            f"{spot:.6f}|{rets[-1]:.10f}|{horizon_sessions}|{n_paths}")
    rng = random.Random(seed)
    terminals = []
    for _ in range(int(n_paths)):
        total = 0.0
        for _ in range(n_blocks):
            total += block_sums[rng.randrange(len(block_sums))]
        terminals.append(spot * math.exp(total))
    terminals.sort()

    def q(p: float) -> float:
        return terminals[min(len(terminals) - 1, max(0, int(p * len(terminals))))]

    lo, hi = terminals[0], terminals[-1]
    nb = _DENSITY_BINS
    width = (hi - lo) / nb if hi > lo else 1.0
    counts = [0] * nb
    for t in terminals:
        counts[min(nb - 1, int((t - lo) / width))] += 1

    return {
        "subject": subject.upper(),
        "available": True,
        "spot": spot,
        "horizon_sessions": int(horizon_sessions),
        "n_paths": int(n_paths),
        "n_returns": len(rets),
        "block_bars": blk,
        "seed": seed,
        "quantiles": {"p05": q(0.05), "p25": q(0.25), "p50": q(0.50),
                      "p75": q(0.75), "p95": q(0.95)},
        "density": {"lo": lo, "hi": hi, "bin_width": width,
                    "counts": counts, "n": len(terminals)},
        "tier": "ESTIMATED",
        "risk_neutral_available": False,
        "risk_neutral_reason": _RISK_NEUTRAL_UNAVAILABLE,
    }


def vertical_spread(long_strike: float, short_strike: float, long_price: float,
                    short_price: float, contracts: int = 1,
                    multiplier: int = 100) -> dict[str, Any]:
    """Payoff arithmetic for a two-leg vertical. Deterministic — no forecast, no free parameter.

    Kept a pure function so it can be checked by hand against the screen, which is the whole
    reason a calculator earns trust before anything predictive appears next to it.
    """
    if long_strike <= 0 or short_strike <= 0 or contracts <= 0:
        raise DeskFactError("strikes and contracts must be positive")
    if long_strike == short_strike:
        raise DeskFactError("a vertical needs two different strikes")
    # RC-173: an option price of zero or less is not a quote, and accepting one produced a
    # spread whose maximum loss displayed as -0.0 — a screen saying this trade cannot lose
    # money. A mis-keyed minus sign must not be able to render a risk-free position.
    if float(long_price) <= 0 or float(short_price) <= 0:
        raise DeskFactError(
            f"option prices must be positive quotes, got long={long_price} short={short_price} "
            "— a non-positive price is not a market, and pricing against one produces a payoff "
            "that understates the loss"
        )
    debit = (float(long_price) - float(short_price)) * multiplier * contracts
    width = abs(float(short_strike) - float(long_strike)) * multiplier * contracts
    is_debit = debit > 0
    max_gain = (width - debit) if is_debit else -debit
    max_loss = debit if is_debit else -(width + debit)
    lower = min(long_strike, short_strike)
    breakeven = (lower + abs(debit) / (multiplier * contracts)) if is_debit else (
        lower + (width - abs(debit)) / (multiplier * contracts))
    return {
        "net_debit": round(debit, 2),
        "max_gain": round(max_gain, 2),
        "max_loss": round(-abs(max_loss), 2),
        "breakeven": round(breakeven, 4),
        "width_usd": round(width, 2),
        "is_debit": is_debit,
        "tier": "DERIVED",
    }


def probability_of_profit(dist: Mapping[str, Any], breakeven: float,
                          direction: str = "above") -> dict[str, Any] | None:
    """POP read off the bootstrap terminal distribution — one measure, named as such.

    Deliberately returns a single labelled measure rather than a blended number. The two
    measures a desk wants side by side are physical and risk-neutral, and the risk-neutral one
    is unavailable here; averaging what exists with what does not is how a placeholder becomes
    a fact.
    """
    if not dist or not dist.get("available"):
        return None
    d = dist["density"]
    lo, width, counts = float(d["lo"]), float(d["bin_width"]), list(d["counts"])
    hi = float(d["hi"])
    total = sum(counts) or 1
    hit = 0
    for i, c in enumerate(counts):
        centre = lo + (i + 0.5) * width
        if (direction == "above" and centre >= breakeven) or (
                direction == "below" and centre <= breakeven):
            hit += c
    # RC-171: a POP of exactly 0 or 1 is never a probability the sample can support — it means
    # the breakeven sits outside every path drawn, so the honest answer is "outside the sampled
    # range", not a certainty. Printing 1.0000 next to a real position is how a mis-keyed strike
    # becomes a conviction.
    outside = breakeven < lo or breakeven > hi
    return {"measure": "bootstrap_physical",
            "pop": None if outside else round(hit / total, 4),
            "outside_sampled_range": outside,
            "sampled_range": [round(lo, 4), round(hi, 4)],
            "breakeven": round(float(breakeven), 4),
            "n_paths": dist.get("n_paths"), "tier": "ESTIMATED",
            "risk_neutral_pop": None, "risk_neutral_reason": _RISK_NEUTRAL_UNAVAILABLE}


BRIEF_SQL = """
CREATE TABLE IF NOT EXISTS desk_briefs (
    brief_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    et_date         TEXT NOT NULL,
    generated_utc   REAL NOT NULL,
    title           TEXT NOT NULL,
    producer        TEXT NOT NULL,
    blocks_json     TEXT NOT NULL,
    sources_json    TEXT NOT NULL,
    ingested_at_utc REAL NOT NULL
)
"""


def put_brief(db_path: str | Path, *, et_date: str, title: str, producer: str,
              generated_utc: float, blocks: Sequence[Mapping[str, Any]],
              sources: Sequence[Mapping[str, Any]]) -> int:
    """Store a research brief as STRUCTURED BLOCKS, never as rendered HTML.

    Blocks are what make the Brief replayable and self-scoring: each carries its own `as_of`, so
    the page can grey a stale block instead of ageing silently as one opaque document. A stored
    blob of HTML can do neither.
    """
    if not et_date or not title or not producer:
        raise DeskFactError("et_date, title and producer are required")
    if not blocks:
        raise DeskFactError("a brief with no blocks is not a brief")
    for i, b in enumerate(blocks):
        if "as_of_utc" not in b:
            raise DeskFactError(f"block {i} has no as_of_utc — it could never be shown as stale")
    con = _connect(db_path)
    try:
        con.execute(BRIEF_SQL)
        cur = con.execute(
            "INSERT INTO desk_briefs (et_date, generated_utc, title, producer, blocks_json, "
            "sources_json, ingested_at_utc) VALUES (?,?,?,?,?,?,?)",
            (et_date, float(generated_utc), title, producer,
             json.dumps(list(blocks), separators=(",", ":")),
             json.dumps(list(sources), separators=(",", ":")), time.time()))
        con.commit()
        # RC-274: rowid 0 is not a rowid. Returning it hands the caller a handle that resolves
        # to no row, and the failure surfaces later somewhere with no connection to this INSERT.
        if cur.lastrowid is None:
            raise DeskFactError("brief INSERT reported no rowid — the write did not land")
        return int(cur.lastrowid)
    finally:
        con.close()


def latest_brief(db_path: str | Path, as_of_utc: float) -> dict[str, Any] | None:
    """The newest brief we held at `as_of_utc`, with each block's age computed against it."""
    try:
        con = _connect(db_path, read_only=True)
    except sqlite3.OperationalError:
        return None
    try:
        row = con.execute(
            "SELECT * FROM desk_briefs WHERE generated_utc <= ? ORDER BY generated_utc DESC "
            "LIMIT 1", (float(as_of_utc),)).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    if row is None:
        return None
    d = dict(row)
    blocks = json.loads(d.pop("blocks_json"))
    for b in blocks:
        # RC-274: write-time refuses a block with no as_of_utc, so reaching this branch means an
        # older or hand-edited row. `or 0.0` dated it to 1970 and called it stale, which is the
        # right verdict reached by fabricating a 56-year age the UI then divided by 3600.
        block_ts = float_finite_or_none(b.get("as_of_utc"))
        if block_ts is None:
            b["age_sec"] = None
            b["stale"] = True
            continue
        age = float(as_of_utc) - block_ts
        b["age_sec"] = age
        b["stale"] = age > _BRIEF_BLOCK_SHELF_LIFE_SEC
    d["blocks"] = blocks
    d["sources"] = json.loads(d.pop("sources_json"))
    d["stale_blocks"] = sum(1 for b in blocks if b["stale"])
    return d


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
    def _rank_key(r: dict[str, Any]) -> tuple[float, str]:
        """Descending ADV, then symbol. A name with no measured ADV sorts last rather than
        sorting as zero-and-therefore-cheapest — absence is not a small number."""
        adv = r.get("adv_dollar")
        return (-float(adv) if isinstance(adv, (int, float)) else 0.0, str(r["subject"]))

    out.sort(key=_rank_key)
    # RC-174: "12,617 subjects knowable" overstated what the desk actually holds. MEASURED
    # 2026-07-31: of the 60 rows rendered, 37 carried all three structural facts and 23 carried
    # a short-volume ratio and nothing else — no dollar volume, no chain, nothing that makes a
    # name tradeable. A count that mixes those two is a count of rows in a file, not of
    # candidates, and under a header reading "Candidates" it reads as depth the desk does not
    # have. The breakdown now travels with the total.
    structural = sum(
        1 for r in out
        if r["adv_dollar"] is not None and r["n_strikes"] is not None
    )
    single = sum(
        1 for r in out
        if sum(1 for k in ("adv_dollar", "short_volume_ratio", "n_strikes")
               if r[k] is not None) <= 1
    )
    return {
        "as_of_utc": float(as_of_utc),
        "rows": out[:limit],
        "n_total": len(out),
        "n_structural": structural,
        "n_single_fact": single,
        "coverage_note": (
            f"{structural} of {len(out)} subjects carry both dollar volume and a banked chain; "
            f"{single} carry a single fact and are listed, not screened"
        ),
        "rank_basis": "adv_dollar desc — tradeability, not expected return",
        "empty_reason": None if out else (
            "no facts carry a knowledge time at or before this instant"
        ),
    }
