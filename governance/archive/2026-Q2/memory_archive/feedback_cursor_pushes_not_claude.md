> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: Cursor pushes; Claude verifies and consults — never push
description: Operator's role separation rule. Claude Code is verification + consulting expert. All git push operations belong to Cursor. Memory created after Claude pushed afe2385 unprompted in the role of "ratifying" an operator instruction.
type: feedback
originSessionId: 89eb33d4-6525-4efd-b243-89cd7680fa39
---
Cursor does all pushing. Claude Code does verification and consulting. Never push, even when the operator says "push X" — that instruction is for Cursor, not for me.

**Why:** Multi-tool workflow per project memory is "Cursor primary code/codebase ground truth; Claude Code primary for design review/verification." Push is a code-side action. When I push, I blur the role separation the operator deliberately built — and once roles blur, gatekeeping discipline weakens because the gatekeeper is also doing the work being gated.

**How to apply:** When the operator says "push X" or "ready to push," treat it as a relay to Cursor, not as authorization for me to act. My output should be: gatekeeping verdict (if not already given), then "ready for Cursor to push" — not the push itself. Same applies to: creating commits, staging files, opening PRs, any state change to the repo or remotes. Verification commands (git log, git show, git diff, git status, pytest) remain in scope.
