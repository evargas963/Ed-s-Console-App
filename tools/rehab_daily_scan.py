"""Daily repo rehab scan (RC-218) — READ-ONLY recommendations.

Appends ranked findings to reports/rehab_queue.jsonl and writes reports/rehab_latest.md.
Does NOT edit product code, commit, or restart servers.

Usage:
  .venv/Scripts/python.exe tools/rehab_daily_scan.py
  .venv/Scripts/python.exe tools/rehab_daily_scan.py --json-only
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QUEUE_PATH = REPO / "reports" / "rehab_queue.jsonl"
LATEST_MD = REPO / "reports" / "rehab_latest.md"
LATEST_JSON = REPO / "reports" / "rehab_latest.json"


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _run(argv: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(
            argv,
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
        return p.returncode, out.strip()
    except Exception as exc:  # noqa: BLE001 — scan must not die
        return 99, f"{type(exc).__name__}: {exc}"


def _git(*args: str) -> str:
    code, out = _run(["git", *args], timeout=60)
    return out if code == 0 else ""


def _measure() -> dict:
    py = REPO / ".venv" / "Scripts" / "python.exe"
    exe = str(py) if py.is_file() else sys.executable
    code, out = _run([exe, "tools/operating_process_lock.py", "--measure"], timeout=180)
    try:
        return json.loads(out) if out else {"error": "empty measure", "exit": code}
    except json.JSONDecodeError:
        return {"error": "measure_not_json", "exit": code, "raw": out[:2000]}


def _porcelain_stats() -> dict:
    raw = _git("status", "--porcelain")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    staged = sum(1 for ln in lines if ln[0] not in (" ", "?"))
    untracked = sum(1 for ln in lines if ln.startswith("??"))
    modified = sum(1 for ln in lines if "M" in ln[:2] or ln[1] == "M")
    return {
        "porcelain_lines": len(lines),
        "staged_ish": staged,
        "untracked": untracked,
        "modified_ish": modified,
    }


def _head() -> str:
    return _git("rev-parse", "--short", "HEAD").strip() or "UNKNOWN"


def _collect_findings(measure: dict, status: dict) -> list[dict]:
    findings: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    live = measure.get("live_collect_disk_only")
    if live:
        findings.append(
            {
                "id": "rehab.live_disk_only",
                "severity": "P0",
                "facet": "collect_runtime",
                "summary": str(live),
                "recommendation": "Operator restart :8000 when ready; until then status is DISK_ONLY_UNTIL_RESTART.",
                "evidence": {"live_collect_disk_only": live},
            }
        )

    mismatches = measure.get("index_worktree_mismatches") or []
    if mismatches:
        findings.append(
            {
                "id": "rehab.index_wt_drift",
                "severity": "P0",
                "facet": "worktree_integrity",
                "summary": f"{len(mismatches)} enforcement path(s) index≠WT",
                "recommendation": "Reconcile WT from index (or re-stage intentional WT) before any green claim or commit.",
                "evidence": {"paths": mismatches[:40]},
            }
        )

    staged_checks = measure.get("staged_checks_not_on_head") or []
    if staged_checks:
        findings.append(
            {
                "id": "rehab.staged_only_checks",
                "severity": "P1",
                "facet": "governance_head_lag",
                "summary": f"{len(staged_checks)} ENFORCED check(s) staged but not on HEAD",
                "recommendation": "Operator GO + coherent iceberg commit, or unstage intentionally. AGENTS claims must not outrun HEAD.",
                "evidence": {"checks": staged_checks[:40]},
            }
        )

    faucet = REPO / "governance" / "level_faucets.json"
    if not faucet.is_file():
        findings.append(
            {
                "id": "rehab.level_faucets_missing",
                "severity": "P1",
                "facet": "multi_faucet",
                "summary": "governance/level_faucets.json missing on disk",
                "recommendation": "Restore registry; domain faucet lock gates nothing without it.",
                "evidence": {},
            }
        )
    else:
        in_index = bool(_git("ls-files", "governance/level_faucets.json").strip())
        if not in_index:
            findings.append(
                {
                    "id": "rehab.level_faucets_untracked",
                    "severity": "P1",
                    "facet": "multi_faucet",
                    "summary": "level_faucets.json on disk but not in git index/HEAD",
                    "recommendation": "Stage/commit with domain faucet checker so RC-212 class cannot CLOSED-ahead-of-HEAD.",
                    "evidence": {},
                }
            )

    if status.get("porcelain_lines", 0) >= 100:
        findings.append(
            {
                "id": "rehab.dirty_tree_sprawl",
                "severity": "P2",
                "facet": "worktree_hygiene",
                "summary": f"Dirty tree sprawl: {status.get('porcelain_lines')} porcelain lines",
                "recommendation": "PM: sequence landings; avoid multi-mission dirt; path-limited commits only.",
                "evidence": status,
            }
        )

    sole = REPO / "governance" / "sole_writer.json"
    if sole.is_file():
        try:
            sw = json.loads(sole.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sw = {}
        if str(sw.get("pm", "")).lower() != "cursor":
            findings.append(
                {
                    "id": "rehab.pm_not_cursor",
                    "severity": "P1",
                    "facet": "process",
                    "summary": "sole_writer.pm is not 'cursor'",
                    "recommendation": "Set governance/sole_writer.json pm=cursor (RC-218).",
                    "evidence": {"pm": sw.get("pm")},
                }
            )

    # Code-health BLOCKING (best-effort; may be slow)
    py = REPO / ".venv" / "Scripts" / "python.exe"
    exe = str(py) if py.is_file() else sys.executable
    panel = REPO / "tools" / "code_health_panel.py"
    if panel.is_file():
        code, out = _run([exe, str(panel), "--check"], timeout=300)
        if code != 0:
            findings.append(
                {
                    "id": "rehab.code_health_blocking",
                    "severity": "P1",
                    "facet": "static_quality",
                    "summary": "code_health_panel --check non-zero (BLOCKING defects or unmeasurable)",
                    "recommendation": "Run /code-health quality circle; drive BLOCKING to 0.",
                    "evidence": {"exit": code, "tail": out[-1500:]},
                }
            )

    for f in findings:
        f["scanned_at_utc"] = now
        f["head"] = _head()
    return findings


def _write_outputs(findings: list[dict], measure: dict, status: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "scanned_at_utc": now,
        "head": _head(),
        "finding_count": len(findings),
        "findings": findings,
        "measure": measure,
        "status": status,
        "pm": "cursor",
        "mode": "recommend_only",
    }
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"scanned_at_utc": now, "head": payload["head"], "findings": findings}) + "\n")
    LATEST_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# Rehab latest — {now}",
        "",
        f"**HEAD:** `{payload['head']}` · **PM:** Cursor · **Mode:** recommend only (no auto-edit)",
        "",
        f"Findings: **{len(findings)}**",
        "",
        "| Sev | ID | Facet | Summary | Recommendation |",
        "|-----|----|-------|---------|----------------|",
    ]
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    for f in sorted(findings, key=lambda x: order.get(str(x.get("severity")), 9)):
        lines.append(
            f"| {f.get('severity')} | `{f.get('id')}` | {f.get('facet')} | "
            f"{str(f.get('summary', '')).replace('|', '/')} | "
            f"{str(f.get('recommendation', '')).replace('|', '/')} |"
        )
    if not findings:
        lines.append("| — | — | — | No findings this scan | Keep PM cadence |")
    lines.extend(
        [
            "",
            "## Operator next",
            "",
            "1. PM (Cursor) triages this table.",
            "2. Operator green-lights one mission.",
            "3. Sole writer executes; Cursor audits.",
            "",
            f"Queue log: `{_display_path(QUEUE_PATH)}`",
            "",
        ]
    )
    LATEST_MD.write_text("\n".join(lines), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args(argv)
    measure = _measure()
    status = _porcelain_stats()
    findings = _collect_findings(measure, status)
    payload = _write_outputs(findings, measure, status)
    def _safe_print(msg: str) -> None:
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", "replace").decode("ascii"))

    if args.json_only:
        _safe_print(json.dumps(payload, indent=2))
    else:
        _safe_print(f"rehab_daily_scan: {len(findings)} finding(s) -> {LATEST_MD}")
        for f in findings:
            _safe_print(f"  [{f.get('severity')}] {f.get('id')}: {f.get('summary')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
