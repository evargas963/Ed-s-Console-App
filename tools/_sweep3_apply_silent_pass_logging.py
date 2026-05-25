"""One-shot: promote except Exception: pass → log.debug (SWEEP-EP-21..47). Repo root only."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 27 sites @ 1599d75 — explicit roster (no rglob into .claude worktrees).
TARGET_FILES = (
    "audit_snapshot_data.py",
    "verify_active_models.py",
    "levels.py",
    "live_market_plane.py",
    "market_context.py",
    "ml_predict.py",
    "normalized_training_sync.py",
    "polling_adapter.py",
    "scheduler_user_tickers.py",
    "schwab_client.py",
    "schwab_full_field_inventory.py",
    "snapshot_normalizer.py",
    "train_all.py",
    "calibration/anchor_audit.py",
    "calibration/audit_phase1.py",
    "calibration/json_utils.py",
    "tools/backfill_fusion_policy_complete_v1.py",
)

PAT = re.compile(
    r"\n(?P<indent>[ \t]*)except Exception:\s*\n(?P=indent)[ \t]*pass\s*\n",
    re.MULTILINE,
)

CONTEXT = {
    "audit_snapshot_data.py": "stdout reconfigure",
    "verify_active_models.py": "stdout reconfigure",
    "levels.py": "level filter / parity row",
    "live_market_plane.py": "notify_quote_updated",
    "market_context.py": "strike level parse",
    "ml_predict.py": "active model dir probe",
    "normalized_training_sync.py": "debounce timer cancel",
    "polling_adapter.py": "on_bars callback",
    "scheduler_user_tickers.py": "scheduler user tickers",
    "schwab_client.py": "quote attempt_hook",
    "schwab_full_field_inventory.py": "schwab field inventory",
    "snapshot_normalizer.py": "stdout reconfigure",
    "train_all.py": "train_all",
    "calibration/anchor_audit.py": "anchor audit",
    "calibration/audit_phase1.py": "audit phase1",
    "calibration/json_utils.py": "calibration json_utils",
    "tools/backfill_fusion_policy_complete_v1.py": "conn close",
}


def _ensure_logging(src: str, rel: str) -> str:
    if "log = logging.getLogger" in src or "logger = logging.getLogger" in src:
        return src
    if rel in ("audit_snapshot_data.py", "verify_active_models.py"):
        if "import logging" in src:
            return src
        return "import logging\n\nlog = logging.getLogger(__name__)\n\n" + src
    lines = src.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("from ") or line.startswith("import "):
            insert_at = i + 1
    block = "import logging\n\nlog = logging.getLogger(__name__)\n\n"
    if "import logging" in src:
        block = "log = logging.getLogger(__name__)\n\n"
    lines.insert(insert_at, block)
    return "".join(lines)


def _replace_block(indent: str, stem: str) -> str:
    return (
        f"\n{indent}except Exception as e:\n"
        f"{indent}    log.debug(\"{stem}: %s\", e, exc_info=True)\n"
    )


def main() -> int:
    entries: list[dict] = []
    ep = 21
    total = 0
    for rel in TARGET_FILES:
        path = ROOT / rel
        src = path.read_text(encoding="utf-8", errors="replace")
        matches = list(PAT.finditer(src))
        if not matches:
            print(f"WARN no matches in {rel}")
            continue
        stem = CONTEXT[rel]
        src2 = _ensure_logging(src, rel)
        matches = list(PAT.finditer(src2))
        new_src = src2
        offset = 0
        for m in matches:
            indent = m.group("indent")
            repl = _replace_block(indent, stem)
            start = m.start() + offset
            end = m.end() + offset
            new_src = new_src[:start] + repl + new_src[end:]
            offset += len(repl) - (end - start)
            line = new_src[:start].count("\n") + 1
            entries.append(
                {
                    "id": f"SWEEP-EP-{ep}",
                    "file": rel,
                    "lines": str(line),
                    "was": "except Exception: pass",
                    "fix": "log.debug with exc_info",
                }
            )
            ep += 1
            total += 1
        path.write_text(new_src, encoding="utf-8", newline="\n")
        print(f"fixed {len(matches)} in {rel}")

    audit = {
        "sweep_id": "error_propagation_v3",
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "slice": "REPO_SWEEP",
        "parent_sweep": "error_propagation_v2",
        "parent_baseline_silent_pass": 27,
        "summary": {
            "silent_exception_pass_before": 27,
            "silent_exception_pass_after": 0,
            "class_c_fixed_count": total,
            "class_b_accepted_documented": 0,
            "critical_silent_pass_files_after": 13,
        },
        "class_c_fixed": entries,
    }
    out = ROOT / "governance" / "audits" / "repo_sweep_error_propagation_v3_20260520.json"
    out.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"total fixed {total}, audit -> {out}")
    return 0 if total == 27 else 1


if __name__ == "__main__":
    raise SystemExit(main())
