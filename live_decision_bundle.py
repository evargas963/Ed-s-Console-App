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
import os
import threading
import time

log = logging.getLogger(__name__)

from datetime import datetime, timezone

from typing import Any, Optional, Tuple


from canonical_distances import canonical_nearest_distances


_lock = threading.Lock()

_next_generation_id: int = 0



from time_et import ET as _ET

# STACK-WIRE-6b FIND-WIRE6-7: tick-refresh thresholds for spot drift (env-overridable).
TICK_REFRESH_SPOT_PCT_DEFAULT: float = 0.0003  # 3 bp percent move triggers full _fetch_state refresh
TICK_REFRESH_SPOT_ABS_DEFAULT: float = 0.05    # nickel absolute move triggers full _fetch_state refresh





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





def _float_or_none(x: Any) -> Optional[float]:
    from numeric_contract import float_finite_or_none

    return float_finite_or_none(x)





def _key_levels_from_ms_dict(ms_dict: dict) -> list[tuple[float, str]]:

    """

    Same geometry as market_state.build_market_state nearest-wall loop (kl_* + vwap).

    Order matches iteration order there.

    """

    from math_levels import displayable_trusted_level

    _conf = ms_dict.get("kl_gamma_flip_confidence") or ms_dict.get("confidence")

    pairs = [

        (displayable_trusted_level(ms_dict.get("kl_call_gamma_wall"), _conf), "Call g-Wall"),

        (displayable_trusted_level(ms_dict.get("kl_put_gamma_wall"), _conf), "Put g-Wall"),

        (displayable_trusted_level(ms_dict.get("kl_hvl"), _conf), "Net Γ peak"),  # RC-134: net book, not total-gamma HVL/pin

        (displayable_trusted_level(ms_dict.get("kl_max_pain"), _conf), "Max Pain"),

        (ms_dict.get("kl_gamma_inflection"), "g-Inflection"),

        (ms_dict.get("kl_call_delta_wall"), "Call d-Wall"),

        (ms_dict.get("kl_put_delta_wall"), "Put d-Wall"),

        (ms_dict.get("kl_delta_inflection"), "D-Inflection"),

        (ms_dict.get("kl_call_oi_wall"), "Call OI Wall"),

        (ms_dict.get("kl_put_oi_wall"), "Put OI Wall"),

        (ms_dict.get("vwap"), "VWAP"),

    ]

    out: list[tuple[float, str]] = []

    for raw, label in pairs:

        v = _float_or_none(raw)

        if v is not None:

            out.append((v, label))

    return out





def recompute_nearest_struct_at_spot(

    spot_f: float,

    ms_dict: dict,

) -> Tuple[

    Optional[float],

    Optional[float],

    Optional[str],

    Optional[str],

]:

    """Mirror market_state nearest above/below selection at an alternate spot (read-only)."""

    nearest_above_name = nearest_above_val = None

    nearest_below_name = nearest_below_val = None

    for lv, ln in _key_levels_from_ms_dict(ms_dict):

        if lv > spot_f:

            if nearest_above_val is None or lv < nearest_above_val:

                nearest_above_val = lv

                nearest_above_name = ln

        elif lv < spot_f:

            if nearest_below_val is None or lv > nearest_below_val:

                nearest_below_val = lv

                nearest_below_name = ln

    nearest_above_dist, nearest_below_dist = canonical_nearest_distances(
        spot_f, nearest_above_val, nearest_below_val
    )

    return nearest_above_dist, nearest_below_dist, nearest_above_name, nearest_below_name





def _session_bucket_et(hour: int, minute: int) -> str:

    from math_volatility import session_bucket as _sb



    return _sb(int(hour), int(minute))





def _session_bucket_from_utc_ts(ts: float) -> str:

    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(_ET)

    return _session_bucket_et(dt.hour, dt.minute)





def _live_session_label() -> Optional[str]:
    """Fetch the live session label.

    Propagates exceptions to the caller — `tick_triggers_coherent_refresh`'s
    outer try/except handles failures uniformly with every other check in
    that function (warning log + refresh). Previously this wrapper swallowed
    exceptions and returned None, causing the caller to silently skip the
    session-label check on `market_context` outages (drift opposite to the
    file's fail-closed-toward-refresh discipline).
    """
    from market_context import _derive_session

    return str(_derive_session())





def tick_triggers_coherent_refresh(

    ms_dict: dict,

    stream_spot: Optional[float],

    stream_of_regime: Optional[str],

    *,

    now_ts: Optional[float] = None,

) -> bool:

    """

    True when stream time/structure implies the last coherent bundle may be stale.

    Full recompute is _fetch_state; this never mutates ms_dict.

    """

    if not ms_dict or not isinstance(ms_dict, dict):

        return False

    if ms_dict.get("state_error"):

        return False



    t_now = float(now_ts if now_ts is not None else time.time())



    # ── Zone integrity: bias + net_delta must agree with stored zone (canonical derive_zone)

    try:

        from market_state import derive_zone



        _nd = ms_dict.get("net_delta")

        _ndf = _float_or_none(_nd)

        _ez = derive_zone(ms_dict.get("bias_signal"), _ndf)

        if ms_dict.get("zone") is not None and _ez != ms_dict.get("zone"):

            return True

    except Exception:
        log.warning("tick_triggers: zone integrity check failed — scheduling refresh", exc_info=True)
        return True

    # ── Market session label (RTH / Pre / After / Closed) — ET clock boundary

    try:

        _live_lbl = _live_session_label()

        if _live_lbl is not None:

            cached_lbl = ms_dict.get("session_label")

            if cached_lbl and str(cached_lbl) != _live_lbl:

                return True

    except Exception:
        log.warning("tick_triggers: session label check failed — scheduling refresh", exc_info=True)
        return True

    # ── Intraday session_bucket vs bucket at decision stamp (signals time-of-day regime)

    try:

        dec_ts = ms_dict.get("decision_timestamp_utc")

        if dec_ts is not None:

            b_now = _session_bucket_from_utc_ts(t_now)

            b_dec = _session_bucket_from_utc_ts(float(dec_ts))

            if b_now != b_dec:

                return True

    except Exception:
        log.warning("tick_triggers: session_bucket check failed — scheduling refresh", exc_info=True)
        return True

    pct_thr = float(os.environ.get("ED_TICK_REFRESH_SPOT_PCT", str(TICK_REFRESH_SPOT_PCT_DEFAULT)))

    abs_thr = float(os.environ.get("ED_TICK_REFRESH_SPOT_ABS", str(TICK_REFRESH_SPOT_ABS_DEFAULT)))



    ns: Optional[float] = None

    if stream_spot is not None:

        try:

            _s = float(stream_spot)

            ns = _s if _s > 0 else None

        except (TypeError, ValueError):

            ns = None



    old_spot = ms_dict.get("spot")

    if ns is not None:

        # Spot move vs bundled spot (existing thresholds)

        if old_spot is None:

            return True

        try:

            os_ = float(old_spot)

        except (TypeError, ValueError):

            return True

        if os_ > 0 and abs(ns - os_) / os_ >= pct_thr:

            return True

        if abs(ns - os_) >= abs_thr:

            return True



        # VWAP side at stream spot vs cached vwap_side (same rule as derive_vwap_side)

        try:

            from math_snapshot_derive import derive_vwap_side



            vwap = _float_or_none(ms_dict.get("vwap"))

            if vwap is not None:

                new_side = derive_vwap_side(ns, vwap)

                old_side = ms_dict.get("vwap_side")

                if new_side is not None and old_side is not None and new_side != old_side:

                    return True

        except Exception:
            log.warning("tick_triggers: vwap_side check failed — scheduling refresh", exc_info=True)
            return True

        # Nearest wall identity + empirical distance buckets (tier / similar-set drivers)

        try:

            from math_probabilities import dist_bucket



            na_d, nb_d, na_nm, nb_nm = recompute_nearest_struct_at_spot(ns, ms_dict)

            if na_nm != ms_dict.get("nearest_above_name"):

                return True

            if nb_nm != ms_dict.get("nearest_below_name"):

                return True

            ob_a = dist_bucket(_float_or_none(ms_dict.get("nearest_above_dist")))

            ob_b = dist_bucket(_float_or_none(ms_dict.get("nearest_below_dist")))

            nb_a = dist_bucket(na_d)

            nb_b = dist_bucket(nb_d)

            if nb_a != ob_a or nb_b != ob_b:

                return True

        except Exception:
            log.warning("tick_triggers: nearest-wall bucket check failed — scheduling refresh", exc_info=True)
            return True

    old_r = ms_dict.get("order_flow_regime")

    if stream_of_regime is not None and old_r is not None and stream_of_regime != old_r:

        return True



    return False


