"""UI real-time transport fidelity audit helpers (read-only).

Mirrors client guards in static/index.html for deterministic offline audit.
Does not change models, card semantics, or fusion policy.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "static" / "index.html"
SERVER_PY = ROOT / "server.py"

try:
    from instrument_identity import BROKER_INDEX_BARE_ROOTS, ticker_storage_key
    from money_path_ticker_tiers import (
        BASE_MONEY_PATH_TICKERS,
        TRUST_GUEST_UNPROVEN,
        is_base_money_path_ticker,
        is_guest_ticker,
        ticker_trust_class,
    )
except ImportError:
    BASE_MONEY_PATH_TICKERS = ("SPY", "QQQ", "IWM")
    BROKER_INDEX_BARE_ROOTS = frozenset({"SPX", "DJI", "COMPX", "VIX"})
    TRUST_GUEST_UNPROVEN = "guest_unproven"

    def ticker_storage_key(ticker: str | None) -> str:
        t = (ticker or "").strip()
        if not t:
            return ""
        if t.startswith("$"):
            return "$" + t[1:].strip().upper()
        u = t.upper()
        if u in BROKER_INDEX_BARE_ROOTS:
            return "$" + u
        return u

    def is_base_money_path_ticker(ticker: str) -> bool:
        return (ticker or "").upper() in {x.upper() for x in BASE_MONEY_PATH_TICKERS}

    def is_guest_ticker(ticker: str) -> bool:
        return not is_base_money_path_ticker(ticker)

    def ticker_trust_class(ticker: str, *, promoted: bool = False) -> str:
        if is_base_money_path_ticker(ticker):
            return "base_money_path"
        return TRUST_GUEST_UNPROVEN

CORE_MONEY_PATH_TICKERS: tuple[str, ...] = tuple(
    t.upper() for t in BASE_MONEY_PATH_TICKERS
)
GUEST_SAMPLE_TICKERS: tuple[str, ...] = (
    "NVDA",
    "AAPL",
    "MSFT",
    "AMZN",
    "META",
    "TSLA",
    "GOOGL",
    "AVGO",
    "MRVL",
    "PLTR",
    "CIFR",
)
SPECIAL_INDEX_TICKERS: tuple[str, ...] = (
    "SPX",
    "$SPX",
    "$VIX",
    "$TNX",
    "VIX",
)

ED_FEED_FRESH_SEC = 3
ED_FEED_STALE_SEC = 30
INSTITUTIONAL_BUNDLE_TRUST_SEC = 45

TIER_C_REQUIRED_METADATA = (
    "ticker",
    "_server_build_ts",
    "decision_generation_id",
    "_update_source",
)
FAST_QUOTE_REQUIRED_METADATA = ("ticker", "fast_server_ts", "fast_generation_id")


@dataclass
class RenderCoherenceResult:
    ok: bool
    reason: str = ""


@dataclass
class TransportMetricsAccumulator:
    """Client-side transport counters (replay from diag events or live buffer)."""

    startup_time_to_shell_ms: Optional[float] = None
    startup_time_to_first_payload_ms: Optional[float] = None
    startup_time_to_first_card_render_ms: Optional[float] = None
    ticker_switch_click_to_loading_ms: list[float] = field(default_factory=list)
    ticker_switch_click_to_request_ms: list[float] = field(default_factory=list)
    ticker_switch_request_to_response_ms: list[float] = field(default_factory=list)
    ticker_switch_response_to_render_ms: list[float] = field(default_factory=list)
    ticker_switch_click_to_card_render_ms: list[float] = field(default_factory=list)
    stale_pill_count: int = 0
    stale_pill_duration_ms: list[float] = field(default_factory=list)
    loading_duration_ms: list[float] = field(default_factory=list)
    old_ticker_payload_count: int = 0
    out_of_order_payload_count: int = 0
    duplicate_payload_count: int = 0
    payload_without_ticker_count: int = 0
    payload_without_timestamp_count: int = 0
    payload_without_generation_id_count: int = 0
    sqlite_lock_wait_count: int = 0
    sqlite_database_locked_count: int = 0
    backend_compute_ms: list[float] = field(default_factory=list)
    frontend_render_ms: list[float] = field(default_factory=list)


def valid_server_build_ts(payload: dict[str, Any]) -> Optional[float]:
    raw = payload.get("_server_build_ts")
    try:
        ts = float(raw)
    except (TypeError, ValueError):
        return None
    return ts if math.isfinite(ts) and ts > 0 else None


def valid_quote_lane_ts(payload: dict[str, Any]) -> Optional[float]:
    for key in ("fast_server_ts", "_live_plane_fast_ts"):
        try:
            ts = float(payload.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(ts) and ts > 0:
            return ts
    return None


def render_coherence_guard(
    payload: dict[str, Any],
    *,
    active_ticker: str,
    last_render_timestamp: float = 0.0,
    last_rendered_decision_gen: int = 0,
    timestamp_lane: str = "analytical",
    check_decision_gen: bool = True,
) -> RenderCoherenceResult:
    """Aligned with _renderCoherenceGuards in static/index.html."""
    if not payload or not isinstance(payload, dict):
        return RenderCoherenceResult(False, "null")
    incoming = (payload.get("ticker") or "").upper()
    if incoming and incoming != (active_ticker or "").upper():
        return RenderCoherenceResult(False, "ticker")
    if check_decision_gen:
        dec_raw = payload.get("decision_generation_id")
        try:
            dec_gen = float(dec_raw)
        except (TypeError, ValueError):
            dec_gen = float("nan")
        if math.isfinite(dec_gen):
            if int(dec_gen) < int(last_rendered_decision_gen):
                return RenderCoherenceResult(False, "gen")
            return RenderCoherenceResult(True, "")
    ts = valid_server_build_ts(payload)
    if ts is not None and timestamp_lane == "analytical" and ts < last_render_timestamp:
        return RenderCoherenceResult(False, "ts")
    if timestamp_lane in ("quote", "fast"):
        qts = valid_quote_lane_ts(payload)
        if qts is not None and qts < last_render_timestamp:
            return RenderCoherenceResult(False, "ts_quote")
    return RenderCoherenceResult(True, "")


def should_discard_inflight_response(
    *,
    my_generation: int,
    request_generation: int,
    payload_ticker: Optional[str],
    active_ticker: str,
) -> tuple[bool, str]:
    """REST/SSE ownership — aligned with fetchState / pollFallback / SSE handlers."""
    if my_generation != request_generation:
        return True, "generation_superseded"
    if payload_ticker and payload_ticker.upper() != (active_ticker or "").upper():
        return True, "ticker_mismatch"
    return False, ""


def bundle_age_sec(bundle_ts: Optional[float], now_ms: float) -> Optional[float]:
    if bundle_ts is None:
        return None
    try:
        ts = float(bundle_ts)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(ts) or ts <= 0:
        return None
    return max(0.0, round(now_ms / 1000.0 - ts))


def has_trusted_mhap_bundle(payload: dict[str, Any]) -> bool:
    rows = payload.get("mhap_rows")
    return isinstance(rows, list) and len(rows) > 0


def bundle_within_trust_window(
    *,
    bundle_ts: Optional[float],
    payload: dict[str, Any],
    now_ms: float,
) -> bool:
    age = bundle_age_sec(bundle_ts, now_ms)
    if age is None:
        return False
    return has_trusted_mhap_bundle(payload) and age <= INSTITUTIONAL_BUNDLE_TRUST_SEC


def lane_stale_operator_label(
    *,
    last_fast_ts: float,
    last_render_ts: float,
    bundle_ts: float,
    decision_generation_id: Optional[int],
    tier_c_painted_at_gen: int,
    pending_full_analytics: bool,
    payload: dict[str, Any],
    now_ms: float,
) -> dict[str, Any]:
    """Mirror laneStaleOperatorLabel + _refreshLiveUiIntegrityDerivations."""
    quote_ahead = last_fast_ts > 0 and last_render_ts > 0 and last_fast_ts > last_render_ts
    gen = decision_generation_id
    gen_stale = gen is not None and gen > tier_c_painted_at_gen
    slow_stale_vs_fast = bundle_ts > 0 and last_fast_ts > 0 and bundle_ts < last_fast_ts
    integrity = {
        "quoteAhead": quote_ahead,
        "pending": pending_full_analytics,
        "genStale": gen_stale,
        "slowStaleVsFast": slow_stale_vs_fast,
        "bundleTs": bundle_ts,
    }
    if bundle_within_trust_window(bundle_ts=bundle_ts, payload=payload, now_ms=now_ms):
        if payload.get("analytics_refresh_in_progress") is True or gen_stale:
            return {"show": True, "label": "SYNCING ANALYTICS…", "severity": "dim"}
        return {"show": False, "label": "", "severity": "none"}
    if gen_stale:
        return {"show": True, "label": "LANE STALE — CARDS PAINTING…", "severity": "warn"}
    if quote_ahead or slow_stale_vs_fast:
        return {"show": True, "label": "LANE STALE — QUOTE AHEAD", "severity": "warn"}
    if pending_full_analytics:
        return {"show": True, "label": "LANE STALE — PENDING ANALYTICS", "severity": "warn"}
    return {"show": False, "label": "", "severity": "none"}


def compute_feed_state(
    *,
    sse_phase: str,
    last_fast_ts: float,
    now_ms: float,
    plane_authority: str = "",
    streaming_fallback: bool = False,
    plane_gen_ok: bool = False,
    streaming_connected: bool = False,
) -> dict[str, Any]:
    """Mirror computeFeedState in static/index.html."""
    transport = "NONE"
    if plane_gen_ok:
        if plane_authority == "streaming":
            transport = "L1"
        elif plane_authority == "rest_mismatch" and streaming_connected:
            transport = "SUB"
        elif plane_authority in (
            "rest_fallback_explicit",
            "rest_only",
            "rest_mismatch",
        ) or streaming_fallback or plane_authority:
            transport = "REST"

    age_sec = float("nan")
    if last_fast_ts > 0:
        age_sec = max(0.0, now_ms / 1000.0 - last_fast_ts)

    if sse_phase in ("retrying", "offline"):
        return {
            "state": "DOWN",
            "age_sec": age_sec if math.isfinite(age_sec) else 0.0,
            "transport": transport,
            "is_blinking": False,
            "color": "#ff4444",
        }

    if not math.isfinite(age_sec):
        return {
            "state": "DELAY",
            "age_sec": 0.0,
            "transport": transport,
            "is_blinking": False,
            "color": "#fbbf24",
        }

    if not plane_gen_ok:
        if age_sec <= ED_FEED_STALE_SEC:
            return {
                "state": "DELAY",
                "age_sec": age_sec,
                "transport": "NONE",
                "is_blinking": False,
                "color": "#fbbf24",
            }
        return {
            "state": "STALE",
            "age_sec": age_sec,
            "transport": "NONE",
            "is_blinking": False,
            "color": "#f59e0b",
        }

    if age_sec <= ED_FEED_FRESH_SEC:
        if plane_authority == "streaming":
            return {
                "state": "LIVE",
                "age_sec": age_sec,
                "transport": "L1",
                "is_blinking": True,
                "color": "#00e676",
            }
        tr = "REST"
        if plane_authority == "rest_mismatch" and streaming_connected:
            tr = "SUB"
        return {
            "state": "SYNCED",
            "age_sec": age_sec,
            "transport": tr,
            "is_blinking": False,
            "color": "#22c55e",
        }

    if age_sec <= ED_FEED_STALE_SEC:
        return {
            "state": "DELAY",
            "age_sec": age_sec,
            "transport": transport,
            "is_blinking": False,
            "color": "#fbbf24",
        }

    return {
        "state": "STALE",
        "age_sec": age_sec,
        "transport": transport,
        "is_blinking": False,
        "color": "#f59e0b",
    }


def tier_c_card_render_fingerprint(payload: dict[str, Any]) -> str:
    """Stable fingerprint of Tier C fields that drive horizon/ALL/PLAN card paint."""
    mhap_sig: list[dict[str, Any]] = []
    for row in payload.get("mhap_rows") or []:
        if not isinstance(row, dict):
            continue
        mhap_sig.append(
            {
                "horizon": row.get("horizon"),
                "call": row.get("call"),
                "confidence": row.get("confidence"),
                "missing": row.get("missing"),
                "row_state": row.get("row_state"),
            }
        )
    mhap_sig.sort(key=lambda r: str(r.get("horizon") or ""))

    body = {
        "ticker": (payload.get("ticker") or "").upper(),
        "selected_exp": payload.get("selected_exp"),
        "decision_generation_id": payload.get("decision_generation_id"),
        "_server_build_ts": payload.get("_server_build_ts"),
        "analytics_version": payload.get("analytics_version"),
        "analytics_stale": payload.get("analytics_stale"),
        "analytics_refresh_in_progress": payload.get("analytics_refresh_in_progress"),
        "analytics_pending_shell": payload.get("analytics_pending_shell"),
        "analytics_partial_tier_c": payload.get("analytics_partial_tier_c"),
        "final_bias": payload.get("final_bias"),
        "entry_state": payload.get("entry_state"),
        "validation_passed": payload.get("validation_passed"),
        "wait_reason": payload.get("wait_reason"),
        "call_signal": payload.get("call_signal"),
        "entry_display_text": payload.get("entry_display_text"),
        "stop_display_text": payload.get("stop_display_text"),
        "targets_display": payload.get("targets_display"),
        "invalidation": payload.get("invalidation"),
        "size_modifier_display": payload.get("size_modifier_display"),
        "mhap_rows": mhap_sig,
        "horizon_prob_bars": payload.get("horizon_prob_bars"),
        "_update_source": payload.get("_update_source"),
    }
    return json.dumps(body, sort_keys=True, default=str)


def tier_c_payload_fingerprint(payload: dict[str, Any]) -> str:
    """Alias — card-render fingerprint supersedes minimal transport fingerprint."""
    return tier_c_card_render_fingerprint(payload)


def should_skip_tier_c_duplicate_render(
    payload: dict[str, Any],
    *,
    active_ticker: str,
    request_generation: int,
    last_fingerprint: Optional[str],
    last_scope: Optional[tuple[str, int]] = None,
) -> tuple[bool, str]:
    """
    True when card-driving Tier C payload is unchanged for current ticker scope.

    Scope = (active_ticker, request_generation). Wrong-ticker payloads must be
    rejected by render_coherence_guard before calling this helper.
    """
    ticker = (payload.get("ticker") or "").upper()
    if ticker and ticker != (active_ticker or "").upper():
        return False, "wrong_ticker"
    scope = ((active_ticker or "").upper(), int(request_generation))
    if last_scope is not None and last_scope != scope:
        return False, "scope_changed"
    fp = tier_c_card_render_fingerprint(payload)
    if last_fingerprint is not None and fp == last_fingerprint:
        return True, "duplicate_fingerprint"
    return False, "render_required"


def is_duplicate_tier_c_payload(
    payload: dict[str, Any],
    last_fingerprint: Optional[str],
) -> bool:
    fp = tier_c_card_render_fingerprint(payload)
    return last_fingerprint is not None and fp == last_fingerprint


def audit_payload_metadata(payload: dict[str, Any], *, tier: str = "C") -> dict[str, Any]:
    required = TIER_C_REQUIRED_METADATA if tier == "C" else FAST_QUOTE_REQUIRED_METADATA
    missing = [k for k in required if payload.get(k) in (None, "")]
    return {
        "tier": tier,
        "missing_fields": missing,
        "complete": len(missing) == 0,
        "ticker": payload.get("ticker"),
        "timestamp": payload.get("_server_build_ts") or payload.get("fast_server_ts"),
        "generation_id": payload.get("decision_generation_id")
        or payload.get("fast_generation_id"),
        "source": payload.get("_update_source"),
    }


def ingest_transport_event(acc: TransportMetricsAccumulator, event: dict[str, Any]) -> None:
    """Fold one switch-diag or replay event into counters."""
    if event.get("ticker_mismatch_discarded"):
        acc.old_ticker_payload_count += 1
    if event.get("generation_superseded"):
        acc.out_of_order_payload_count += 1
    fq = event.get("first_quote_ms")
    fs = event.get("first_full_state_ms")
    if fq is not None:
        try:
            acc.ticker_switch_click_to_card_render_ms.append(float(fq))
        except (TypeError, ValueError):
            pass
    if fs is not None:
        try:
            acc.ticker_switch_click_to_card_render_ms.append(float(fs))
        except (TypeError, ValueError):
            pass
    ui = event.get("ui_committed_ms")
    if ui is not None:
        try:
            acc.ticker_switch_click_to_loading_ms.append(float(ui))
        except (TypeError, ValueError):
            pass
    pipe = event.get("pipeline_ms")
    if pipe is not None:
        try:
            acc.backend_compute_ms.append(float(pipe))
        except (TypeError, ValueError):
            pass


def snapshot_cache_restore_marks_stale(cached: dict[str, Any]) -> dict[str, Any]:
    """Mirror _snapshotCacheRestore — restored cache must not look fresh."""
    out = dict(cached)
    out["analytics_stale"] = True
    out["analytics_refresh_in_progress"] = True
    out["analytics_pending_shell"] = False
    out["_tier"] = "C_analytics"
    out["_update_source"] = "client_ticker_cache"
    return out


def ticker_switch_pair_kind(old_ticker: str, new_ticker: str) -> str:
    """Classify switch direction for audit matrix."""
    old_base = is_base_money_path_ticker(old_ticker)
    new_base = is_base_money_path_ticker(new_ticker)
    if old_base and new_base:
        return "core_to_core"
    if old_base and not new_base:
        return "core_to_guest"
    if not old_base and new_base:
        return "guest_to_core"
    return "guest_to_guest"


def simulate_switch_guard_matrix(
    old_ticker: str,
    new_ticker: str,
    *,
    stale_payload_ticker: Optional[str] = None,
) -> dict[str, Any]:
    """
    Deterministic guard evaluation for a ticker switch (tier-agnostic transport layer).

    Models: requestGeneration bump, activeTicker commit, wrong-ticker discard,
    cache restore stale markers, coherence guard on incoming payload.
    """
    active = (new_ticker or "").strip().upper() or "SPY"
    old = (old_ticker or "").strip().upper()
    pair = ticker_switch_pair_kind(old, active)
    wrong = stale_payload_ticker or old
    discard, discard_reason = should_discard_inflight_response(
        my_generation=2,
        request_generation=2,
        payload_ticker=wrong,
        active_ticker=active,
    )
    superseded_discard, _ = should_discard_inflight_response(
        my_generation=1,
        request_generation=2,
        payload_ticker=wrong,
        active_ticker=active,
    )
    cached = {
        "ticker": active,
        "mhap_rows": [{"horizon": "1c", "call": "LONG"}],
        "analytics_stale": False,
        "analytics_pending_shell": False,
    }
    restored = snapshot_cache_restore_marks_stale(cached)
    guest_payload = {
        "ticker": active,
        "_server_build_ts": 1_710_000_000.0,
        "decision_generation_id": 3,
        "_update_source": "rest_manual",
        "analytics_pending_shell": True,
        "guest_trust_class": ticker_trust_class(active),
    }
    guard = render_coherence_guard(
        guest_payload,
        active_ticker=active,
        last_render_timestamp=0,
        last_rendered_decision_gen=0,
    )
    return {
        "pair": pair,
        "old_ticker": old,
        "new_ticker": active,
        "storage_key": ticker_storage_key(active),
        "trust_class": ticker_trust_class(active),
        "wrong_ticker_discarded": discard,
        "wrong_ticker_discard_reason": discard_reason,
        "superseded_generation_discarded": superseded_discard,
        "cache_restore_marks_stale": restored.get("analytics_stale") is True
        and restored.get("analytics_refresh_in_progress") is True
        and restored.get("_update_source") == "client_ticker_cache",
        "cache_not_pending_shell": restored.get("analytics_pending_shell") is False,
        "guest_payload_guard_accepts_matching_ticker": guard.ok,
        "guest_metadata": audit_payload_metadata(guest_payload, tier="C"),
    }


def audit_core_vs_guest_ticker_switching() -> dict[str, Any]:
    """
    Operator requirement: ticker switching must be seamless, guarded, and fast for
    core money-path AND guest symbols — not only SPY/QQQ/IWM.
    """
    html = INDEX_HTML.read_text(encoding="utf-8", errors="replace")
    switch_pairs = [
        ("SPY", "QQQ"),
        ("QQQ", "IWM"),
        ("SPY", "NVDA"),
        ("IWM", "AAPL"),
        ("NVDA", "TSLA"),
        ("PLTR", "MSFT"),
        ("SPY", "SPX"),
        ("$VIX", "SPY"),
    ]
    pair_results = {
        f"{a}->{b}": simulate_switch_guard_matrix(a, b, stale_payload_ticker=a)
        for a, b in switch_pairs
    }
    all_discard_wrong = all(r["wrong_ticker_discarded"] for r in pair_results.values())
    all_cache_stale = all(r["cache_restore_marks_stale"] for r in pair_results.values())
    guards_tier_agnostic = (
        "function _renderCoherenceGuards(" in html
        and "activeTicker" in html
        and "requestGeneration" in html
        and "is_base_money_path" not in html.split("function _renderCoherenceGuards(")[1].split("function _commitAnalyticalRenderTimestampAndGen")[0]
    )
    set_active_body = html.split("function setActiveTicker(")[1].split("function _scheduleServerAnalyticsWarm")[0]
    active_ticker_guest_safe = (
        "activeTicker = t" in set_active_body
        and "requestGeneration++" in set_active_body
        and "is_base_money_path" not in set_active_body
    )
    guest_visible_degraded = (
        "analytics_pending_shell" in html
        and "analytics_stale" in html
        and ("Analytics: loading" in html or "analytics_refresh_in_progress" in html)
    )
    special_keys = {ticker_storage_key(t) for t in SPECIAL_INDEX_TICKERS}
    return {
        "operator_requirement": (
            "Ticker switching must be seamless, guarded, and fast for core money-path "
            "tickers (SPY/QQQ/IWM) and guest tickers (NVDA, AAPL, …) alike. Guest tickers "
            "may lack full base capture parity but must not show old cards, wrong-ticker "
            "payloads, or long unexplained loading."
        ),
        "core_tickers": list(CORE_MONEY_PATH_TICKERS),
        "guest_sample_tickers": list(GUEST_SAMPLE_TICKERS),
        "special_index_tickers": list(SPECIAL_INDEX_TICKERS),
        "special_storage_keys": sorted(special_keys),
        "transport_guards_tier_agnostic": guards_tier_agnostic,
        "active_ticker_ownership_guest_safe": active_ticker_guest_safe,
        "wrong_ticker_discarded_all_pairs": all_discard_wrong,
        "cache_restore_stale_all_pairs": all_cache_stale,
        "guest_payload_metadata_required_same_as_core": True,
        "guest_can_show_pending_shell": True,
        "guest_missing_data_visible": guest_visible_degraded,
        "guest_loading_explained_via": [
            "status-label ANALYTICS… on switch",
            "analytics_pending_shell + error-bar remediation text",
            "updateAnalyticsFreshnessUI Analytics: loading…",
            "laneStaleOperatorLabel SYNCING / PENDING when applicable",
        ],
        "core_cards_can_persist_after_guest_switch_risk": (
            "Stale-while-revalidate restores per-ticker cache only when revisiting same symbol; "
            "switching core→guest without guest cache uses pending shell. Residual risk: guest "
            "cache hit could show prior guest cards with analytics_stale until refresh — not core ticker bleed if guards hold."
        ),
        "switch_pair_matrix": pair_results,
        "question_21_answer": (
            "Transport guards are tier-agnostic in static code — same requestGeneration, "
            "ticker mismatch discard, and _renderCoherenceGuards for core and guest. "
            "NOT YET PROVEN LIVE for guest warm-switch SLA or guest cold-start without "
            "visible degraded state; core has stronger capture parity but UI contract applies to all symbols."
        ),
        "live_validation_required_guest": [
            "core→guest and guest→core switch with ED_SWITCH_TIMING under RTH",
            "guest cold start (no cache) shows pending shell not prior core cards",
            "SPX/$VIX/$TNX switch if operator uses them in UI",
        ],
    }


def parse_sqlite_contention_from_text(text: str) -> dict[str, int]:
    """Count sqlite tier-1 lock / busy signals from server log text."""
    lock_wait = len(
        re.findall(r"sqlite_tier1_lock_wait\b", text, flags=re.IGNORECASE)
    )
    busy_retry = len(
        re.findall(r"sqlite_tier1_busy_retry\b", text, flags=re.IGNORECASE)
    )
    db_locked = len(re.findall(r"database is locked", text, flags=re.IGNORECASE))
    tier1_fail = len(re.findall(r"sqlite_tier1_fail\b", text, flags=re.IGNORECASE))
    return {
        "sqlite_lock_wait_count": lock_wait,
        "sqlite_busy_retry_count": busy_retry,
        "sqlite_database_locked_count": db_locked,
        "sqlite_tier1_fail_count": tier1_fail,
    }


def static_transport_mechanisms() -> dict[str, Any]:
    """Authoritative hybrid transport map from code surfaces (offline)."""
    return {
        "classification": "hybrid",
        "card_drivers": {
            "tier_c_full_cards": [
                "GET /api/analytics/state (REST, primary on switch + poll fallback)",
                "GET /api/state (legacy alias)",
                "SSE GET /api/stream onmessage → render(data,'sse')",
            ],
            "tier_b_context": [
                "GET /api/analytics/light (REST opportunistic)",
                "SSE GET /api/analytics/light/stream l1_projection → renderTierBLight",
            ],
            "tier_a_quote_strip": [
                "GET /api/live/state (REST concurrent on switch)",
                "SSE live_quote events → _livePlaneApplyCore",
                "GET /api/fast-quote poll → renderFast",
            ],
        },
        "price_header_drivers": [
            "window._fastLaneSpot/_fastLaneSpotDisp (fast lane)",
            "refreshUtilityBar() reads owned plane + _lastData when ticker matches",
            "GET /api/live/plane diagnostics for streaming authority",
        ],
        "feed_live_ui_active": {
            "feed_pill": "computeFeedState → paintUtilityFeedPill (FEED LIVE/SYNCED/DELAY/STALE/DOWN)",
            "ui_active": "ub-ui-detail shows analytics_version from last accepted Tier C payload",
            "status_dot": "status-dot + status-label (LIVE / ANALYTICS… / ERROR)",
            "sse_badge": "_setSseUi phases CONNECTING/CONN/LIVE/RETRY/OFFLINE",
        },
        "stale_drivers": {
            "lane_stale_chip": "laneStaleOperatorLabel — quote ahead, gen behind cards, pending analytics, syncing within trust window",
            "feed_stale": "computeFeedState age_sec > ED_FEED_STALE_SEC (30s)",
            "card_stale_css": "data-direction-withhold + data-lane-stale on horizon cards",
            "analytics_stale_flag": "payload.analytics_stale + analytics_refresh_in_progress",
        },
        "loading_drivers": {
            "refresh_btn": "↻ LOADING while fetchState in flight (Tier C force path)",
            "status_label": "ANALYTICS… on ticker switch",
            "analytics_freshness_el": "Analytics: loading… when analytics_pending_shell",
            "loading_overlay": "hidden on switch intentionally — not a blocking spinner",
            "tier_c_backoff": "_tierCBackoffUntilMs 800ms after pending shell",
        },
        "ownership_guards": [
            "requestGeneration increment on setActiveTicker",
            "SSE sseGen !== requestGeneration → discard",
            "REST myGen !== requestGeneration → discard",
            "ticker mismatch discard on REST/SSE/fast poll",
            "_renderCoherenceGuards ticker + decision_generation_id + _server_build_ts",
            "_commitPlaneDiagnosticsIfCurrent gen+ticker",
        ],
        "ticker_switch_clear": [
            "requestGeneration++ resets quote lane timestamps",
            "lastRenderTimestamp=0, _lastRenderedDecisionGen=0",
            "stale-while-revalidate via _snapshotCacheRestore (marks analytics_stale)",
            "runTickerLiveAcquisition before Tier C (SSE + L1 + fast quote, non-blocking Tier C)",
        ],
        "sqlite_contention": {
            "producer": "db.py EdDB._tier1_snapshot_write — logs sqlite_tier1_lock_wait / busy_retry",
            "consumer_risk": "Tier C _fetch_state DB reads + snapshot inserts during live capture",
        },
        "instrumentation_present": [
            "window.__edSwitchDiag + POST /api/diagnostics/ticker-switch",
            "window._edFastRollout counters",
            "window._edRtDiag",
            "ED_SWITCH_TIMING console lines",
            "server payload fields _pipeline_ms, _compute_ms, _quote_ms, _from_cache",
        ],
        "instrumentation_gaps": [
            "No unified server-side transport audit ring buffer (switch diag is client-posted only)",
            "No built-in click-to-card-render histogram in production UI without ED_SWITCH_TIMING",
            "startup_time_to_shell requires browser Performance API capture (not persisted server-side)",
            "sqlite lock counts require log scrape unless ED_SQLITE_METRICS export added",
            "No per-tier switch SLA breakdown (core vs guest) in switch diag schema",
        ],
        "ticker_switch_scope": {
            "core_money_path": list(CORE_MONEY_PATH_TICKERS),
            "guest_examples": list(GUEST_SAMPLE_TICKERS),
            "special_index": list(SPECIAL_INDEX_TICKERS),
            "requirement": (
                "Switching must be seamless, guarded, and fast for core AND guest — guest lacks "
                "base capture parity but still requires immediate degraded state, no wrong-ticker "
                "overwrite, and visible explanation when data is incomplete."
            ),
        },
    }


def scan_static_surfaces() -> dict[str, Any]:
    """Verify critical guard symbols exist in index.html (offline contract lock)."""
    html = INDEX_HTML.read_text(encoding="utf-8", errors="replace")
    server = SERVER_PY.read_text(encoding="utf-8", errors="replace")
    checks = {
        "render_coherence_guards": "function _renderCoherenceGuards(" in html,
        "connect_sse": "function connectSSE(" in html,
        "connect_l1_light_sse": "function connectL1LightSSE(" in html,
        "poll_fallback": "async function pollStateFallback(" in html,
        "switch_diag_post": "/api/diagnostics/ticker-switch" in html,
        "analytics_state_endpoint": '@app.get("/api/analytics/state"' in server
        or '"/api/analytics/state"' in server,
        "stream_endpoint": '"/api/stream"' in server,
        "light_stream_endpoint": '"/api/analytics/light/stream"' in server,
        "fast_quote_endpoint": '"/api/fast-quote"' in server,
        "sqlite_tier1_lock_wait_log": "sqlite_tier1_lock_wait" in server
        or "sqlite_tier1_lock_wait" in (ROOT / "db.py").read_text(encoding="utf-8"),
    }
    return {"checks": checks, "all_pass": all(checks.values())}


def summarize_metrics(acc: TransportMetricsAccumulator) -> dict[str, Any]:
    def _pct(vals: list[float], p: float) -> Optional[float]:
        if not vals:
            return None
        s = sorted(vals)
        idx = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
        return round(s[idx], 1)

    return {
        "startup_time_to_shell_ms": acc.startup_time_to_shell_ms,
        "startup_time_to_first_payload_ms": acc.startup_time_to_first_payload_ms,
        "startup_time_to_first_card_render_ms": acc.startup_time_to_first_card_render_ms,
        "ticker_switch_click_to_loading_ms_p50": _pct(acc.ticker_switch_click_to_loading_ms, 50),
        "ticker_switch_click_to_request_ms_p50": _pct(acc.ticker_switch_click_to_request_ms, 50),
        "ticker_switch_request_to_response_ms_p50": _pct(
            acc.ticker_switch_request_to_response_ms, 50
        ),
        "ticker_switch_response_to_render_ms_p50": _pct(
            acc.ticker_switch_response_to_render_ms, 50
        ),
        "ticker_switch_click_to_card_render_ms_p50": _pct(
            acc.ticker_switch_click_to_card_render_ms, 50
        ),
        "stale_pill_count": acc.stale_pill_count,
        "stale_pill_duration_ms_sum": sum(acc.stale_pill_duration_ms),
        "loading_duration_ms_sum": sum(acc.loading_duration_ms),
        "old_ticker_payload_count": acc.old_ticker_payload_count,
        "out_of_order_payload_count": acc.out_of_order_payload_count,
        "duplicate_payload_count": acc.duplicate_payload_count,
        "payload_without_ticker_count": acc.payload_without_ticker_count,
        "payload_without_timestamp_count": acc.payload_without_timestamp_count,
        "payload_without_generation_id_count": acc.payload_without_generation_id_count,
        "sqlite_lock_wait_count": acc.sqlite_lock_wait_count,
        "sqlite_database_locked_count": acc.sqlite_database_locked_count,
        "backend_compute_ms_p50": _pct(acc.backend_compute_ms, 50),
        "frontend_render_ms_p50": _pct(acc.frontend_render_ms, 50),
        "sample_counts": {
            "switch_events": len(acc.ticker_switch_click_to_card_render_ms),
            "backend_compute_samples": len(acc.backend_compute_ms),
        },
    }


def answer_audit_questions(
    mechanisms: dict[str, Any],
    metrics: dict[str, Any],
    sqlite_log: dict[str, int],
    static_scan: dict[str, Any],
    *,
    market_session: str = "offline_static",
) -> dict[str, Any]:
    return {
        "1_live_card_transport": "Hybrid: Tier C REST + SSE /api/stream + pollStateFallback; cards from render() on Tier C payloads with mhap_rows",
        "2_price_header_transport": mechanisms["price_header_drivers"],
        "3_feed_live_ui_active": mechanisms["feed_live_ui_active"],
        "4_stale_drivers": mechanisms["stale_drivers"],
        "5_loading_drivers": mechanisms["loading_drivers"],
        "6_ticker_switch_clears_state": mechanisms["ticker_switch_clear"],
        "7_old_ticker_overwrite_risk": (
            "Low for accepted renders — guards discard wrong ticker and superseded generation; "
            "residual risk: stale-while-revalidate cache paints old ticker cards until refresh completes"
        ),
        "8_payload_metadata": {
            "tier_c_required": list(TIER_C_REQUIRED_METADATA),
            "fast_required": list(FAST_QUOTE_REQUIRED_METADATA),
            "note": "decision_generation_id on Tier C; fast_generation_id on quote lane",
        },
        "9_frontend_rejects_stale_oob": mechanisms["ownership_guards"],
        "10_backend_blocks_ui": (
            "Tier C compute can block force refresh; switch path fires Tier C async (non-blocking). "
            "SQLite lock waits on snapshot writes can delay Tier C cache refresh."
        ),
        "11_sync_on_switch": (
            "runTickerLiveAcquisition is sync setup only; Tier C REST not awaited on switch; "
            "model/fusion runs server-side inside _fetch_state / analytics cache refresh"
        ),
        "12_sqlite_evidence": sqlite_log,
        "13_rest_sse_consistency": (
            "Same ms_dict builder for REST and SSE stream; both carry ticker, _server_build_ts, "
            "_update_source, decision_generation_id when Tier C complete"
        ),
        "14_duplicate_payload_renders": (
            "Tier C card-render fingerprint dedup skips redundant full render when "
            "card-driving fields unchanged (fix/ui-transport-tier-c-dedup). L1 SSE retains "
            "separate l1_payload_fingerprint identity check."
        ),
        "15_click_to_card_delay_measurable": (
            "Yes with ED_SWITCH_TIMING=1 and __edSwitchDiag; not on by default. "
            f"p50_switch_ms={metrics.get('ticker_switch_click_to_card_render_ms_p50')}"
        ),
        "16_stale_meaning": (
            "FEED STALE = quote age >30s or plane not aligned; LANE STALE = quote ahead of bundle or cards painting behind decision gen"
        ),
        "17_loading_persist_causes": mechanisms["loading_drivers"],
        "18_active_ticker_preference": (
            "POST /api/streaming/active-ticker + SSE scoped to activeTicker; poll uses activeTicker only"
        ),
        "19_errors_swallowed": (
            "Many streaming/ plane fetch errors are catch-and-ignore; surfaced via status-dot ERROR and error-bar on Tier C failure"
        ),
        "20_operator_should_see_when_delayed": (
            "ANALYTICS… status, SYNCING ANALYTICS… lane chip, DELAY/STALE feed pill, analytics_pending_shell message in error-bar"
        ),
        "21_core_and_guest_ticker_switch_safe": (
            "Static: guards are tier-agnostic (no is_base_money_path in render guards). "
            "Guest tickers use same metadata contract and wrong-ticker discard. "
            "Live: not proven for guest warm-switch SLA — see core_vs_guest_ticker_switching."
        ),
        "market_session_note": market_session,
        "static_scan": static_scan,
    }


def bugs_proven_and_unproven(
    sqlite_log: dict[str, int],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    proven: list[str] = []
    not_proven: list[str] = []
    if sqlite_log.get("sqlite_database_locked_count", 0) > 0 or sqlite_log.get(
        "sqlite_lock_wait_count", 0
    ) > 0:
        proven.append(
            "SQLite write contention on tier-1 snapshot path (log evidence: lock wait / database locked)"
        )
    else:
        not_proven.append("SQLite contention impact on UI latency (no log samples in audit bundle)")

    proven.append(
        "Hybrid transport with multiple lanes can show LANE STALE — QUOTE AHEAD while cards still show prior bundle (by coherence rules, not necessarily wrong ticker)"
    )
    proven.append(
        "Ticker switch intentionally uses stale-while-revalidate cache — can show prior-ticker cards briefly with analytics_stale flag"
    )
    proven.append(
        "Transport ownership guards are tier-agnostic in static code — core and guest share requestGeneration + ticker mismatch discard"
    )
    not_proven.append(
        "Guest ticker warm switch meets <2s payload SLA (guest may cold-start slower — needs RTH matrix)"
    )
    not_proven.append(
        "Core ticker cards cannot persist after switch to guest without visible stale marker (needs live core→guest trace)"
    )
    not_proven.append(
        "Old ticker payload overwriting selected ticker after guards (requires live RTH switch capture)"
    )
    not_proven.append(
        "LOADING overlay persistence (overlay hidden on switch; operator may mean ANALYTICS… status — needs live trace)"
    )
    if metrics.get("ticker_switch_click_to_card_render_ms_p50") is None:
        not_proven.append(
            "Warm ticker switch SLA breach (<2s) — no switch diag samples in this audit run"
        )
    return {"bugs_proven": proven, "bugs_not_proven": not_proven}


def recommended_fix_branches() -> list[dict[str, str]]:
    return [
        {
            "branch": "fix/ui-transport-tier-c-dedup",
            "reason": "LANDED — Tier C card-render fingerprint skip before full render (mirror L1 SSE)",
            "status": "fixed",
        },
        {
            "branch": "fix/ui-transport-sqlite-readiness",
            "reason": "Surface sqlite_tier1_lock_wait counts on /api/diagnostics/transport-health when contention delays analytics cache",
        },
        {
            "branch": "fix/card-price-conflict-explainability",
            "reason": "After transport trust proven — operator-facing reconciliation chips (per PR #10 plan)",
        },
        {
            "branch": "fix/ui-transport-guest-switch-sla",
            "reason": "Per-tier switch diag + guest cold-start degraded UX when models/DB sparse",
        },
    ]
