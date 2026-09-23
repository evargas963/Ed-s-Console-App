"""Background analytics recompute scheduling and failure handling (server.py
decomposition, thirtieth slice, RC-REHAB-1, 2026-09-23).

_schedule_analytics_recompute (runs _fetch_state in a thread pool, dedupes
in-flight jobs, broadcasts on success) moves here along with the private cluster
of helpers that exist ONLY to serve it -- each confirmed to have no OTHER caller
anywhere in server.py before moving, verified individually, not assumed:
_invalidate_analytics_cache_after_bg_failures, _reset_analytics_bg_fail_count,
_record_analytics_bg_failure, _fetch_state_sse_bounded,
_stamp_analytics_freshness_on_completed_fetch, _analytics_bg_error_detail, and
_write_analytics_bg_error_shell. Not a _fetch_state phase (no server_state_
prefix): called from 7 sites scattered across server.py's own body (all stay
there, calling the re-exported name).

MONKEYPATCH/RUNTIME-STATE NOTE: every name this module touches that has a
confirmed OTHER reader/caller elsewhere in server.py stays there, reached via
the established lazy `import server` pattern -- _analytics_bg_shutdown,
_analytics_bg_lock, _analytics_inflight, _analytics_bg_fail_counts,
_analytics_bg_last_error, _analytics_cache_observability, _state_cache, _lmp,
_fetch_state, _main_event_loop, _schedule_sse_broadcast, _submit_analytics_task,
_is_operator_priority_update_source, _maybe_broadcast_sse_cache_fanout (a THIRD
call site exists elsewhere in server.py), _latest_cached_ms_and_key_for_ticker,
_minimal_analytics_pending_dict, SSE_RECOMPUTE_FETCH_TIMEOUT_SEC, CACHE_TTL,
ANALYTICS_STALE_GRACE_CYCLES, ANALYTICS_BG_MAX_CONSECUTIVE_FAILURES.
_get_sse_fetch_timeout_executor deliberately STAYS in server.py despite having
only one call site here (inside _fetch_state_sse_bounded): its own body uses
`global _sse_fetch_timeout_executor` for a lazy-singleton executor -- moving it
would silently create a SECOND, disconnected global in this module instead of
mutating server.py's real one (the exact trap that also kept _app_lifespan out
of this decomposition project). Reached via `_srv.` instead, same as every
other executor-getter function in this codebase.

HTTPException (fastapi) and SchwabAuthError (schwab_client) are re-imported
here directly -- neither is server.py-specific logic.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

from fastapi import HTTPException
from schwab_client import SchwabAuthError


def _invalidate_analytics_cache_after_bg_failures(
    inflight_key: tuple,
    ticker: str,
    *,
    reason: str,
    failure_count: Optional[int] = None,
    detail: str = "",
) -> None:
    """Mark cached Tier C payload stale after repeated background recompute failures.

    Institutional rule: never drop the last good analytical bundle — serve stale with
    an explicit operator-visible error instead of an empty pending shell.
    """
    import server as _srv

    t = ticker.upper().strip()
    exp = inflight_key[1] if len(inflight_key) > 1 else "__auto__"
    n_fail = (
        failure_count
        if failure_count is not None
        else _srv._analytics_bg_fail_counts.get(inflight_key, 0)
    )
    err_msg = (detail or _srv._analytics_bg_last_error.get(inflight_key) or reason or "unknown").strip()
    marked: list[tuple] = []
    for key in list(_srv._state_cache.keys()):
        if not isinstance(key, tuple) or len(key) < 2 or key[0] != t:
            continue
        if exp != "__auto__" and key[1] != exp:
            continue
        ent = _srv._state_cache.get(key)
        if not ent or not isinstance(ent.get("ms_dict"), dict):
            continue
        md = dict(ent["ms_dict"])
        md["state_error"] = "analytics_refresh_failed"
        md["state_error_detail"] = (
            f"Tier C refresh failed after {n_fail} attempt(s): {err_msg[:240]}"
        )
        md["analytics_last_error"] = err_msg[:500]
        md["analytics_stale"] = True
        md["analytics_refresh_in_progress"] = False
        ent["ms_dict"] = md
        marked.append(key)
    if marked:
        _srv._analytics_cache_observability["bg_failure_stale_marks"] += len(marked)
        log.warning(
            "analytics cache marked stale after bg failures ticker=%s exp=%s n=%s reason=%s keys=%s",
            t,
            exp,
            n_fail,
            reason,
            marked,
        )


def _reset_analytics_bg_fail_count(inflight_key: tuple) -> None:
    import server as _srv

    _srv._analytics_bg_fail_counts.pop(inflight_key, None)
    _srv._analytics_bg_last_error.pop(inflight_key, None)


def _record_analytics_bg_failure(
    inflight_key: tuple,
    ticker: str,
    *,
    reason: str,
    detail: str = "",
    token_invalid: bool = False,
) -> None:
    import server as _srv

    if detail:
        _srv._analytics_bg_last_error[inflight_key] = detail[:500]
    n = _srv._analytics_bg_fail_counts.get(inflight_key, 0) + 1
    _srv._analytics_bg_fail_counts[inflight_key] = n
    exp = inflight_key[1] if len(inflight_key) > 1 and inflight_key[1] != "__auto__" else None
    if token_invalid or n == 1:
        _write_analytics_bg_error_shell(
            ticker,
            exp,
            detail or reason,
            token_invalid=token_invalid,
        )
    if n >= _srv.ANALYTICS_BG_MAX_CONSECUTIVE_FAILURES:
        _invalidate_analytics_cache_after_bg_failures(
            inflight_key,
            ticker,
            reason=reason,
            failure_count=n,
            detail=detail,
        )
        _srv._analytics_bg_fail_counts.pop(inflight_key, None)


def _fetch_state_sse_bounded(
    ticker: str,
    expiry: Optional[str],
    *,
    update_source: str,
    timeout_sec: float,
) -> Optional[dict]:
    """Run _fetch_state on an isolated worker with a hard wall-clock timeout."""
    import server as _srv

    fut = _srv._get_sse_fetch_timeout_executor().submit(
        _srv._fetch_state, ticker, expiry, update_source=update_source
    )
    try:
        return fut.result(timeout=max(0.5, float(timeout_sec)))
    except TimeoutError:
        return None


def _schedule_analytics_recompute(
    inflight_key: tuple,
    ticker: str,
    expiry: Optional[str],
    update_source: str,
) -> None:
    """
    Run _fetch_state in a thread pool; broadcast full snapshot on success.
    Dedupes identical (ticker, expiry|__auto__) jobs.

    SSE loop path (update_source=sse_loop): cache fanout on each cadence / while in-flight
    so Tier C SSE is not starved by slow _fetch_state or DB lock contention (T5).
    """
    import server as _srv

    if _srv._analytics_bg_shutdown:
        return
    sse_loop = update_source == "sse_loop"
    # LIVE_OPERATOR_MODE_RESET_V1 Step 3 — deadlock fix: decide the in-flight branch
    # under _analytics_bg_lock, then RELEASE before fanning out. The fanout chain
    # re-enters this same non-reentrant lock via _attach_analytics_freshness_contract,
    # which self-deadlocked the event loop (py-spy proof:
    # reports/ui_transport/step1_2_proof_wedge_pyspy_dump_20260702.txt).
    with _srv._analytics_bg_lock:
        if _srv._analytics_bg_shutdown:
            return
        in_flight = inflight_key in _srv._analytics_inflight
        if not in_flight:
            _srv._analytics_inflight.add(inflight_key)
    if in_flight:
        if sse_loop:
            _srv._maybe_broadcast_sse_cache_fanout(
                ticker,
                expiry,
                inflight_key=inflight_key,
                fanout_reason="fetch_in_flight",
            )
        log.debug("analytics refresh already in flight %s", inflight_key)
        return

    def _work() -> None:
        try:
            executor_queue_wait_sec = round(max(0.0, time.monotonic() - _submitted_monotonic), 3)
            fetch_started_monotonic = time.monotonic()
            if sse_loop:
                timeout_sec = max(0.5, float(_srv.SSE_RECOMPUTE_FETCH_TIMEOUT_SEC))
                result = _fetch_state_sse_bounded(
                    ticker,
                    expiry,
                    update_source=update_source,
                    timeout_sec=timeout_sec,
                )
                if result is None:
                    log.info(
                        "sse_loop fetch timeout ticker=%s expiry=%s timeout_s=%.1f",
                        ticker,
                        expiry,
                        timeout_sec,
                    )
                    _srv._maybe_broadcast_sse_cache_fanout(
                        ticker,
                        expiry,
                        inflight_key=inflight_key,
                        fanout_reason="fetch_timeout",
                    )
                    return
            else:
                result = _srv._fetch_state(ticker, expiry, update_source=update_source)
            if result:
                recompute_duration_sec = round(time.monotonic() - fetch_started_monotonic, 3)
                _srv._analytics_recompute_last_duration_sec[ticker.upper().strip()] = recompute_duration_sec
                result["analytics_recompute_duration_sec"] = recompute_duration_sec
                result["analytics_executor_queue_wait_sec"] = executor_queue_wait_sec
                stale_budget_sec = float(_srv.CACHE_TTL) * _srv.ANALYTICS_STALE_GRACE_CYCLES
                if recompute_duration_sec >= stale_budget_sec:
                    log.info(
                        "analytics recompute exceeded staleness budget ticker=%s "
                        "duration=%.3fs queue_wait=%.3fs budget=%.1fs source=%s",
                        ticker,
                        recompute_duration_sec,
                        executor_queue_wait_sec,
                        stale_budget_sec,
                        update_source,
                    )
                _reset_analytics_bg_fail_count(inflight_key)
                _stamp_analytics_freshness_on_completed_fetch(result, ticker, inflight_key)
                try:
                    from planes.l1_events import notify_l2_snapshot_ready

                    notify_l2_snapshot_ready(ticker, result.get("selected_exp"))
                except Exception as e:
                    log.debug("notify_l2_snapshot_ready failed ticker=%s: %s", ticker, e, exc_info=True)
            if result and _srv._main_event_loop is not None and not _srv._main_event_loop.is_closed():
                _srv._schedule_sse_broadcast(result)
        except HTTPException as ex:
            log.warning("analytics bg HTTPException for %s", inflight_key)
            detail, token_invalid = _analytics_bg_error_detail(ex)
            _record_analytics_bg_failure(
                inflight_key,
                ticker,
                reason="http_exception",
                detail=detail,
                token_invalid=token_invalid,
            )
        except SchwabAuthError as ex:
            log.warning("analytics bg SchwabAuthError for %s: %s", inflight_key, ex)
            _record_analytics_bg_failure(
                inflight_key,
                ticker,
                reason="schwab_auth",
                detail=str(ex),
                token_invalid=True,
            )
        except Exception as ex:
            if isinstance(ex, RuntimeError) and "shutdown" in str(ex).lower():
                log.debug("analytics bg skipped during shutdown %s", inflight_key)
            else:
                log.error("analytics bg failed %s: %s", inflight_key, ex, exc_info=True)
                detail, token_invalid = _analytics_bg_error_detail(ex)
                _record_analytics_bg_failure(
                    inflight_key,
                    ticker,
                    reason="generic_exception",
                    detail=detail,
                    token_invalid=token_invalid,
                )
        finally:
            with _srv._analytics_bg_lock:
                _srv._analytics_inflight.discard(inflight_key)

    _submitted_monotonic = time.monotonic()
    try:
        # UI_05_OPERATOR_PRIORITY_ADMISSION_V1: operator-facing sources get the
        # bounded priority lane; background sources keep the analytics pool.
        _srv._submit_analytics_task(
            _work, priority=_srv._is_operator_priority_update_source(update_source)
        )
    except RuntimeError:
        with _srv._analytics_bg_lock:
            _srv._analytics_inflight.discard(inflight_key)


def _stamp_analytics_freshness_on_completed_fetch(
    md: dict,
    ticker: str,
    inflight_key: tuple,
) -> None:
    """Align SSE/pushed Tier C payloads with the analytics freshness contract."""
    import server as _srv

    t = ticker.upper().strip()
    exp = md.get("selected_exp")
    ck = (t, exp)
    ent = _srv._state_cache.get(ck)
    analytics_freshness_eval_wall_ts = time.time()
    sse_live = _srv._sse_subscribers.get(ck, 0) > 0
    _srv._attach_analytics_freshness_contract(
        md,
        data_cache_key=ck,
        entry=ent,
        now=analytics_freshness_eval_wall_ts,
        sse_live=sse_live,
        inflight_key=inflight_key,
    )
    # Completed fetch — this payload is the fresh computation (not a queued stale read).
    md["analytics_stale"] = False
    md["analytics_refresh_in_progress"] = False
    if ent:
        gen_ts = _srv._analytics_generated_ts(ent)
        if gen_ts is not None:      # RC-282: None is undatable, not "timestamp zero"
            md["analytics_age_sec"] = max(
                0.0, round(analytics_freshness_eval_wall_ts - gen_ts, 3)
            )


def _analytics_bg_error_detail(exc: BaseException) -> tuple[str, bool]:
    """Normalize bg failure text + whether this is a Schwab auth failure."""
    if isinstance(exc, SchwabAuthError):
        return (str(exc)[:500], True)
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            msg = str(
                detail.get("remediation")
                or detail.get("message")
                or detail.get("error")
                or detail
            )
            token_invalid = detail.get("error") == "token_invalid"
            return (msg[:500], token_invalid)
        msg = str(detail or exc)
        token_invalid = "token" in msg.lower() and (
            "invalid" in msg.lower() or "revoked" in msg.lower() or "expired" in msg.lower()
        )
        return (msg[:500], token_invalid)
    msg = str(exc)
    from schwab_client import _is_token_error

    return (msg[:500], _is_token_error(exc))


def _write_analytics_bg_error_shell(
    ticker: str,
    expiry: Optional[str],
    detail: str,
    *,
    token_invalid: bool = False,
) -> None:
    """Cold-cache Tier C: persist operator-visible error instead of endless empty pending shell."""
    import server as _srv

    t = ticker.upper().strip()
    _, existing_key = _srv._latest_cached_ms_and_key_for_ticker(t)
    if existing_key is not None:
        return
    exp = expiry if expiry is not None else "__auth_error__"
    ck = (t, exp)
    now = time.time()
    rem = "Schwab auth failed — run: python reauth_schwab.py --manual"
    err_text = rem if token_invalid else (detail or "Tier C refresh failed")
    md = _srv._minimal_analytics_pending_dict(t, expiry)
    md["analytics_pending_shell"] = False
    md["state_error"] = "token_invalid" if token_invalid else "analytics_refresh_failed"
    md["state_error_detail"] = err_text[:500]
    md["analytics_last_error"] = (detail or err_text)[:500]
    md["analytics_stale"] = True
    md["analytics_refresh_in_progress"] = False
    if token_invalid:
        md["error"] = "token_invalid"
        md["remediation"] = rem
    md["call_signal"] = "wait"
    md["fusion_available"] = False
    md["mhap_rows"] = []
    _srv._lmp.merge_into_state(md, t)
    _srv._state_cache[ck] = {
        "ts": now,
        "generated_at": now,
        "analytics_version": 0,
        "ms_dict": md,
        "pcr_val": None,
        "spot_f": md.get("spot"),
        "vix": None,
        "price_levels": None,
        "pl_date": "",
        "pl_generation": None,
        "pl_mono": None,
    }
