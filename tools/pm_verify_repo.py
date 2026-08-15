"""PM repo measurement (RC-242) — the evidence base a verdict must rest on.

OPERATOR LAW (non-negotiable, 2026-08-04): the PM/auditor seat verifies material claims
against the REPO, same turn. Prose from the writer is not evidence.

WHY THIS EXISTS. The audit function was trusting the audited party's narration: verdicts about
repo state (HEAD sha, GO granted, open-class count, a control being ON HEAD, quiet PASS/FAIL)
were published from chat text. It failed in both directions on 2026-08-04 — the PM ACCEPTED
claims it had not measured, and the writer asserted the GO was closed while the committed blob
read granted=true (RC-241). A verdict about the repo must carry a reading OF the repo.

This tool takes that reading. It writes `reports/pm_verify_latest.json` with each field it
actually measured plus a UTC timestamp, and `tools/pm_verify_lock.py` checks a verdict's
claims against that file (or against git output pasted inline). Nothing here interprets or
judges — it measures and records, so the judging half cannot also be the reporting half.

Run:  python tools/pm_verify_repo.py
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORT_REL = "reports/pm_verify_latest.json"

#: Controls whose presence on HEAD the PM routinely asserts. Measured by grepping the COMMITTED
#: tree, never the worktree — "it works on my disk" is precisely the claim that keeps being wrong.
ON_HEAD_PROBES: dict[str, tuple[str, str]] = {
    "pm_coverage": ("pm_coverage_violations", "tools/operating_process_lock.py"),
    "go_closeout": ("go_closeout_violations", "tools/operating_process_lock.py"),
    "commit_pipe": ("commit_pipe_violations", "tools/operating_process_lock.py"),
    "log_law_enforced": ('("log_law", check_log_law, True)',
                         "tools/check_institutional_correctness.py"),
    "pm_verify_repo": ("pm_verify_repo_violations", "tools/pm_verify_lock.py"),
    "writer_drift": ("hard_denylist_violation", "tools/writer_drift_lock.py"),
    "reset_guard": ("reset_guard_violations", "tools/operating_process_lock.py"),
}


def _git(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, f"{type(e).__name__}: {e}"
    return r.returncode, r.stdout


def head_sha() -> str | None:
    code, out = _git(["rev-parse", "HEAD"])
    return out.strip()[:40] if code == 0 and out.strip() else None


def head_blob(rel: str) -> str | None:
    code, out = _git(["show", f"HEAD:{rel}"])
    return out if code == 0 else None


def open_class_count() -> int | None:
    """OPEN+PARTIAL rows in the defect ledger AS COMMITTED — not as edited on disk."""
    src = head_blob("governance/root_cause_log.md")
    if src is None:
        return None
    return len(re.findall(r"^\|\s*RC-\d+\s*\|\s*(?:OPEN|PARTIAL)\s*\|", src, re.M))


def go_granted() -> bool | None:
    src = head_blob("governance/operator_go.json")
    if src is None:
        return None
    try:
        return bool(json.loads(src).get("granted"))
    except (ValueError, json.JSONDecodeError):
        return None


def on_head(name: str) -> bool | None:
    """Is a named control's defining text present in the COMMITTED file?"""
    probe = ON_HEAD_PROBES.get(name)
    if probe is None:
        return None
    needle, rel = probe
    src = head_blob(rel)
    if src is None:
        return False
    return needle in src


def quiet_verdict() -> str | None:
    p = REPO / "reports" / "ed_server_warn_quiet_window_latest.json"
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("verdict") or "")
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def bars_workers() -> int | None:
    src = head_blob("server.py")
    if src is None:
        return None
    m = re.search(r"^BARS_WORKERS\s*:\s*int\s*=\s*(\d+)", src, re.M)
    return int(m.group(1)) if m else None


def rule_on_head(rel: str) -> bool:
    return head_blob(rel) is not None


def measure() -> dict:
    """One pass over every field a PM verdict routinely asserts."""
    return {
        "measured_at_utc": time.time(),
        "head_sha": head_sha(),
        "open_class": open_class_count(),
        "go_granted": go_granted(),
        "quiet_verdict": quiet_verdict(),
        "bars_workers": bars_workers(),
        "on_head": {name: on_head(name) for name in ON_HEAD_PROBES},
        "rules_on_head": {
            rel: rule_on_head(rel)
            for rel in (".cursor/rules/09-pm-full-prompt-coverage.mdc",
                        ".cursor/rules/07-cursor-pm.mdc")
        },
    }


def write_report(data: dict | None = None) -> Path:
    data = data if data is not None else measure()
    out = REPO / REPORT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return out


def main() -> int:
    data = measure()
    write_report(data)
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
