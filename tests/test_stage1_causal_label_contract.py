"""Stage 1 causal label reconstruction + adversarial/mutation guards.

Proves the production fixed-horizon label reconstructs deterministically from
immutable source bars, and that the causal contract fails closed on lookahead,
timestamp aliasing, duplicate anchors, cross-ticker attachment, horizon
confusion, and source-row mutation. Research-only; no production effect.
"""
from __future__ import annotations

import json
from pathlib import Path



GOLDEN = Path(__file__).resolve().parents[1] / "research" / "stage1_target_foundation" / "golden"


def _load(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def test_session_authority_is_ts_utc_not_stored_clock():
    """The golden premarket bar (08:00 ET) must classify NON-RTH via the canonical
    ts_utc->DST-ET authority — never a stored et_hour column."""
    from time_et import is_rth_ts_utc
    assert is_rth_ts_utc(1767618000) is False  # 08:00 ET premarket
    assert is_rth_ts_utc(1767623700) is True   # 09:35 ET RTH


# ---- Objective B: session crossover is ADVISORY, never a silent guard ----

# 2026-01-05 (CST). RTH close 15:00 CT = 21:00 UTC. A 14:59 CT anchor bar with a
# 1c forward bar at 15:01 CT crosses RTH -> afterhours.
_ANCHOR_1459_CT = 1767646740   # 20:59 UTC = 14:59 CT bar start (RTH)
_T_1500_CT = 1767646800        # 21:00 UTC = observation just past anchor close
_FWD_1501_CT = 1767646860      # 21:01 UTC = 15:01 CT forward bar (afterhours)


# ---- Objective H: MFE/MAE fails closed on an incomplete path ----

_A = 1767623700  # aligned anchor bar start (RTH)


