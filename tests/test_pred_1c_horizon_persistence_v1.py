"""1c empirical horizon: schema + snapshot dict parity (persistence contract)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import SnapshotRow




def test_snapshot_row_has_pred_1c_columns():
    fields = SnapshotRow.__dataclass_fields__
    assert "pred_1c_up_prob" in fields
    assert "pred_1c_down_prob" in fields
    assert "pred_1c_flat_prob" in fields






