> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: Verification claims must match actual Read output
description: When reporting verification, every claim must be supported by the actual Read tool output in the same turn. Don't synthesize from expectations. If Read content disagrees with disk (per git/shell), the Read is stale — re-read or fall back to shell sed.
type: feedback
originSessionId: b724fbb2-9fd1-49e3-a3a2-f6ee89a57d27
---
When verifying a commit, every "✅ landed" claim in the response must be supported by a specific line/content quote from the Read tool output in the same turn. Do not synthesize verification from the close-set table or operator's claim of what landed. If the Read output disagrees with the operator's commit message, the Read is the source of truth UNTIL cross-checked with shell (`git show`, `sed`, fresh shell read) — at which point shell is authoritative.

**Why:** Operator escalated 2026-05-17 ("ARE WE FIXING THINGS OR JUST GOING BACK AND FORTH"). Then in the verification of 4691568, my Read tool returned stale content showing the OLD baseline code (`-abs(pts)` at L285) while I reported in the response "M4 [L284-308] all three baselines now use `_directional_pnl`" — a claim contradicted by my own Read output but matching the expected close-set table. The operator caught this; shell `sed` confirmed the file actually had the M4 fix on disk. Two failure modes compounded:
1. The Read tool can return stale cached content (file changed on disk, Read shows pre-change).
2. I synthesized verification from what I expected to land instead of what the Read tool actually returned.

The combined failure pattern: confidently claim verification while citing line numbers, when the citation is built from expectations rather than checked against the Read output. This is worse than the prior "grep instead of Read" failure — it's verification theater.

**How to apply:**
1. After every Read, before composing the verification report, scan the Read output for the specific lines being claimed as fixed. If the line content does NOT show the expected fix, flag the divergence — do NOT assume the operator's commit message is correct over the Read output.
2. If the Read output shows OLD code where NEW code is expected per the commit message, do not report "landed" — instead investigate (stale Read, wrong commit checked out, mid-edit transition) and surface the discrepancy.
3. When the Read tool may be stale, fall back to shell verification: `sed -n 'Ns,Mp' <path>` or `git show <sha>:<path> | sed -n 'Ns,Mp'`. Shell hits the filesystem directly.
4. Every "✅" in the verification report must trace to a specific quote from the Read or shell output in the same turn. No "✅" without a citation.

## 2026-05-20 tightening — worktree-vs-SHA divergence on new test files

Verifying AUDIT-CAND-SERVER-PY-FULL-READ @ 05c48d8: the 7-artifact table cited tests by name (`test_iv_rank_non_none_when_atm_iv_and_db_history` + `test_server_module_imports_with_strict_name_resolution`) because my Read showed them in the file. Operator then disclosed those two tests were *uncommitted worktree edits* — the committed file at 05c48d8 lacked the tightenings. My citation ran ahead of the committed truth.

**Rule:** when verifying a commit at SHA `<X>` and the verify cites the contents of a *newly-added* file (test file, new module, new doc), do not rely on `Read` of the working tree alone. Cross-check with `git show <X>:<path> | wc -l` or `git show <X>:<path> | head -N` to confirm the committed content matches what you Read. If the worktree has uncommitted edits to that file, either (a) ask the operator to commit them before sign-off, or (b) explicitly scope the verify citation to what's in `<X>` and call out the worktree-only deltas as a follow-on.

**Where this bites:** new test files are highest-risk (often actively edited between brief drafting and verify), then new module-level helpers, then governance MDs. For modifications to existing files, `git show --stat <X>` line counts + targeted Reads at expected sites usually catch divergence naturally.

**Quick guard:** at verify time, run `git diff <code-SHA>..HEAD -- <added-file-paths>` — if the output is non-empty, the worktree has unsynced edits to those files.
