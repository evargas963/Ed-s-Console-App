#!/usr/bin/env python3
"""
Universal card fidelity runtime harness — read-only, ticker-agnostic, live API + browser DOM.

Default institutional proof set: SPY, QQQ, IWM (base seeds) + NVDA (guest seed).
Same validation path for every ticker; expected values derived from each ticker's live payload.

Usage:
  python tools/run_universal_card_fidelity_runtime.py
  python tools/run_universal_card_fidelity_runtime.py --tickers SPY,QQQ,IWM,NVDA \\
      --stable-reads 3 --require-browser-dom --require-live-transport
  python tools/run_universal_card_fidelity_runtime.py --tickers AAPL,MSFT

Reports (untracked): reports/ui_transport/universal_card_fidelity_<date>.json|.md
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scheduler_user_tickers import TRAINING_ANCHOR_TICKERS, is_training_anchor_ticker

# Base coverage seeds — not universality by themselves; guest required for institutional proof.
DEFAULT_BASE_TICKERS: tuple[str, ...] = TRAINING_ANCHOR_TICKERS
DEFAULT_GUEST_TICKERS: tuple[str, ...] = ("NVDA",)
DEFAULT_INSTITUTIONAL_TICKERS: tuple[str, ...] = DEFAULT_BASE_TICKERS + DEFAULT_GUEST_TICKERS

HORIZON_SLUGS: tuple[str, ...] = ("1c", "5c", "15c", "60c")

ORPHAN_FIELD_NAMES: tuple[str, ...] = (
    "pred_headline",
    "reversal_risk",
    "reversal_label",
    "call_headline",
    "call_signal",
    "call_state",
    "call_forecast_state",
    "z_score",
    "expected_move",
)

EM_BOUND_FIELDS: tuple[str, ...] = (
    "em_straddle_upper",
    "em_straddle_lower",
    "kl_em_upper",
    "kl_em_lower",
)

OPERATOR_DECISION_ORPHANS: frozenset[str] = frozenset(
    {
        "call_state",
        "call_forecast_state",
    }
)

# Design approved @ EXPLAINABILITY_AND_OPERATOR_DECISION_SURFACE_V1 — DOM not wired yet.
DESIGN_APPROVED_PENDING_EXPLANATION_RAIL: str = "DESIGN_APPROVED_PENDING_EXPLANATION_RAIL"
DESIGN_APPROVED_PENDING_RISK_RAIL: str = "DESIGN_APPROVED_PENDING_RISK_RAIL"

PENDING_EXPLANATION_RAIL_FIELDS: frozenset[str] = frozenset({"pred_headline"})
PENDING_RISK_RAIL_PAIRED_FIELDS: frozenset[str] = frozenset({"reversal_risk", "reversal_label"})

DESIGN_APPROVED_PENDING_UI_FIELDS: frozenset[str] = (
    PENDING_EXPLANATION_RAIL_FIELDS | PENDING_RISK_RAIL_PAIRED_FIELDS
)

ORPHAN_PAYLOAD_HANDLING_OVERALL_STATUS: str = "NOT_PROVEN"

DISPLAY_TRUST_GATE: str = "analyticsCardTrustGate"

CARD_TRUST_REQUIRED_HORIZONS: tuple[str, ...] = HORIZON_SLUGS
CARD_TRUST_REQUIRED_HORIZON_COUNT: int = 4

# HARNESS_CLASSIFIER_OPERATOR_MIRROR_ALIGNMENT_V1 — scoring contract note:
# This harness scores against the OPERATOR MIRROR / S2B card-trust contract
# (resolve_card_trust_gate below, mirroring static/index.html
# resolveCardTrustGate): when operator_card_* mirror fields are present on the
# payload they are the authority, including quote-age/operator veto codes such
# as quote_newer_than_signal. Analytics-only trust (analytics_card_trust_gate)
# is insufficient when those fields exist and remains ONLY as an explicitly
# labeled legacy fallback for artifacts that predate the mirrors. Ticker
# identity must never affect expected card state — the same scoring path runs
# for every ticker (TICKER_AGNOSTIC_CONSTRUCTION_REQUIRED).
#
# Trust-aware DOM parity / withhold statuses (mirror static/index.html contract).
PARITY_STATUS_PARITY: str = "PARITY"
PARITY_STATUS_DOM_MISMATCH: str = "DOM_MISMATCH"
PARITY_STATUS_TRUST_WITHHELD: str = "TRUST_WITHHELD"
PARITY_STATUS_STALE_WITHHELD: str = "STALE_WITHHELD"
PARITY_STATUS_PENDING_WITHHELD: str = "PENDING_WITHHELD"
PARITY_STATUS_DEGRADED_WITHHELD: str = "DEGRADED_WITHHELD"
PARITY_STATUS_TICKER_MISMATCH_WITHHELD: str = "TICKER_MISMATCH_WITHHELD"
PARITY_STATUS_MISSING_MHAP_WITHHELD: str = "MISSING_MHAP_WITHHELD"
# Operator-mirror veto on a FRESH bundle (e.g. quote_newer_than_signal): the UI
# withholds actionability while preserving values — UI-fidelity PASS, distinct
# from analytics staleness so RTH-freshness accounting stays honest.
PARITY_STATUS_QUOTE_VETO_WITHHELD: str = "QUOTE_VETO_WITHHELD"

SCORING_AUTHORITY_OPERATOR_MIRROR: str = "operator_mirror"
SCORING_AUTHORITY_LEGACY_DEGRADED: str = "legacy_analytics_gate_degraded"

UI_FIDELITY_PASS_PARITY_STATUSES: frozenset[str] = frozenset(
    {
        PARITY_STATUS_PARITY,
        PARITY_STATUS_TRUST_WITHHELD,
        PARITY_STATUS_STALE_WITHHELD,
        PARITY_STATUS_PENDING_WITHHELD,
        PARITY_STATUS_DEGRADED_WITHHELD,
        PARITY_STATUS_TICKER_MISMATCH_WITHHELD,
        PARITY_STATUS_MISSING_MHAP_WITHHELD,
        PARITY_STATUS_QUOTE_VETO_WITHHELD,
    }
)

# Acceptance semantics — harness classification only; does not close card fidelity / RTH / real-money.
TRUST_AWARE_ACCEPTANCE_SEMANTICS: dict[str, str] = {
    "trust_withheld_ui_fidelity": "PASS",
    "stale_withheld_non_rth_closure": "NOT_ADMISSIBLE",
    "stale_withheld_rth_freshness": "FAIL",
    "true_dom_mismatch": "FAIL",
    "card_fidelity_overall": "NOT_PROVEN",
    "universal_runtime_live_proof": "NOT_PROVEN",
    "real_money_readiness": "NOT_PROVEN",
    "rth_dom_parity_proof": "NOT_PROVEN_BY_THIS_CHANGE",
}

BACKEND_ONLY_ORPHAN_FIELDS: frozenset[str] = frozenset(
    {
        "call_headline",
    }
)

DOM_CARD_IDS: dict[str, str] = {
    "1c": "tf-signal-1c",
    "5c": "tf-signal-5c",
    "15c": "tf-signal-15c",
    "60c": "tf-signal-60c",
    "ALL": "tf-signal-consolidated",
    "PLAN": "tf-signal-plan",
}


def parse_ticker_list(raw: str) -> list[str]:
    parts = re.split(r"[\s,]+", (raw or "").strip())
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        t = p.strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def split_base_guest(tickers: list[str]) -> tuple[list[str], list[str]]:
    bases = [t for t in tickers if is_training_anchor_ticker(t)]
    guests = [t for t in tickers if not is_training_anchor_ticker(t)]
    return bases, guests


def norm_dir(call: Any) -> str:
    u = str(call or "").upper()
    if u == "LONG":
        return "LONG"
    if u == "SHORT":
        return "SHORT"
    if u == "UNAVAILABLE":
        return "UNAVAILABLE"
    if u in ("WAIT", "FLAT", "NEUTRAL"):
        return "FLAT"
    return "FLAT"


def parse_confidence_pct(conf: Any) -> Optional[int]:
    if conf is None:
        return None
    try:
        n = float(conf)
    except (TypeError, ValueError):
        return None
    if 0 <= n <= 1:
        return round(n * 100)
    return round(min(100, max(0, n)))


def analytics_card_trust_gate(
    payload: Optional[dict[str, Any]],
    *,
    active_ticker: Optional[str] = None,
    check_ticker: bool = True,
) -> dict[str, Any]:
    """Mirror analyticsCardTrustGate in static/index.html."""
    if payload is None or not isinstance(payload, dict):
        return {"trusted": False, "reason": "no_payload"}
    if check_ticker:
        incoming = str(payload.get("ticker") or "").strip().upper()
        active = str(active_ticker or "").strip().upper()
        if incoming and active and incoming != active:
            return {"trusted": False, "reason": "ticker_mismatch"}
    if payload.get("analytics_stale") is True:
        return {"trusted": False, "reason": "analytics_stale"}
    if payload.get("analytics_pending_shell") is True:
        return {"trusted": False, "reason": "pending_shell"}
    if payload.get("analytics_partial_tier_c") is True:
        return {"trusted": False, "reason": "partial_tier_c"}
    src = str(payload.get("_update_source") or "")
    if payload.get("analytics_refresh_in_progress") is True and src == "client_ticker_cache":
        return {"trusted": False, "reason": "cache_refresh_in_progress"}
    mhap = payload.get("mhap_rows")
    if not isinstance(mhap, list) or len(mhap) == 0:
        return {"trusted": False, "reason": "mhap_missing"}
    if len(mhap) < CARD_TRUST_REQUIRED_HORIZON_COUNT:
        return {"trusted": False, "reason": "mhap_incomplete"}
    for slug in CARD_TRUST_REQUIRED_HORIZONS:
        if not any(
            isinstance(r, dict) and str(r.get("horizon") or "").lower() == slug for r in mhap
        ):
            return {"trusted": False, "reason": f"mhap_horizon_missing_{slug}"}
    if payload.get("fusion_available") is False:
        return {"trusted": False, "reason": "fusion_unavailable"}
    si = payload.get("stack_integrity_v1")
    if isinstance(si, dict) and si.get("degraded") is True:
        return {"trusted": False, "reason": "stack_integrity_degraded"}
    rt = payload.get("stack_runtime") if isinstance(payload.get("stack_runtime"), dict) else {}
    if rt.get("signals_engine_failed") is True:
        return {"trusted": False, "reason": "signals_engine_failed"}
    if str(rt.get("stack_mode") or "").upper() == "INVALID":
        return {"trusted": False, "reason": "stack_invalid"}
    if payload.get("state_error"):
        return {"trusted": False, "reason": "state_error"}
    if payload.get("error") == "token_invalid":
        return {"trusted": False, "reason": "token_invalid"}
    return {"trusted": True, "reason": None}


def card_trust_operator_label(reason: Optional[str]) -> str:
    """Mirror cardTrustOperatorLabel in static/index.html (incl. operator veto codes)."""
    r = str(reason or "").lower()
    if r in ("analytics_stale", "cache_refresh_in_progress"):
        return "STALE"
    if r in ("pending_shell", "partial_tier_c", "mhap_missing"):
        return "PENDING"
    if r == "mhap_incomplete" or r.startswith("mhap_horizon_missing_"):
        return "WITHHELD"
    if r in (
        "fusion_unavailable",
        "stack_integrity_degraded",
        "signals_engine_failed",
        "stack_invalid",
    ):
        return "DEGRADED"
    if r in ("state_error", "token_invalid"):
        return "UNAVAILABLE"
    if r in ("quote_newer_than_signal", "quote_carried_forward"):
        return "STALE"
    if r == "revalidate_quarantine":
        return "WITHHELD"
    return "WITHHELD"


def has_operator_card_mirror_fields(payload: Optional[dict[str, Any]]) -> bool:
    """Mirror hasOperatorCardMirrorFields in static/index.html (S2B-1 mirrors present)."""
    return isinstance(payload, dict) and isinstance(payload.get("operator_card_actionable"), bool)


def resolve_card_trust_gate(
    payload: Optional[dict[str, Any]],
    *,
    active_ticker: Optional[str] = None,
    check_ticker: bool = True,
) -> dict[str, Any]:
    """Mirror resolveCardTrustGate in static/index.html — operator mirrors are the
    authority when present; otherwise the legacy analytics-only gate applies and is
    explicitly labeled as degraded scoring. Ticker-agnostic: expected state derives
    from payload fields only.
    """
    if has_operator_card_mirror_fields(payload):
        actionable = payload.get("operator_card_actionable") is True
        reason: Optional[str] = None
        if not actionable:
            oar = payload.get("operator_actionability_reason")
            codes = payload.get("operator_stale_reason_codes")
            if oar is not None and str(oar).strip() != "":
                reason = str(oar).strip()
            elif isinstance(codes, list) and codes:
                reason = str(codes[0])
            elif payload.get("operator_card_trust_state") is not None:
                reason = str(payload.get("operator_card_trust_state"))
            else:
                reason = "not_actionable"
        return {
            "trusted": actionable,
            "reason": reason,
            "authority": SCORING_AUTHORITY_OPERATOR_MIRROR,
            "trust_state": (
                str(payload.get("operator_card_trust_state"))
                if payload.get("operator_card_trust_state") is not None
                else None
            ),
            "stale_reason_codes": [
                str(c) for c in (payload.get("operator_stale_reason_codes") or [])
            ],
        }
    legacy = analytics_card_trust_gate(
        payload, active_ticker=active_ticker, check_ticker=check_ticker
    )
    return {
        "trusted": legacy["trusted"],
        "reason": legacy["reason"],
        "authority": SCORING_AUTHORITY_LEGACY_DEGRADED,
        "trust_state": None,
        "stale_reason_codes": [],
    }


def operator_mirror_withhold_label(trust: dict[str, Any]) -> str:
    """Mirror operatorMirrorWithholdLabel in static/index.html."""
    ts = str(trust.get("trust_state") or "").upper()
    if "STALE" in ts:
        return "STALE"
    if "PENDING" in ts:
        return "PENDING"
    if "DEGRADED" in ts:
        return "DEGRADED"
    if trust.get("reason"):
        return card_trust_operator_label(str(trust.get("reason")))
    return "WITHHELD"


def trust_reason_to_withheld_parity_status(reason: Optional[str]) -> str:
    """Map trust-gate reason → harness parity_status for correct withhold."""
    r = str(reason or "").lower()
    if r in ("analytics_stale", "cache_refresh_in_progress"):
        return PARITY_STATUS_STALE_WITHHELD
    if r in ("pending_shell",):
        return PARITY_STATUS_PENDING_WITHHELD
    if r == "partial_tier_c":
        return PARITY_STATUS_DEGRADED_WITHHELD
    if r == "ticker_mismatch":
        return PARITY_STATUS_TICKER_MISMATCH_WITHHELD
    if r in ("mhap_missing", "mhap_incomplete") or r.startswith("mhap_horizon_missing_"):
        return PARITY_STATUS_MISSING_MHAP_WITHHELD
    if r in (
        "fusion_unavailable",
        "stack_integrity_degraded",
        "signals_engine_failed",
        "stack_invalid",
    ):
        return PARITY_STATUS_DEGRADED_WITHHELD
    if r in (
        "quote_newer_than_signal",
        "quote_carried_forward",
        "quote_age_exceeded",
        "auth_degraded",
        "auth_fallback",
    ):
        return PARITY_STATUS_QUOTE_VETO_WITHHELD
    # missing_quote_ts and all unmapped operator codes take the default WITHHELD
    # path (label WITHHELD → expected PLAN "NO SETUP"), per the reason-code table —
    # the actionable boolean alone never decides expected card state.
    return PARITY_STATUS_TRUST_WITHHELD


def expected_plan_state_for_withheld_label(label: str) -> str:
    if label == "STALE":
        return "STALE"
    if label == "PENDING":
        return "PENDING"
    return "NO SETUP"


def dom_horizon_card_matches_withheld(card: dict[str, Any], label: str) -> bool:
    cls = str(card.get("class") or "")
    if "tf-state-dim" not in cls:
        return False
    dir_ok = str(card.get("dir") or "") == label
    pct = card.get("pct")
    if pct is None:
        return dir_ok
    return dir_ok and str(pct) == label


def is_rth_session_label(session_label: Any) -> bool:
    """Conservative session gate for stale-withheld RTH freshness semantics."""
    s = str(session_label or "").lower()
    if not s:
        return False
    if "after" in s or "closed" in s or "pre-market" in s or "pre market" in s:
        return False
    if "regular" in s or "rth" in s:
        return True
    return False


def parity_status_passes_ui_fidelity(status: str) -> bool:
    return status in UI_FIDELITY_PASS_PARITY_STATUSES


def engine_tradeable_setup(payload: dict[str, Any]) -> bool:
    if not analytics_card_trust_gate(payload, check_ticker=False)["trusted"]:
        return False
    bias = str(payload.get("final_bias") or "WAIT").upper()
    return bool(payload.get("final_tradeable")) and bias in ("LONG", "SHORT")


def expected_tf_state_from_call(call: Any) -> str:
    d = norm_dir(call)
    if d == "LONG":
        return "up"
    if d == "SHORT":
        return "down"
    return "dim"


def mhap_row_by_horizon(payload: dict[str, Any], slug: str) -> Optional[dict[str, Any]]:
    for row in payload.get("mhap_rows") or []:
        if isinstance(row, dict) and str(row.get("horizon") or "").lower() == slug:
            return row
    return None


def derive_horizon_parity(payload: dict[str, Any], slug: str) -> dict[str, Any]:
    row = mhap_row_by_horizon(payload, slug)
    if not row:
        return {
            "field": f"mhap_{slug}",
            "expected_dir": "UNAVAILABLE",
            "expected_state": "dim",
            "expected_pct": None,
            "status": "MISSING_ROW",
        }
    call = row.get("call")
    conf = parse_confidence_pct(row.get("confidence"))
    state = expected_tf_state_from_call(call)
    nd = norm_dir(call)
    dom_dir = "UNAVAILABLE" if nd == "UNAVAILABLE" else ("NEUTRAL" if nd == "FLAT" else nd)
    return {
        "field": f"mhap_{slug}",
        "payload_call": call,
        "expected_dir": dom_dir,
        "expected_state": state,
        "expected_pct": conf,
        "status": "DERIVED",
    }


def derive_all_parity(payload: dict[str, Any]) -> dict[str, Any]:
    tradeable = engine_tradeable_setup(payload)
    bias = str(payload.get("final_bias") or "WAIT").upper()
    if tradeable and bias in ("LONG", "SHORT"):
        state = "up" if bias == "LONG" else "down"
        dom_dir = bias
    else:
        state = "dim"
        dom_dir = "NEUTRAL"
    return {
        "field": "ALL_final_bias",
        "payload_value": f"{bias} tradeable={tradeable}",
        "expected_state": state,
        "expected_dir": dom_dir,
        "status": "DERIVED",
    }


def derive_plan_parity(payload: dict[str, Any]) -> dict[str, Any]:
    tradeable = engine_tradeable_setup(payload)
    entry = str(payload.get("entry_state") or "no_setup").lower()
    if not tradeable:
        expected = "NO SETUP"
    elif entry == "no_setup":
        expected = "NO SETUP"
    else:
        expected = entry.replace("_", " ").upper()
    return {
        "field": "PLAN_entry_state",
        "payload_entry_state": entry,
        "expected_plan_state": expected,
        "status": "DERIVED",
    }


def derive_card_parity_expectations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for slug in HORIZON_SLUGS:
        out.append(derive_horizon_parity(payload, slug))
    out.append(derive_all_parity(payload))
    out.append(derive_plan_parity(payload))
    return out


def classify_orphan_field(
    field_name: str,
    payload: dict[str, Any],
    *,
    dom_body: str = "",
    card_dom_text: str = "",
    dom_snapshot: Optional[dict[str, Any]] = None,
) -> str:
    if field_name == "call_state":
        val = payload.get(field_name)
        if val is None or val == "":
            return "ABSENT"
        snap = dom_snapshot or {}
        expected = str(val).strip().upper()
        chip_state = str(snap.get("execution_chip_call_state") or "").upper()
        chip_text = str(snap.get("execution_chip_text") or "").upper()
        chip_trusted = str(snap.get("execution_chip_trusted") or "").lower()
        if chip_state == expected:
            if expected in ("WAIT", "WATCH") and chip_text == expected:
                return "RENDERED"
            if expected == "ACTIVE" and chip_trusted == "true" and chip_text == "ACTIVE":
                return "RENDERED"
            if expected == "ACTIVE" and chip_trusted == "false" and chip_text == "WITHHELD":
                return "RENDERED"
        return "OPERATOR_DECISION_REQUIRED"

    if field_name == "call_signal":
        val = payload.get(field_name)
        if val is None or val == "":
            return "ABSENT"
        sig = str(val).strip().lower()
        snap = dom_snapshot or {}
        promoted = payload.get("mh_promoted_directional") is True or snap.get(
            "mh_promotion_chip_visible"
        ) in ("true", True)
        chip_text = str(snap.get("mh_promotion_chip_text") or "").upper()
        if promoted and sig in ("long", "short"):
            expected = f"MH PROMOTED {sig.upper()}"
            if chip_text == expected or expected in chip_text:
                return "RENDERED"
            return "OPERATOR_DECISION_REQUIRED"
        # Supporting directional — not primary execution readiness; intentionally unrendered when not promoted.
        return "SUPPORTING_UNRENDERED"

    if field_name in BACKEND_ONLY_ORPHAN_FIELDS:
        val = payload.get(field_name)
        if val is None or val == "":
            return "ABSENT"
        return "BACKEND_ONLY"

    if field_name in PENDING_EXPLANATION_RAIL_FIELDS:
        val = payload.get(field_name)
        if val is None or val == "":
            return "ABSENT"
        return DESIGN_APPROVED_PENDING_EXPLANATION_RAIL

    if field_name in PENDING_RISK_RAIL_PAIRED_FIELDS:
        if field_name == "reversal_risk":
            risk = payload.get("reversal_risk")
            if risk is None or risk == "":
                return "ABSENT"
            return DESIGN_APPROVED_PENDING_RISK_RAIL
        # reversal_label — derivative; never independently closable
        label = payload.get("reversal_label")
        if not label:
            return "ABSENT"
        return DESIGN_APPROVED_PENDING_RISK_RAIL

    if field_name in EM_BOUND_FIELDS:
        present = any(payload.get(k) not in (None, "") for k in EM_BOUND_FIELDS if k.startswith("em_") or k.startswith("kl_em_"))
        if not present:
            return "ABSENT"
        # EM bounds render on key-level / exec surfaces, not horizon pills — backend-only on cards.
        return "BACKEND_ONLY"

    val = payload.get(field_name)
    if val is None or val == "":
        return "ABSENT"

    needle = str(val).strip()
    if len(needle) >= 8 and needle in dom_body:
        # Incidental body match is not a dedicated render — still orphaned for operator fields.
        if field_name in OPERATOR_DECISION_ORPHANS:
            return "OPERATOR_DECISION_REQUIRED"
        return "ORPHANED"

    if field_name in OPERATOR_DECISION_ORPHANS:
        return "OPERATOR_DECISION_REQUIRED"

    return "ORPHANED"


def build_orphan_table(payload: dict[str, Any], dom_snapshot: dict[str, Any]) -> dict[str, str]:
    body = str(dom_snapshot.get("body_text") or "")
    card_text = str(dom_snapshot.get("card_text") or "")
    combined = body + "\n" + card_text
    table: dict[str, str] = {}
    for name in ORPHAN_FIELD_NAMES:
        table[name] = classify_orphan_field(
            name,
            payload,
            dom_body=combined,
            card_dom_text=card_text,
            dom_snapshot=dom_snapshot,
        )
    em_vals = {k: payload.get(k) for k in EM_BOUND_FIELDS}
    has_em = any(v not in (None, "") for v in em_vals.values())
    table["EM_bounds"] = "BACKEND_ONLY" if has_em else "ABSENT"
    return table


def compare_dom_to_expectations(
    expectations: list[dict[str, Any]],
    dom_cards: dict[str, Any],
    *,
    payload: Optional[dict[str, Any]] = None,
    active_ticker: Optional[str] = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    trust: Optional[dict[str, Any]] = None
    withheld_label: Optional[str] = None
    withheld_status: Optional[str] = None
    preserve_raw = False
    scoring_authority: Optional[str] = None
    if payload is not None:
        # Operator mirror / S2B card-trust contract is the scoring authority when
        # present (same contract the DOM renders from); legacy gate = labeled fallback.
        trust = resolve_card_trust_gate(payload, active_ticker=active_ticker, check_ticker=True)
        scoring_authority = trust.get("authority")
        if not trust.get("trusted"):
            if scoring_authority == SCORING_AUTHORITY_OPERATOR_MIRROR:
                withheld_label = operator_mirror_withhold_label(trust)
            else:
                withheld_label = card_trust_operator_label(str(trust.get("reason")))
            withheld_status = trust_reason_to_withheld_parity_status(str(trust.get("reason")))
            # UI preserveRawContext: under operator-mirror veto with mhap rows,
            # horizon/ALL cards keep VALUES + veto markers (never dim to label text).
            preserve_raw = (
                scoring_authority == SCORING_AUTHORITY_OPERATOR_MIRROR
                and bool(payload.get("mhap_rows"))
            )

    def _has_veto_marker(card: dict[str, Any]) -> bool:
        cls = str(card.get("class") or "")
        return (
            "--operator-actionability-veto" in cls
            or str(card.get("cardTrustWithhold") or "") != ""
        )

    for exp in expectations:
        field = exp.get("field", "")
        trust_reason = trust.get("reason") if trust else None
        if field.startswith("mhap_"):
            slug = field.replace("mhap_", "")
            card = dom_cards.get(slug) or {}
            cls = str(card.get("class") or "")
            exp_state = exp.get("expected_state")
            exp_pct = exp.get("expected_pct")
            if withheld_status and preserve_raw:
                parity = f"tf-state-{exp_state}" in cls if exp_state else False
                pct = card.get("pct")
                pct_ok = exp_pct is None or pct == f"{exp_pct}%" or pct == str(exp_pct)
                status = (
                    withheld_status
                    if parity and pct_ok and _has_veto_marker(card)
                    else PARITY_STATUS_DOM_MISMATCH
                )
                rows.append(
                    {
                        "field": field,
                        "payload_value": f"{exp.get('payload_call')}@{exp_pct}%",
                        "dom_value": f"{cls} dir={card.get('dir')} pct={pct}",
                        "parity_status": status,
                        "trust_gate_reason": trust_reason,
                        "expected_withheld_label": withheld_label,
                        "scoring_authority": scoring_authority,
                    }
                )
                continue
            if withheld_status:
                if dom_horizon_card_matches_withheld(card, withheld_label or ""):
                    status = withheld_status
                else:
                    status = PARITY_STATUS_DOM_MISMATCH
                rows.append(
                    {
                        "field": field,
                        "payload_value": f"{exp.get('payload_call')}@{exp_pct}%",
                        "dom_value": f"{cls} dir={card.get('dir')} pct={card.get('pct')}",
                        "parity_status": status,
                        "trust_gate_reason": trust_reason,
                        "expected_withheld_label": withheld_label,
                        "scoring_authority": scoring_authority,
                    }
                )
                continue
            parity = f"tf-state-{exp_state}" in cls if exp_state else False
            pct = card.get("pct")
            pct_ok = exp_pct is None or pct == f"{exp_pct}%" or pct == str(exp_pct)
            status = PARITY_STATUS_PARITY if parity and pct_ok else PARITY_STATUS_DOM_MISMATCH
            rows.append(
                {
                    "field": field,
                    "payload_value": f"{exp.get('payload_call')}@{exp_pct}%",
                    "dom_value": f"{cls} dir={card.get('dir')} pct={pct}",
                    "parity_status": status,
                    "trust_gate_reason": None,
                }
            )
        elif field == "ALL_final_bias":
            card = dom_cards.get("consolidated") or {}
            cls = str(card.get("class") or "")
            exp_state = exp.get("expected_state")
            if withheld_status and preserve_raw:
                # UI operatorMirrorVeto branch keeps direction from final_bias on ALL.
                _bias = str((payload or {}).get("final_bias") or "WAIT").upper()
                exp_state_veto = "up" if _bias == "LONG" else ("down" if _bias == "SHORT" else "dim")
                parity = f"tf-state-{exp_state_veto}" in cls
                status = (
                    withheld_status
                    if parity and _has_veto_marker(card)
                    else PARITY_STATUS_DOM_MISMATCH
                )
                rows.append(
                    {
                        "field": field,
                        "payload_value": exp.get("payload_value"),
                        "dom_value": f"{cls} dir={card.get('dir')}",
                        "parity_status": status,
                        "trust_gate_reason": trust_reason,
                        "expected_withheld_label": withheld_label,
                        "scoring_authority": scoring_authority,
                    }
                )
                continue
            if withheld_status:
                if dom_horizon_card_matches_withheld(card, withheld_label or ""):
                    status = withheld_status
                else:
                    status = PARITY_STATUS_DOM_MISMATCH
                rows.append(
                    {
                        "field": field,
                        "payload_value": exp.get("payload_value"),
                        "dom_value": f"{cls} dir={card.get('dir')}",
                        "parity_status": status,
                        "trust_gate_reason": trust_reason,
                        "expected_withheld_label": withheld_label,
                        "scoring_authority": scoring_authority,
                    }
                )
                continue
            status = PARITY_STATUS_PARITY if f"tf-state-{exp_state}" in cls else PARITY_STATUS_DOM_MISMATCH
            rows.append(
                {
                    "field": field,
                    "payload_value": exp.get("payload_value"),
                    "dom_value": f"{cls} dir={card.get('dir')}",
                    "parity_status": status,
                    "trust_gate_reason": None,
                }
            )
        elif field == "PLAN_entry_state":
            dom_state = dom_cards.get("plan_state")
            exp_state = exp.get("expected_plan_state")
            if withheld_status:
                expected_plan = expected_plan_state_for_withheld_label(withheld_label or "")
                status = (
                    PARITY_STATUS_DOM_MISMATCH
                    if dom_state != expected_plan
                    else withheld_status
                )
                rows.append(
                    {
                        "field": field,
                        "payload_value": exp.get("payload_entry_state"),
                        "dom_value": dom_state,
                        "parity_status": status,
                        "trust_gate_reason": trust_reason,
                        "expected_withheld_plan_state": expected_plan,
                        "scoring_authority": scoring_authority,
                    }
                )
                continue
            status = PARITY_STATUS_PARITY if dom_state == exp_state else PARITY_STATUS_DOM_MISMATCH
            rows.append(
                {
                    "field": field,
                    "payload_value": exp.get("payload_entry_state"),
                    "dom_value": dom_state,
                    "parity_status": status,
                    "trust_gate_reason": None,
                }
            )
    return rows


def _institutional_proof_parity_failure(
    parity_rows: list[dict[str, Any]],
    *,
    session_label: Any,
    ticker: str,
) -> list[str]:
    """Return institutional-proof blockers from parity rows (UI fidelity vs closure admissibility)."""
    blockers: list[str] = []
    for row in parity_rows:
        status = str(row.get("parity_status") or "")
        if status == PARITY_STATUS_DOM_MISMATCH:
            blockers.append(f"{ticker}_dom_parity_mismatch")
            continue
        if not parity_status_passes_ui_fidelity(status):
            blockers.append(f"{ticker}_dom_parity_unknown:{status}")
            continue
        if status == PARITY_STATUS_STALE_WITHHELD:
            if is_rth_session_label(session_label):
                blockers.append(f"{ticker}_stale_withheld_rth_freshness_expected")
            else:
                blockers.append(f"{ticker}_stale_withheld_non_rth_not_admissible")
        elif status == PARITY_STATUS_QUOTE_VETO_WITHHELD:
            # UI-fidelity PASS (contract-correct withhold on a fresh bundle), but the
            # actionability veto keeps institutional proof honest — informational blocker.
            blockers.append(f"{ticker}_quote_veto_withheld")
    return blockers


def evaluate_institutional_proof(
    *,
    tickers: list[str],
    ticker_results: dict[str, Any],
    require_browser_dom: bool,
    require_live_transport: bool,
    stable_reads_required: int,
) -> dict[str, Any]:
    """Institutional proof is NOT_PROVEN unless every gate passes for every required ticker."""
    bases_present, guests_present = split_base_guest(tickers)
    missing_bases = [t for t in DEFAULT_BASE_TICKERS if t not in tickers]
    reasons: list[str] = []

    if missing_bases:
        reasons.append(f"missing_base_tickers:{','.join(missing_bases)}")
    if not guests_present:
        reasons.append("missing_guest_ticker")

    for t in tickers:
        tr = ticker_results.get(t) or {}
        stab = tr.get("stability") or {}
        if stab.get("status") != "STABLE":
            reasons.append(f"{t}_stability:{stab.get('status')}")
        if stab.get("consecutive_stable_reads", 0) < stable_reads_required:
            reasons.append(f"{t}_stable_reads_insufficient")

        if require_browser_dom:
            dom = tr.get("browser_dom") or {}
            if dom.get("status") != "OK":
                reasons.append(f"{t}_browser_dom:{dom.get('status')}")
            parity_rows = dom.get("parity_rows") or []
            session_label = dom.get("session_label")
            if session_label is None:
                payload = (stab.get("payload") or {}) if isinstance(stab.get("payload"), dict) else {}
                session_label = payload.get("session_label")
            reasons.extend(
                _institutional_proof_parity_failure(
                    parity_rows,
                    session_label=session_label,
                    ticker=t,
                )
            )
            if require_live_transport and dom.get("live_transport") != "CAPTURED":
                reasons.append(f"{t}_live_transport:{dom.get('live_transport')}")

    status = "NOT_PROVEN" if reasons else "PROVEN"
    return {
        "institutional_proof_status": status,
        "reasons": reasons,
        "base_tickers_present": bases_present,
        "guest_tickers_present": guests_present,
        "trust_aware_acceptance": TRUST_AWARE_ACCEPTANCE_SEMANTICS,
    }


def spy_only_institutional_pass_possible(ticker_results: dict[str, Any], stable_reads: int) -> bool:
    """True if only SPY could satisfy gates — used by regression tests to forbid SPY-only PASS."""
    if len(ticker_results) != 1 or "SPY" not in ticker_results:
        return False
    tr = ticker_results["SPY"]
    stab_ok = (tr.get("stability") or {}).get("status") == "STABLE"
    dom_ok = (tr.get("browser_dom") or {}).get("status") == "OK"
    return stab_ok and dom_ok


def base_only_institutional_pass_possible(tickers: list[str], ticker_results: dict[str, Any]) -> bool:
    _, guests = split_base_guest(tickers)
    if guests:
        return False
    return evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=ticker_results,
        require_browser_dom=True,
        require_live_transport=True,
        stable_reads_required=3,
    )["institutional_proof_status"] == "PROVEN"


class HttpClient:
    def __init__(self, base: str, timeout_sec: float = 180.0, token: Optional[str] = None) -> None:
        self.base = base
        self.timeout_sec = timeout_sec
        self.token = token

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def get_json(self, path: str) -> dict[str, Any]:
        req = urllib.request.Request(self.base + path, headers=self._headers(), method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
            return json.loads(resp.read().decode())

    def post_json(self, path: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(self.base + path, data=data, headers=self._headers(), method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
            return json.loads(resp.read().decode())


def poll_stability(
    client: HttpClient,
    ticker: str,
    *,
    stable_reads: int = 3,
    poll_interval_sec: float = 8.0,
    max_wait_sec: float = 420.0,
) -> dict[str, Any]:
    reads: list[dict[str, Any]] = []
    streak = 0
    last_payload: dict[str, Any] = {}
    warm_status = "OK"
    warm_error: Optional[str] = None

    try:
        client.post_json(f"/api/analytics/warm?ticker={ticker}", {"source": "universal_card_fidelity_harness"})
    except Exception as exc:
        warm_status = "FAIL"
        warm_error = str(exc)

    t0 = time.time()
    while time.time() - t0 < max_wait_sec:
        try:
            payload = client.get_json(f"/api/analytics/state?ticker={ticker}&force=1")
        except Exception as exc:
            reads.append({"error": str(exc), "ts": time.time()})
            streak = 0
            time.sleep(poll_interval_sec)
            continue

        n_mhap = len(payload.get("mhap_rows") or [])
        pending = bool(payload.get("analytics_pending_shell"))
        snap = {
            "ts": time.time(),
            "mhap_rows": n_mhap,
            "final_bias": payload.get("final_bias"),
            "final_tradeable": payload.get("final_tradeable"),
            "entry_state": payload.get("entry_state"),
            "call_signal": payload.get("call_signal"),
            "call_state": payload.get("call_state"),
            "analytics_stale": payload.get("analytics_stale"),
            "analytics_pending_shell": pending,
        }
        reads.append(snap)
        last_payload = payload
        ok = n_mhap >= 4 and not pending
        streak = streak + 1 if ok else 0
        if streak >= stable_reads:
            break
        time.sleep(poll_interval_sec)

    # Refetch torture
    refetch_empty = False
    try:
        refetch = client.get_json(f"/api/analytics/state?ticker={ticker}&force=1")
        if len(last_payload.get("mhap_rows") or []) >= 4 and len(refetch.get("mhap_rows") or []) == 0:
            refetch_empty = True
    except Exception:
        refetch_empty = True

    status = "STABLE" if streak >= stable_reads and not refetch_empty else "NOT_PROVEN"
    return {
        "warm": warm_status,
        "warm_error": warm_error,
        "consecutive_stable_reads": streak,
        "stable_reads_required": stable_reads,
        "reads": reads,
        "refetch_empty_mhap": refetch_empty,
        "status": status,
        "payload": last_payload,
    }


def _node_playwright_script(base_url: str, ticker: str, timeout_ms: int) -> str:
    return textwrap.dedent(
        f"""
        const {{ chromium }} = require('playwright');
        (async () => {{
          const browser = await chromium.launch({{ headless: true }});
          const page = await browser.newPage();
          await page.addInitScript(() => {{ window.__ED_E2E__ = true; }});
          await page.goto({json.dumps(base_url + '/')}, {{ waitUntil: 'domcontentloaded', timeout: {timeout_ms} }});
          await page.waitForFunction(() => typeof window.setActiveTicker === 'function', null, {{ timeout: {timeout_ms} }});
          await page.evaluate(async (sym) => {{
            window.setActiveTicker(sym, null);
            if (typeof window.manualFullRefresh === 'function') {{
              await window.manualFullRefresh();
            }} else if (typeof window.fetchState === 'function') {{
              await window.fetchState(true);
            }}
          }}, {json.dumps(ticker)});
          await page.waitForFunction((sym) => {{
            const d = window._lastData;
            return d && String(d.ticker || '').toUpperCase() === sym.toUpperCase()
              && Array.isArray(d.mhap_rows) && d.mhap_rows.length >= 4
              && d.analytics_pending_shell !== true;
          }}, {json.dumps(ticker)}, {{ timeout: {timeout_ms} }});
          const out = await page.evaluate(() => {{
            const readCard = (id) => {{
              const el = document.getElementById(id);
              if (!el) return null;
              return {{
                class: el.className,
                dir: el.querySelector('.tf-dir')?.textContent?.trim() || null,
                pct: el.querySelector('.tf-pct')?.textContent?.trim() || null,
                dataDir: el.getAttribute('data-tf-signal-dir'),
                withhold: el.getAttribute('data-direction-withhold'),
                cardTrustWithhold: el.getAttribute('data-card-trust-withhold'),
              }};
            }};
            const cards = {{
              '1c': readCard('tf-signal-1c'),
              '5c': readCard('tf-signal-5c'),
              '15c': readCard('tf-signal-15c'),
              '60c': readCard('tf-signal-60c'),
              consolidated: readCard('tf-signal-consolidated'),
              plan: readCard('tf-signal-plan'),
            }};
            const planState = document.getElementById('tf-plan-state')?.textContent?.trim() || null;
            const tickerInput = document.getElementById('ticker-input')?.value?.trim()?.toUpperCase() || null;
            const staleLabel = document.getElementById('status-label')?.textContent || '';
            const transport = window.__edTransport || {{}};
            const src = window._lastPayloadUpdateSource || window._lastFullRenderSource || transport.lastFullRenderSource || '';
            const cardIds = ['tf-signal-1c','tf-signal-5c','tf-signal-15c','tf-signal-60c','tf-signal-consolidated','tf-signal-plan'];
            const card_text = cardIds.map(id => document.getElementById(id)?.textContent || '').join(' ');
            const execChip = document.getElementById('tf-execution-state-chip');
            const mhChip = document.getElementById('dr-mh-promotion-chip');
            const mhVisible = mhChip && mhChip.style.display !== 'none' && mhChip.textContent?.trim();
            return {{
              cards,
              plan_state: planState,
              ticker_input: tickerInput,
              active_ticker: window.activeTicker,
              last_data_ticker: window._lastData?.ticker,
              last_data: window._lastData,
              analytics_stale: window._lastData?.analytics_stale,
              analytics_pending_shell: window._lastData?.analytics_pending_shell,
              payload_update_source: src,
              transport_mode: transport.mode,
              body_text: document.body.innerText.slice(0, 120000),
              card_text,
              execution_chip_text: execChip ? execChip.textContent : null,
              execution_chip_call_state: execChip ? execChip.getAttribute('data-call-state') : null,
              execution_chip_trusted: execChip ? execChip.getAttribute('data-call-state-trusted') : null,
              mh_promotion_chip_text: mhChip ? mhChip.textContent?.trim() : null,
              mh_promotion_chip_visible: mhVisible ? 'true' : 'false',
              stale_label: staleLabel,
            }};
          }});
          console.log(JSON.stringify(out));
          await browser.close();
        }})().catch(err => {{ console.error(JSON.stringify({{ error: String(err) }})); process.exit(1); }});
        """
    ).strip()


def capture_browser_dom_live_transport(
    base_url: str,
    ticker: str,
    *,
    timeout_sec: float = 420.0,
) -> dict[str, Any]:
    node_modules = _REPO / "node_modules"
    env = os.environ.copy()
    env["NODE_PATH"] = str(node_modules)
    script = _node_playwright_script(base_url, ticker, int(timeout_sec * 1000))
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec + 30,
            cwd=str(_REPO),
            env=env,
        )
    except FileNotFoundError:
        return {"status": "SKIP", "error": "node_not_found", "live_transport": "NOT_PROVEN"}
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "error": "browser_timeout", "live_transport": "NOT_PROVEN"}

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[-500:]
        return {"status": "FAIL", "error": err, "live_transport": "NOT_PROVEN"}

    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
    if not lines:
        return {"status": "FAIL", "error": "no_json_from_browser", "live_transport": "NOT_PROVEN"}

    try:
        snap = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return {"status": "FAIL", "error": f"json_parse:{exc}", "live_transport": "NOT_PROVEN"}

    src = str(snap.get("payload_update_source") or "").lower()
    inject_only = "inject" in src or src in ("harness_inject", "evaluate_inject")
    has_live_payload = bool(snap.get("last_data_ticker")) and bool(snap.get("cards"))
    if inject_only:
        live_transport = "NOT_PROVEN"
    elif has_live_payload:
        live_transport = "CAPTURED"
    else:
        live_transport = "PARTIAL"

    ticker_ok = (
        str(snap.get("active_ticker") or "").upper() == ticker.upper()
        and str(snap.get("last_data_ticker") or "").upper() == ticker.upper()
    )

    return {
        "status": "OK",
        "snapshot": snap,
        "live_transport": live_transport,
        "ticker_identity_ok": ticker_ok,
        "payload_update_source": snap.get("payload_update_source"),
        "transport_mode": snap.get("transport_mode"),
    }


def collect_confirmed_defects(ticker_results: dict[str, Any]) -> list[str]:
    defects: list[str] = []
    for ticker, tr in ticker_results.items():
        ot = (tr.get("browser_dom") or {}).get("orphan_table") or tr.get("api_orphan_table") or {}
        for field, status in ot.items():
            if status in (
                "ORPHANED",
                "OPERATOR_DECISION_REQUIRED",
                DESIGN_APPROVED_PENDING_EXPLANATION_RAIL,
                DESIGN_APPROVED_PENDING_RISK_RAIL,
            ):
                defects.append(f"{ticker}:{field}={status}")
    if defects:
        defects.append("rth_guest_switch_events_not_captured")
    return sorted(set(defects))


def evaluate_overall_card_fidelity(ticker_results: dict[str, Any]) -> str:
    """Overall card fidelity stays NOT_PROVEN while orphan operator fields remain unresolved."""
    _ = ticker_results
    return ORPHAN_PAYLOAD_HANDLING_OVERALL_STATUS


def orphan_payload_handling_overall_status() -> str:
    """Explicit overall orphan disposition — never PROVEN until RTH DOM closure for all fields."""
    return ORPHAN_PAYLOAD_HANDLING_OVERALL_STATUS


def run_harness(args: argparse.Namespace) -> dict[str, Any]:
    tickers = parse_ticker_list(args.tickers) if args.tickers else list(DEFAULT_INSTITUTIONAL_TICKERS)
    if not tickers:
        tickers = list(DEFAULT_INSTITUTIONAL_TICKERS)

    base_url = (args.base_url or os.environ.get("ED_DIAG_BASE") or "http://127.0.0.1:8000").rstrip("/")
    timeout = float(args.timeout_sec or os.environ.get("ED_CARD_FIDELITY_TIMEOUT") or 180)
    client = HttpClient(base=base_url, timeout_sec=timeout, token=os.environ.get("ED_DIAG_TOKEN"))

    server_reachable = False
    try:
        client.get_json("/api/build")
        server_reachable = True
    except Exception as exc:
        server_reachable = False
        server_error = str(exc)

    report: dict[str, Any] = {
        "schema_version": 1,
        "harness": "universal_card_fidelity_runtime",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "head_sha": args.head_sha,
        "base_url": base_url,
        "tickers": tickers,
        "default_institutional_tickers": list(DEFAULT_INSTITUTIONAL_TICKERS),
        "base_coverage_seeds": list(DEFAULT_BASE_TICKERS),
        "guest_seed_default": list(DEFAULT_GUEST_TICKERS),
        "stable_reads_required": args.stable_reads,
        "require_browser_dom": args.require_browser_dom,
        "require_live_transport": args.require_live_transport,
        "server_reachable": server_reachable,
        "ticker_results": {},
    }

    if not server_reachable:
        report["server_error"] = server_error
        report["harness_result"] = "NOT_RUN"
        report["institutional_proof"] = evaluate_institutional_proof(
            tickers=tickers,
            ticker_results={},
            require_browser_dom=args.require_browser_dom,
            require_live_transport=args.require_live_transport,
            stable_reads_required=args.stable_reads,
        )
        report["card_fidelity_runtime_status"] = "NOT_PROVEN"
        return report

    ticker_results: dict[str, Any] = {}
    for ticker in tickers:
        tr: dict[str, Any] = {"ticker": ticker}
        tr["stability"] = poll_stability(
            client,
            ticker,
            stable_reads=args.stable_reads,
            poll_interval_sec=args.poll_interval_sec,
            max_wait_sec=args.max_wait_sec,
        )
        payload = tr["stability"].get("payload") or {}

        browser: dict[str, Any] = {"status": "SKIP", "live_transport": "NOT_PROVEN"}
        if not args.skip_browser:
            browser = capture_browser_dom_live_transport(base_url, ticker, timeout_sec=args.max_wait_sec)
            if browser.get("status") == "OK":
                snap = browser.get("snapshot") or {}
                cards = snap.get("cards") or {}
                cards["plan_state"] = snap.get("plan_state")
                render_payload = snap.get("last_data") if isinstance(snap.get("last_data"), dict) else payload
                expectations = derive_card_parity_expectations(render_payload)
                parity_rows = compare_dom_to_expectations(
                    expectations,
                    cards,
                    payload=render_payload,
                    active_ticker=ticker,
                )
                trust = resolve_card_trust_gate(render_payload, active_ticker=ticker, check_ticker=True)
                browser["parity_rows"] = parity_rows
                browser["card_trust"] = trust
                browser["scoring_authority"] = trust.get("authority")
                browser["trust_gate_reason"] = trust.get("reason")
                browser["session_label"] = render_payload.get("session_label")
                browser["ui_fidelity_pass"] = all(
                    parity_status_passes_ui_fidelity(str(r.get("parity_status") or ""))
                    for r in parity_rows
                )
                browser["orphan_table"] = build_orphan_table(render_payload, snap)
                browser["stale_pending"] = {
                    "analytics_stale_payload": render_payload.get("analytics_stale"),
                    "analytics_stale_dom": snap.get("analytics_stale"),
                    "pending_shell_payload": render_payload.get("analytics_pending_shell"),
                    "pending_shell_dom": snap.get("analytics_pending_shell"),
                    "loading_class_present": any(
                        "analytics-loading" in str((cards.get(k) or {}).get("class") or "")
                        for k in ("1c", "5c", "15c", "60c", "consolidated", "plan")
                    ),
                }
                call_state = render_payload.get("call_state")
                body = snap.get("body_text") or ""
                chip_state = snap.get("execution_chip_call_state")
                chip_text = str(snap.get("execution_chip_text") or "")
                chip_trusted = str(snap.get("execution_chip_trusted") or "")
                exec_visible = True
                if call_state:
                    cs = str(call_state).strip().upper()
                    if chip_state and str(chip_state).upper() == cs:
                        if cs == "ACTIVE" and chip_trusted == "false":
                            exec_visible = chip_text.upper() == "WITHHELD"
                        else:
                            exec_visible = cs in chip_text.upper() or chip_trusted == "true"
                    else:
                        exec_visible = cs in body.upper()
                browser["wait_watch_active"] = {
                    "call_state_payload": call_state,
                    "execution_chip_call_state": chip_state,
                    "execution_chip_text": chip_text,
                    "execution_chip_trusted": chip_trusted,
                    "visible_in_body": exec_visible,
                    "status": "NOT_PROVEN" if call_state and not exec_visible else "PROVEN",
                }
        tr["browser_dom"] = browser
        tr["api_orphan_table"] = build_orphan_table(payload, {})
        ticker_results[ticker] = tr

    report["ticker_results"] = ticker_results
    report["institutional_proof"] = evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=ticker_results,
        require_browser_dom=args.require_browser_dom,
        require_live_transport=args.require_live_transport,
        stable_reads_required=args.stable_reads,
    )
    report["card_fidelity_runtime_status"] = report["institutional_proof"]["institutional_proof_status"]
    report["defects_confirmed"] = collect_confirmed_defects(ticker_results)
    report["card_fidelity_overall_status"] = evaluate_overall_card_fidelity(ticker_results)
    report["harness_result"] = "PASS" if server_reachable else "NOT_RUN"
    if report["institutional_proof"]["institutional_proof_status"] != "PROVEN":
        report["harness_result"] = "FAIL"

    report["rth_guest_switch_support"] = "PARTIAL"
    report["rth_note"] = (
        "RTH guest-switch proof requires operator-driven switches via "
        "tools/run_rth_guest_switch_validation.py with switch_event_count > 0."
    )
    return report


def write_reports(report: dict[str, Any], out_dir: Path, audit_date: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"universal_card_fidelity_{audit_date}.json"
    md_path = out_dir / f"universal_card_fidelity_{audit_date}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        f"# Universal card fidelity runtime — {audit_date}",
        "",
        f"- harness_result: **{report.get('harness_result')}**",
        f"- institutional_proof: **{report.get('institutional_proof', {}).get('institutional_proof_status')}**",
        f"- card_fidelity_runtime_status: **{report.get('card_fidelity_runtime_status')}**",
        "",
    ]
    for t, tr in (report.get("ticker_results") or {}).items():
        stab = tr.get("stability") or {}
        dom = tr.get("browser_dom") or {}
        lines.append(f"## {t}")
        lines.append(f"- stability: {stab.get('status')} ({stab.get('consecutive_stable_reads')} reads)")
        lines.append(f"- browser_dom: {dom.get('status')} live_transport={dom.get('live_transport')}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--tickers",
        default=",".join(DEFAULT_INSTITUTIONAL_TICKERS),
        help="Comma/space-separated tickers (default institutional set)",
    )
    p.add_argument("--base-url", default=None, help="Server base URL (default ED_DIAG_BASE or :8000)")
    p.add_argument("--stable-reads", type=int, default=3, help="Consecutive stable reads required")
    p.add_argument("--poll-interval-sec", type=float, default=8.0)
    p.add_argument("--max-wait-sec", type=float, default=420.0)
    p.add_argument("--timeout-sec", type=float, default=180.0, help="HTTP timeout per request")
    p.add_argument("--require-browser-dom", action="store_true", help="Require Playwright DOM capture")
    p.add_argument("--require-live-transport", action="store_true", help="Require live transport (not inject-only)")
    p.add_argument("--audit-date", default=datetime.date.today().isoformat())
    p.add_argument("--output-dir", type=Path, default=_REPO / "reports" / "ui_transport")
    p.add_argument("--no-write-report", action="store_true")
    p.add_argument("--head-sha", default=None)
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.head_sha is None:
        try:
            import subprocess as sp

            args.head_sha = sp.check_output(["git", "rev-parse", "HEAD"], cwd=str(_REPO), text=True).strip()
        except Exception:
            args.head_sha = "unknown"

    if args.require_browser_dom:
        args.skip_browser = False
    else:
        args.skip_browser = True

    report = run_harness(args)
    if not args.no_write_report:
        jp, mp = write_reports(report, args.output_dir, args.audit_date)
        print(f"wrote {jp}")
        print(f"wrote {mp}")

    print(json.dumps({
        "harness_result": report.get("harness_result"),
        "institutional_proof_status": report.get("institutional_proof", {}).get("institutional_proof_status"),
        "card_fidelity_runtime_status": report.get("card_fidelity_runtime_status"),
        "card_fidelity_overall_status": report.get("card_fidelity_overall_status"),
        "defects_confirmed_count": len(report.get("defects_confirmed") or []),
        "reasons": report.get("institutional_proof", {}).get("reasons"),
    }, indent=2))

    inst = report.get("institutional_proof", {}).get("institutional_proof_status")
    overall = report.get("card_fidelity_overall_status")
    if inst != "PROVEN" or overall != "PROVEN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
