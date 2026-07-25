#!/usr/bin/env python3
"""Git-shaped multi-agent handoff + worktree boundary gate.

HEAD is the shared brain between Cursor and Claude. Uncommitted source edits are
invisible to the other agent and cause stale reads / overwrites. Physical
isolation is a sibling git worktree (`<repo>-Claude`). This gate fails closed when:
  1. ED_AGENT_ROLE is missing or not exactly cursor|claude (no silent default),
  2. Role disagrees with the physical worktree path, or
  3. Protected source paths are dirty in THIS worktree.

    ED_AGENT_ROLE=cursor python tools/check_worktree_handoff.py

Exit 0 = clean handoff surface + correct worktree. Exit 1 = blocked.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_POLICY_PATH = Path(__file__).resolve().parent / "agent_worktree_policy.json"
_VALID_ROLES = frozenset({"cursor", "claude"})


def _load_policy() -> dict:
    try:
        return json.loads(_POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "env_role_var": "ED_AGENT_ROLE",
            "claude_root_suffix": "-Claude",
        }


def _porcelain(repo: Path | None = None) -> list[str]:
    root = repo or REPO
    p = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "git status failed").strip()
        raise RuntimeError(err)
    return [ln for ln in (p.stdout or "").splitlines() if ln.strip()]


def _paths_from_line(line: str) -> list[str]:
    """Parse one porcelain line into path(s). Handles rename `->` form."""
    body = line[3:] if len(line) >= 3 else line
    body = body.strip()
    if " -> " in body:
        return [p.strip().strip('"') for p in body.split(" -> ", 1)]
    return [body.strip().strip('"')]


def is_protected_source(path: str) -> bool:
    """Protected surface: *.py, static/*, AGENTS.md, governance/*."""
    norm = path.replace("\\", "/").lstrip("./")
    if not norm or norm.endswith("/"):
        return False
    if norm == "AGENTS.md":
        return True
    if norm.startswith("governance/"):
        return True
    if norm.startswith("static/"):
        return True
    if norm.endswith(".py"):
        return True
    return False


def dirty_protected_paths(
    porcelain_lines: list[str] | None = None,
    *,
    repo: Path | None = None,
) -> list[str]:
    lines = _porcelain(repo) if porcelain_lines is None else porcelain_lines
    found: set[str] = set()
    for ln in lines:
        for path in _paths_from_line(ln):
            if is_protected_source(path):
                found.add(path.replace("\\", "/"))
    return sorted(found)


def require_role(env: dict | None = None) -> tuple[str | None, str | None]:
    """Return (role, error). Role is set only when ED_AGENT_ROLE is explicit.

    No silent defaults — missing/invalid role is a fatal boundary violation.
    """
    policy = _load_policy()
    env = env if env is not None else os.environ
    var = str(policy.get("env_role_var") or "ED_AGENT_ROLE")
    raw = env.get(var)
    if raw is None or not str(raw).strip():
        return None, (
            f"FATAL: {var} is not set. Set {var}=cursor or {var}=claude "
            f"explicitly — no silent default (worktree isolation)."
        )
    role = str(raw).strip().lower()
    if role not in _VALID_ROLES:
        return None, (
            f"FATAL: {var}={raw!r} is invalid. Must be exactly "
            f"'cursor' or 'claude'."
        )
    return role, None


def worktree_boundary_violations(
    repo: Path | None = None,
    env: dict | None = None,
) -> list[str]:
    """Fail closed when role is unset or disagrees with the physical worktree.

    OBSERVED (2026-07-25): multi-agent fracture when both edit the same checkout;
    silent role inference hid mis-routed agents. VALIDATED: explicit ED_AGENT_ROLE
    + path suffix binding; no operator-home absolute paths in policy.
    """
    policy = _load_policy()
    root = (repo or REPO).resolve()
    suffix = str(policy.get("claude_root_suffix") or "-Claude")
    role, err = require_role(env)
    if err:
        return [err]
    assert role is not None
    out: list[str] = []
    if role == "claude" and not root.name.endswith(suffix):
        out.append(
            f"FATAL: ED_AGENT_ROLE=claude but root name {root.name!r} "
            f"does not end with {suffix!r}. Use the dedicated *-Claude worktree."
        )
    if role == "cursor" and root.name.endswith(suffix):
        out.append(
            f"FATAL: ED_AGENT_ROLE=cursor but root is Claude worktree "
            f"{root.name!r}. Stay in the primary checkout."
        )
    # Claude worktree must be a linked git worktree (git-dir ≠ common-dir), not a clone.
    if role == "claude":
        try:
            gd = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=root, capture_output=True, text=True, encoding="utf-8",
            )
            cd = subprocess.run(
                ["git", "rev-parse", "--git-common-dir"],
                cwd=root, capture_output=True, text=True, encoding="utf-8",
            )
            if gd.returncode == 0 and cd.returncode == 0:
                git_dir = Path(gd.stdout.strip())
                common = Path(cd.stdout.strip())
                if not git_dir.is_absolute():
                    git_dir = (root / git_dir).resolve()
                if not common.is_absolute():
                    common = (root / common).resolve()
                if git_dir.resolve() == common.resolve():
                    out.append(
                        "FATAL: Claude root is a standalone .git clone, "
                        "not a linked `git worktree`. Recreate with "
                        "`git worktree add <path> -b worktree/claude`."
                    )
        except OSError as e:
            out.append(f"FATAL: git rev-parse failed: {e}")
    return out


def main() -> int:
    blocked = False

    boundary = worktree_boundary_violations()
    if boundary:
        blocked = True
        print("Handoff blocked: worktree boundary violation.", file=sys.stderr)
        for msg in boundary:
            print(f"  {msg}", file=sys.stderr)

    try:
        dirty = dirty_protected_paths()
    except RuntimeError as e:
        print(f"Handoff blocked: {e}", file=sys.stderr)
        return 1
    if dirty:
        blocked = True
        print(
            "Handoff blocked: Uncommitted working tree changes. "
            "Commit or stash before handoff.",
            file=sys.stderr,
        )
        for p in dirty:
            print(f"  {p}", file=sys.stderr)

    if blocked:
        return 1
    role, _ = require_role()
    print(
        f"Handoff OK — role={role} root={REPO.name} "
        "protected source clean at HEAD."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
