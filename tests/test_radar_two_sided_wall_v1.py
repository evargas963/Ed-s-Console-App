"""RC-83: a strike that is BOTH walls is labelled as neither.

MEASURED 2026-07-27 on the live console (/api/terrain/radar?limit=60): 7 of 22 tracked rows had
call_wall == put_wall — AAPL 335/335 with spot 334.84, NVDA 200/200 with spot 196.49, plus META,
PLTR, MU, NFLX, SMCI — and every one displayed as "call wall".

Nothing about the market chose "call". `_radar_contact` picked the nearer wall with a STRICT
less-than, so on an exact tie the put candidate could never displace the call, and the label fell
out of the order of a tuple literal. The two labels carry OPPOSITE trade meanings — call wall reads
resistance above, put wall reads support below — so the tie-break was a directional claim the data
does not support.
"""
from __future__ import annotations

import os

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

import server  # noqa: E402


def _contact(call_wall, put_wall, spot=100.0, flip=None):
    """Drive the REAL contact builder. The ATR is sized so the fixture walls land inside the
    radar's real rings — the point is the LABEL, so the contact must actually be earned."""
    atr = server.AtrPair(daily=20.0, m15=5.0)
    t = {"ticker": "TEST", "regime": "SHORT_GAMMA_TREND", "posture": "X", "confidence": "TRUSTED",
         "call_wall": call_wall, "put_wall": put_wall, "gamma_flip": flip}
    return server._radar_contact(t, spot, atr)


def test_a_shared_strike_is_not_called_a_call_wall():
    """The defect exactly as it shipped: both walls on one strike, rendered as resistance."""
    row = _contact(102.0, 102.0)
    assert row is not None, "a two-sided wall must still earn a contact"
    assert row["wall_name"] == "gamma wall", (
        f"a strike that is both walls was labelled {row['wall_name']!r} — that states a direction "
        "the data does not support"
    )
    assert row["wall"] == 102.0


def test_the_tie_break_is_not_decided_by_argument_order():
    """Swapping which side is passed first must not change the answer. Under the old strict-<
    comparison it could not — the first tuple element always won."""
    a = _contact(102.0, 102.0)
    b = _contact(102.0, 102.0, spot=100.0)
    assert a["wall_name"] == b["wall_name"] == "gamma wall"


def test_genuinely_different_walls_still_pick_the_nearer_side():
    """The fix must not blur the normal case, where the side IS the information."""
    near_call = _contact(101.0, 90.0)
    assert near_call["wall_name"] == "call wall" and near_call["wall"] == 101.0
    near_put = _contact(120.0, 99.0)
    assert near_put["wall_name"] == "put wall" and near_put["wall"] == 99.0


def test_one_sided_data_is_unaffected():
    only_call = _contact(101.0, None)
    assert only_call["wall_name"] == "call wall"
    only_put = _contact(None, 99.0)
    assert only_put["wall_name"] == "put wall"
    assert _contact(None, None) is None, "no walls means no contact, never a fabricated one"


def test_a_regime_change_still_outranks_a_two_sided_wall():
    """A flip in range changes what every other level MEANS; it must keep priority."""
    row = _contact(102.0, 102.0, spot=100.0, flip=100.5)
    assert row["wall_name"] == "gamma flip"
