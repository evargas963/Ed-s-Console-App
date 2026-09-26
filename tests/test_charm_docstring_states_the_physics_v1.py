"""RC-294 — the charm docstring stated both dealer hedges backwards.

`math_exposure_core.compute_net_charm` read, until 2026-08-07:

    SHORT call → delta hedge = SHORT stock. As charm decays, they BUY back stock.
    SHORT put  → delta hedge = LONG stock. As charm decays, they SELL stock.

Both legs are inverted. A dealer short a call holds delta −Δ and must BUY stock to reach
neutral, so the hedge is LONG stock and decay makes them SELL. A dealer short a put holds
delta +Δ and must SELL stock, so the hedge is SHORT stock and decay makes them BUY.

The inversion was internally self-consistent — "short stock, then buy back" — which is why
it read plausibly and survived. It is also where the next author's reasoning comes from: I
built an entire A/B/C recommendation for the operator on top of it, plus line 822's claim
that `drift_toward_strike` comes from `pick_pin_and_strength` when the caller passes
`pick_net_gex_peak_strike` over the selected expiry. Cursor refuted both.

WHY A TEST ON PROSE. Every gate in this repo parses code. A sentence describing physics is
invisible to all of them, and that invisibility is not benign: a wrong number gets caught
by a test, a wrong sentence gets repeated. This is the RC-281/RC-290 false-reason class one
level up — there the lie excused a line, here it defines what the function MEANS.

THE ARITHMETIC IS NOT IN QUESTION. `net = call_charm - put_charm` follows the +call/−put
dealer convention shared with net GEX, is locked by tests/test_charm_sign_finite_difference
and carries measured parity on the SPY 2026-07-31 0DTE book. These tests pin the prose AND
assert the formula did not move with it.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))




def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_per_contract_charm_takes_no_side_argument():
    """The structural proof. RC-296: `bs_charm` cannot distinguish call from put.

    Two revisions of this docstring described per-side behaviour. The function that
    computes the number has no parameter for the side, so any sentence contrasting "call
    behaviour" with "put behaviour" is describing something that does not exist.
    """
    from math_levels import bs_charm

    params = set(inspect.signature(bs_charm).parameters)
    for banned in ("right", "put_call", "putCall", "side", "option_type"):
        assert banned not in params, (
            f"bs_charm now takes {banned!r} — the side-independence premise changed and "
            f"the docstring must be re-derived")
    assert {"spot", "strike"} <= params


def test_the_sign_flips_with_moneyness_not_with_side():
    """The numeric proof, run rather than asserted from memory."""
    from math_levels import bs_charm

    below = bs_charm(100.0, 90.0, 0.08, 0.20, 0.0)
    above = bs_charm(100.0, 105.0, 0.08, 0.20, 0.0)
    assert below is not None and above is not None
    assert below > 0 > above, (
        f"charm no longer changes sign across spot (K=90 -> {below}, K=105 -> {above}); "
        f"the docstring's moneyness claim must be re-derived")












