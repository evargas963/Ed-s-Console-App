"""Causal label reconstruction contract + mechanical lookahead guards (research-only).

This module RE-IMPLEMENTS the production fixed-horizon label formula (proven by
audit: db._apply_bar_based_outcome_updates / horizon_outcomes.py) from an
immutable list of 1-minute bars, so that:

  * every label reconstructs deterministically from source-row identity alone
    (ticker, bar_start_ts_utc, close) — Phase E/J;
  * mechanical guards fail closed on lookahead, incomplete-bar use, timestamp
    aliasing, duplicate anchors, horizon confusion, and cross-ticker
    attachment — Phase E;
  * realized MFE/MAE from the OHLC path is available as a research label
    (distinct from the runtime Monte-Carlo forecast) — Phase H.

THREE DISTINCT THINGS — do not conflate them (Objective B):

  1. RECONSTRUCTION-OF-PRODUCTION. `reconstruct_fixed_horizon_label` faithfully
     reproduces the DEPLOYED label. The production formula applies NO session
     filter: the forward bar is chosen purely by floor((T+N*60)/60)*60 and may
     fall in after-hours, span the RTH close, or cross a session/closure
     boundary. This module does NOT protect against session crossover, because
     doing so would CHANGE the reconstructed production label. There is no
     silent session guard here: adding one would alter the deployed formula,
     which the reconstruction contract forbids.

  2. KNOWN UNGOVERNED SESSION CROSSOVER. That the production label can cross
     sessions is a real, ungoverned property. It is SURFACED here as an
     ADVISORY, read-only field (`session_crossover`) computed from the canonical
     ts_utc -> America/Chicago + exchange-calendar authority (ct_session). The
     advisory NEVER alters `outcome`/`pts`; it only reports.

  3. INSTITUTIONAL-CANDIDATE-LABEL. A future governed label MAY add a
     session-crossover policy (e.g. truncate at RTH close, or forbid
     cross-session horizons). That is a NEW candidate target in the registry,
     NOT a change to this reconstruction, and is not part of Stage 1.

It is NOT wired into production. It never reads snapshots.spot, quotes, or any
future bar beyond the label's own forward bar. Session authority (advisory only)
is the canonical ts_utc -> CT + calendar path in ct_session — NEVER a stored
et_hour/et_minute column (the RTH-integrity contradiction those columns cause is
documented in the Stage 1 report and session/cohort contract).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

from research.stage1_target_foundation import ct_session

BAR_SECONDS = 60
# canonical horizons in candles (1 candle = 1 minute); matches ml_horizon primary set
HORIZON_MINUTES = {"1c": 1, "5c": 5, "15c": 15, "60c": 60}


@dataclass(frozen=True)
class Bar:
    """One immutable 1-minute OHLC bar. Identity = (ticker, bar_start_ts_utc).

    `synthetic` is the provenance flag: True when this bar was produced by an
    interior-gap repair (synthetic_interior_grid_repair / edge_carry /
    anchor_coverage_pad) rather than observed from the wire. It NEVER changes the
    label value; it makes provenance observable so Stage 2 can stratify/exclude
    synthetic-repaired rows (registry gate synthetic_provenance_flagged)."""
    ticker: str
    bar_start_ts_utc: int
    open: float
    high: float
    low: float
    close: float
    synthetic: bool = False

    @property
    def bar_end_ts_utc(self) -> int:
        return self.bar_start_ts_utc + BAR_SECONDS


class CausalLabelError(ValueError):
    """Raised when a label request would violate the causal contract (fail closed)."""


def _index_bars(bars: list[Bar], ticker: str) -> tuple[list[int], dict[int, Bar]]:
    """Return (sorted bar_start list, start->Bar map) for one ticker, rejecting
    duplicate anchors and cross-ticker rows."""
    starts: list[int] = []
    by_start: dict[int, Bar] = {}
    for b in bars:
        if b.ticker != ticker:
            continue
        if b.bar_start_ts_utc in by_start:
            raise CausalLabelError(
                f"duplicate anchor bar_start {b.bar_start_ts_utc} for {ticker}"
            )
        if b.bar_start_ts_utc % BAR_SECONDS != 0:
            raise CausalLabelError(
                f"bar_start {b.bar_start_ts_utc} not aligned to the 60s grid (timestamp aliasing)"
            )
        by_start[b.bar_start_ts_utc] = b
        starts.append(b.bar_start_ts_utc)
    starts.sort()
    return starts, by_start


def anchor_bar_for(bars: list[Bar], ticker: str, anchor_ts_utc: float) -> Bar | None:
    """Last completed 1m bar whose bar_end_ts_utc <= anchor_ts_utc (production rule)."""
    starts, by_start = _index_bars(bars, ticker)
    ends = [s + BAR_SECONDS for s in starts]
    i = bisect.bisect_right(ends, anchor_ts_utc) - 1
    if i < 0:
        return None
    return by_start[starts[i]]


def _advisory_session_crossover(anchor_bar_start: int, fwd_start: int) -> dict:
    """ADVISORY ONLY. Report whether the anchor bar and the forward bar fall in
    different Central-Time sessions (the known ungoverned crossover of the
    production label). This NEVER changes outcome/pts. Fail-soft: if the calendar
    cannot classify an instant (e.g. outside its validity window), sessions are
    reported as 'unknown' and crossover as None — the reconstruction stays pure."""
    try:
        a = ct_session.classify_session(float(anchor_bar_start))
        f = ct_session.classify_session(float(fwd_start))
    except Exception:  # advisory must never break reconstruction
        return {"anchor_session": "unknown", "forward_session": "unknown",
                "session_crossover": None}
    return {
        "anchor_session": a,
        "forward_session": f,
        # crossover if the sessions differ, or the forward bar is outside RTH
        "session_crossover": (a != f) or (f != ct_session.SESSION_RTH),
    }


def classify_direction_pts(pts: float, threshold: float) -> str:
    """Mirror of math_probabilities.classify_direction_pts (fail closed to flat)."""
    if threshold is None or threshold <= 0:
        return "flat"
    if pts > threshold:
        return "up"
    if pts < -threshold:
        return "down"
    return "flat"


def reconstruct_fixed_horizon_label(
    bars: list[Bar],
    ticker: str,
    anchor_ts_utc: float,
    horizon: str,
    threshold_pts: float,
    *,
    now_ts_utc: float,
) -> dict:
    """Deterministically reconstruct the production fixed-horizon outcome for one
    (ticker, anchor, horizon) from immutable bars. Fails closed on any causal
    hazard. Returns {outcome, pts, forward_bar_start, anchor_bar_start,
    complete, reconstructable}."""
    if horizon not in HORIZON_MINUTES:
        raise CausalLabelError(f"unknown horizon {horizon!r} (horizon confusion)")
    n_min = HORIZON_MINUTES[horizon]
    anchor = anchor_bar_for(bars, ticker, anchor_ts_utc)
    if anchor is None:
        return {"outcome": None, "pts": None, "reconstructable": False,
                "reason": "no anchor bar <= anchor_ts_utc"}
    fwd_start = int((anchor_ts_utc + n_min * BAR_SECONDS) // BAR_SECONDS) * BAR_SECONDS
    fwd_end = fwd_start + BAR_SECONDS
    # LOOKAHEAD GUARD: the label may only be written once its forward bar is fully
    # complete relative to observation time (now_ts_utc). Requesting it earlier is
    # a lookahead violation, not a NULL.
    if now_ts_utc < fwd_end:
        raise CausalLabelError(
            f"lookahead: forward bar [{fwd_start},{fwd_end}) not complete at "
            f"now_ts_utc={now_ts_utc} (horizon {horizon})"
        )
    _starts, by_start = _index_bars(bars, ticker)
    crossover = _advisory_session_crossover(anchor.bar_start_ts_utc, fwd_start)
    fwd = by_start.get(fwd_start)
    if fwd is None:
        return {"outcome": None, "pts": None, "reconstructable": True,
                "forward_bar_start": fwd_start, "anchor_bar_start": anchor.bar_start_ts_utc,
                "complete": True, "reason": "forward bar missing (NULL label)", **crossover}
    pts = round(fwd.close - anchor.close, 4)
    return {
        "outcome": classify_direction_pts(pts, threshold_pts),
        "pts": pts,
        "forward_bar_start": fwd_start,
        "anchor_bar_start": anchor.bar_start_ts_utc,
        "complete": True,
        "reconstructable": True,
        # provenance (read-only; does NOT affect outcome/pts): whether a synthetic
        # -repaired bar backs the anchor or forward close (Objective G)
        "anchor_synthetic": bool(anchor.synthetic),
        "forward_synthetic": bool(fwd.synthetic),
        "synthetic_involved": bool(anchor.synthetic or fwd.synthetic),
        # advisory, read-only; does NOT affect outcome/pts (Objective B)
        **crossover,
    }


def realized_mfe_mae(
    bars: list[Bar],
    ticker: str,
    anchor_ts_utc: float,
    horizon: str,
    *,
    now_ts_utc: float,
) -> dict:
    """Realized favorable/adverse excursion over the horizon window from the OHLC
    path (research label — NOT the Monte-Carlo forecast).

    CONVENTIONS (Objective H — declared, not implied):
      * basis: excursion measured from anchor.close (the entry reference of the
        reconstructed label). A tradeable variant would use next-bar OPEN and is
        a distinct candidate target, not this reconstruction.
      * sign: MFE = max(high) - anchor.close (>=0 favorable up-move reach);
        MAE = anchor.close - min(low) (>=0 adverse down-move reach). Both are
        magnitudes; a short/long direction split is a candidate refinement.
      * high/low vs close: uses the intrabar HIGH/LOW of every window bar, so
        gap-through and same-bar touch-both extremes are captured (unlike the
        endpoint close-to-close label).
      * costs: NONE applied (raw path). Cost binding is a separate economic
        candidate.
      * window: forward bars strictly after the anchor bar through the horizon's
        forward bar, i.e. (anchor_bar_start, fwd_start].
      * FAIL-CLOSED on incomplete path: if ANY expected 1-minute bar in the
        window is missing, return a NULL excursion with reconstructable=False —
        never a partial-path excursion over the surviving bars.
      * session crossover / early close: reported ADVISORY-ONLY via
        session_crossover; the excursion window is NOT truncated at the RTH
        close (that truncation is a governed candidate variant, not this
        reconstruction).
    """
    if horizon not in HORIZON_MINUTES:
        raise CausalLabelError(f"unknown horizon {horizon!r}")
    n_min = HORIZON_MINUTES[horizon]
    anchor = anchor_bar_for(bars, ticker, anchor_ts_utc)
    if anchor is None:
        return {"mfe": None, "mae": None, "reconstructable": False}
    fwd_start = int((anchor_ts_utc + n_min * BAR_SECONDS) // BAR_SECONDS) * BAR_SECONDS
    if now_ts_utc < fwd_start + BAR_SECONDS:
        raise CausalLabelError("lookahead: horizon window not complete for MFE/MAE")
    _starts, by_start = _index_bars(bars, ticker)
    crossover = _advisory_session_crossover(anchor.bar_start_ts_utc, fwd_start)
    # expected contiguous 1m grid from first forward bar through fwd_start
    expected = list(range(anchor.bar_start_ts_utc + BAR_SECONDS, fwd_start + BAR_SECONDS, BAR_SECONDS))
    if not expected:
        return {"mfe": None, "mae": None, "reconstructable": True,
                "reason": "empty window", **crossover}
    missing = [s for s in expected if s not in by_start]
    if missing:
        # FAIL CLOSED: an incomplete path yields NO excursion (Objective H)
        return {"mfe": None, "mae": None, "reconstructable": False,
                "reason": f"incomplete path: {len(missing)} of {len(expected)} bars missing",
                "missing_bar_count": len(missing), **crossover}
    window = [by_start[s] for s in expected]
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    return {
        "mfe": round(hi - anchor.close, 4),
        "mae": round(anchor.close - lo, 4),
        "window_bars": len(window),
        "reconstructable": True,
        **crossover,
    }
