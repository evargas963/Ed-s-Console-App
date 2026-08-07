# BRUTAL ADVERSARIAL AUDIT v18 — 2026-07-28 ~15:50 CT

**HEAD (committed):** `580172be` — `RC-119: day's error census E-25..E-33, every mechanizable class locked (audit v17 processed).`  
**Dirty WIP:** RC-120 row + `stop_guard` / `data_faucet_audit` / negative-control (+36/−2 uncommitted)  
**Prior:** deep v17 @ `36b9fa17`  
**Verdict:** **PARTIAL ACCEPT** on lock hygiene · **REJECT** “every mechanizable class locked” as airtight · **REJECT** “audit v17 processed” as *mechanical* inbox truth · program guns still **OUTSTANDING** (Claude admits)

---

## Charter

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — adversarial verification of Claude lock pass |
| GAP | Claimed E-25..E-33 / RC-118 receipt / RC-6 bleed stop vs reality |
| SMALLEST_COMPLETE_CHANGE | This report |
| MINIMUM_SUFFICIENT_EVIDENCE | Live gate + guard probes + SQL + file:line |
| DECISION_PATH_EFFECT | none |
| WHY_NOW | Operator pasted Claude finish narrative |
| TASK_ADMISSION | audit only |

---

## What shipped @ `580172be` (7 files, +75/−9)

| Path | Intent |
|---|---|
| `tools/operator_law_guard.py` | Blind-stage + heredoc-source rules |
| `tools/check_institutional_correctness.py` | RC-118 same-line receipt (`audit`/`processed`) |
| `snapshot_normalizer.py` | `_RC6_CULLED` exclude from INSERT intersection |
| `tests/test_money_path_orphan_keys_v1.py` | Region-scoped migrate ban + normalizer pin |
| `tests/test_enforced_check_negative_controls_v1.py` | Receipt negative control (v99) |
| `governance/root_cause_log.md` | RC-119 CLOSED |
| `governance/agent_error_log.md` | E-25..E-33 census |

**Not in this commit:** `server.py`, Decide, LP-01, dual walls, RC-120 (dirty only).

---

## Headline grades (same-turn)

| Claim | Grade | Smoking gun |
|---|---|---|
| RC-118 receipt form (same-line audit/processed) | **FIXED (narrow)** | `check_institutional_correctness.py:2435-2440`; neg control wants `audit v99 processed` (`test_enforced…:319`) |
| “Audit v17 processed on the record” (mechanical) | **FAKE_CLOSE / HOLE** | Gate glob still `_v(\d+)\.md$` → **best = 16**. On-disk deep audit is `…_v17_deep.md` — **invisible**. Live `check_adversarial_audits_are_answered()` = `[]` against **v16** receipt on RC-117 line, not a v17 inbox entry |
| Blind staging `git add -A/--all/.` | **FIXED (narrow)** | Fires same-turn; explicit path quiet. No pytest suite — ad-hoc only |
| Heredoc `.py` source writes “locked” | **PARTIAL / ESCAPABLE** | `io.open('foo.py','w')` **fires**; builtin `open('foo.py','w')` and `Path.write_text` **quiet** (same-turn probes) |
| RC-6 normalizer bleed stop | **FIXED (forward)** | `_RC6_CULLED` + filter `snapshot_normalizer.py:288-289` |
| RC-6 residue gone / debts paid | **REJECT** | Live still **1,380** non-null / ΣLENGTH **240,250,082** B (grew from v17’s 1,373) — drop still owed 08-09 |
| Region-scoped migrate test | **FIXED (narrow)** | `test_money_path_orphan_keys_v1.py:97-109` — ADD COLUMN regions; comment lines legal |
| “Every mechanizable class locked” | **REJECT as absolute** | E-32 **OPEN**; E-33 stated limit (honest); E-30 heredoc **incomplete**; guard escapes = restated incident |
| C4 / C1 / Decide / LP-01 untouched | **ACCEPT honesty** | Claude states; confirmed no money/UI/LP files in commit |
| RC-120 after-hours guard | **PARTIAL / DIRTY** | Row CLOSED in worktree; **not** in `580172be`; stop_guard filter dirty |

---

## Critical hole — v17 inbox invisibility

```
gate_best = 16
files include: claude_finish_adversarial_audit_v17_deep.md  # does NOT match _v(\d+)\.md$
receipts_for_best → RC-117 prose containing "v16" + "processed"
v17_mentions → RC-119 "audit v17 processed" (prose only; gate never asks for v17)
```

So: Claude can write “audit v17 processed,” commit RC-119, and the ENFORCED inbox still only polices **v16**. The deep audit that drove the day’s work is the exact absence-of-signal class RC-118 claimed to kill — renamed with a suffix that drops it out of the glob.

**To make the claim true mechanically:** add/rename to `reports/claude_finish_adversarial_audit_v17.md` (or widen the glob) **and** require a receipt line for that N.

---

## Guard probe matrix (same-turn)

| Action | Fired? | Note |
|---|---|---|
| `git add -A` / `--all` / `.` | YES | Claim OK |
| `git add tools/foo.py` | NO | Sanctioned |
| heredoc + `io.open('x.py','w')` | YES | Incident-shaped |
| heredoc + `open('x.py','w')` | **NO** | **ESCAPE** |
| heredoc + `Path('x.py').write_text` | **NO** | **ESCAPE** |
| heredoc + `io.open('…md','w')` | NO | Governance path OK by design |

Fire-and-quiet for blind-stage: **proven ad-hoc**. Heredoc class: **not** invariant-locked (open/Path evade). **No** dedicated pytest for either guard rule found under `tests/`.

---

## E-25..E-33 census vs locks

| ID | Claude status | Cursor grade |
|---|---|---|
| E-25 memo name-count | LOCKED (earlier) | prior FIXED (money agent) |
| E-26 normalizer bleed | LOCKED | **FIXED forward** / residue OUTSTANDING |
| E-27 region migrate test | LOCKED | **FIXED narrow** |
| E-28 receipt form | LOCKED | **FIXED narrow**; v17 file still orphan |
| E-29 RC-118 inbox | LOCKED | **PARTIAL** — exists; highest-N hole |
| E-30 heredoc source | LOCKED | **PARTIAL** — `io.open` only |
| E-31 blind staging | LOCKED | **FIXED narrow** |
| E-32 wrong-victim proof | OPEN | **OPEN** (honest) |
| E-33 prose overclaim | STATED LIMIT | **ACCEPT** |

---

## Program guns (unchanged — ACCEPT)

Still OUTSTANDING exactly as v17: **LP-01**, **W3-C4**, **W3-C1**, **Decide**, RC-6 supervised drop, RC-107/58.

---

## RC-120 (dirty)

Exempts `refresh_active is False` in `stop_guard.freshness_blockers`; `data_faucet_audit` attaches `refresh_active` from `levels_refresh_active`. Ledger row already **CLOSED** in dirty tree — premature relative to commit. Re-audit after it lands.

---

## Top burns (if locking continues)

1. Rename/register `v17` so RC-118’s highest-N includes the deep audit (or change glob).  
2. Widen heredoc ban to `open(` / `Path.write_text` / `>` redirects on `.py`.  
3. Pytest both guard rules (fire + quiet), not `python -c` folklore.  
4. Then operator fork: **LP-01** | **P0b** | **DECIDE**.

---

## Agent merge ([Audit Claude 580172be locks](52b85bee-a0ff-4c02-a260-028a69a59d36))

Additive (verdict unchanged):

| Add | Proof |
|---|---|
| Blind-stage also escapes `git add *`, `git add -- .`, `git add -u` | probe vs `_BLIND_STAGE` `:105` |
| Tracked-only inbox highest = **v9** (`git ls-files`); untracked audits drive live gate | worktree hygiene hole |
| RC-118 control lacks assert that bare incidental `answered v99` now fails | incomplete negative control |
| RC-120 CLOSED while uncommitted | **FAKE_CLOSE** timing |

---

## Status line

`CLAIM: PARTIAL locks @580172be — SYNTHESIZED w/ explore; receipt+normalizer real; heredoc+blind-stage escapable; v17_deep invisible (best 16@commit, 18 now); RC-120 dirty FAKE_CLOSE; program guns untouched · DONE: v18 · NEXT: operator · BLOCKER: none`
