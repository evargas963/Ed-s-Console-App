"""RC-478 — the mixed-unit mc_sigma_value history is quarantined in code.

WHAT WAS MEASURED (2026-08-25, reports/mc_sigma_blast_area_2026-08-25.md): the stored
snapshot column mc_sigma_value spans three unit eras in one column — blend rows
(annualized), garch rows before 2026-07-08 (mixed per-bar cadences, ~30x spread inside
the era, unconvertible per-row), garch rows after (per-1-minute-bar, ~313.5x below
annualized). No current model, study, backtest, or UI reads the history — the liability
is latent. This suite keeps it latent:

  1. the era classifier is pinned to the measured boundaries, and
  2. the set of tracked .py files that mention mc_sigma_value is pinned by NAME, so a
     new reader cannot appear without editing this file and confronting the era contract.

A legitimate new historical reader adds itself to READER_CENSUS in the same commit AND
classifies rows via monte_carlo.mc_sigma_unit_for_row (filter to one era, or convert
only the per_bar_1m era by sqrt(ANNUALIZED_HOURS*60/BAR_MINUTES)).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


#: Every tracked .py allowed to mention mc_sigma_value: the live write chain
#: (monte_carlo -> bayesian_fusion -> market_state -> server -> db), the tests, the
#: mega3 derivation inventory whose row for monte_carlo.mc_sigma_unit_for_row names the
#: column it classifies (a documentation MENTION, not a historical-row reader — it derives
#: nothing, RC-478), and the RC-478 normalization migration + its test (a LEGITIMATE
#: historical reader — it classifies each row with mc_sigma_unit_for_row and derives the
#: single-unit mc_sigma_annualized column, exactly what this census requires of a new
#: reader). Measured 2026-08-25; the two offline diagnostics left with the unused-code prune.
READER_CENSUS = frozenset({
    "bayesian_fusion.py",
    "db.py",
    "market_state.py",
    "monte_carlo.py",
    "server.py",
    "tools/mc_sigma_normalize_history_v1.py",
    "tests/test_mc_sigma_normalize_history_v1.py",
    "governance/provenance_roots.py",  # RC-532: names the MarketState FIELD mc_sigma_value with its category — a mention, not a reader (was mega3_traceable_inventory.py)
    "tests/test_bayesian_fusion_v2.py",
    "tests/test_mc_sigma_unit_quarantine_v1.py",
    # Base-neutral MC proof: writes ONE fresh row through the current producer and reads that same
    # row back within the test. It never reads historical rows, so no era classification applies —
    # pinned here because this census is a source-text mention census. Added 2026-08-28.
    "tests/test_mc_base_neutral_mode_v1.py",
})












def test_training_lanes_stay_clear_of_mc_columns():
    """ml_train's feature lists exclude all mc_ columns (measured clean 2026-08-25);
    a training lane that starts consuming mc_sigma_value inherits the unit mix."""
    text = (ROOT / "ml_train.py").read_text(encoding="utf-8", errors="replace")
    assert "mc_sigma_value" not in text
