> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: No new governance MDs as task deliverables
description: Never frame a task's deliverable as a new governance MD file. Decisions and rationale go in commit messages or existing protocol/program/brief docs.
type: feedback
originSessionId: e54ed980-71da-4ce6-8f50-f3e4a2d445a0
---
Do not write spawned-task prompts, slice plans, or recommendations that ask for a new standalone governance MD (e.g. `SCHWAB_V4_REGISTER_STORAGE_PLAN.md`, `*_PROPOSAL.md`, `*_PLAN.md`). Storage/architecture/process decisions land as: (a) the rationale in the commit message body of the implementing commit, or (b) an amendment to an existing protocol/program/brief doc when the rule is normative and recurring.

**Why:** Operator caught me 2026-05-12 framing the V4 register-storage decision as needing a proposal MD before implementation. This violates the existing per-iteration-scoreboard memory ("MD churn that doesn't move P or shrink unreviewed_count is motion, not progress") and the no-permission-asks memory (the back-and-forth from drafting a proposal, reviewing it, then implementing it). The operator was specific: "I'm tired of you not obeying. You said you had this in memory and it wouldn't happen again."

**How to apply:**
- When summarizing options for the operator, do it in chat — short, ≤ 10 lines, with a committed recommendation.
- When the operator picks, the next artifact is the implementing commit. Rationale lives in the commit message body, not a sibling MD.
- When spawning tasks, the deliverable is code + commit message. Never `Deliverable: a short proposal doc in governance/`.
- Existing protocol/program/brief docs may be amended for normative rules that govern future work. They should not gain new sibling MDs for one-off decisions.
- If unsure whether a doc is needed, default to no doc. The bar is: would future Claude/Cursor be unable to reconstruct this from git history + existing governance? If yes, amend an existing doc. If no, commit message is enough.
