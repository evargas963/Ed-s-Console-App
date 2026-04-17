#!/usr/bin/env python3
"""Move `from db import get_snapshot_sql` to after `from __future__ import annotations`."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = [
    ROOT / "backfill_snapshot_derived.py",
    ROOT / "db_health_audit.py",
    ROOT / "debug_flow_snapshot.py",
    ROOT / "ml_data_common.py",
    ROOT / "similarity_feature_survivorship.py",
    ROOT / "tools" / "bar_history_recovery_audit_v1.py",
    ROOT / "tools" / "canonical_timeframe_db_evidence_v1.py",
    ROOT / "tools" / "issue19_forward_canonical_validation_v1.py",
    ROOT / "tools" / "issue19_rehydration_range_v1.py",
    ROOT / "tools" / "pin_neutral_1m_5m_divergence_audit_v1.py",
    ROOT / "tools" / "pin_neutral_eligibility_funnel_v1.py",
    ROOT / "tools" / "pin_neutral_reachability_audit_v1.py",
    ROOT / "tools" / "repair_validation_counts_v1.py",
]

PREFIX = "from db import get_snapshot_sql\n\n"


def main() -> None:
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        if not text.startswith(PREFIX):
            print(f"SKIP unexpected start: {path}", file=sys.stderr)
            continue
        rest = text[len(PREFIX) :]
        marker = "from __future__ import annotations\n"
        idx = rest.find(marker)
        if idx < 0:
            print(f"SKIP no __future__: {path}", file=sys.stderr)
            continue
        insert_at = idx + len(marker)
        new = rest[:insert_at] + "\n" + PREFIX + rest[insert_at:]
        path.write_text(new, encoding="utf-8")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
