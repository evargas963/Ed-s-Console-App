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

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monte_carlo import (  # noqa: E402
    ANNUALIZED_HOURS,
    BAR_MINUTES,
    MC_SIGMA_BAR_CADENCE_CUTOVER_TS,
    MC_SIGMA_LEGACY_LAST_WRITE_TS,
    mc_sigma_unit_for_row,
)

#: Every tracked .py allowed to mention mc_sigma_value: the live write chain
#: (monte_carlo -> bayesian_fusion -> market_state -> server -> db), the two
#: diagnostics, the tests, and the mega3 derivation inventory whose row for
#: monte_carlo.mc_sigma_unit_for_row names the column it classifies (a documentation
#: MENTION, not a historical-row reader — it derives nothing, RC-478). Measured
#: 2026-08-25 (see module docstring).
READER_CENSUS = frozenset({
    "bayesian_fusion.py",
    "db.py",
    "inspect_trading_data.py",
    "market_state.py",
    "monte_carlo.py",
    "server.py",
    "verify_snapshot_pipeline.py",
    "governance/mega3_traceable_inventory.py",
    "tests/test_bayesian_fusion_v2.py",
    "tests/test_mc_sigma_unit_quarantine_v1.py",
})


def test_blend_rows_are_annualized_regardless_of_date():
    assert mc_sigma_unit_for_row(1740000000.0, "blend") == "annualized"
    assert mc_sigma_unit_for_row(None, "blend") == "annualized"


def test_pre_cutover_garch_rows_are_legacy_unverified():
    assert mc_sigma_unit_for_row(MC_SIGMA_BAR_CADENCE_CUTOVER_TS, "garch") == "legacy_unverified"
    assert mc_sigma_unit_for_row(1740000000.0, "garch") == "legacy_unverified"
    assert mc_sigma_unit_for_row(None, "garch") == "legacy_unverified"


def test_post_cutover_legacy_garch_rows_are_per_bar_1m_and_convertible():
    mid = (MC_SIGMA_BAR_CADENCE_CUTOVER_TS + MC_SIGMA_LEGACY_LAST_WRITE_TS) / 2
    assert mc_sigma_unit_for_row(mid, "garch") == "per_bar_1m"
    # The conversion factor for this one era: x sqrt(minutes per trading year).
    factor = (ANNUALIZED_HOURS * 60 / BAR_MINUTES) ** 0.5
    assert 313.0 < factor < 314.0, factor


def test_rows_after_the_legacy_boundary_are_annualized():
    """No rows exist between the boundary and the fixed producer (measured: all NULL),
    so everything the fixed producer writes classifies as the current contract."""
    assert mc_sigma_unit_for_row(MC_SIGMA_LEGACY_LAST_WRITE_TS + 1, "garch") == "annualized"


def test_no_new_mc_sigma_value_reader_appears_unpinned():
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    mentions = set()
    for rel in proc.stdout.split("\0"):
        if not rel:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "mc_sigma_value" in text:
            mentions.add(rel.replace("\\", "/"))
    assert mentions == set(READER_CENSUS), (
        f"mc_sigma_value consumer census moved.\n"
        f"NEW (not pinned): {sorted(mentions - set(READER_CENSUS))}\n"
        f"GONE (still pinned): {sorted(set(READER_CENSUS) - mentions)}\n"
        f"The stored column mixes three units (~310x apart, RC-478). A new reader of "
        f"HISTORICAL rows must classify each row with monte_carlo.mc_sigma_unit_for_row "
        f"and filter/convert per era, then add itself here in the same commit.")


def test_training_lanes_stay_clear_of_mc_columns():
    """ml_train's feature lists exclude all mc_ columns (measured clean 2026-08-25);
    a training lane that starts consuming mc_sigma_value inherits the unit mix."""
    text = (ROOT / "ml_train.py").read_text(encoding="utf-8", errors="replace")
    assert "mc_sigma_value" not in text
