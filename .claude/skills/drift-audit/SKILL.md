---
name: drift-audit
description: Independent verification of a change (AGENTS.md § Changing the code). Run BEFORE a PR merges and before any "MET/clean/verified" claim — by a reviewer with fresh context, never by the change's author.
---

Run by a reviewer that did not write the change: a fresh agent given only `AGENTS.md`, the definitions in `docs/DATA_FLOW.md` §7 that the change touches, and the diff (not the author's conclusions). Check the change on the real repository state, with same-turn command output, against: "Ed Console is a financial application" and § Every value; "Conflicts and exceptions" (a conflict without the operator's explicit confirmation is FAIL); every rule; "Changing the code"; "Close the change". Check every changed test, fixture, expected value, hook and CI step for a weakened requirement. Record in the PR what was checked, the evidence and the verdict in the form of "Review verdicts" (PASS / FAIL / NOT_PROVEN, the tier of each proof). The standard has one home, `AGENTS.md`; this skill carries no copy.
