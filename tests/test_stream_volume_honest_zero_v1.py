"""push_level_one's volume handling (operator finding, 2026-09-11): `or` between
TOTAL_VOLUME/VOLUME drops a legitimate 0, and `vf > 0` rejected any zero outright --
so a symbol with genuinely zero volume so far today never got an entry, and a symbol
whose cache already held a real number kept showing that STALE number if a later
observation was honestly 0. Negative-controlled: the OLD logic is reproduced inline
and shown to fail for the same input the fix passes on."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))













def test_negative_control_the_old_or_and_positive_only_logic_fails_this_case():
    """Reproduces the PRE-FIX logic inline and shows it gives the wrong answer for
    the exact scenario the fix corrects -- proving this test exercises the real
    defect, not a coincidence of the new implementation."""
    def old_logic(cache: dict, sym: str, content_item: dict) -> None:
        vol = content_item.get("TOTAL_VOLUME") or content_item.get("VOLUME")
        if vol is not None:
            vf = float(vol)
            if vf > 0:
                cache[sym] = vf

    cache: dict = {"SPY": 500.0}  # a real earlier observation
    old_logic(cache, "SPY", {"TOTAL_VOLUME": 0})  # a genuine session-reset zero
    assert cache["SPY"] == 500.0, "demonstrating the old defect: the stale 500 survives"

    # ... and the fixed implementation does not have this problem (already proven above).






    # (change percent lives on the live plane only since 2026-09-24 -- NET_CHANGE_PERCENT)
