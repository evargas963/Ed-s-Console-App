"""Terrain (gamma-level) API routes: radar, quarantine, per-strike, scorecard, payload.

RC-REHAB-1 (Phase 3). Every shared dependency here (module-level caches/locks the
background terrain-refresh loop also writes, and the private helper functions the loop
also calls) stays in server.py and is imported back lazily inside each route body — see
app/api/routes/options.py's get_options_gamma_surface for the established precedent.
"""

from __future__ import annotations

import json
import time

from config import DEFAULT_TICKER
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from instrument_identity import ticker_storage_key
from json_blob_codec import decode_json_blob   # RC-REHAB-3: transparent gzip on JSON blob columns
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from time_et import is_trading_day_et
from time_et import now_et

router = APIRouter()


@router.get("/api/terrain/radar")
def get_terrain_radar(limit: int = Query(default=12, ge=1, le=60)):
    """Air-traffic radar: ONLY tickers currently in the operator's airspace.

    A 51-row grid is a list, not a radar. A controller tracks the aircraft that are
    actually in the sector, so a ticker earns a slot only by doing something:
      * sitting at a wall (within RADAR_NEAR_PCT)
      * having broken a wall with acceptance
      * an unambiguous regime with a wall within RADAR_WATCH_PCT
    Everything mid-box and quiet is deliberately invisible. Untrusted tickers are never
    ranked as if their levels were real -- they are reported separately as blind spots.
    """
    from terrain_radar import (
        RADAR_NEAR_PCT,
        RADAR_WATCH_PCT,
        _radar_atr,
        _radar_contact,
        _terrain_snapshots_for_radar,
    )

    # Coerced so the handler is callable directly in tests, not only over HTTP
    # (FastAPI passes a Query object when the default is used outside a request).
    try:
        max_rows = int(limit)
    except (TypeError, ValueError):
        max_rows = 12

    rows: list[dict] = []
    blind = 0
    cached = _terrain_snapshots_for_radar()
    for t in cached:
        spot = t.get("spot")
        if t.get("confidence") != "TRUSTED" or not spot:
            blind += 1
            continue
        atr = _radar_atr(t.get("ticker"))
        if not atr.daily:
            blind += 1                    # no scale means no ring; never guess one
            continue
        contact = _radar_contact(t, spot, atr)
        if contact is not None:
            rows.append(contact)

    rows.sort(key=lambda r: r["_sort"])
    for r in rows:
        r.pop("_sort", None)
    return {"rows": rows[:max_rows], "tracked": len(rows), "scanned": len(cached),
            "blind_spots": blind, "near_pct": RADAR_NEAR_PCT, "watch_pct": RADAR_WATCH_PCT}


@router.get("/api/diagnostics/terrain-producer")
def get_terrain_producer_diagnostics():
    """RC-148: the producer's own state, readable. Until this existed, `_terrain_refresh_last_error`
    was reachable only through one dead branch and the console had NO way to answer "why is this
    ticker not refreshing" — the question that cost a session on $SPX (RC-126) and another on
    RTY/XXT. Read-only, no Schwab call, no model stack."""
    from terrain_freshness import TERRAIN_STALE_AFTER_SEC
    from terrain_state import TERRAIN_REFRESH_SEC, _terrain_refresh_last_error
    from terrain_loop import terrain_cache_size
    from terrain_quarantine import (
        TERRAIN_QUARANTINE_HARD_FAILS,
        TERRAIN_QUARANTINE_LEDGER,
        _terrain_consecutive_fails,
        _terrain_quarantine,
        _terrain_quarantine_lock,
        _terrain_quarantine_skips,
        _terrain_skip_lock,
        _terrain_skipped_reason,
    )

    with _terrain_skip_lock:
        skips = dict(_terrain_skipped_reason)
    with _terrain_quarantine_lock:
        quar = {k: dict(v) for k, v in _terrain_quarantine.items()}
        avoided = dict(_terrain_quarantine_skips)
    return JSONResponse({
        "last_error": dict(_terrain_refresh_last_error),
        "consecutive_failures": dict(_terrain_consecutive_fails),
        "quarantined": quar,
        "fetches_avoided_by_quarantine": avoided,
        "skipped_this_cycle": skips,
        "cache_size": terrain_cache_size(),
        "stale_after_sec": TERRAIN_STALE_AFTER_SEC,
        "refresh_sec": TERRAIN_REFRESH_SEC,
        "hard_fail_threshold": TERRAIN_QUARANTINE_HARD_FAILS,
        "ledger_path": str(TERRAIN_QUARANTINE_LEDGER),
    })


@router.post("/api/terrain/quarantine/release")
def post_terrain_quarantine_release(ticker: str = Query(...)):
    """Operator re-admission — the ONLY exit from a permanent hold, and it is logged.

    A quarantine with no way back is a deletion the operator never approved, so this exists in
    the same commit as the quarantine itself rather than as a follow-up.
    """
    from terrain_quarantine import terrain_quarantine_release

    return JSONResponse(terrain_quarantine_release(ticker))


# ── CR-03 screen 1 — per-strike gamma/volume bars for the histogram panel ────
# Feeds the /chart sidebar: today's per-strike dealer gamma + traded volume, plus
# the PRIOR wide capture's bars (the day-over-day migration ghosts), each in three
# expiry scopes (all / near<=7DTE / far). Sources are STORED chains only (wide
# morning capture preferred, live narrow chain as fallback) — read-only, no Schwab
# call, no model stack. Bar heights use the same exposure math as terrain.
@router.get("/api/terrain/strikes")
def get_terrain_strikes(ticker: str = Query(default=DEFAULT_TICKER)):
    from math_exposure_core import compute_exposures_by_strike as _cebs
    # RC-REHAB-1 (route-extraction audit fix): `get_db` deliberately excluded from
    # this `from server import (...)` tuple -- see logger.py's identical fix comment
    # for why a blanket import eagerly resolving `get_db` raises ImportError before
    # either try/except below (the accrual-bank fallback, the wide-chain read) ever
    # gets a chance to run. `import server as _server` defers resolution to each call
    # site, already inside its own try/except.
    import server as _server
    from math_exposure_core import bucket_metric, total_gamma_raw_at_strike
    from calibration.option_chain_morning_full import latest_accrual_rows
    from terrain_freshness import TERRAIN_STALE_AFTER_SEC, terrain_staleness
    from gamma_surface_state import _note_gamma_surface_demand
    from terrain_loop import terrain_cache_get
    from server import log, resolve_spot

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)   # RC-126: SPX -> $SPX etc., ONE authority
    # Operator-reproduced defect (2026-09-14, "the collection schedule must not block live
    # viewing"): _note_gamma_surface_demand was only ever called from
    # get_options_gamma_surface (the Heatmap grid's own route) -- GEX-by-Strike, the
    # Positioning Migration panel, and the Chart view all read THIS route instead and never
    # registered that anyone was watching. A ticker viewed only through one of those three
    # screens could never reach _terrain_loop's `_previewed` set, so it never got a live
    # refresh attempt regardless of enrollment. Every screen that shows this ticker's live
    # terrain-derived data must register the same demand signal, not just one of them.
    _note_gamma_surface_demand(tk)

    def _per_strike(contracts: list, spot: float) -> dict:
        def _scope(cts: list) -> list:
            if not cts:
                return []
            exposures, _diag = _cebs(cts, spot=spot, require_oi=True)
            vol_by_k: dict[float, float] = {}
            # SINGLE SOURCE: totalVolume read through the canonical non-negative reader so
            # the REST aggregation drops NaN/±inf (raw float() used to admit them, poisoning
            # the sum) and reads 0/negatives identically to the exposure and order-flow paths.
            from numeric_contract import (
                float_finite_or_none as _fin,
                float_nonnegative_or_none as _vol_read,
            )
            for ct in cts:
                # single source: reject NaN strike (raw float() let a NaN become a dict key)
                k = _fin(ct.get("strikePrice"))
                if k is None:
                    continue
                v = _vol_read(ct.get("totalVolume"))
                if v:
                    vol_by_k[k] = vol_by_k.get(k, 0.0) + v
            out = []
            for k, b in exposures.items():
                # Independent-review finding, REPRODUCED (live SPX, 2026-09-14): net_gex_1pct/
                # call_gamma/put_gamma are pre-initialized to a real 0.0 by _strike_bucket, so
                # bucket_metric/total_gamma_raw_at_strike returned a real float (never None)
                # even for a strike where every contract failed the OI gate -- Schwab's SPX
                # feed currently reports openInterest=0/stuck for every contract, so this drew
                # a $0 bar indistinguishable from a strike genuinely measured at flat gamma.
                # has_oi (math_exposure_core.py's own canonical signal) is checked FIRST, before
                # either metric read, so a no-OI strike is skipped the same way RC-276's
                # gamma-resolves-nowhere case already is below -- one exclusion rule, not two.
                if not (isinstance(b, dict) and b.get("has_oi")):
                    continue
                g = bucket_metric(b, "net_gex_1pct")
                if g is None:
                    g = total_gamma_raw_at_strike(b)
                if g is None:
                    # RC-276: the second copy of the terrain_engine:202 bar RC-274 removed. A
                    # strike whose gamma resolves nowhere drew a bar at 0.0, indistinguishable
                    # from a strike measured at flat gamma on the surface used to read dealer
                    # positioning. Hidden here because server.py was allowlisted wholesale.
                    continue
                out.append([round(float(k), 2), round(float(g), 1),
                            int(vol_by_k.get(float(k), 0))])
            out.sort(key=lambda r: r[0])
            return out

        # Cursor-audit F8: unknown DTE must belong to NEITHER near nor far, not silently to far.
        # This endpoint carried its own near/far splitter with the old 999.0 sentinel — a duplicate
        # of the RC-290-fixed canonical _dte_of, which drops an unreadable DTE from BOTH sides. With
        # 999.0 a parse-failed 0-DTE was rendered in the prior-day MONTHLY+ (far) chip and omitted
        # from the ≤7DTE (near) chip. Use the ONE canonical splitter so the two can't diverge again.
        from terrain_engine import _dte_of
        near = [c for c in contracts if (d := _dte_of(c)) is not None and d <= 7]
        far = [c for c in contracts if (d := _dte_of(c)) is not None and d > 7]
        return {"all": _scope(contracts), "near": _scope(near), "far": _scope(far)}

    import sqlite3 as _sq
    today_src, prior_src = None, None
    today, prior = None, None
    spot_used = None
    today_age_sec = None
    # RC-146: bound BEFORE the try. `_snap` was assigned only inside the try body yet read
    # unconditionally in the response dict below — a raising terrain_cache_get took the
    # logged-and-swallowed path and then killed the endpoint with NameError on the way out,
    # turning a degraded panel into a 500. Absence must degrade, never explode.
    _snap: dict = {}
    # RC-68 SINGLE SOURCE FOR TODAY'S PER-STRIKE DATA: the LIVE terrain snapshot.
    # This panel used to render from option_chain_morning_full — MEASURED 2026-07-27 11:31 ET:
    # a 09:47 capture served at 11:31 understated session volume by 281 percent (1,095,874 shown
    # vs 4,176,672 live), ~500K missing on strike 740 alone, while the walls beside it moved on
    # the 60s loop. Two clocks, one story. The terrain loop already computes this exact map from
    # a live wide chain every cycle (terrain_engine._per_strike_map) — it was simply discarded.
    # Reading it here costs ZERO additional vendor calls. The archive is demoted to the
    # prior-day ghost, which is the one thing it is genuinely correct for.
    try:
        _snap = terrain_cache_get(tk) or {}
        _ps = _snap.get("_per_strike") or {}
        # RC-79: the terrain loop hands over FINISHED rows ({all,near,far} of
        # [strike, net_gex_1pct$, volume]) and they are served as-is. This previously rebuilt
        # synthetic contract dicts out of them and pushed those back through
        # compute_exposures_by_strike(require_oi=True) — the synthetics had no open interest, so
        # every row was rejected and the panel rendered EMPTY on a live, 7-second-old snapshot.
        # Data that is already computed is never recomputed from a lossy reconstruction of its
        # own inputs.
        if isinstance(_ps, dict) and _ps.get("all"):
            today = {k: (_ps.get(k) or []) for k in ("all", "near", "far")}
            spot_used = _snap.get("spot")
            _cts_utc = _snap.get("computed_ts_utc")
            today_age_sec = round(time.time() - float(_cts_utc), 1) if _cts_utc else None
            today_src = "terrain_live_cache"
    except Exception as e:
        log.debug("terrain strikes live read failed %s: %s", tk, e)
    # RC-162 — THE BANK'S FIRST READER. RC-159 built the accrual writer and RC-161 made the
    # producer universal, but nothing ever read it: with a cold, thin or stale live cache the
    # Chart painted NOTHING while this session's own gamma and volume sat in the DB. Banking is
    # not rendering, and a bank with no reader satisfies no operator intent.
    #
    # This is a DECLARED SECOND SOURCE, not a silent one, and it is bounded three ways so it
    # cannot become the RC-68 failure again (a 09:47 archive served at 11:31 under a live label):
    #   1. It serves only when the live snapshot is ABSENT or older than TERRAIN_STALE_AFTER_SEC.
    #   2. It serves only rows banked TODAY, and only if they are NEWER than what live has.
    #   3. It stamps its own source and age, so no consumer can mistake it for the live cache.
    # The prior-day morning_full archive is untouched and still serves ONLY the ghost — a bank
    # row is this session's own wide book, which is exactly what the archive is not.
    try:
        _live_ts = float(_snap.get("computed_ts_utc") or 0.0) if isinstance(_snap, dict) else 0.0  # silent-zero-ok: epoch-0 ancient sentinel — an undated snapshot must lose every freshness comparison  # caps-ok: same epoch-0-ancient-sentinel reasoning as the silent-zero-ok marker — forces "stale", never a fabricated fresh timestamp
        _live_stale = (today is None) or (
            _live_ts <= 0.0) or ((time.time() - _live_ts) > TERRAIN_STALE_AFTER_SEC)
        if _live_stale:
            _bank = latest_accrual_rows(_server.get_db().db_path, tk)
            if _bank and _bank.get("rows") and _bank["ts_utc"] > _live_ts:
                # `near`/`far` stay EMPTY on purpose: the bank holds the `all` scope only, and
                # inventing a DTE split it never measured would be a fabricated level. The scope
                # chips render empty and say so rather than showing `all` under another name.
                today = {"all": _bank["rows"], "near": [], "far": []}
                spot_used = _bank.get("spot") if _bank.get("spot") is not None else spot_used
                today_age_sec = round(time.time() - _bank["ts_utc"], 1)
                today_src = f"accrual_bank:{_bank['et_minute']:04d}et"
    except Exception as e:
        log.debug("terrain strikes accrual fallback failed %s: %s", tk, e)
    try:
        db = _server.get_db()
        con = _sq.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=10.0)
        try:
            rows = con.execute(
                "SELECT et_date, spot, chain_json FROM option_chain_morning_full "
                "WHERE ticker=? ORDER BY et_date DESC LIMIT 2", (tk,)).fetchall()
        finally:
            con.close()
        if rows:
            # ONE FAUCET FOR TODAY. The archive is NOT a fallback for today's per-strike data —
            # a fallback IS a second faucet, and it is exactly how a 09:47 capture ended up
            # rendering at 11:31 under the label "TODAY'S OPTION VOLUME". If the live terrain
            # snapshot is absent (cold start), `today` stays empty and today_source stays None so
            # the panel can say so: absence reads as absence, never as a stale substitute.
            # The archive serves ONLY the prior-day ghost, which is what it is genuinely correct
            # for — yesterday's close does not change.
            _prior_row = rows[1] if len(rows) > 1 else (rows[0] if today_src else None)
            if _prior_row is not None:
                d1, s1, c1 = _prior_row
                prior = _per_strike(decode_json_blob(c1), float(s1))
                prior_src = f"wide_capture:{d1}"
    except Exception as e:
        log.debug("terrain strikes wide read failed %s: %s", tk, e)
    # The narrow-snapshot fallback is REMOVED (RC-68). It was the third faucet for one field:
    # the same panel could be fed by the live cache, the morning archive, or a stored narrow
    # chain — three different widths and three different clocks — with nothing on screen saying
    # which. If the live snapshot is absent the panel renders empty and says so.
    live_spot, live_src, _ts = resolve_spot(tk)
    _payload_spot = live_spot if live_spot is not None else spot_used

    # STRIP kill (one-faucet-closeout-v1): per-side GEX/OV sums are computed HERE, against
    # the exact spot this payload serves — the chart strip used to re-derive them in the
    # browser from the same rows (a second aggregation site that breaks silently when the
    # payload changes, and can straddle a different spot than the server's). One aggregator.
    def _side_sums(rows, s):
        from numeric_contract import float_finite_or_none, float_nonnegative_or_none
        if not rows or s is None:
            return None
        gb = ga = vb = va = 0.0
        for r in rows:
            # RC-276: the third copy. A row with no gamma used to add 0.0 to a side sum, which
            # is not neutral -- it drags the below/above comparison toward whichever side holds
            # the unmeasured strikes. Absence is dropped, not counted as flat.
            k = float_finite_or_none(r[0])
            g = float_finite_or_none(r[1])
            v = float_nonnegative_or_none(r[2])
            if k is None or g is None or v is None:
                continue
            if k < s:
                gb += g; vb += v
            elif k > s:
                ga += g; va += v
        return {"gex_below": round(gb, 1), "gex_above": round(ga, 1),
                "vol_below": int(vb), "vol_above": int(va),
                "spot_basis": float(s)}

    return JSONResponse({
        "ticker": tk, "spot": _payload_spot,
        "spot_source": live_src,
        "today": today or {"all": [], "near": [], "far": []},
        "today_side_sums": _side_sums((today or {}).get("all"), _payload_spot),
        "today_source": today_src,
        # RC-68: every consumer must be able to render an AGE on the panel's face. A number with
        # no age is how a 2.1-hour-old volume histogram sat under the label "TODAY'S OPTION VOLUME".
        "today_age_sec": today_age_sec,
        # RC-91: PROVENANCE IS NOT FRESHNESS. single_faucet_provenance passes here — one declared
        # source, no fallback — while the panel served levels 90 MINUTES old under a
        # `terrain_live_cache` label, because the terrain loop stops at the background-logging
        # window (16:30 ET) and nothing said so. Naming the right source proves only that the
        # right tap was opened, never that anything is still coming out of it.
        **terrain_staleness(_snap.get("computed_ts_utc") if isinstance(_snap, dict) else None, tk),
        "prior": prior or {"all": [], "near": [], "far": []},
        "prior_source": prior_src,
    })


@router.get("/api/terrain/scorecard")
def get_terrain_scorecard():
    """Coach copy's measured numbers, LIVE from the latest daily scorecard.

    Operator 2026-07-23: "will the coach be updated as we self-test?" — the
    tooltip hold-rates were frozen into the page the night they were measured.
    Now the UI reads them from reports/terrain_backtest_latest.json, so every
    daily scorecard run updates what the coach is allowed to claim.

    FAIL-CLOSED ON STALE AS WELL AS ABSENT (RC-78). This previously refused a
    missing or malformed report and served an out-of-date one, while claiming in
    this very docstring that it "never" served a stale rate — and it was found
    serving hold-rates 111.6 hours (4.6 days) old under the coach's "Measured on
    our own history". Age is a precondition to serve, not a footnote to display:
    a date printed beside a number does not stop the number being read. Past the
    budget the figures are WITHHELD and the reason is published, so the coach
    says "measuring" instead of quoting a four-day-old measurement.

    The budget counts TRADING days, so Friday's scorecard is still current on
    Monday and stale on Tuesday. A wall-clock budget would condemn every
    scorecard each weekend and teach the operator to ignore the warning."""
    from runtime_layout import reports_dir as _artifact_reports_dir

    p = _artifact_reports_dir() / "terrain_backtest_latest.json"    # RC-523: artifacts root
    try:
        rep = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return JSONResponse({})
    gen = rep.get("generated_utc")
    age = scorecard_trading_day_age(gen)
    if age is None or age > SCORECARD_MAX_TRADING_DAY_AGE:
        return JSONResponse({
            "generated_utc": gen,
            "stale": True,
            "age_trading_days": age,
            "max_trading_days": SCORECARD_MAX_TRADING_DAY_AGE,
            "stale_reason": (
                "scorecard has not been regenerated" if age is None
                else f"scorecard is {age} trading day(s) old"
            ),
        })
    return JSONResponse({
        "generated_utc": gen,
        "stale": False,
        "age_trading_days": age,
        "wall_hold_trusted": rep.get("wall_hold_trusted"),
        "weighting_scorecard": rep.get("weighting_scorecard"),
        "pdca": rep.get("pdca"),
    })


@router.get("/api/terrain")
def get_terrain(ticker: str = Query(default=DEFAULT_TICKER)):
    """Terrain payload — levels only, NO model stack.

    Deliberately separate from /api/state: that path runs the full pipeline (chain +
    greeks + xgb/lstm/transformer x 4 horizons + fusion + decision bundle), which is why
    background collection had to be throttled to keep it responsive. Terrain is ~5 ms of
    math on the same chain, so it never needs to compete for that budget.
    """
    from terrain_refresh import _terrain_refresh_one
    from terrain_engine import compute_terrain
    from terrain_freshness import terrain_staleness
    from terrain_state import _terrain_refresh_last_error
    from terrain_loop import terrain_cache_get
    from terrain_reprice import _reprice_cached_terrain
    from server import resolve_spot

    tk = ticker_storage_key(ticker or DEFAULT_TICKER)   # RC-126: SPX -> $SPX etc., ONE authority
    cached = terrain_cache_get(tk)
    if cached is None:
        # RC-80 — ONE PRODUCER OF LEVELS. This branch used to compute its own terrain from
        # _latest_chain_and_spot(), the most recent NARROW stored snapshot chain, while the
        # terrain loop computed from a WIDE chain sized by the resolve_chain_strike_count
        # faucet. Wall and flip selection depends on how much of the wing is present, so the
        # two disagreed: MEASURED 2026-07-27, /api/terrain?ticker=SPY alternated between
        # call=750/put=740/flip=746.59 and call=739/put=736/flip=739.80 within ten seconds
        # while spot moved four cents. The operator was reading two different sets of trade
        # levels from one endpoint. A second producer is a second faucet even when both write
        # the same cache key — the provenance audit only ever saw the read side.
        #
        # So on a miss the endpoint drives THE producer instead of imitating it, and if that
        # cannot deliver, the terrain reads UNAVAILABLE. Absence reads as absence; it never
        # reads as a narrower chain's answer.
        _terrain_refresh_one(tk, priority=True)
        cached = terrain_cache_get(tk)
    if cached is not None:
        # Cached LEVELS, live SPOT (RC-28). Never serve a frozen price beside a live header.
        return _reprice_cached_terrain(cached, tk)
    spot, spot_source, spot_ts = resolve_spot(tk)
    _why = _terrain_refresh_last_error.get(tk)
    return compute_terrain(tk, None, spot).to_dict() | {
        "spot_source": spot_source, "spot_as_of_ts_utc": spot_ts,
        # RC-126: not_ready carries its REASON when the producer has one — an eternal
        # unexplained shrug is how $SPX stayed dark for a session.
        "error": ("terrain_not_ready: no wide-chain snapshot yet for this ticker"
                  + (f" (last refresh error: {_why})" if _why else "")),
        # RC-151: and it carries the STRUCTURED state too. The cached branch above spreads
        # terrain_staleness while this one shipped only a prose `error` string, so
        # levels_failing / levels_quarantined were absent on /api/terrain for precisely the
        # tickers that were failing — MEASURED 2026-07-30 12:08 ET: RTY returned [] structured
        # fields while SPY returned all five. A flag a consumer must parse English to discover
        # is not a flag, and "absent" is indistinguishable from "healthy" to every reader.
        **terrain_staleness(None, tk),
    }


# Scorecard age gate (moved from server.py, RC-REHAB-1 forty-seventh slice):
# /api/terrain/scorecard is its only consumer.
#: Trading days a daily scorecard may be old and still be quoted as a measurement. 1 = yesterday's
#: run is current, the day before that is not. DERIVED from the artifact's own cadence: the job is
#: daily, so anything older than one trading day means a run was MISSED, and a missed run is
#: exactly the condition under which the numbers must stop speaking.
SCORECARD_MAX_TRADING_DAY_AGE: int = 1


def scorecard_trading_day_age(generated_utc: object) -> int | None:
    """TRADING days between `generated_utc` (YYYY-MM-DD...) and today ET. None = unusable.

    Counts sessions, not hours, so a Friday scorecard reads as 1 day old on Monday rather than 3
    — the distinction between "the job did not run" and "the market was shut"."""
    # RC-98: CONVERT to ET, never slice the UTC string. `generated_utc[:10]` is a UTC calendar
    # date being compared against an ET calendar date, and after 20:00 ET the UTC date is already
    # TOMORROW — so a scorecard that had just run successfully scored `gen > today`, returned
    # None, and the API reported the FRESH artifact as unusable. MEASURED 2026-07-27 21:21 ET:
    # generated_utc 2026-07-28T00:30:00+00:00 (= 20:30 ET today) returned None instead of 0.
    # The session calendar is ET, so the timestamp must be moved onto that clock before any date
    # arithmetic — comparing two different clocks' dates is the defect, not the comparison.
    raw = str(generated_utc or "").strip()
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if len(raw) == 10:
            # A DATE-ONLY string carries no time and no zone — it is already a calendar date, so
            # converting it is the bug, not the fix. Treating "2026-07-24" as UTC midnight and
            # shifting to ET lands on 07-23 and ages the scorecard by an extra day. Caught by
            # tests/test_scorecard_stale_fails_closed_v1.py the moment the ET conversion landed.
            gen = ts.date()
        else:
            if ts.tzinfo is None:            # naive TIMESTAMPS are UTC by this repo's storage law
                ts = ts.replace(tzinfo=timezone.utc)
            gen = ts.astimezone(now_et().tzinfo).date()
    except (TypeError, ValueError):
        return None                          # unparseable age is NOT a fresh age
    today = now_et().date()
    if gen > today:
        return None                          # a future stamp is a broken clock, never "fresh"
    age, day = 0, gen
    while day < today:
        day += timedelta(days=1)
        if is_trading_day_et(day.isoformat()):
            age += 1
    return age
