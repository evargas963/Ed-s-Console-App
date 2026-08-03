"""RC-218: rehab daily scan is recommend-only and writes ledger artifacts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.rehab_daily_scan as scan  # noqa: E402


def test_collect_findings_flags_disk_only_when_present(tmp_path: Path, monkeypatch) -> None:
    measure = {"live_collect_disk_only": "DISK_ONLY: test", "index_worktree_mismatches": [], "staged_checks_not_on_head": []}
    status = {"porcelain_lines": 0, "staged_ish": 0, "untracked": 0, "modified_ish": 0}
    monkeypatch.setattr(scan, "_head", lambda: "deadbeef")
    findings = scan._collect_findings(measure, status)
    ids = {f["id"] for f in findings}
    assert "rehab.live_disk_only" in ids
    assert all(f.get("recommendation") for f in findings)


def test_write_outputs_appends_queue_and_md(tmp_path: Path, monkeypatch) -> None:
    q = tmp_path / "rehab_queue.jsonl"
    md = tmp_path / "rehab_latest.md"
    js = tmp_path / "rehab_latest.json"
    monkeypatch.setattr(scan, "QUEUE_PATH", q)
    monkeypatch.setattr(scan, "LATEST_MD", md)
    monkeypatch.setattr(scan, "LATEST_JSON", js)
    monkeypatch.setattr(scan, "_head", lambda: "abc1234")
    findings = [
        {
            "id": "rehab.test",
            "severity": "P2",
            "facet": "test",
            "summary": "unit",
            "recommendation": "noop",
            "evidence": {},
            "scanned_at_utc": "t",
            "head": "abc1234",
        }
    ]
    payload = scan._write_outputs(findings, {}, {"porcelain_lines": 1})
    assert payload["mode"] == "recommend_only"
    assert payload["pm"] == "cursor"
    assert q.is_file() and md.is_file() and js.is_file()
    row = json.loads(q.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["findings"][0]["id"] == "rehab.test"
    assert "Rehab latest" in md.read_text(encoding="utf-8")


def test_main_recommend_only_exit_zero(monkeypatch) -> None:
    monkeypatch.setattr(scan, "_measure", lambda: {"index_worktree_mismatches": [], "staged_checks_not_on_head": []})
    monkeypatch.setattr(scan, "_porcelain_stats", lambda: {"porcelain_lines": 0, "staged_ish": 0, "untracked": 0, "modified_ish": 0})
    monkeypatch.setattr(scan, "_collect_findings", lambda m, s: [])
    written: list[dict] = []

    def _wo(findings, measure, status):
        written.append({"findings": findings})
        return {"finding_count": 0, "mode": "recommend_only", "pm": "cursor"}

    monkeypatch.setattr(scan, "_write_outputs", _wo)
    assert scan.main(["--json-only"]) == 0
    assert written and written[0]["findings"] == []
