"""tools/cleanup_stop_hook.py, run as Claude Code runs it (through tools/hook_chain.py, the Stop
payload on stdin), on a transcript in Claude Code's own record format: the turn may not end while
the session's change leaves a stale mention or dead code, and it may on the third attempt."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPT = (ROOT / "tests" / "fixtures" / "stop_hook_transcript.jsonl").read_text(encoding="utf-8").splitlines()
BASE = {"calc.py": 'def spot(row):\n    return row["last"]\n\n\ndef mark_price(row):\n    return row["mark"]\n',
        "use.py": "from calc import mark_price, spot\n\nprint(spot({}), mark_price({}))\n",
        "NOTES.md": "Prices come from `calc.spot` and `calc.mark_price`.\n"}
DELETED = {"calc.py": 'def spot(row):\n    return row["last"]\n',
           "use.py": "from calc import spot\n\nprint(spot({}))\n"}


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8", newline="\n")


def _session(tmp_path: Path, edits: dict[str, str], lines: list[str]) -> subprocess.CompletedProcess:
    """A worktree whose origin/main is BASE, the session's uncommitted `edits`, and the Stop event
    for a transcript of `lines`."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _write(root, BASE)
    _git(root, "add", *BASE)
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _write(root, edits)
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("\n".join(lines).replace("__REPO__", root.as_posix()) + "\n", encoding="utf-8")
    payload = {"session_id": "08a41ba7-592b-44d9-9e52-614ec3c56c51", "transcript_path": str(transcript),
               "cwd": str(root), "hook_event_name": "Stop", "stop_hook_active": False}
    return subprocess.run([sys.executable, str(ROOT / "tools" / "hook_chain.py"), "tools/cleanup_stop_hook.py"],
                          cwd=ROOT, input=json.dumps(payload), capture_output=True, text=True, timeout=120)


def test_a_deleted_function_still_named_in_the_notes_blocks_the_stop(tmp_path):
    r = _session(tmp_path, DELETED, TRANSCRIPT[:4])
    assert r.returncode == 2, r.stderr
    assert "attempt 1 of 2" in r.stderr
    assert "NOTES.md:1: `mark_price` is still mentioned; this change removed its last definition (calc.py)" in r.stderr


def test_a_function_the_session_added_and_nothing_calls_blocks_the_stop(tmp_path):
    added = {"calc.py": BASE["calc.py"] + '\n\ndef last_trade(row):\n    return row["trade"]\n'}
    r = _session(tmp_path, added, TRANSCRIPT[:4])
    assert r.returncode == 2, r.stderr
    assert "calc.py:9: unused function 'last_trade' (60% confidence)" in r.stderr


def test_after_two_blocks_the_third_stop_is_allowed_and_the_operator_is_told(tmp_path):
    r = _session(tmp_path, DELETED, TRANSCRIPT)
    assert r.returncode == 0, r.stderr
    assert "CLEANUP CHECKS still refuse after 2 attempts" in json.loads(r.stdout)["systemMessage"]


def test_an_operator_message_after_the_blocks_starts_the_count_again(tmp_path):
    r = _session(tmp_path, DELETED, TRANSCRIPT + TRANSCRIPT[:4])
    assert r.returncode == 2 and "attempt 1 of 2" in r.stderr, r.stderr


def test_a_clean_deletion_ends_the_turn(tmp_path):
    clean = dict(DELETED, **{"NOTES.md": "Prices come from `calc.spot`.\n"})
    r = _session(tmp_path, clean, TRANSCRIPT[:4])
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
