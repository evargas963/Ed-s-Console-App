> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: worktree-staleness-check
description: "Worktree branches can be behind the operational tip; both Read AND shell python reads of the local file are then stale. Source of truth is origin/<operational-branch>, not local HEAD."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0c0dc4ac-d25e-46af-b696-3be671664dda
---

When working in a Claude worktree (e.g., `claude/jovial-blackwell-*`), the worktree's HEAD may be branched from an older point than the operational branch (e.g., `feature/institutional-key-levels`). In that case, BOTH the Read tool AND shell-based reads (`python open(path)`, `git show HEAD:file`) of the local file are stale by construction — they reflect the worktree branch, not what's actually deployed.

**Why:** [[full-read-verification-protocol]] says fall back to shell sed when Read returns stale content. That rule assumes the worktree matches HEAD on the operational branch. When the worktree is itself behind, the shell fallback is also stale — and they will agree with each other (because they both read the same stale tree), creating false confidence.

**How to apply:**
1. When [[full-read-verification-protocol]] disagrees with the operator's reported file state or line count, do NOT assume the operator is wrong. First check: `git log --first-parent -- <file>` on the worktree, then compare to `git log origin/<operational-branch> --oneline -- <file>`. If the operational branch has commits the worktree doesn't, the local file IS stale even if Read and shell agree.
2. Source of truth for file content under review: `git show origin/<operational-branch>:<file>` — NOT `git show HEAD:<file>` (which is the worktree branch's view).
3. Before producing a chunk-1 disposition brief on a file: confirm the worktree includes the latest order_flow_engine-type commits (or fetch and read from origin). Operator caught me 2026-05-19 producing a 7-FIND brief based on a 1017-line stale snapshot of `order_flow_engine.py`; the operational file is 1161 lines and had 4 of the 7 FINDs already fixed by 92b85ff/0edebc3.
4. The Read tool was actually showing the correct post-92b85ff state; my shell-python "fallback" pointed at the stale worktree and looked authoritative because it agreed with `git show HEAD:`. Both wrong; both consistent.
