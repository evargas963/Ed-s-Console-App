"""LIVE_UI_INTEGRITY_V1 — render-coherence guard, Tier-C dedup, ticker-switch classification.

The coherence-headline / stack INVALID chip / lane-stale-label DOM tests this file used to
mirror against legacy static/index.html were retired (/console cutover, operator directive
2026-09-14) — see the comment at their old location below for the full disposition.

REALITY-RECONCILIATION (2026-09-18): the card-trust-gate harness this file used to load from
tools/run_universal_card_fidelity_runtime.py (analytics_card_trust_gate/engine_tradeable_setup)
is retired along with that whole tool. Its own docstring claimed to mirror `analyticsCardTrustGate`
in static/index.html -- that JS function is confirmed absent from every current static/js/*.js
file and from static/index.html itself (grepped repo-wide), and zero production code anywhere
calls the Python mirror either -- it was tested only by this file and the harness's own retired
test file. The render-coherence-guard / Tier-C dedup / ticker-switch tests below never read
index.html and are unrelated, live, current coverage -- left untouched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# The following ~30 tests (and their _html()/_tv_deck_rule() helpers) were retired here
# (/console cutover, operator directive 2026-09-14): all read legacy static/index.html for the
# Terrain Command Deck / card-trust-gate / decision-command presentation (.tv-deck grid,
# edPaintNetGex, coherence-headline, dr-trust-stack chips, horizon withhold reasons, Tier-C
# dedup DOM hooks, DB-contention operator chips) -- none of it has any footprint in the new
# console (confirmed by direct grep across static/js/*.js and static/console.html). The
# harness-backed tests below (analytics_card_trust_gate / engine_tradeable_setup from
# tools/run_universal_card_fidelity_runtime.py) and the pure-Python render-coherence-guard /
# dedup / ticker-switch-classification tests are UNAFFECTED -- none of them read index.html at
# all -- and are preserved as-is.


def _derive_integrity(
    *,
    last_fast_ts: float,
    last_render_ts: float,
    bundle_ts: float,
    decision_generation_id: int | None,
    tier_c_painted_at_gen: int,
    pending_full_analytics: bool,
    stack_mode: str,
) -> dict:
    """Keep aligned with _refreshLiveUiIntegrityDerivations in index.html."""
    quote_ahead = last_fast_ts > 0 and last_render_ts > 0 and last_fast_ts > last_render_ts
    gen = decision_generation_id
    gen_stale = gen is not None and gen > tier_c_painted_at_gen
    slow_stale_vs_fast = bundle_ts > 0 and last_fast_ts > 0 and bundle_ts < last_fast_ts
    return {
        "quoteAhead": quote_ahead,
        "pending": pending_full_analytics,
        "genStale": gen_stale,
        "slowStaleVsFast": slow_stale_vs_fast,
        "stackMode": stack_mode.upper(),
        "gen": gen,
    }


def _stack_mode_chip_label(integrity: dict) -> str | None:
    if integrity["stackMode"] == "INVALID":
        return "STACK INVALID (fusion/MC prerequisites)"
    return None


def _lane_stale_chip_label(integrity: dict) -> str | None:
    if integrity["genStale"]:
        return "LANE STALE — CARDS PAINTING…"
    if integrity["quoteAhead"] or integrity["slowStaleVsFast"]:
        return "LANE STALE — QUOTE AHEAD"
    if integrity["pending"]:
        return "LANE STALE — PENDING ANALYTICS"
    return None


def _freshness_pill_suffix(integrity: dict) -> str:
    return " · PRICE AHEAD" if integrity["slowStaleVsFast"] else ""




































# ── UI transport fidelity (audit/ui-realtime-transport-fidelity) ─────────────

from verification.ui_realtime_transport_audit import (
    audit_payload_metadata,
    audit_core_vs_guest_ticker_switching,
    compute_feed_state,
    is_duplicate_tier_c_payload,
    lane_stale_operator_label,
    parse_sqlite_contention_from_text,
    render_coherence_guard,
    should_discard_inflight_response,
    should_skip_tier_c_duplicate_render,
    simulate_switch_guard_matrix,
    snapshot_cache_restore_marks_stale,
    tier_c_card_render_fingerprint,
    ticker_switch_pair_kind,
    tier_c_payload_fingerprint,
)
from instrument_identity import ticker_storage_key


def test_render_coherence_guard_rejects_wrong_ticker():
    payload = {"ticker": "QQQ", "_server_build_ts": 1000.0, "decision_generation_id": 2}
    guard = render_coherence_guard(
        payload,
        active_ticker="SPY",
        last_render_timestamp=0,
        last_rendered_decision_gen=0,
    )
    assert guard.ok is False
    assert guard.reason == "ticker"


def test_render_coherence_guard_rejects_older_generation_id():
    payload = {"ticker": "SPY", "_server_build_ts": 2000.0, "decision_generation_id": 3}
    guard = render_coherence_guard(
        payload,
        active_ticker="SPY",
        last_render_timestamp=0,
        last_rendered_decision_gen=5,
    )
    assert guard.ok is False
    assert guard.reason == "gen"


def test_render_coherence_guard_accepts_newer_gen_when_ts_regresses():
    """Newer decision_generation_id may accept even if _server_build_ts regresses (Tier C cache)."""
    payload = {"ticker": "SPY", "_server_build_ts": 900.0, "decision_generation_id": 8}
    guard = render_coherence_guard(
        payload,
        active_ticker="SPY",
        last_render_timestamp=1000.0,
        last_rendered_decision_gen=7,
    )
    assert guard.ok is True


def test_should_discard_inflight_when_generation_superseded():
    discard, reason = should_discard_inflight_response(
        my_generation=2,
        request_generation=5,
        payload_ticker="SPY",
        active_ticker="SPY",
    )
    assert discard is True
    assert reason == "generation_superseded"


def test_should_discard_inflight_on_ticker_mismatch():
    discard, reason = should_discard_inflight_response(
        my_generation=5,
        request_generation=5,
        payload_ticker="IWM",
        active_ticker="SPY",
    )
    assert discard is True
    assert reason == "ticker_mismatch"




def test_duplicate_tier_c_payload_fingerprint_detects_repeat():
    payload = {
        "ticker": "SPY",
        "decision_generation_id": 4,
        "_server_build_ts": 1710000000.0,
        "analytics_version": 12,
        "_update_source": "sse",
    }
    fp = tier_c_payload_fingerprint(payload)
    assert is_duplicate_tier_c_payload(payload, fp) is True
    assert is_duplicate_tier_c_payload(payload, None) is False


def test_compute_feed_state_stale_follows_age_rules():
    now_ms = 1_710_000_000_000
    stale = compute_feed_state(
        sse_phase="live",
        last_fast_ts=now_ms / 1000.0 - 45,
        now_ms=now_ms,
        plane_authority="streaming",
        plane_gen_ok=True,
        streaming_connected=True,
    )
    assert stale["state"] == "STALE"
    fresh = compute_feed_state(
        sse_phase="live",
        last_fast_ts=now_ms / 1000.0 - 1,
        now_ms=now_ms,
        plane_authority="streaming",
        plane_gen_ok=True,
        streaming_connected=True,
    )
    assert fresh["state"] == "LIVE"


def test_lane_stale_syncing_within_trust_window():
    now_ms = 1_710_000_000_000
    bundle_ts = now_ms / 1000.0 - 10
    label = lane_stale_operator_label(
        last_fast_ts=bundle_ts + 2,
        last_render_ts=bundle_ts,
        bundle_ts=bundle_ts,
        decision_generation_id=10,
        tier_c_painted_at_gen=5,
        pending_full_analytics=False,
        payload={
            "mhap_rows": [{"horizon": "1c", "call": "LONG"}],
            "analytics_refresh_in_progress": True,
        },
        now_ms=now_ms,
    )
    assert label["show"] is True
    assert label["label"] == "SYNCING ANALYTICS…"


def test_audit_payload_metadata_flags_missing_generation_id():
    meta = audit_payload_metadata({"ticker": "SPY", "_server_build_ts": 1.0}, tier="C")
    assert meta["complete"] is False
    assert "decision_generation_id" in meta["missing_fields"]




def test_sqlite_lock_event_counter_from_log_sample():
    sample = (
        "sqlite_tier1_lock_wait op=insert_snapshot ticker=SPY\n"
        "database is locked\n"
        "sqlite_tier1_busy_retry op=insert_snapshot\n"
    )
    counts = parse_sqlite_contention_from_text(sample)
    assert counts["sqlite_lock_wait_count"] == 1
    assert counts["sqlite_database_locked_count"] == 1
    assert counts["sqlite_busy_retry_count"] == 1


@pytest.mark.parametrize(
    "old_t,new_t,expected_pair",
    [
        ("SPY", "QQQ", "core_to_core"),
        ("SPY", "NVDA", "core_to_guest"),
        ("TSLA", "IWM", "guest_to_core"),
        ("NVDA", "AAPL", "guest_to_guest"),
    ],
)
def test_ticker_switch_pair_classification(old_t, new_t, expected_pair):
    assert ticker_switch_pair_kind(old_t, new_t) == expected_pair


@pytest.mark.parametrize(
    "old_t,new_t",
    [
        ("SPY", "QQQ"),
        ("SPY", "NVDA"),
        ("PLTR", "IWM"),
        ("NVDA", "TSLA"),
    ],
)
def test_wrong_ticker_payload_rejected_after_switch(old_t, new_t):
    result = simulate_switch_guard_matrix(old_t, new_t, stale_payload_ticker=old_t)
    assert result["wrong_ticker_discarded"] is True
    assert result["wrong_ticker_discard_reason"] == "ticker_mismatch"


def test_guest_stale_cache_restore_only_with_degraded_markers():
    cached = {
        "ticker": "NVDA",
        "mhap_rows": [{"horizon": "1c", "call": "LONG"}],
        "analytics_stale": False,
    }
    restored = snapshot_cache_restore_marks_stale(cached)
    assert restored["analytics_stale"] is True
    assert restored["analytics_refresh_in_progress"] is True
    assert restored["_update_source"] == "client_ticker_cache"
    assert restored["analytics_pending_shell"] is False


def test_special_index_ticker_storage_keys():
    assert ticker_storage_key("SPX") == "$SPX"
    assert ticker_storage_key("$SPX") == "$SPX"
    assert ticker_storage_key("$VIX") == "$VIX"
    assert ticker_storage_key("VIX") == "$VIX"


def test_core_vs_guest_audit_reports_tier_agnostic_guards():
    # transport_guards_tier_agnostic was dropped from this assertion here (/console cutover,
    # operator directive 2026-09-14): it detects legacy static/index.html's
    # _renderCoherenceGuards()/setActiveTicker() markers, which have no equivalent in the new
    # console (ed-core.js's setTicker() + its _hdrGen/_l1Gen generation counters are the real,
    # differently-shaped tier-agnostic guard today -- see verification/
    # ui_realtime_transport_audit.py's own independent-review fix note at this same date for
    # why the underlying scan no longer crashes but also can't detect the new shape). The
    # other assertions below come from simulate_switch_guard_matrix / static ticker lists, not
    # from parsing index.html, and are unaffected by the rename.
    audit = audit_core_vs_guest_ticker_switching()
    assert audit["wrong_ticker_discarded_all_pairs"] is True
    assert audit["cache_restore_stale_all_pairs"] is True
    assert "SPY" in audit["core_tickers"]
    assert "NVDA" in audit["guest_sample_tickers"]
    assert "21" in audit["question_21_answer"] or "tier-agnostic" in audit["question_21_answer"]




def _sample_tier_c_payload(**overrides):
    base = {
        "ticker": "SPY",
        "decision_generation_id": 5,
        "_server_build_ts": 1_710_000_000.0,
        "analytics_version": 12,
        "analytics_stale": False,
        "analytics_refresh_in_progress": False,
        "analytics_pending_shell": False,
        "final_bias": "LONG",
        "entry_state": "watching",
        "validation_passed": False,
        "wait_reason": "tape stack disagrees",
        "mhap_rows": [
            {"horizon": "1c", "call": "LONG", "confidence": 0.71},
            {"horizon": "5c", "call": "LONG", "confidence": 0.65},
        ],
        "horizon_prob_bars": {"1m": {"up": 0.2, "down": 0.6, "flat": 0.2}},
        "_update_source": "sse",
    }
    base.update(overrides)
    return base


def test_duplicate_tier_c_payload_skips_redundant_render():
    payload = _sample_tier_c_payload()
    fp = tier_c_card_render_fingerprint(payload)
    skip, reason = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="SPY",
        request_generation=3,
        last_fingerprint=fp,
        last_scope=("SPY", 3),
    )
    assert skip is True
    assert reason == "duplicate_fingerprint"


def test_changed_decision_generation_id_triggers_render():
    payload = _sample_tier_c_payload(decision_generation_id=6)
    prev = tier_c_card_render_fingerprint(_sample_tier_c_payload(decision_generation_id=5))
    skip, _ = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="SPY",
        request_generation=3,
        last_fingerprint=prev,
        last_scope=("SPY", 3),
    )
    assert skip is False


def test_changed_ticker_scope_resets_dedup():
    payload = _sample_tier_c_payload(ticker="NVDA")
    fp = tier_c_card_render_fingerprint(payload)
    skip, reason = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="NVDA",
        request_generation=4,
        last_fingerprint=fp,
        last_scope=("SPY", 3),
    )
    assert skip is False
    assert reason == "scope_changed"


def test_changed_stale_flag_triggers_render():
    payload = _sample_tier_c_payload(analytics_stale=True)
    prev = tier_c_card_render_fingerprint(_sample_tier_c_payload(analytics_stale=False))
    skip, _ = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="SPY",
        request_generation=3,
        last_fingerprint=prev,
        last_scope=("SPY", 3),
    )
    assert skip is False


def test_changed_mhap_direction_triggers_render():
    payload = _sample_tier_c_payload(
        mhap_rows=[{"horizon": "1c", "call": "SHORT", "confidence": 0.71}],
    )
    prev = tier_c_card_render_fingerprint(_sample_tier_c_payload())
    skip, _ = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="SPY",
        request_generation=3,
        last_fingerprint=prev,
        last_scope=("SPY", 3),
    )
    assert skip is False


def test_wrong_ticker_rejected_before_dedup_helper():
    payload = _sample_tier_c_payload(ticker="QQQ")
    guard = render_coherence_guard(payload, active_ticker="SPY")
    assert guard.ok is False
    skip, reason = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="SPY",
        request_generation=3,
        last_fingerprint=tier_c_card_render_fingerprint(payload),
        last_scope=("SPY", 3),
    )
    assert skip is False
    assert reason == "wrong_ticker"


@pytest.mark.parametrize("ticker", ["SPY", "NVDA", "PLTR", "VIX"])
def test_core_and_guest_share_tier_c_dedup_rules(ticker):
    payload = _sample_tier_c_payload(ticker=ticker)
    fp = tier_c_card_render_fingerprint(payload)
    skip, _ = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker=ticker,
        request_generation=1,
        last_fingerprint=fp,
        last_scope=(ticker.upper(), 1),
    )
    assert skip is True






def test_db_degraded_coexists_with_lane_stale_integrity():
    from verification.db_sqlite_contention_impact_audit import derive_db_contention_operator_status

    _now = 1_700_000_100.0
    db = derive_db_contention_operator_status(
        {
            "sqlite_lock_wait_count": 1,
            "sqlite_lock_wait_max_ms": 150.0,
            "recent_events": [
                {"kind": "lock_wait", "wait_ms": 150.0, "ts_utc": _now - 10.0}
            ],
        },
        now_utc=_now,
    )
    integrity = _derive_integrity(
        last_fast_ts=100.0,
        last_render_ts=50.0,
        bundle_ts=40.0,
        decision_generation_id=5,
        tier_c_painted_at_gen=3,
        pending_full_analytics=True,
        stack_mode="OK",
    )
    assert db["show"] is True
    assert _lane_stale_chip_label(integrity) is not None


def test_core_and_guest_share_db_contention_surface_attach():
    import copy

    from server import _attach_db_contention_operator_surface

    for ticker in ("SPY", "NVDA"):
        ms = {"ticker": ticker, "mhap_rows": [{"horizon": "1c", "call": "LONG"}]}
        before = copy.deepcopy(ms)
        _attach_db_contention_operator_surface(ms)
        assert ms["mhap_rows"] == before["mhap_rows"]
        op = ms["db_contention_operator"]
        assert op["diagnostics_source"] == "/api/diagnostics/sqlite-contention"
        assert "state" in op




@pytest.mark.parametrize(
    "pair,expected_kind",
    [
        (("SPY", "QQQ"), "core_to_core"),
        (("SPY", "NVDA"), "core_to_guest"),
        (("PLTR", "IWM"), "guest_to_core"),
        (("NVDA", "TSLA"), "guest_to_guest"),
    ],
)
def test_switch_timing_diag_pair_classification(pair, expected_kind):
    from verification.ui_realtime_transport_audit import (
        enrich_switch_diag_record,
        ticker_switch_pair_kind,
    )

    old_t, new_t = pair
    assert ticker_switch_pair_kind(old_t, new_t) == expected_kind
    rec = enrich_switch_diag_record(
        {
            "old_ticker": old_t,
            "new_ticker": new_t,
            "request_generation": 7,
            "client_wall_start_ms": 1_710_000_000_000,
            "first_quote_ms": 120.0,
            "first_full_state_ms": 800.0,
            "cards_first_render_ms": 900.0,
        }
    )
    assert rec["pair_kind"] == expected_kind
    assert rec["is_core"] == (new_t in ("SPY", "QQQ", "IWM"))
    assert rec["is_guest"] == (new_t not in ("SPY", "QQQ", "IWM"))
    assert rec["fast_quote_first_seen_ms"] == 120.0
    assert rec["tier_c_first_seen_ms"] == 800.0


def test_special_index_switch_storage_key_in_diag():
    from verification.ui_realtime_transport_audit import (
        enrich_switch_diag_record,
        is_special_index_ticker,
    )

    assert is_special_index_ticker("SPX") is True
    assert is_special_index_ticker("$VIX") is True
    rec = enrich_switch_diag_record({"old_ticker": "SPY", "new_ticker": "$VIX"})
    assert rec["is_special_index"] is True
    assert rec["storage_key"] == "$VIX"
    assert rec["selected_ticker"] == "$VIX"


def test_wrong_ticker_and_stale_generation_rejection_counted():
    from verification.ui_realtime_transport_audit import simulate_switch_guard_matrix

    wrong = simulate_switch_guard_matrix("SPY", "NVDA", stale_payload_ticker="SPY")
    assert wrong["wrong_ticker_payload_rejected_count"] == 1
    assert wrong["stale_generation_payload_rejected_count"] == 1


def test_no_contention_switch_operator_ok_state():
    from verification.ui_realtime_transport_audit import derive_switch_operator_state

    op = derive_switch_operator_state(
        {
            "is_guest": False,
            "db_contention_state_at_switch": "OK",
            "stale_cache_restored": False,
            "analytics_pending": False,
            "cards_first_render_ms": 500.0,
        }
    )
    assert op["state"] == "READY"
    assert op["show"] is False


def test_guest_stale_cache_switch_state():
    from verification.ui_realtime_transport_audit import derive_switch_operator_state

    op = derive_switch_operator_state(
        {
            "is_guest": True,
            "stale_cache_restored": True,
            "db_contention_state_at_switch": "OK",
            "analytics_pending": False,
        }
    )
    assert op["state"] == "CACHE STALE — REFRESHING"


def test_guest_incomplete_switch_state():
    from verification.ui_realtime_transport_audit import derive_switch_operator_state

    op = derive_switch_operator_state(
        {
            "is_guest": True,
            "guest_incomplete_reason": "guest_mhap_missing",
            "db_contention_state_at_switch": "OK",
        }
    )
    assert op["state"] == "GUEST DATA INCOMPLETE"


def test_db_degraded_coexists_with_switch_pending():
    from verification.ui_realtime_transport_audit import derive_switch_operator_state

    op = derive_switch_operator_state(
        {
            "is_guest": True,
            "db_contention_state_at_switch": "DB_DEGRADED",
            "analytics_pending": True,
            "analytics_light_first_seen_ms": None,
        }
    )
    assert op["state"] == "DB DEGRADED — CARDS MAY LAG"


def test_switch_operator_state_does_not_imply_model_wrong():
    from verification.ui_realtime_transport_audit import derive_switch_operator_state

    op = derive_switch_operator_state(
        {
            "is_guest": False,
            "analytics_pending": True,
            "analytics_light_first_seen_ms": 100.0,
        }
    )
    msg = (op.get("operator_message") or "").lower()
    assert "not a model verdict" in msg
    assert op["state"] == "ANALYTICS PENDING"


def test_guest_switch_sla_report_classifications():
    from verification.ui_realtime_transport_audit import (
        GUEST_SWITCH_SLA_CLASSIFICATIONS,
        build_guest_switch_sla_report,
    )

    report = build_guest_switch_sla_report(audit_date="2026-06-18")
    for tag in report.get("classifications", []):
        assert tag in GUEST_SWITCH_SLA_CLASSIFICATIONS
    # GUEST_COLD_START_UX_GAP_FIXED was dropped from this assertion here (/console cutover,
    # operator directive 2026-09-14): it requires legacy static/index.html's
    # dr-switch-state-chip / "GUEST DATA WARMING" markers, which have no equivalent in the new
    # console (grepped, zero matches) -- a real, if narrow, gap: nothing in the new console
    # today visibly distinguishes a guest ticker's cold-start warming state from a stuck load.
    assert "LIVE_GUEST_SLA_NOT_PROVEN" in report["classifications"]


# REALITY-RECONCILIATION (2026-09-18): the card-trust-gate tests that used to live here
# (test_analytics_stale_suppresses_engine_tradeable_setup and ~10 siblings, plus
# test_wrong_ticker_render_coherence_guard_blocks_before_card_paint's card-trust half) were
# retired along with tools/run_universal_card_fidelity_runtime.py -- see this file's own
# module docstring for why. render_coherence_guard's own coverage (the wrong-ticker/stale-
# generation tests above) is untouched and already proves the guard-blocks-before-paint
# property on its own, without the retired card-trust half.


# ── TERRAIN COMMAND DECK — layout contract ──────────────────────────────────
# Caught by Cursor's audit 2026-07-20: `grid-template-rows: minmax(0,1fr) minmax(0,auto)`
# collapsed the row-2 context tiles to ~40px — header visible, every value clipped.
# `.tv-z` carries `overflow:auto`, whose min-content contribution is zero, so a
# content-sized row resolves to nothing. The page then reports "no scroll" while the
# content is simply cut off, which reads as fitted when it is truncated.
#
# These assert the CONTRACT (row 2 is explicitly sized), not the pixel outcome, which
# only a browser can measure.







# ── TERRAIN v2 — NET GEX chip, pill tooltips, KDS/HVP/LVP (operator 2026-07-21:
# "insert the gamma exposure whether it is positive or negative … tooltips at the
# pills") ────────────────────────────────────────────────────────────────────











