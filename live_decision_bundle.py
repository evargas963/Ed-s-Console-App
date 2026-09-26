"""
Issue 20 / 23 — coherent live decision bundle metadata and tick-trigger rules.


All decision-critical fields in ms_dict must share one generation stamp per full recompute.
No partial tick patches may advance spot/order_flow without bumping that generation.


Tick triggers schedule a full _fetch_state (never partial ms_dict patches). Structural
comparisons use stream spot + cached levels from the last bundle so vwap_side, nearest
wall choice, distance buckets, and session boundaries cannot drift across generations.
"""
from __future__ import annotations
import logging
import threading
import time
log = logging.getLogger(__name__)
from typing import Optional




_lock = threading.Lock()
_next_generation_id: int = 0




def stamp_decision_bundle(ms_dict: dict, *, route: str = "unknown") -> dict:
    """
    Assign immutable decision_id, monotonic decision_generation_id, release_id, and timestamps.
    Keys decision_id, decision_generation_id, decision_timestamp_utc, release_id are present
    on success paths. Values are None when signals_engine_failed or release unavailable.
    """
    if ms_dict.get("signals_engine_failed"):
        ms_dict["decision_tick_kind"] = "signals_engine_error"
        ms_dict["decision_generation_skipped"] = True
        ms_dict["decision_id"] = None
        ms_dict["decision_generation_id"] = None
        ms_dict["decision_timestamp_utc"] = None
        ms_dict["release_id"] = None
        ms_dict["decision_route"] = route
        return ms_dict
    from trade_impacting_gate import apply_trade_impacting_gate
    gate = apply_trade_impacting_gate(ms_dict, route=route)
    if gate.quarantined or not gate.production_emission_allowed:
        ms_dict["decision_tick_kind"] = "market_quarantine"
        ms_dict["decision_generation_skipped"] = True
        ms_dict["decision_id"] = None
        ms_dict["decision_generation_id"] = None
        ms_dict["decision_timestamp_utc"] = None
        ms_dict["release_id"] = None
        ms_dict["decision_route"] = route
        ms_dict["decision_gate_blocked"] = True
        ms_dict["decision_gate_reasons"] = gate.reasons
        log.warning(
            "stamp_decision_bundle: gate blocked route=%s class=%s reasons=%s",
            route,
            gate.route_class,
            gate.reasons,
        )
        return ms_dict
    from release_object import get_current_release, validate_release_for_emission
    release = get_current_release(required=False)
    ok, reason = validate_release_for_emission(release)
    if not ok:
        ms_dict["decision_tick_kind"] = "release_unavailable"
        ms_dict["decision_generation_skipped"] = True
        ms_dict["decision_id"] = None
        ms_dict["decision_generation_id"] = None
        ms_dict["decision_timestamp_utc"] = None
        ms_dict["release_id"] = None
        ms_dict["release_unavailable_reason"] = reason
        ms_dict["decision_route"] = route
        log.warning("stamp_decision_bundle: release gate blocked route=%s reason=%s", route, reason)
        return ms_dict
    from decision_record import new_decision_id
    global _next_generation_id
    with _lock:
        _next_generation_id += 1
        gid = _next_generation_id
    # execution_identity_v1: the identity anchor may have generated the
    # decision_id earlier in the same cycle (before the model-derived snapshot
    # insert). One cycle = one decision_id — never regenerate over it.
    ms_dict["decision_id"] = ms_dict.get("decision_id") or new_decision_id()
    ms_dict["decision_generation_id"] = int(gid)
    ms_dict["decision_timestamp_utc"] = float(time.time())
    ms_dict["decision_tick_kind"] = "live"
    ms_dict["decision_generation_skipped"] = False
    ms_dict["release_id"] = release["release_id"]
    ms_dict["release_object"] = release
    ms_dict["decision_route"] = route
    return ms_dict


def persist_stamped_decision(ms_dict: dict, *, route: str, db_path) -> Optional[str]:
    """Persist immutable decision record after stamp_decision_bundle (I-31)."""
    if ms_dict.get("decision_generation_skipped") or not ms_dict.get("decision_id"):
        return None
    if ms_dict.get("decision_gate_blocked"):
        return None
    from trade_impacting_gate import classify_route, production_emission_allowed
    if not production_emission_allowed(ms_dict, route=route) or classify_route(route) != "production":
        return None
    quarantine = ms_dict.get("market_data_quarantine") or {}
    if isinstance(quarantine, dict) and quarantine.get("active"):
        return None
    release = ms_dict.get("release_object")
    if not isinstance(release, dict):
        from release_object import get_current_release
        release = get_current_release(required=False)
    if not release:
        return None
    from decision_record import persist_production_decision
    return persist_production_decision(
        ms_dict,
        route=route,
        release=release,
        db_path=db_path,
        execution_identity_sha256=ms_dict.get("execution_identity_sha256"),
    )















