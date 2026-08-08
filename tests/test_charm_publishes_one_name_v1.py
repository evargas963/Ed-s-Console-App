"""RC-302 — charm published one borrowed value under two names, and nothing read the second.

MEASURED. `compute_net_charm` returned the caller-supplied strike under BOTH `drift_toward`
and `gamma_pin`, on the success path and the error path, with an intermediate alias between
them. A `git ls-files`-scoped search for any reader of `charm["gamma_pin"]` returned ZERO.

So the second name carried no information and existed only to collide: `gamma_pin` is
simultaneously terrain's max-TOTAL-gamma strike over the wide multi-expiry book (Cursor
faucet conflict 1) and, here, the selected-expiry max-absolute-net-GEX strike that charm was
handed and did NOT compute (RC-292, RC-294). One identifier, two definitions, two chain
scopes — and one publisher with no audience.

Charm measures directional hedge DECAY. It does not compute a price attractor, so
`drift_toward` is a caller's label travelling through, and one name for it is one too many
only if nothing needs it at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from math_exposure_core import compute_net_charm  # noqa: E402

#: A REAL SPY chain captured from data/ed_console.db — 40 contracts, spot 743.88, all
#: expiring 2026-07-17. Charm needs T > 0 to compute anything, and that expiry is now past,
#: so `now` is pinned to a real moment inside that session rather than the chain being
#: rewritten with invented dates. Real strikes, real open interest, real IVs, real clock.
_FIXTURE = json.loads(
    (REPO / "tests" / "fixtures" / "real_spy_0dte_chain_with_poison.json").read_text(
        encoding="utf-8"))
REAL_CHAIN = _FIXTURE["chain"]
REAL_SPOT = _FIXTURE["spot"]
REAL_EXPIRY = "2026-07-17"
DURING_THAT_SESSION = datetime(2026, 7, 17, 10, 0, tzinfo=ZoneInfo("America/New_York"))


def test_the_error_path_publishes_drift_toward_and_not_gamma_pin():
    out = compute_net_charm([], 100.0, "2026-08-14", drift_toward_strike=772.0)
    assert "gamma_pin" not in out, (
        "charm republishes terrain's field name again — one identifier, two definitions")
    assert out["drift_toward"] == 772.0, "the caller's strike stopped travelling through"


def test_a_real_chain_also_publishes_only_one_name():
    """The success path had its own copy of the alias plus an intermediate variable.

    Driven by the real captured chain so the payload under test is the one production
    builds — an empty-chain error payload could have lost the key while the live one kept it.
    """
    out = compute_net_charm(REAL_CHAIN, REAL_SPOT, REAL_EXPIRY,
                            drift_toward_strike=772.0, now=DURING_THAT_SESSION)
    assert out["contracts_used"] > 0, (
        f"the fixture no longer reaches the success path: {out.get('error')}")
    assert out["net_charm_daily"] is not None, "charm computed nothing to publish"
    assert "gamma_pin" not in out
    assert out["drift_toward"] == 772.0


def test_charm_still_reports_its_own_measurements():
    """Negative control: removing a duplicate NAME must not remove any VALUE."""
    out = compute_net_charm([], 100.0, "2026-08-14", drift_toward_strike=None)
    for key in ("net_charm_daily", "charm_direction", "charm_magnitude",
                "contracts_used", "drift_toward", "error"):
        assert key in out, f"charm stopped publishing {key}"


def test_the_two_pin_metrics_are_different_quantities():
    """RC-315: demonstrate the distinction the register describes, instead of describing it.

    RC-292 measured both at 775.0 on live SPY and warned that a coincidence reads as a
    contract. This builds a book where they SEPARATE, so the claim "these are two metrics"
    is executed rather than asserted — and so the register's wording cannot quietly drift
    back to treating them as one.

    It also pins what each one IS. `pick_pin_and_strength` maximises |call| + |put| GEX$: a
    gross CONCENTRATION, where the most hedging sits. `pick_net_gex_peak_strike` maximises
    |call - put|: where the SIGNED book leans. The first discards the sign, and the sign is
    what decides whether hedging at a strike stabilises or repels — which is why neither is
    a demonstrated magnet and why RC-315 withdrew the claim that one of them is.
    """
    from math_exposure_core import pick_net_gex_peak_strike, pick_pin_and_strength

    # 800: enormous and nearly BALANCED — the biggest gross concentration, tiny net.
    # 810: smaller book, entirely one-sided — the biggest signed-net peak.
    exposures = {
        800.0: {"call_gex_1pct": 9.0e9, "put_gex_1pct": -8.6e9, "net_gex_1pct": 0.4e9},
        810.0: {"call_gex_1pct": 4.0e9, "put_gex_1pct": -0.1e9, "net_gex_1pct": 3.9e9},
    }
    strikes = [800.0, 810.0]

    pin, strength = pick_pin_and_strength(exposures, strikes)
    peak = pick_net_gex_peak_strike(exposures, strikes)

    assert pin == 800.0, f"gross concentration is at 800 (17.6B vs 4.1B), got {pin}"
    assert peak == 810.0, f"signed-net peak is at 810 (3.9B vs 0.4B), got {peak}"
    assert pin != peak, (
        "the two metrics returned the same strike on a book built to separate them — "
        "if this ever passes trivially the fixture has stopped testing anything")
    assert strength is not None and 0.0 < strength <= 100.0, (
        f"strength_pct is the margin over the runner-up, got {strength}")


def test_no_consumer_of_the_removed_key_appears():
    """The measurement that made the removal safe, re-run so it stays true.

    If a reader of `charm["gamma_pin"]` ever appears, this fails and sends the author to
    RC-302 rather than letting the collision return through a new consumer.
    """
    import re

    files = [f for f in subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True,
        check=True).stdout.split("\0")
        if f.endswith((".py", ".html")) and not f.startswith("tests/")]
    hits = []
    for rel in files:
        try:
            lines = (REPO / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if re.search(r'(_charm_raw|charm)\s*\[\s*["\']gamma_pin', line):
                hits.append(f"{rel}:{i}")
    assert not hits, (
        f"a consumer of charm's removed gamma_pin key appeared at {hits}. That key was "
        f"terrain's name for a different metric on a different chain scope — see RC-302.")


def test_the_alias_and_its_intermediate_are_gone_from_the_source():
    src = (REPO / "math_exposure_core.py").read_text(encoding="utf-8", errors="replace")
    assert '"gamma_pin": drift_toward_strike' not in src
    assert '"gamma_pin": gamma_pin' not in src
    assert "gamma_pin = drift_toward_strike" not in src, (
        "the intermediate alias is back; it is what made the duplicate look intentional")
