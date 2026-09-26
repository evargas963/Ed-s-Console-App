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




def test_server_snapshot_kwargs_includes_pred_1c_assignment():
    """Guard: server _snapshot_kwargs must wire ms.up_prob_1c → pred_1c_* (grep-level contract)."""
    from pathlib import Path

    text = Path(ROOT / "server.py").read_text(encoding="utf-8")
    assert "pred_1c_up_prob=ms.up_prob_1c" in text
    assert "pred_1c_down_prob=ms.down_prob_1c" in text
    assert "pred_1c_flat_prob=ms.flat_prob_1c" in text


