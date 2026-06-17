> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: verify-target-exists-before-trigger
description: "Before sending `go layer-5 <path>` (or any walk trigger naming a file), verify the file exists at the operational tip with `git ls-tree` or `git show <branch>:<path>`. Do NOT trust file names from earlier conversation lists."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0c0dc4ac-d25e-46af-b696-3be671664dda
---

Before sending any walk trigger that names a specific file path, verify the file actually exists at the operational branch tip. Earlier conversation lists, candidate menus, and your own prior briefs are NOT authoritative — files get renamed, refactored, or never existed.

**Why:** Operator caught me 2026-05-19 authorizing `go layer-5 features/parallel_stack_contract` — that file doesn't exist in the repo (zero references). Cursor delivered `stack_integrity_v1.py` walk instead with explicit gatekeeper note that my target didn't exist. The error came from carrying a name forward through several turns of "remaining features/* files" lists without re-verifying.

**How to apply:**
1. Before sending a walk trigger naming a file:
   - `git show feature/institutional-key-levels:<path> 2>&1 | python -c "import sys; print(len(sys.stdin.read().splitlines()))"` — line count if exists, error if not
   - OR `git ls-tree feature/institutional-key-levels features/ | findstr <basename>` — confirms the file is in the operational tree
2. If the file doesn't exist: flag it explicitly to the operator and ask which target they meant (or pick the closest sibling that DOES exist).
3. Apply the same check to chunked-walk requests: confirm the line range exists in the actual file by reading the last few lines first.

**Related:** [[worktree-staleness-check]] — both rules are about "don't trust assumed repo state; verify before acting."
