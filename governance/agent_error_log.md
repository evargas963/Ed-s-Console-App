# Agent Error Log

Every agent error, one row. Rendered by `tools/agent_error_report.py` (daily, or ad hoc on
operator request). This file is the INPUT; the report maps each error to the lock that caught it,
or records that **nothing did** — which is the list that tells us what lock to build next.

**Why this exists (operator, 2026-07-27):** "we are going to use this to then figure out what
mechanical locks you need in order to produce a pristine, error free, patch free, dead code free
repo." An error with no lock is not a lesson; it is a scheduled recurrence.

## Columns

| id | date | class | what happened | caught_by | lock_that_should_exist | status |

`caught_by` values: `OPERATOR` (worst — the human was the detector), `LOCK:<name>`, `SELF` (my own
verification found it before reporting), `NOTHING` (shipped undetected, found later).

## Classes

- **FALSE_CLAIM** — asserted something as done/verified that was not
- **PROMISE_UNKEPT** — named an action, never performed it
- **INERT_INSTRUMENT** — built a check that could not fail
- **BROKEN_PROOF** — a verification satisfied by the thing being broken
- **SURFACE_NOT_CLASS** — fixed the reported instance, left the same defect elsewhere
- **UNPROVEN_ASSERTION** — stated from memory/priors without same-turn derivation
- **MISDIAGNOSIS** — read evidence to confirm a held belief rather than to discriminate
- **TOOLING** — self-inflicted damage from how I edited (heredoc mangling, bad staging)
- **LOCK_VIOLATION** — broke a documented repo law

## Rows

| id | date | class | what happened | caught_by | lock_that_should_exist | status |
|---|---|---|---|---|---|---|
| E-01 | 2026-07-27 | FALSE_CLAIM | Reported options volume "code-complete, unverified" when the endpoint served ZERO rows — it was broken, not merely unverified | OPERATOR | live-probe required before any liveness claim | FIXED (RC-79) |
| E-02 | 2026-07-27 | SURFACE_NOT_CLASS | Fixed the spot faucet in chart.html; the identical defect sat in index.html untouched | OPERATOR | enumerate every surface of a defect class before closing | FIXED (RC-77) |
| E-03 | 2026-07-27 | SURFACE_NOT_CLASS | Removed `_latest_chain_and_spot` from /api/terrain/strikes as "the third faucet", left the identical call in /api/terrain — walls swung 11 points | OPERATOR | producer-enumeration test per computed value | FIXED (RC-80, test_levels_single_producer_v1) |
| E-04 | 2026-07-27 | SURFACE_NOT_CLASS | Fixed two-sided walls (RC-83) on the radar server-side; left the chart drawing two overlapping CALL/PUT bands on one strike | SELF | same as E-03 | FIXED (RC-86) |
| E-05 | 2026-07-27 | INERT_INSTRUMENT | Client faucet detector matched source NAMES, so it scored chart.html clean while the meta bar used Promise.all aliases | OPERATOR | negative control required before registering any check | FIXED (RC-76) |
| E-06 | 2026-07-27 | INERT_INSTRUMENT | check_no_orphan_dict_keys counted 3 write shapes, missed dataclass fields and dict(k=v) — reported live correct code as broken | SELF | same as E-05 | FIXED (RC-84) |
| E-07 | 2026-07-27 | INERT_INSTRUMENT | verdicts_declare_their_power shipped with five literal 0x08 BACKSPACE chars in its regex — could never match | SELF (negative control) | same as E-05 | FIXED (RC-87) |
| E-08 | 2026-07-27 | BROKEN_PROOF | Proved `_ratchet_may_write` worked by checking "files unchanged" — the fix had crashed on a missing `import os`, so the proof was satisfied by total failure | SELF (expected-value assertion) | every proof must observe the MECHANISM running, not the absence of an effect | FIXED (RC-90) |
| E-09 | 2026-07-27 | UNPROVEN_ASSERTION | Cited a remembered GEX-R1 retirement as settled fact across several turns; re-derivation showed n=66, 95% CI [-0.289,+0.194] containing the -0.22 it rejected, 43% power | OPERATOR | proof_only_guard (built same day) | FIXED (RC-87) |
| E-10 | 2026-07-27 | MISDIAGNOSIS | Asserted weekend/holiday contamination explained the GEX null; measurement showed the scored set had 0 non-trading days. Real cause was underpowering | SELF | state the discriminating measurement before asserting a cause | RECORDED |
| E-11 | 2026-07-27 | UNPROVEN_ASSERTION | Proposed FWHM and GEX-concentration as "institutional" wall-range methods from priors; both were degenerate on live chains (5/10 zero width; NVDA 0.3%) | SELF | research external practice BEFORE proposing it | FIXED (RC-86, methods rejected by measurement) |
| E-12 | 2026-07-27 | PROMISE_UNKEPT | Said "opening it as RC-86 and fixing now" in two separate turns; never created the row or the fix | OPERATOR | proof_only_guard promise check (built after) | FIXED (RC-86) |
| E-13 | 2026-07-27 | FALSE_CLAIM | Wrote "RC-68 CLOSED" into commit 62e3f730's message while the row still read OPEN | OPERATOR | commit-message claims must be checkable against the log | OPEN — no lock yet |
| E-14 | 2026-07-27 | TOOLING | `schwab_client.py` never staged, so 3 of 7 external-key declarations sat outside the commit while I reported money-path 0 | SELF | report state from the COMMITTED tree, not the working tree | FIXED |
| E-15 | 2026-07-27 | TOOLING | Heredoc-generated Python source mangled escapes twice: 0x08 backspaces (E-07), then 4 of 5 substitutions silently failing | SELF | never generate source via heredoc; Edit tool fails loudly on non-match | RECORDED |
| E-16 | 2026-07-27 | MISDIAGNOSIS | Misread 3 consecutive commit failures — grepped for "Failed", stopped at pre-commit's summary line, never read "files were modified by this hook" | SELF | read the whole failure block before acting | FIXED (RC-90) |
| E-17 | 2026-07-27 | FALSE_CLAIM | Reported a commit as failed by checking `git log` before the background commit had finished | SELF | wait for the completion signal, then verify by hash | RECORDED |
| E-18 | 2026-07-27 | TOOLING | `git add -A` swept a home-path audit artifact into the index three times; unstaged by hand each time instead of fixing the cause | SELF | gitignore generated artifacts | FIXED (RC-89) |
| E-19 | 2026-07-27 | SURFACE_NOT_CLASS | First cut of the one-tick paint fix regressed cold start — 3 of 4 price displays blank ~10s | SELF (DOM probe) | rendered-DOM probe on every UI change | FIXED (RC-81) |
| E-20 | 2026-07-27 | FALSE_CLAIM | An earlier "fix" ADDED an archive fallback for per_strike, taking it from 2 faucets to 3 — worse than before | SELF (faucet audit) | a fallback IS a second faucet | FIXED (RC-68) |
| E-21 | 2026-07-27 | TOOLING | Test pinned a hard line number (chart.html:308); an unrelated edit above it broke the lock | SELF | assert on content, never on line numbers | FIXED |
| E-22 | 2026-07-27 | LOCK_VIOLATION | Used shell `grep`/`grep -v` in pipes throughout the session to filter command output, against the standing no-grep law | SELF | the law targets CODE VERIFICATION; output filtering is unaddressed — needs an explicit carve-out or a ban | OPEN — needs operator ruling |
| E-23 | 2026-07-27 | INERT_INSTRUMENT | The institutional gate WROTE files while running, so it failed its own pre-commit hook while printing PASS — the repo could not accept any commit for 4 attempts | SELF | a check must never mutate the repo | FIXED (RC-90) |
| E-24 | 2026-07-27 | FALSE_CLAIM | Declared terrain/volume verified live in the afternoon; at 18:02 ET the terrain loop was dead and the panel served 90-minute-old data under a `terrain_live_cache` label | LOCK:repo_exposure_audit | liveness must be asserted for a STATE, not a moment | OPEN (RC-91) |
| E-25 | 2026-07-28 | FAKE_CLOSE | Closed the W3-C8 memo class as "both paths" while FIVE more vendor-quote callers existed; then TWO by-reference handoffs evaded the paren lock the same day | OPERATOR (v10/v11 audits) | lock must assert the INVARIANT (name references) not the incident (call syntax) | LOCKED (name-count test, 5d82adce) |
| E-26 | 2026-07-28 | SCOPE_NOT_CLASS | Fixed the RC-6 re-ADD vector while the normalizer FILL path kept bleeding (measured 1,097 -> 1,373 rows in a day) | OPERATOR (v17 audit) | a data-regrowth fix must close every producer path, proven by measuring the growth stops | LOCKED (normalizer exclusion + region test) |
| E-27 | 2026-07-28 | THEATER_LOCK | RC-6 structural test banned ONE exact spelling repo-wide - evadable by padding, and it would false-positive on the legitimate raw-table list | OPERATOR (v17 audit) | structural bans must be region-scoped and formatting-independent | LOCKED (region-scoped test) |
| E-28 | 2026-07-28 | WEAK_RECEIPT | Audit-inbox lock satisfied by an INCIDENTAL word match, not a processing receipt | OPERATOR (v17 audit) | a receipt is a line that names the thing AS what it is, not a substring anywhere | LOCKED (audit+vN same-line rule) |
| E-29 | 2026-07-28 | PROCESS_HOLE | Audit v14 arrived between turns and was never processed; v15 found zero delta | OPERATOR (v15 audit) | the newest audit must leave ledger evidence or the gate fails | LOCKED (RC-118 check; caught v16 on first run) |
| E-30 | 2026-07-28 | TOOL_MISUSE | Heredoc scripts writing .py source mangled escapes FOUR times in one day (literal newlines breaking string literals; E-15 class recurrence) | SELF (syntax errors at run) | writing source through shell heredocs must be blocked at the tool boundary | LOCKED (operator_law_guard heredoc-source rule) |
| E-31 | 2026-07-28 | BLIND_STAGING | git add -A swept another agent's in-flight files into my commits TWICE (530KB runtime log; audit scratch) | SELF (post-commit stat review) | staging must be explicit paths in a shared worktree | LOCKED (operator_law_guard blind-stage rule) |
| E-32 | 2026-07-28 | WRONG_VICTIM_PROOF | Closed RC-110 on a screenshot proving the mechanism against KDS/LVP while the row named call-wall/flip as victims | OPERATOR (v10 audit) | closure proof must exercise the NAMED victims; the close contract checks tags exist, not that they match the symptom | OPEN - candidate: desc-cell DOM ids must appear in the fix cell |
| E-33 | 2026-07-28 | PROSE_OVERCLAIM | A code comment claimed computed_ts_utc was the "chain-fetch instant" (it is the compute stamp) | OPERATOR (v13 audit) | not mechanizable in general - comments are claims enforced by adversarial review (stated limit) | STATED LIMIT |
