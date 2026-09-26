"""Hard contract: primary vs secondary governed horizons (authoritative vs diagnostics-only)."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_partition_and_constants():
    from ml_horizon import (
        ALL_GOVERNED_HORIZONS,
        ML_HORIZON_SLUGS,
        PRIMARY_DECISION_HORIZONS,
        SECONDARY_SUPPORT_HORIZONS,
    )

    assert ALL_GOVERNED_HORIZONS == ML_HORIZON_SLUGS
    assert ALL_GOVERNED_HORIZONS == PRIMARY_DECISION_HORIZONS
    assert PRIMARY_DECISION_HORIZONS == ("1c", "5c", "15c", "60c")
    assert SECONDARY_SUPPORT_HORIZONS == ()
    assert set(ALL_GOVERNED_HORIZONS) == set(PRIMARY_DECISION_HORIZONS) | set(
        SECONDARY_SUPPORT_HORIZONS
    )
    assert not (set(PRIMARY_DECISION_HORIZONS) & set(SECONDARY_SUPPORT_HORIZONS))














def test_outcome_bar_specs_four_primary_slugs():
    from horizon_outcomes import OUTCOME_BAR_SPECS

    assert len(OUTCOME_BAR_SPECS) == 4
    slugs = tuple(odir[len("outcome_") :] for odir, _opt, _n in OUTCOME_BAR_SPECS)
    assert slugs == ("1c", "5c", "15c", "60c")




