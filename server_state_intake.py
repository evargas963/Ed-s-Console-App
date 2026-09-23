"""Intake phase of _fetch_state (server.py): the parallel Schwab chain + quote fetch and the
three early-exit responses, extracted (RC-REHAB-1, 2026-09-23). Thirty-fourth slice of the
_fetch_state decomposition -- see server_state_volatility.py's own docstring for why this
decomposition exists.

_fetch_chain_and_quote_for_state owns the executor-pool choice (inline when the analytics
pool is shutting down or for log-only pipelines; the priority leaf lane for operator-facing
recomputes; the recompute leaf lane otherwise -- never the analytics pool itself, which would
self-deadlock), the single-slot chain gate, the auth-error -> 401 translation and the
vendor-status -> 502 translation. It returns one _ChainQuoteForState.

The three early-exit builders produce the exact payloads _fetch_state used to build inline
(no valid expiry / empty expiry slice / missing canonical spot). The two that carried a
copy-pasted `spot_disp` try/except now share _spot_disp.

MONKEYPATCH/RUNTIME-STATE NOTE: every server.py-owned name (the leaf executors, the chain
gate, the quote memo, the date-bound helpers, _analytics_bg_shutdown -- a module global that
is REBOUND at shutdown, so it must be read at call time -- _lmp, _finalize_production_decision)
is reached through the lazy `import server` pattern, so existing mock.patch.object(server, ...)
tests keep working.
"""
from __future__ import annotations

import time
from typing import Any, NamedTuple, Optional

from fastapi import HTTPException

from live_decision_bundle import stamp_decision_bundle
from schwab_client import SchwabAuthError


class _ChainQuoteForState(NamedTuple):
    c_json: dict
    contracts: list
    q_json: Any
    chain_priority: bool
    chain_gate_wait_sec: float
    chain_fetch_pure_sec: Optional[float]
    t_after_chain_mono: float
    t_after_quote_mono: float
    t_after_quote_wall: float


def _fetch_chain_and_quote_for_state(
    ticker: str,
    expiry: Optional[str],
    client,
    *,
    log_only: bool,
    update_source: Optional[str],
    window_marks: list,
) -> _ChainQuoteForState:
    """Chain + quote in parallel (independent Schwab calls -- saves one RTT on cold Tier C).

    Schwab CSV authority checked: yes
    CSV row(s): NO_SCHWAB_EQUIVALENT — executor-pool scheduling only; the Schwab chain and
      quote reads themselves (safe_get_chain / _safe_get_quote_with_retry) are unchanged.
    Derived-field disposition: none required (no derived field touched).
    All consumers checked: yes — c_resp/q_resp consumed identically downstream.
    SCHWAB_CSV_CHECKED
    """
    import server as _srv

    chain_gate_wait_sec: float = 0.0
    chain_fetch_pure_sec: Optional[float] = None
    # UI_05_OPERATOR_PRIORITY_ADMISSION_V1: operator-facing recomputes acquire the (still
    # single-slot) chain gate ahead of queued background acquirers. log_only pipelines are
    # background by definition.
    chain_priority = (not log_only) and _srv._is_operator_priority_update_source(update_source)
    chain_kwargs = dict(
        strike_count=_srv.resolve_chain_strike_count(ticker),   # RC-59: one faucet
        to_date=_srv._chain_to_date_for(ticker, expiry),   # RC-494: bound index expiry count (keep an explicit far pick)
        from_date=_srv._chain_from_date_for(ticker, expiry),   # Cursor-audit F2: bound near edge for a far pick
        priority=chain_priority,
    )
    try:
        # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_1: log_only joins the shutdown inline path
        # — background pipelines stay out of the shared route pool; operator-facing
        # recomputes keep bounded parallelism. These futures must NOT run on the analytics
        # pool: _fetch_state itself occupies an analytics worker, and nested submit+.result()
        # on the same 4-worker pool self-deadlocks (py-spy proof 2026-07-04).
        if _srv._analytics_bg_shutdown or _srv._log_only_inline_leaf_fetches(log_only):
            c_resp, chain_gate_wait_sec, chain_fetch_pure_sec = _srv._gated_safe_get_chain(
                client, ticker, **chain_kwargs)
            q_resp = _srv._memoized_quote_response(ticker, client=client)   # RC-112/W3-C8: one vendor faucet
        else:
            # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2: leaf futures run on the dedicated
            # recompute-leaf pool; PRIORITY recomputes use their own bounded leaf lane so
            # cold-guest legs never queue behind background idle-refresh bursts (measured
            # 13.7-21s FIFO wait at pure-fetch 0.5-0.8s).
            pool = (
                _srv._get_priority_leaf_executor()
                if chain_priority
                else _srv._get_recompute_leaf_executor()
            )
            chain_fut = pool.submit(_srv._gated_safe_get_chain, client, ticker, **chain_kwargs)
            # RC-112 recurrence 2: the pool leaf passes the memoized quote faucet by NAME.
            quote_fut = pool.submit(_srv._memoized_quote_response, ticker, client=client)
            c_resp, chain_gate_wait_sec, chain_fetch_pure_sec = chain_fut.result()
            q_resp = quote_fut.result()
    except SchwabAuthError as e:
        raise HTTPException(
            status_code=401,
            detail={"error": "token_invalid", "remediation": e.remediation, "message": str(e)},
        ) from e
    window_marks.append(("chain_window_leaf_wall_ms", time.monotonic()))
    if c_resp is None or c_resp.status_code != 200:
        # Cursor-audit F4: carry the real vendor status so the background logger's quarantine
        # can tell a PERMANENT symbol refusal (4xx) from a transient venue error. Detail still
        # starts with "Chain fetch failed" for existing consumers.
        raise HTTPException(status_code=502,
                            detail=f"Chain fetch failed [vendor_status={getattr(c_resp, 'status_code', None)}]")
    c_json = c_resp.json()
    contracts = _srv.flatten_chain_contracts(c_json)
    t_after_chain_mono = time.monotonic()
    window_marks.append(("chain_window_contracts_parse_ms", t_after_chain_mono))

    if q_resp is None or q_resp.status_code != 200:
        raise HTTPException(status_code=502,   # Cursor-audit F4: carry vendor status (see chain raise)
                            detail=f"Quote fetch failed [vendor_status={getattr(q_resp, 'status_code', None)}]")
    q_json = q_resp.json()
    return _ChainQuoteForState(
        c_json=c_json,
        contracts=contracts,
        q_json=q_json,
        chain_priority=chain_priority,
        chain_gate_wait_sec=chain_gate_wait_sec,
        chain_fetch_pure_sec=chain_fetch_pure_sec,
        t_after_chain_mono=t_after_chain_mono,
        t_after_quote_mono=time.monotonic(),
        t_after_quote_wall=time.time(),
    )


def _spot_disp(spot) -> str:
    try:
        return f"{float(spot):.2f}" if spot else "—"
    except (TypeError, ValueError):
        return "—"


def _wait_shell(ticker: str, *, selected_exp, expiries: list, today_str: str, spot,
                session_label, state_error: str, detail: str) -> dict:
    """The shared WAIT-shaped body of the no-expiry / empty-slice early exits."""
    return {
        "ticker": ticker.upper(),
        "selected_exp": selected_exp,
        "expiries": [e for e in expiries if e >= today_str],
        "state_error": state_error,
        "state_error_detail": detail,
        "spot": float(spot) if spot else None,
        "spot_disp": _spot_disp(spot),
        "bid_disp": "—",
        "ask_disp": "—",
        "session_label": session_label,
        "call_signal": "wait",
        "call_conviction": "low",
        "fusion_available": False,
        "dominant_dir": "flat",
        "rules_headline": "—",
    }


def _no_valid_expiry_state(
    ticker: str, *, expiries: list, today_str: str, spot, session_label,
    update_source: Optional[str], fetch_start_mono: float, cq: _ChainQuoteForState,
) -> dict:
    import server as _srv
    from trade_impacting_gate import apply_trade_impacting_gate

    minimal = _wait_shell(
        ticker, selected_exp=None, expiries=expiries, today_str=today_str, spot=spot,
        session_label=session_label, state_error="no_valid_expiry",
        detail=("No usable option expiry (empty chain or all expiries past). "
                "WTDS / Call need an options chain — try another symbol or refresh."),
    )
    end_mono = time.monotonic()
    minimal["_server_build_ts"] = time.time()
    minimal["_pipeline_ms"] = round((end_mono - fetch_start_mono) * 1000)
    minimal["_chain_ms"] = round((cq.t_after_chain_mono - fetch_start_mono) * 1000)
    minimal["_quote_ms"] = round((cq.t_after_quote_mono - cq.t_after_chain_mono) * 1000)
    minimal["_compute_ms"] = round((end_mono - cq.t_after_quote_mono) * 1000)
    if update_source is not None:
        minimal["_update_source"] = update_source
    apply_trade_impacting_gate(minimal, route="server._fetch_state.no_valid_expiry")
    _srv._lmp.merge_into_state(minimal, ticker)
    return _srv._finalize_production_decision(minimal, "server._fetch_state.no_valid_expiry")


def _expiry_slice_empty_state(
    ticker: str, *, selected_exp: str, expiries: list, today_str: str, spot, session_label,
    kl_expiry_source, update_source: Optional[str],
) -> dict:
    import server as _srv

    shell = _wait_shell(
        ticker, selected_exp=selected_exp, expiries=expiries, today_str=today_str, spot=spot,
        session_label=session_label, state_error="expiry_slice_empty",
        detail=(f"No option contracts with Schwab expirationDate={selected_exp}. "
                "Refusing full-chain fallback for KEY LEVELS / exposures."),
    )
    # kl_expiry_source sits right after state_error_detail, as it always has.
    exp_err = {}
    for k, v in shell.items():
        exp_err[k] = v
        if k == "state_error_detail":
            exp_err["kl_expiry_source"] = kl_expiry_source
    exp_err = stamp_decision_bundle(exp_err)
    exp_err["_server_build_ts"] = time.time()
    if update_source is not None:
        exp_err["_update_source"] = update_source
    _srv._lmp.merge_into_state(exp_err, ticker)
    return exp_err


def _missing_spot_state(
    ticker: str, *, selected_exp: str, expiries: list, today_str: str, q,
) -> dict:
    return stamp_decision_bundle({
        "ticker": ticker.upper(),
        "selected_exp": selected_exp,
        "expiries": [e for e in expiries if e >= today_str],
        "state_error": "missing_canonical_spot",
        "state_error_detail": "Schwab quote missing positive lastPrice and mark; refusing to compute state from synthetic spot.",
        "spot": None,
        "spot_disp": "—",
        "bid": q.bid,
        "ask": q.ask,
        "bid_disp": f"{float(q.bid):.2f}" if q.bid is not None else "—",
        "ask_disp": f"{float(q.ask):.2f}" if q.ask is not None else "—",
        "quote_source_detail": q.quote_source_detail(spot_label="unavailable_missing_last_and_mark"),
        "server_ts": time.time(),
    })
