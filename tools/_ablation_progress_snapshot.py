#!/usr/bin/env python3
"""One-line ablation run progress for operator monitoring (stdout only)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "governance" / "artifacts" / "feature_ablation_report_leaf.json"
TARGET_DEFAULT = 1120


def main() -> int:
    if not REPORT.is_file():
        print("ablation_progress: report_missing", flush=True)
        return 1
    d = json.loads(REPORT.read_text(encoding="utf-8"))
    meta = d.get("run_meta") or {}
    acc = d.get("ablation_accounting") or {}
    cells = d.get("whole_stack_feature_cells") or []
    target = int(
        acc.get("runnable_target")
        or d.get("whole_stack_runnable_cell_target")
        or TARGET_DEFAULT
    )
    ok = sum(1 for c in cells if c.get("status") == "ok")
    skipped = sum(1 for c in cells if c.get("status") == "skipped")
    failed = sum(
        1
        for c in cells
        if c.get("status") not in (None, "ok", "skipped") and c.get("status")
    )
    terminal = ok + skipped + failed
    pct = round(100.0 * terminal / target, 2) if target else 0.0
    mtime = datetime.fromtimestamp(REPORT.stat().st_mtime, tz=timezone.utc).isoformat()
    print(
        json.dumps(
            {
                "report_mtime_utc": mtime,
                "started_at": meta.get("started_at"),
                "run_status": meta.get("status"),
                "whole_stack_ok": meta.get("whole_stack_ok"),
                "runnable_target": target,
                "cells_terminal": terminal,
                "cells_ok": ok,
                "cells_skipped": skipped,
                "cells_failed": failed,
                "progress_pct": pct,
                "scoring_pass": meta.get("ed_ablation_scoring_pass"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
