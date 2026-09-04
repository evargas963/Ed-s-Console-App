"""Shared A2 lifecycle health helpers."""

from __future__ import annotations

from typing import Any


def resolve_a2_option_right(ms_dict: dict, winner: dict) -> str:
    """Resolve CALL/PUT with Schwab-canonical ``putCall`` as the primary source.

    The selected ``chain_row.putCall`` leaf is the Schwab-native option-side
    field and is read first. App-side aliases
    (``ms.call_option_right`` / ``ms.rec_side`` / ``winner.side``) are legacy
    fallbacks used only when the chain row does not expose ``putCall``.
    Per SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1 OP-011 /
    SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_V1 CSV-R8.
    """
    right, _ = resolve_a2_option_right_with_source(ms_dict, winner)
    return right


def resolve_a2_option_right_with_source(
    ms_dict: dict, winner: dict
) -> tuple[str, str | None]:
    """Same precedence and first-truthy semantics as ``resolve_a2_option_right``,
    but also return the provenance leaf name so callers can label the surface.

    Behaviour matches the original ``or``-chain: the first non-empty candidate
    wins regardless of validity; if that value does not normalize to CALL/PUT
    the result is ``"NONE"`` (no silent skip to the next alias). This preserves
    misconfiguration visibility — e.g. ``ms.call_option_right == "C"`` must
    still fail closed, not silently pass through to ``winner.side``.

    Returns
    -------
    tuple[str, str | None]
        (CALL/PUT/NONE, source_leaf_name) where source_leaf_name is one of
        ``"chains.*.putCall"`` (Schwab-primary), ``"ms.call_option_right"``,
        ``"ms.rec_side"``, ``"winner.side"``, or ``None`` when none of those
        candidates carried a truthy value.
    """
    try:
        ms = ms_dict if isinstance(ms_dict, dict) else {}
        win = winner if isinstance(winner, dict) else {}
        chain_row = win.get("chain_row") if isinstance(win.get("chain_row"), dict) else {}
        candidates = (
            (chain_row.get("putCall"), "chains.*.putCall"),
            (ms.get("call_option_right"), "ms.call_option_right"),
            (ms.get("rec_side"), "ms.rec_side"),
            (win.get("side"), "winner.side"),
        )
        for raw, source in candidates:
            if raw:
                right = str(raw).upper().strip()
                return (right if right in ("CALL", "PUT") else "NONE"), source
        return "NONE", None
    except Exception:
        return "NONE", None


def select_a2_pin_risk_audit_row(
    *,
    proof: dict,
    winner: dict,
    strike: float | None,
    option_right: str,
) -> dict:
    """Select the audited option-row context used for A2 pin-risk detection."""
    try:
        p = proof if isinstance(proof, dict) else {}
        win = winner if isinstance(winner, dict) else {}
        if strike is None:
            return dict(win)
        side = str(option_right or "").upper()
        candidates = []
        for key in ("chain_rows_scored", "ranked_candidates_top5"):
            rows = p.get(key)
            if isinstance(rows, list):
                candidates.extend(row for row in rows if isinstance(row, dict))
        for row in candidates:
            row_strike = _num(row.get("strike"))
            row_side = str(row.get("side") or "").upper()
            if row_strike is not None and abs(row_strike - strike) < 0.01 and (not side or row_side == side):
                return row
        return dict(win)
    except Exception:
        return dict(winner) if isinstance(winner, dict) else {}


def derive_a2_pin_risk_health(*, selected_audit: dict, strike: float | None) -> dict:
    """Return the A2 pin-risk health payload. Never raises in production."""
    try:
        audit = selected_audit if isinstance(selected_audit, dict) else {}
        detail = audit.get("wall_contribution_detail")
        if not isinstance(detail, dict):
            detail = {}
        proximity = detail.get("proximity_detail")
        if not isinstance(proximity, list):
            proximity = []

        nearest_wall = None
        if strike is not None:
            for item in proximity:
                if not isinstance(item, dict):
                    continue
                wall_strike = _num(item.get("strike"))
                if wall_strike is None:
                    continue
                distance = abs(wall_strike - strike)
                candidate = {
                    "level": item.get("level"),
                    "strike": wall_strike,
                    "distance": round(distance, 4),
                    "contrib": _num(item.get("contrib")),
                }
                if nearest_wall is None or distance < nearest_wall["distance"]:
                    nearest_wall = candidate

        wall_score = _num(audit.get("wall_score_component"))
        wall_proximity = _num(audit.get("wall_proximity_component"))
        wall_bias = _num(audit.get("wall_bias_component"))
        reasons: list[str] = []
        status = "not_detected"

        if nearest_wall and nearest_wall["distance"] <= 1.0:
            status = "elevated"
            reasons.append("selected_strike_near_gamma_or_oi_wall")
        elif wall_score is not None and wall_score >= 1.0:
            status = "watch"
            reasons.append("material_wall_contribution")
        elif wall_proximity is not None and wall_proximity >= 0.75:
            status = "watch"
            reasons.append("material_wall_proximity")

        return {
            "status": status,
            "selected_strike": strike,
            "nearest_wall": nearest_wall,
            "wall_score_component": wall_score,
            "wall_proximity_component": wall_proximity,
            "wall_bias_component": wall_bias,
            "bias_notes": detail.get("bias_notes") if isinstance(detail.get("bias_notes"), list) else [],
            "reasons": reasons,
        }
    except Exception:
        return _empty_pin_risk_health(strike)


def build_a2_pin_risk_event_source(*, pin_risk_health: dict, session_type: str | None) -> dict | None:
    """Return a sidecar event_sources entry, or None when no event should emit."""
    try:
        health = pin_risk_health if isinstance(pin_risk_health, dict) else {}
        status = health.get("status")
        if status not in ("watch", "elevated"):
            return None
        selected_strike = health.get("selected_strike")
        nearest_wall = health.get("nearest_wall")
        if selected_strike is None or not isinstance(nearest_wall, dict):
            return None
        if session_type in ("full_closure", "out_of_session"):
            return None
        emitted_session_type = session_type if session_type in ("normal_rth", "early_close") else "calendar_unavailable"
        return {
            "event_type": "pin_risk",
            "status": status,
            "reasons": list(health.get("reasons")) if isinstance(health.get("reasons"), list) else [],
            "nearest_wall": nearest_wall,
            "wall_score_component": _num(health.get("wall_score_component")),
            "wall_proximity_component": _num(health.get("wall_proximity_component")),
            "selected_strike": _num(selected_strike),
            "session_type": emitted_session_type,
            "source_classification": "derived_because_schwab_does_not_provide",
        }
    except Exception:
        return None


def _empty_pin_risk_health(strike: float | None) -> dict:
    return {
        "status": "not_detected",
        "selected_strike": strike,
        "nearest_wall": None,
        "wall_score_component": None,
        "wall_proximity_component": None,
        "wall_bias_component": None,
        "bias_notes": [],
        "reasons": [],
    }


def _num(value: Any) -> float | None:
    from app.domain.numeric_contract import float_finite_or_none

    return float_finite_or_none(value)
