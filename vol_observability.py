"""VOL_OBSERVABILITY_V1 — read-only native-volatility observability surface.

V2 prerequisite lane (operator-authorized 2026-07-10): the ratified
VOL_INPUT_CONTRACT 1.0.0 fetches $VIX / $VXN / $RVX every market-context
cycle, but only $VIX is consumed (market_iv_*). $VXN / $RVX were
FETCHED_UNCONSUMED with no observable surface — this module IS that surface.

HARD BOUNDARY (mechanically locked in tests/test_vol_observability_v1.py):
this module records and serializes observations ONLY. It must never be
imported by money-path modules (signals / market_state / ml_* / monte_carlo /
volatility_regime / call_engine), and nothing here feeds a model, regime,
fusion, or decision output. Native-index consumption remains NOT_APPROVED
until the V2 consumer lane.

Schwab CSV authority checked: yes
CSV row(s): quotes.$VIX.lastPrice, quotes.$VXN.lastPrice, quotes.$RVX.lastPrice
  — values arrive via market_context.fetch_market_context (existing fetch
  sites, unchanged); this module serializes the already-fetched observations.
Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE — change /
  direction_candidate are signed deltas vs the previous RECORDED observation,
  labeled candidates (the money-path direction authority remains the V1
  per-cycle vol context); NO_SCHWAB_EQUIVALENT for those deltas.
All consumers checked: yes — the /api/vol-observability endpoint is the only
  consumer; FETCHED_UNCONSUMED status is preserved for $VXN/$RVX.
SCHWAB_CSV_CHECKED
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

VOL_OBSERVABILITY_SCHEMA_VERSION = 1
VOL_INPUT_CONTRACT_VERSION = "1.0.0"

# Observation staleness: one context refresh should land well inside this.
VOL_OBSERVATION_STALE_SEC = 120.0

# Consumption truth per VOL_INPUT_CONTRACT 1.0.0 (V1): macro $VIX feeds the
# per-cycle market-IV context; the native indices are fetched but unconsumed.
_CONSUMED_STATUS = {
    "$VIX": "CONSUMED_MARKET_IV",
    "$VXN": "FETCHED_UNCONSUMED",
    "$RVX": "FETCHED_UNCONSUMED",
}

# Ratified ticker-class mapping CANDIDATE (freeze Matrix 4). Labeled candidate:
# classification authority moves to instrument_identity in the V2 lane.
_INDEX_CONE_CANDIDATES = {
    "SPY": ("spx_cone", "$VIX", "NATIVE_EQUALS_MARKET"),
    "$SPX": ("spx_cone", "$VIX", "NATIVE_EQUALS_MARKET"),
    "SPX": ("spx_cone", "$VIX", "NATIVE_EQUALS_MARKET"),
    "QQQ": ("ndx_cone", "$VXN", "NATIVE_INDEX"),
    "IWM": ("rut_cone", "$RVX", "NATIVE_INDEX"),
}

_lock = threading.Lock()
_observations: dict[str, dict[str, Any]] = {}


def _direction_candidate(change: Optional[float]) -> Optional[str]:
    if change is None:
        return None
    if change > 0:
        return "rising"
    if change < 0:
        return "falling"
    return "flat"


def record_market_vol_observation(mkt_ctx: Any, vol_ctx: Any) -> None:
    """Record one per-cycle observation of the three vol indices.

    Called once per _fetch_state cycle right after the V1 vol context is
    built. Reads only already-fetched values; performs no I/O; never raises
    (observability must not break the serve cycle)."""
    try:
        now = time.time()
        # Direct attribute access on purpose (no silent getattr defaults):
        # a malformed context is an explicit AttributeError handled by the
        # observability-only except below — absence stays UNAVAILABLE.
        as_of = vol_ctx.as_of_ts if vol_ctx is not None else None
        if mkt_ctx is None:
            values = {"$VIX": None, "$VXN": None, "$RVX": None}
        else:
            values = {
                "$VIX": mkt_ctx.vix,
                "$VXN": mkt_ctx.vxn,
                "$RVX": mkt_ctx.rvx,
            }
        with _lock:
            for sym, raw in values.items():
                try:
                    cur = float(raw) if raw is not None else None
                except (TypeError, ValueError):
                    cur = None
                prev_rec = _observations.get(sym) or {}
                prev_val = prev_rec.get("value")
                change = (
                    round(cur - prev_val, 4)
                    if cur is not None and prev_val is not None
                    else None
                )
                _observations[sym] = {
                    "value": cur,
                    "previous_value": prev_val,
                    "change": change,
                    "direction_candidate": _direction_candidate(change),
                    "source_ts": as_of,
                    "recorded_ts": now,
                    "quality_status": "VALID" if cur is not None else "UNAVAILABLE",
                }
    except Exception:
        # institutional-swallow-ok: fail-open for observability only — a recording defect
        # must never break the serve cycle; absence stays honest (-> UNAVAILABLE),
        # nothing is fabricated.
        pass


def _ticker_class_candidate(ticker: Optional[str]) -> dict[str, Any]:
    sym = (ticker or "").strip().upper()
    if not sym:
        return {
            "ticker": None,
            "class_candidate": None,
            "native_source_candidate": None,
            "native_relation_candidate": None,
        }
    cone = _INDEX_CONE_CANDIDATES.get(sym)
    if cone:
        cls, native, relation = cone
    else:
        cls, native, relation = ("single_equity_guest", "ticker_atm_iv", "CHAIN_DERIVED")
    return {
        "ticker": sym,
        "class_candidate": cls,
        "native_source_candidate": native,
        "native_relation_candidate": relation,
    }


def vol_observability_payload(ticker: Optional[str] = None) -> dict[str, Any]:
    """Serialize the current observations (read-only projection)."""
    now = time.time()
    with _lock:
        snap = {sym: dict(rec) for sym, rec in _observations.items()}
    indices: dict[str, Any] = {}
    for sym in ("$VIX", "$VXN", "$RVX"):
        rec = snap.get(sym)
        if rec is None:
            indices[sym] = {
                "value": None,
                "previous_value": None,
                "change": None,
                "direction_candidate": None,
                "source_ts": None,
                "recorded_ts": None,
                "age_sec": None,
                "staleness_status": "UNAVAILABLE",
                "quality_status": "UNAVAILABLE",
                "consumed_status": _CONSUMED_STATUS[sym],
            }
            continue
        age = round(now - rec["recorded_ts"], 3) if rec.get("recorded_ts") else None
        stale = (
            "UNAVAILABLE"
            if rec.get("value") is None
            else ("STALE" if age is not None and age > VOL_OBSERVATION_STALE_SEC else "VALID")
        )
        indices[sym] = {
            **rec,
            "age_sec": age,
            "staleness_status": stale,
            "consumed_status": _CONSUMED_STATUS[sym],
        }
    return {
        "schema_version": VOL_OBSERVABILITY_SCHEMA_VERSION,
        "contract_version": VOL_INPUT_CONTRACT_VERSION,
        "route_identity": "live",
        "as_of_ts": now,
        "broad_market_iv_source": "$VIX",
        "native_iv_consumption": "NOT_APPROVED_V2_PENDING",
        "indices": indices,
        "ticker_class_candidate": _ticker_class_candidate(ticker),
    }
