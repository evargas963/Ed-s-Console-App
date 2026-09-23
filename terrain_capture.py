"""Universal chain capture driven by the terrain loop: the once-daily wide MORNING capture
(`_universal_capture_wanted` / `_persist_universal_capture`) and the systematic near-term
COMPLETE-chain capture (`_persist_universal_complete_chain`), with their in-process
per-day memo and attempt-cap state. Extracted from server.py (RC-REHAB-1, 2026-09-23,
forty-first slice) as one unit; every dict/set here is mutated in place, never rebound.

Server-owned runtime (get_db, the rate-limited chain gate, flatten_chain_contracts,
resolve_spot) is read through a lazy `import server as _srv` at call time, so tests that
monkeypatch those names on `server` keep reaching this code.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date

from calibration.complete_chain_capture import (
    COMPLETENESS_BASIS_STRIKE_RANGE_ALL,
    eligible_near_term_expiries,
    has_complete_chain_capture_today,
    next_capture_batch,
    persist_complete_chain_capture,
)
from calibration.option_chain_morning_full import (
    MAX_DTE_DAYS as COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS,
    SOURCE_WIDE as GEX_SOURCE_WIDE,
    et_date_and_mins as gex_et_date_and_mins,
    has_morning_full_capture,
    maybe_persist_morning_full_chain,
    universal_capture_window,
)
from time_et import is_trading_day_et

log = logging.getLogger(__name__)


#: (ticker, et_date) pairs whose morning wide capture is already persisted — in-process
#: memo so the loop does not hit the DB with has_morning_full_capture every 60s.
_morning_capture_done: set[tuple[str, str]] = set()
_morning_capture_lock = threading.Lock()


def _universal_capture_wanted(tk: str) -> tuple[bool, tuple[str, str]]:
    """Does `tk` still need today's wide morning capture?

    UNIVERSAL MORNING CAPTURE (operator 2026-07-20). The sentinel-only capture rides the
    money-path logger, which RC-1's operator-mode gate skips for non-sentinels whenever a
    viewer is connected — measured result: 3 of ~51 tickers captured today. The terrain
    loop touches EVERY ticker each cycle, so it closes the gap in the post-window span
    (10:00-11:30 ET, deliberately AFTER the money-path window): one wide fetch serves
    both terrain and the archive. Idempotent per (ticker, ET day); DB checked once per
    day per ticker, then memoised in-process.
    """
    import server as _srv                      # runtime: get_db (monkeypatched by tests)

    cap_date, cap_mins = gex_et_date_and_mins()
    key = (tk, cap_date)
    if not universal_capture_window(cap_mins):
        return False, key
    with _morning_capture_lock:
        if key in _morning_capture_done:
            return False, key
        attempts = _morning_capture_attempts.get(key, 0)
        if attempts >= _MORNING_CAPTURE_MAX_ATTEMPTS:
            # Three wide fetches produced nothing persistable — stop paying for wide
            # width every cycle; the day is a miss for this ticker, said out loud once.
            _morning_capture_done.add(key)
            log.warning("morning wide capture GIVEN UP ticker=%s after %d attempts",
                        tk, attempts)
            return False, key
        _morning_capture_attempts[key] = attempts + 1
    if has_morning_full_capture(_srv.get_db().db_path, tk, cap_date):
        with _morning_capture_lock:
            _morning_capture_done.add(key)
        return False, key
    return True, key


#: Per-(ticker, et_date) persist attempts. Bugbot MEDIUM (confirmed): an empty flatten
#: skipped persist WITHOUT memoising, so the loop re-forced the wide width every ~60s for
#: the entire 90-minute span. Three strikes and the day is done for that ticker.
_morning_capture_attempts: dict[tuple[str, str], int] = {}
_MORNING_CAPTURE_MAX_ATTEMPTS = 3


def _persist_universal_capture(tk: str, key: tuple[str, str], width: int,
                               contracts: list, spot: float | None) -> None:
    """Persist the wide chain just fetched. Archive concern — terrain must still serve.

    Bugbot 2026-07-20 (HIGH — confirmed): the first version ignored the persist RETURN
    DICT and memoised + logged success on any non-exception — including the status
    dicts that mean "nothing was written". A silently-discarded capture then read as
    captured for the rest of the ET day. The dict is now the arbiter:
      ok / idempotent_skip            -> memoise (done for the day), log accordingly
      too_few_near_term_contracts    -> memoise WITH WARNING (a thin chain will not
                                         thicken intraday; retrying burns wide fetches)
      anything else                  -> warn, do NOT memoise, bounded by the attempt cap
    """
    import server as _srv                      # runtime: get_db (monkeypatched by tests)

    try:
        result = maybe_persist_morning_full_chain(
            _srv.get_db().db_path, ticker=tk, contracts=contracts,
            spot=float(spot) if spot is not None else None,
            ts_utc=time.time(), source=GEX_SOURCE_WIDE,
        )
    except Exception as e:
        log.warning("morning wide capture persist failed ticker=%s: %s", tk, e)
        return
    status = str(result.get("status", ""))  # caps-ok: fail-closed -- a capture result without status is not "ok", so nothing is persisted as a successful morning capture
    if status == "ok":
        with _morning_capture_lock:
            _morning_capture_done.add(key)
        log.info("morning wide capture persisted ticker=%s width=%d n=%s",
                 tk, width, result.get("n_contracts"))
    elif status == "idempotent_skip":
        with _morning_capture_lock:
            _morning_capture_done.add(key)
    elif result.get("reason") == "too_few_near_term_contracts":
        with _morning_capture_lock:
            _morning_capture_done.add(key)
        log.warning("morning wide capture SKIPPED for the day ticker=%s: only %s "
                    "near-term contracts", tk, result.get("n"))
    else:
        log.warning("morning wide capture not persisted ticker=%s status=%s reason=%s",
                    tk, status, result.get("reason"))


#: OPTIONS_ORDER_FLOW_V1 round 4 (material-defect-lifecycle review, 2026-08-31): the
#: PROVEN-complete strike_range=ALL fetch built for /api/chain (round 3) had NO
#: systematic producer -- persist_complete_chain_capture only ever ran from that
#: operator-triggered endpoint, so an expiry earned a proven-complete record ONLY if a
#: human happened to click it in /options. The systematic collector below reuses the
#: SAME once-daily universal-capture WINDOW (`universal_capture_window`) the
#: sentinel/whole-roster wide fetch already uses, and discovers this ticker's listed
#: expiries from the REGULAR per-cycle terrain chain fetch it is called with -- the
#: SAME unwindowed "full"-basis request _terrain_refresh_one already makes every cycle
#: (terrain_refresh._terrain_refresh_one's basis ladder), at ZERO extra vendor cost for
#: discovery. Only the per-expiry strike_range=ALL fetches below are new vendor calls,
#: through the same rate-limited/coalesced _gated_safe_get_chain gate every other
#: chain read uses.
#:
#: OPERATOR-CAUGHT DEFECT (2026-08-31, same day): the first version sliced
#: `eligible[:CAP]` BEFORE filtering out already-captured expiries. Once the first CAP
#: expiries were captured, every later cycle kept re-selecting that SAME first-CAP
#: slice (all already done, so the loop body no-opped on every one) -- expiry #(CAP+1)
#: and beyond were NEVER attempted, on ANY cycle, ANY day: a bounded per-cycle vendor
#: budget had silently become a PERMANENT completeness ceiling. Fixed by filtering to
#: `still_needed` (not yet proven complete today, not yet given up on today) FIRST,
#: THEN slicing the per-cycle budget from THAT -- so once today's first CAP are
#: captured, they drop out of `still_needed` and the NEXT cycle's slice naturally
#: advances to the next uncaptured expiries. This also required decoupling this
#: function from the sibling `_persist_universal_capture`'s once-per-day "done" gate
#: (it previously only ran once per ticker per day, piggybacked on that gate, so
#: "successive cycles" never actually happened in production regardless of the slice
#: bug) -- it is now called every terrain cycle inside the capture window and
#: self-gates on whether there is still real work, so it gets many chances per day.
#:
#: Bounded to _COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER new-work items per CALL (not
#: per day) so an unusually weekly-heavy name cannot unboundedly inflate one cycle's
#: vendor cost; a chronically-failing expiry gives up after
#: _COMPLETE_CAPTURE_EXPIRY_MAX_ATTEMPTS attempts THE SAME ET day (mirrors
#: _MORNING_CAPTURE_MAX_ATTEMPTS's existing give-up convention) so it cannot
#: permanently occupy a budget slot ahead of expiries never yet attempted; both a
#: truncation and a give-up are logged, never silent.
_COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER = 8
_COMPLETE_CAPTURE_EXPIRY_MAX_ATTEMPTS = 3
#: (ticker, expiry, et_date) -> attempts. In-memory, like _morning_capture_attempts --
#: a restart simply grants a fresh attempt budget, which is safe: the DURABLE state
#: that must survive restart is COMPLETION (has_complete_chain_capture_today, DB-
#: backed), not the give-up bookkeeping for a same-day chronic failure.
_complete_chain_capture_attempts: dict[tuple[str, str, str], int] = {}


def _persist_universal_complete_chain(tk: str, client, contracts: list,
                                      ts_utc: float | None = None) -> None:
    """Systematic near-term COMPLETE-chain capture, one expiry at a time, into
    complete_chain_captures -- the same table and completeness basis /api/chain's
    on-demand path already uses, extended to run universally without waiting on an
    operator's click. Self-gated: returns immediately (zero vendor calls) outside the
    capture window, on a non-trading day, or once every eligible near-term expiry is
    already proven complete (or given up on) for today.

    `ts_utc` (defaults to real now) is the ONE clock read this call uses -- derived
    into et_date/mins AND threaded through to every persisted row, so the idempotency
    check and the row it is checking against can never disagree about which ET day
    they mean (a prior draft read `time.time()` twice, separately, for exactly that
    purpose, and a same-day re-entry test caught it re-fetching every expiry).
    """
    import server as _srv          # runtime: get_db / chain gate / flatten / resolve_spot

    ts = float(ts_utc if ts_utc is not None else time.time())
    et_date, mins = gex_et_date_and_mins(ts)
    if not universal_capture_window(mins) or not is_trading_day_et(et_date):
        return
    all_exps = {
        str(c.get("expirationDate") or "")[:10]
        for c in contracts if isinstance(c, dict) and c.get("expirationDate")
    }
    eligible = eligible_near_term_expiries(
        all_exps, max_dte_days=COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS, now_et_date=et_date)
    db_path = _srv.get_db().db_path
    already_captured = {
        expiry for expiry in eligible
        if has_complete_chain_capture_today(db_path, tk, expiry, et_date)
    }
    given_up = {
        expiry for expiry in eligible
        if _complete_chain_capture_attempts.get((tk, expiry, et_date), 0)
        >= _COMPLETE_CAPTURE_EXPIRY_MAX_ATTEMPTS
    }
    still_needed_count = sum(1 for e in eligible if e not in already_captured and e not in given_up)
    if not still_needed_count:
        return
    batch = next_capture_batch(
        eligible, already_captured=already_captured, given_up=given_up,
        batch_size=_COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER)

    attempted = captured = failed = 0
    for expiry in batch:
        attempt_key = (tk, expiry, et_date)
        n_attempts = _complete_chain_capture_attempts.get(attempt_key, 0) + 1
        _complete_chain_capture_attempts[attempt_key] = n_attempts
        attempted += 1
        try:
            d = date.fromisoformat(expiry)
            c_resp, _gw, _fs = _srv._gated_safe_get_chain(
                client, tk, strike_range="ALL", from_date=d, to_date=d, priority=False)
            if c_resp is None or c_resp.status_code != 200:
                failed += 1
                continue
            c_json = c_resp.json()
            exp_contracts = _srv.flatten_chain_contracts(c_json)
            returned_exps = sorted({
                str(c.get("expirationDate") or "")[:10]
                for c in exp_contracts if isinstance(c, dict) and c.get("expirationDate")
            })
            if returned_exps != [expiry]:
                log.warning(
                    "complete-chain systematic capture: expiry scope mismatch "
                    "ticker=%s requested=%s returned=%s -- not persisting",
                    tk, expiry, returned_exps)
                failed += 1
                continue
            exp_spot, _ss, _sa = _srv.resolve_spot(tk, chain_json=c_json)
            result = persist_complete_chain_capture(
                db_path, ticker=tk, expiry=expiry, contracts=exp_contracts,
                spot=exp_spot, completeness_basis=COMPLETENESS_BASIS_STRIKE_RANGE_ALL,
                ts_utc=ts)
            if result.get("status") == "written":
                captured += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            log.warning("complete-chain systematic capture failed ticker=%s expiry=%s: %s",
                        tk, expiry, e)
        if n_attempts >= _COMPLETE_CAPTURE_EXPIRY_MAX_ATTEMPTS and not has_complete_chain_capture_today(
            db_path, tk, expiry, et_date
        ):
            log.warning(
                "complete-chain systematic capture: ticker=%s expiry=%s given up for "
                "today after %d attempts", tk, expiry, n_attempts)
    if still_needed_count > _COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER:
        log.warning(
            "complete-chain systematic capture: ticker=%s truncated to %d of %d "
            "still-needed near-term expiries this cycle -- the remainder are "
            "carried to the next cycle, never dropped", tk,
            _COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER, still_needed_count)
    if attempted:
        log.info(
            "complete-chain systematic capture ticker=%s et_date=%s attempted=%d "
            "captured=%d failed=%d still_needed=%d eligible=%d", tk, et_date, attempted,
            captured, failed, still_needed_count, len(eligible))
