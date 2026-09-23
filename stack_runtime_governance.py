"""Stack runtime/governance/signal-chain UI attachment (server.py decomposition,
twenty-eighth slice, RC-REHAB-1, 2026-09-23).

_attach_stack_runtime_and_governance moves here verbatim, along with the private
_TRADER_UI_PRODUCT_HORIZONS constant -- confirmed the only reader anywhere in
server.py before moving. Not a _fetch_state phase (no server_state_ prefix): it's
called from two sites inside _fetch_state's own body (both stay in server.py,
calling the re-exported name), and has no external caller.

Small, UI-oriented bundle for decision surfaces (not a second truth) -- see the
function's own docstring: stack_runtime (fusion active, MC participation, coarse
stack mode), stack_governance (architecture competition state from
models/arch_state.json), and signal_chain (per-stage health bar).

MONKEYPATCH/RUNTIME-STATE NOTE: APP_DIR (8 other occurrences in server.py) stays
in server.py, reached via the established lazy `import server` pattern.
governed_stack_contract.classify_stack_health and fusion_contract.
is_ms_dict_fusion_authoritative were already lazily imported inline inside the
function body in the original code and stay that way, unchanged.
ticker_storage_key (instrument_identity.py) is re-imported here directly from
its own module -- not server.py-specific logic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key
from ml_horizon import PRIMARY_DECISION_HORIZONS

# RC-REHAB-1: moved with _attach_stack_runtime_and_governance -- confirmed the only
# reader anywhere in server.py before moving.
_TRADER_UI_PRODUCT_HORIZONS = frozenset(PRIMARY_DECISION_HORIZONS)


def _attach_stack_runtime_and_governance(ms_dict: dict, *, ticker: str) -> None:
    """
    Small, UI-oriented bundle for decision surfaces (not a second truth).

    - stack_runtime: fusion active, MC participation, coarse stack mode (FULL/INVALID)
    - stack_governance: architecture competition state from models/arch_state.json (when present)
    """
    import server as _srv

    # ONE producer for stack health. The former `except Exception:` shadow re-implemented
    # classify_stack_health here — a FOURTH code path answering the same question, silently
    # swapped in on an import failure, and carrying the very substitution the contract forbids
    # (`team_ok = n_ml_layers_available >= 3 and fusion_available`, a fusion-AVAILABILITY predicate
    # standing in for directional AUTHORIZATION). A hand-maintained copy cannot be kept honest, so
    # the import is now unguarded: if the contract module cannot load, that must surface.
    from governed_stack_contract import classify_stack_health

    # STACK-WIRE-4-CAND-MS-DICT-ADOPTION: tradability gate, not bare .available flag.
    # fusion_available=True + canonical_provenance="canonical_forecast_missing" is a
    # non-tradable split-brain state — surface it as fusion_active=False / stack_mode=INVALID.
    from fusion_contract import is_ms_dict_fusion_authoritative
    fusion_ok = is_ms_dict_fusion_authoritative(ms_dict)
    mc_ok = bool(ms_dict.get("mc_available"))
    xgb_ok = bool(ms_dict.get("xgb_available"))
    lstm_ok = bool(ms_dict.get("lstm_available"))
    trans_ok = bool(ms_dict.get("transformer_available"))
    n_ml_layers = 0
    for k in ("xgb_available", "lstm_available", "transformer_available"):
        if ms_dict.get(k):
            n_ml_layers += 1

    # DIRECTIONAL AUTHORIZATION IS TRANSPORTED, NOT RECOMPUTED.
    # This used to rebuild layer namespaces from ms_dict and call
    # unified_stack_team_can_authorize(..., stack_probs=None) — a SECOND authority answering a
    # structurally different question (passing stack_probs=None disabled a branch the engine uses)
    # and then overwriting the engine's own field with its answer. Worse, the reconstructed layers
    # reported available=True with all three probs None whenever ml_layer_probs was absent, so the
    # verdict depended on payload serialization completeness rather than on what the stack did.
    # The engine computes it once, where composition and provenance are known, and stamps it on the
    # payload; here we only read it.
    _authorized = ms_dict.get("stack_directional_authorized")
    team_ok = bool(_authorized) if _authorized is not None else False  # caps-ok: "absent" and "present" are both preserved -- the absent case is captured separately in team_reason below ("authorization_absent_from_payload"), so collapsing to False here never hides the distinction, it's the correct default for "not authorized"
    team_reason = ms_dict.get("stack_directional_authorization_reason") or (
        "authorization_absent_from_payload" if _authorized is None else "")
    ms_dict["unified_stack_team_ok"] = team_ok
    ms_dict["unified_stack_team_reason"] = team_reason

    cm = ms_dict.get("fusion_contributing_models")
    if not isinstance(cm, list) or not cm:
        cm = []
        fpc = ms_dict.get("fusion_policy_snapshot_cols")
        if isinstance(fpc, dict):
            seen: set[str] = set()
            for hz in sorted(_TRADER_UI_PRODUCT_HORIZONS):
                raw = fpc.get(f"fused_contributing_models_{hz}")
                if not isinstance(raw, str) or not raw.strip():
                    continue
                try:
                    parsed = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(parsed, list):
                    continue
                for item in parsed:
                    s = str(item).strip()
                    if not s or s in seen:
                        continue
                    seen.add(s)
                    cm.append(s)

    ms_dict["stack_runtime"] = {
        "fusion_active": fusion_ok,
        "mc_participated": mc_ok,
        "n_ml_layers_live": int(n_ml_layers),
        "unified_stack_team_ok": bool(team_ok),
        "stack_mode": classify_stack_health(
            fusion_available=fusion_ok,
            mc_available=mc_ok,
            n_ml_layers_available=n_ml_layers,
            unified_stack_team_ok=bool(team_ok),
        ),
        "contributing_models": cm,
    }

    gov: dict[str, Any] = {"available": False}
    arch_ent: dict[str, Any] | None = None
    try:
        arch_path = Path(_srv.APP_DIR) / "models" / "arch_state.json"
        if arch_path.exists():
            arch = json.loads(arch_path.read_text(encoding="utf-8"))
            ent = arch.get(ticker_storage_key(ticker)) if isinstance(arch, dict) else None  # RC-345/F25: reader key == canonical writer key
            if isinstance(ent, dict):
                arch_ent = ent
                active = str(ent.get("active_architecture") or "").strip().lower()
                promoted = bool(ent.get("promoted"))
                mode = "promoted" if promoted else ("challenger" if active == "cascade" else "baseline")
                gov = {
                    "available": True,
                    "active_architecture": active or None,
                    "promoted": promoted,
                    "promotion_reason": ent.get("promotion_reason"),
                    "authority_mode": mode,
                    # RC-85: the `or ent.get("signal_chain_authoritative")` fallback is REMOVED.
                    # Nothing in this repo has ever written that key and the live payload does
                    # not carry it, so the branch could never be taken — it advertised a second
                    # source that does not exist.
                    "authoritative_stage": ent.get("authoritative_stage"),
                }
    except Exception:
        gov = {"available": False, "error": "arch_state_read_failed"}
    ms_dict["stack_governance"] = gov

    # Signal chain bar (UI): per-stage health + optional authoritative stage (driven by runtime + arch overrides).
    def _tri(active: bool, degraded: bool = False) -> str:
        if degraded:
            return "degraded"
        return "active" if active else "off"

    sm = str(ms_dict.get("stack_runtime", {}).get("stack_mode") or "").upper()  # caps-ok: both defaults are dead-code-safe, not masking -- ms_dict["stack_runtime"]["stack_mode"] was set unconditionally a few lines above in this same function, from the stack-health classifier call above, whose return type is `str`, never None
    spot_ok = ms_dict.get("spot") is not None
    # RC-85: `micro_5m_headline` dropped from this chain — never written anywhere in the repo
    # and absent from the live /api/state payload, so it could only ever contribute False.
    rules_ok = bool(
        ms_dict.get("rules_headline")
        or ms_dict.get("rules_conviction")
    )
    valp = ms_dict.get("validation_passed")
    et_raw = ms_dict.get("entry_display_text")
    et_ok = bool(
        et_raw
        and str(et_raw).strip()
        and str(et_raw).strip().lower() not in ("no valid setup", "—", "-")
    )

    feat_st = "off" if sm == "INVALID" else ("degraded" if sm in ("DEGRADED", "PARTIAL") or not spot_ok else "active")
    rules_st = "degraded" if not rules_ok else "active"
    mc_deg = (not mc_ok) and fusion_ok

    if valp is True:
        pol_st = "active"
    elif valp is False:
        pol_st = "degraded"
    else:
        pol_st = "off"

    sc_status = {
        "features": feat_st,
        "rules": rules_st,
        "xgb": _tri(xgb_ok),
        "lstm": _tri(lstm_ok),
        "trans": _tri(trans_ok),
        "mc": _tri(mc_ok, mc_deg),
        "fusion": _tri(fusion_ok),
        "policy": pol_st,
        "trade": _tri(et_ok),
    }

    auth_stage: str | None = None
    try:
        if isinstance(arch_ent, dict):
            raw_a = arch_ent.get("authoritative_stage")   # RC-85: dead alias fallback removed
            if isinstance(raw_a, str) and raw_a.strip():
                a = raw_a.strip().lower()
                alias = {
                    "transformer": "trans",
                    "trade_plan": "trade",
                    "plan": "trade",
                }
                a = alias.get(a, a)
                if a in sc_status:
                    auth_stage = a
    except Exception:
        auth_stage = None

    if auth_stage is None:
        prov = str(ms_dict.get("canonical_provenance") or "")
        pl = prov.lower()
        if pl and "fusion_unavailable" not in pl:
            if "bayesian" in pl or pl.endswith("bayesian_fusion"):
                auth_stage = "fusion"
            elif "xgb" in pl or "tabular" in pl:
                auth_stage = "xgb"
            elif "lstm" in pl:
                auth_stage = "lstm"
            elif "transformer" in pl:
                auth_stage = "trans"
            elif "rules" in pl:
                auth_stage = "rules"
            elif "monte" in pl or "mc" in pl or "carlo" in pl:
                auth_stage = "mc"
            elif "policy" in pl:
                auth_stage = "policy"
            elif "feature" in pl:
                auth_stage = "features"
            elif "trade" in pl or "entry" in pl:
                auth_stage = "trade"

    ms_dict["signal_chain"] = {
        "status": sc_status,
        "authoritative": auth_stage,
    }
