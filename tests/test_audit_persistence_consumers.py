"""Pass 2 — lock persistence consumer map shape + determinism.

Three guarantees:
  1. Map JSON file is present and matches what the tool generates from current
     sources (byte-identical under --stable-time + generated_at strip).
  2. Re-running the tool twice in a row produces identical output (determinism).
  3. Every writer discovered by the tool has the four required fields and a
     valid status enum.

If the tool changes shape on purpose, regenerate the file:
    python tools/audit_persistence_consumers.py --stable-time
and commit the result alongside the tool change.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "governance" / "artifacts" / "persistence_consumer_map.json"
TOOL_PATH = ROOT / "tools" / "audit_persistence_consumers.py"


_VALID_STATUS = {"live", "dormant"}
_REQUIRED_WRITER_KEYS = {
    "writer_fn",
    "file",
    "line",
    "tables_written",
    "production_callers",
    "read_consumers",
    "status",
}
_REQUIRED_CANDIDATE_KEYS = {
    "candidate_fn",
    "file",
    "line",
    "production_callers",
    "recommended_hook_file",
}


def _run_tool_stdout() -> str:
    proc = subprocess.run(
        [sys.executable, str(TOOL_PATH), "--stdout", "--stable-time"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def _strip_generated_at(obj: dict) -> dict:
    obj = dict(obj)
    obj["generated_at"] = "stable"
    return obj


def test_persistence_consumer_map_present():
    assert MAP_PATH.exists(), (
        f"{MAP_PATH.relative_to(ROOT)} missing; run "
        "`python tools/audit_persistence_consumers.py --stable-time` to generate."
    )


def test_persistence_consumer_map_matches_current_sources():
    """File on disk must equal tool output under stable-time (modulo generated_at)."""
    on_disk = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    regenerated = json.loads(_run_tool_stdout())
    assert _strip_generated_at(on_disk) == _strip_generated_at(regenerated), (
        "persistence_consumer_map.json is stale vs persistence sources; "
        "run `python tools/audit_persistence_consumers.py --stable-time`."
    )


def test_persistence_consumer_map_is_deterministic():
    """Two consecutive runs against unchanged sources produce identical output."""
    a = _run_tool_stdout()
    b = _run_tool_stdout()
    assert a == b, "audit_persistence_consumers.py is non-deterministic"


def test_persistence_consumer_map_schema():
    obj = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    assert obj.get("schema_version") == 1
    assert obj.get("persistence_files") == ["db.py", "calibration/writer.py"]
    assert isinstance(obj.get("writers"), list)
    assert isinstance(obj.get("writer_candidates"), list)
    assert isinstance(obj.get("summary"), dict)

    for w in obj["writers"]:
        missing = _REQUIRED_WRITER_KEYS - set(w.keys())
        assert not missing, f"writer missing keys {missing}: {w.get('writer_fn')}"
        assert w["status"] in _VALID_STATUS, f"invalid status {w['status']} on {w['writer_fn']}"
        assert isinstance(w["tables_written"], list) and w["tables_written"]
        assert isinstance(w["production_callers"], list)
        assert isinstance(w["read_consumers"], dict)
        for tbl in w["tables_written"]:
            assert tbl in w["read_consumers"], (
                f"{w['writer_fn']}: read_consumers missing entry for {tbl}"
            )

    for c in obj["writer_candidates"]:
        missing = _REQUIRED_CANDIDATE_KEYS - set(c.keys())
        assert not missing, f"candidate missing keys {missing}: {c.get('candidate_fn')}"


def test_persistence_consumer_map_summary_consistent():
    obj = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    writers = obj["writers"]
    summary = obj["summary"]

    assert summary["writer_count"] == len(writers)
    assert summary["live_count"] == sum(1 for w in writers if w["status"] == "live")
    assert summary["dormant_count"] == sum(1 for w in writers if w["status"] == "dormant")
    tables = {t for w in writers for t in w["tables_written"]}
    assert summary["table_count"] == len(tables)


def test_persistence_consumer_map_originally_known_dormants_status():
    """Lock the dormants-progress story so Passes 5-7 can't accidentally
    flip a writer's status without updating this test in the same commit.

    Pass 4 @ <wire SHA> wired log_level_cross via EdDB.detect_and_log_level_crosses;
    it must now be LIVE. The remaining originals (log_confluence, start_session)
    stay DORMANT until Passes 6-7 wire or drop them.
    """
    obj = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    by_fn = {w["writer_fn"]: w for w in obj["writers"]}

    assert by_fn.get("EdDB.log_level_cross", {}).get("status") == "live", (
        "log_level_cross expected LIVE post-Pass 4; if Pass 4 was reverted, "
        "update this test in the same commit."
    )

    # Pass 6 dropped EdDB.start_session + session_log table.
    # Pass 7 dropped EdDB.log_confluence + confluence_log table.
    # Both symbols must be GONE from the map (per-table drop tests cover
    # the surface; here we just ensure the audit reflects it).
    for dropped in ("EdDB.start_session", "EdDB.log_confluence"):
        assert dropped not in by_fn, (
            f"{dropped} reappeared after wire-or-drop decision; revert or open "
            "a redecision row in OPEN_ITEMS"
        )

    candidate_fns = {c["candidate_fn"] for c in obj["writer_candidates"]}
    assert "EdDB.compute_accuracy" in candidate_fns, (
        "compute_accuracy missing from writer_candidates — Pass 5a hook "
        "recommendation depends on it being present."
    )


def test_check_mode_succeeds_on_committed_map():
    """`--check` exits 0 when the committed map matches current sources."""
    proc = subprocess.run(
        [sys.executable, str(TOOL_PATH), "--check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"--check failed: stderr={proc.stderr!r}; map may be stale, "
        "run `python tools/audit_persistence_consumers.py --stable-time`."
    )
