"""Stop hook: the turn does not end while the cleanup checks refuse what the session changed.

Claude Code runs it when the agent is about to end its turn (wired in `.claude/settings.json` through
`tools/hook_chain.py`). From the session transcript it takes the files the session edited (Edit,
Write, MultiEdit, NotebookEdit). For each git worktree holding one of them that has `origin/main`,
it runs `tools/check_stale_references.py` and `tools/check_dead_code.py` on the worktree against
its merge base with `origin/main`, as CI will. A refusal blocks the stop (exit 2, the findings on
stderr, which Claude Code hands back to the agent). After two blocks with no operator message in
between, the third stop is allowed and the operator is told the checks still refuse (CLAUDE.md
rule 7: after two failed attempts, stop and report).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import check_dead_code, check_stale_references  # noqa: E402
from tools.hook_chain import MUTATING_TOOLS  # noqa: E402

MARK = "CLEANUP CHECKS"
ALLOWED_BLOCKS = 2


def _records(transcript: Path) -> list[dict]:
    out = []
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rec = json.loads(line)
            if isinstance(rec, dict):
                out.append(rec)
    return out


def edited_files(records: list[dict]) -> list[Path]:
    out: dict[Path, None] = {}
    for rec in records:
        content = (rec.get("message") or {}).get("content")
        if rec.get("type") != "assistant" or not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in MUTATING_TOOLS:
                args = block.get("input") or {}
                path = args.get("file_path") or args.get("notebook_path") or args.get("path")
                if path:
                    out[Path(path)] = None
    return list(out)


def consecutive_blocks(records: list[dict]) -> int:
    """This hook's blocks since the operator's last message."""
    n = 0
    for rec in reversed(records):
        content = (rec.get("message") or {}).get("content")
        if rec.get("type") != "user":
            continue
        if isinstance(content, str):
            if content.startswith("Stop hook feedback") and MARK in content:
                n += 1
            elif not rec.get("isMeta"):
                return n
        elif isinstance(content, list) and not rec.get("isMeta") and any(
                isinstance(b, dict) and b.get("type") == "text" for b in content):
            return n
    return n


def _git(cwd: Path, *args: str) -> str | None:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def worktrees(files: list[Path]) -> list[Path]:
    out: dict[Path, None] = {}
    for f in files:
        folder = f.parent
        while not folder.is_dir() and folder != folder.parent:
            folder = folder.parent
        top = _git(folder, "rev-parse", "--show-toplevel")
        if top:
            out[Path(top)] = None
    return list(out)


def refusals(root: Path) -> list[str]:
    base = _git(root, "merge-base", "origin/main", "HEAD")
    if base is None:
        return []
    try:
        found = check_stale_references.violations(root, base)
        found += [str(f) for f in check_dead_code.new_findings(root, base)]
    except (check_stale_references.ToolError, check_dead_code.ToolError, SyntaxError) as e:
        found = [f"the check failed: {e}"]
    return found


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        sys.stderr.write(f"{MARK}: the hook payload is not a readable JSON object; it cannot be judged.\n")
        return 2
    transcript = Path(payload.get("transcript_path") or "")
    if not transcript.is_file():
        return 0
    records = _records(transcript)
    found = {root: lines for root in worktrees(edited_files(records)) if (lines := refusals(root))}
    if not found:
        return 0
    report = "\n".join(f"{root}:\n" + "\n".join(f"  {line}" for line in lines) for root, lines in found.items())
    blocks = consecutive_blocks(records)
    if blocks >= ALLOWED_BLOCKS:
        print(json.dumps({"systemMessage": f"{MARK} still refuse after {blocks} attempts; the turn ends "
                                           f"so the agent can report it to you:\n{report}"}))
        return 0
    sys.stderr.write(f"{MARK} refuse ending the turn (attempt {blocks + 1} of {ALLOWED_BLOCKS}): delete the "
                     f"stale mentions and the dead code below, or restore what uses them; after "
                     f"{ALLOWED_BLOCKS} attempts, stop and report to the operator.\n{report}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
