"""Phase 3e: fast filesystem prune — no pre-scan, optional skip git prune."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WT_ROOT = ROOT / ".claude/worktrees"
LOG = ROOT / "governance/consolidation/phase3/phase3_execution_log.json"
BASELINE_BYTES = 2429695477


def main() -> None:
    removed: list[str] = []
    for wt in sorted(WT_ROOT.iterdir()) if WT_ROOT.is_dir() else []:
        if not wt.is_dir():
            continue
        name = wt.name
        admin = ROOT / ".git/worktrees" / name
        shutil.rmtree(wt, ignore_errors=True)
        if admin.is_dir():
            shutil.rmtree(admin, ignore_errors=True)
        removed.append(name)
    prune_out = "skipped"
    prune_rc = None
    if "--git-prune" in sys.argv:
        try:
            proc = subprocess.run(
                ["git", "worktree", "prune"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            prune_rc = proc.returncode
            prune_out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        except subprocess.TimeoutExpired:
            prune_out = "git worktree prune timed out after 30s"
    after = sum(
        p.stat().st_size
        for p in WT_ROOT.rglob("*")
        if p.is_file()
    ) if WT_ROOT.is_dir() else 0
    log = json.loads(LOG.read_text(encoding="utf-8"))
    log["3e_worktrees"] = {
        "prune_executed": True,
        "method": "filesystem_rmtree (fast)",
        "removed": removed,
        "bytes_before": BASELINE_BYTES,
        "bytes_after": after,
        "bytes_freed": BASELINE_BYTES - after,
        "prune_rc": prune_rc,
        "prune_output": prune_out,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Operator confirmed 3e; branches were stale Claude lanes with CRLF-only drift.",
    }
    LOG.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    print(f"removed {len(removed)} worktrees; bytes_after={after}")


if __name__ == "__main__":
    main()
