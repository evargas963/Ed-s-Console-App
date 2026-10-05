"""tools/check_stale_references.py on the repository's own history: a change that deletes a name's
last definition and leaves a mention of it is refused; one that leaves none is allowed."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_stale_references as csr  # noqa: E402


def test_cut_the_fat_part_1_left_the_spy_zone_comment_and_is_refused():
    """022c44c2 dropped the snapshot table's `spy_zone` column from db.py, the name's last
    definition, and left `# ETF zone classification (spy_zone / qqq_zone / iwm_zone)` in server.py."""
    found = csr.violations(ROOT, "022c44c2^", "022c44c2")
    assert "server.py:950: `spy_zone` is still mentioned; this change removed its last definition (db.py)" in found
    assert "server.py:950: `qqq_zone` is still mentioned; this change removed its last definition (db.py)" in found


def test_one_bar_history_deleted_its_names_everywhere_and_is_allowed():
    """d965484b (#459) deleted upsert_1m_bars, _tier1_snapshot_write, COLLECT_WINDOW_START_MINS,
    collect_window_end_mins_for_et_date, in_window_ts and more, and no mention stayed behind."""
    assert csr.violations(ROOT, "93fca283", "d965484b") == []
