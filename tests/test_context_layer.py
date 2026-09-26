"""Smoke tests: institutional behavior scores + news module import."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))








def test_snapshot_row_has_context_fields():
    from db import SnapshotRow

    assert "sentiment_composite" in SnapshotRow.__dataclass_fields__
    assert "absorption_score" in SnapshotRow.__dataclass_fields__
