"""
Symmetric CUSUM-style event filter + SMA(8,21) side rule (pilot v1).

Not production authority. Events are research artifacts under prereg_v1.json.

Sigma for CUSUM z: continuous causal EWM std on the full ordered RTH bar tape
(see ``sigma_contract`` in prereg). Legacy per-day reset retained for diagnostics only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import numpy as np

from app.domain.time_et import ET as _ET

from . import pilot_config
from .data_loader import Bar1m, RTH_START_MINS


def _et_calendar_key(ts_utc: float) -> str:
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(_ET)
    return dt.strftime("%Y-%m-%d")


def _et_minute_of_day_from_start(ts_start_utc: float) -> int:
    dt = datetime.fromtimestamp(float(ts_start_utc), tz=timezone.utc).astimezone(_ET)
    return int(dt.hour * 60 + dt.minute)


def _in_first_30min_rth(ts_start_utc: float) -> bool:
    m = _et_minute_of_day_from_start(ts_start_utc)
    return RTH_START_MINS <= m < RTH_START_MINS + 30


@dataclass
class PilotEvent:
    event_id: str
    signal_bar_index: int
    T_close_ts_utc: float
    side: str  # LONG | SHORT
    sma_fast: float
    sma_slow: float
    cusum_pos: float
    cusum_neg: float
    z_trigger: float
    candidate_generator_id: str
    withheld_reason: str | None = None


def pd_ewm_std(x: np.ndarray, *, span: int, variance_eps: float = 0.0) -> np.ndarray:
    import pandas as pd

    s = pd.Series(x, dtype=float)
    s.ewm(span=span, adjust=False).mean()
    v = s.ewm(span=span, adjust=False).var(bias=True)
    eps = float(variance_eps)
    # Continuous path uses eps=0; legacy daily-reset diagnostic uses eps=1e-16 to match pre-refactor numerics.
    out = np.sqrt(np.maximum(v.to_numpy(), eps))
    return out.astype(float)


def _ewm_std_by_rth_day_legacy(
    closes: np.ndarray,
    bar_starts: np.ndarray,
    *,
    span: int,
) -> np.ndarray:
    """
    Legacy: per ET calendar day, EWM std of simple returns with ``span``, reset each day.

    Retained for before/after diagnostics only (not used by generate_events).
    """
    n = len(closes)
    sigma = np.full(n, np.nan, dtype=float)
    day_keys = np.array([_et_calendar_key(float(t)) for t in bar_starts])
    rets = np.zeros(n, dtype=float)
    rets[1:] = (closes[1:] - closes[:-1]) / np.maximum(closes[:-1], 1e-12)

    i0 = 0
    while i0 < n:
        i1 = i0
        d = day_keys[i0]
        while i1 < n and day_keys[i1] == d:
            i1 += 1
        seg = rets[i0:i1]
        s = pd_ewm_std(seg, span=span, variance_eps=1e-16)
        sigma[i0:i1] = s
        i0 = i1
    return sigma


def _ewm_std_continuous_rth(closes: np.ndarray, *, span: int) -> np.ndarray:
    """Single causal EWM std of simple returns on the full ordered ``closes`` tape (no daily reset)."""
    n = len(closes)
    rets = np.zeros(n, dtype=float)
    rets[1:] = (closes[1:] - closes[:-1]) / np.maximum(closes[:-1], 1e-12)
    return pd_ewm_std(rets, span=span, variance_eps=0.0)


def _apply_relative_sigma_floor(sigma_raw: np.ndarray, *, M: int, phi: float) -> np.ndarray:
    """
    sigma_i = max(sigma_raw_i, phi * median(sigma_raw[i-M : i])) using strictly past indices only.
    """
    n = len(sigma_raw)
    out = np.copy(sigma_raw)
    M = max(0, int(M))
    phi = float(phi)
    for i in range(n):
        lo = max(0, i - M)
        hi = i
        if hi <= lo:
            continue
        w = sigma_raw[lo:hi]
        finite = w[np.isfinite(w) & (w > 0)]
        if finite.size == 0:
            continue
        med = float(np.median(finite))
        if not np.isfinite(med) or med <= 0:
            continue
        srs = sigma_raw[i]
        if not np.isfinite(srs) or srs <= 0:
            continue
        out[i] = max(float(srs), phi * med)
    return out


def build_sigma_for_cusum(
    closes: np.ndarray,
    bar_starts: np.ndarray,
    cg: dict[str, Any],
) -> np.ndarray:
    """
    Build sigma array aligned with ``closes`` / ``bar_starts`` per ``cg['sigma_contract']``.

    ``bar_starts`` is required for API compatibility; continuous EWM does not use calendar reset.
    """
    _ = bar_starts
    sc = cg.get("sigma_contract") or {}
    span = int(sc.get("ewm_span_bars", cg.get("ewm_span_bars", 390)))
    sigma_raw = _ewm_std_continuous_rth(closes, span=span)
    rf = sc.get("relative_floor") or {}
    if bool(rf.get("enabled", True)):
        M = int(rf.get("M", 120))
        phi = float(rf.get("phi", 0.25))
        return _apply_relative_sigma_floor(sigma_raw, M=M, phi=phi)
    return sigma_raw


def sma(closes: np.ndarray, window: int) -> np.ndarray:
    out = np.full_like(closes, np.nan, dtype=float)
    c = np.cumsum(closes, dtype=float)
    out[window - 1 :] = (c[window - 1 :] - np.concatenate(([0.0], c[:-window]))) / float(window)
    return out


def generate_events(
    bars: list[Bar1m],
    prereg: dict[str, Any],
) -> tuple[list[PilotEvent], dict[str, int]]:
    """
    Returns (events, stats). stats include dropped_none_sma_near_equal (SMA tie per tolerance).
    """
    stats = {"dropped_none_sma_near_equal": 0}
    if len(bars) < 100:
        return [], stats

    if prereg.get("prereg_id") == pilot_config.FROZEN_PILOT_PREREG_ID:
        pilot_config.validate_prereg_integrity(prereg)

    cg = prereg["candidate_generator"]
    cusum_cfg = cg["cusum"]
    k = float(cusum_cfg["k"])
    h = float(cusum_cfg["h_threshold"])
    min_gap = int(cg["min_bar_gap"])
    exclude_first_30 = bool(cg.get("exclude_first_30min_rth", True))
    sma_fast_n = int(cg["sma"]["fast"])
    sma_slow_n = int(cg["sma"]["slow"])
    sma_tol = float(cg.get("sma", {}).get("near_equal_tolerance", 1e-9))
    gen_id = str(cg["candidate_generator_id"])

    closes = np.array([b.close for b in bars], dtype=float)
    starts = np.array([b.bar_start_ts_utc for b in bars], dtype=float)

    sigma = build_sigma_for_cusum(closes, starts, cg)
    sma_f = sma(closes, sma_fast_n)
    sma_s = sma(closes, sma_slow_n)

    pos = neg = 0.0
    events: list[PilotEvent] = []
    last_emit = -10**9

    for i in range(1, len(bars)):
        sig = sigma[i]
        if not np.isfinite(sig) or sig <= 0:
            continue
        r = (closes[i] - closes[i - 1]) / max(closes[i - 1], 1e-12)
        z = r / sig
        pos = max(0.0, pos + z - k)
        neg = max(0.0, neg - z - k)

        fire = pos >= h or neg >= h
        if not fire:
            continue
        if exclude_first_30 and _in_first_30min_rth(starts[i]):
            pos = neg = 0.0
            continue
        if i - last_emit < min_gap:
            pos = neg = 0.0
            continue
        if i + 1 >= len(bars):
            break

        sf = sma_f[i]
        ss = sma_s[i]
        if not (np.isfinite(sf) and np.isfinite(ss)):
            pos = neg = 0.0
            continue
        if abs(float(sf) - float(ss)) < sma_tol:
            stats["dropped_none_sma_near_equal"] += 1
            pos = neg = 0.0
            continue
        if sf > ss:
            side = "LONG"
        else:
            side = "SHORT"

        Tc = bars[i].bar_end_ts_utc
        eid = f"evt_{int(Tc)}_{i}"
        events.append(
            PilotEvent(
                event_id=eid,
                signal_bar_index=i,
                T_close_ts_utc=Tc,
                side=side,
                sma_fast=float(sf),
                sma_slow=float(ss),
                cusum_pos=float(pos),
                cusum_neg=float(neg),
                z_trigger=float(z),
                candidate_generator_id=gen_id,
            )
        )
        last_emit = i
        pos = neg = 0.0

    return events, stats
