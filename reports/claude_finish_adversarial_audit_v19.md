# BRUTAL ADVERSARIAL AUDIT v19 — 2026-07-28 ~16:40 CT

**HEAD:** `891080b4` — `v18 guns fixed: inbox sees suffixed audits; guard locks widened to all spellings.`  
**Prior commit:** `c62d5e9f` RC-120 (confirms v18 “dirty mid-turn” catch)  
**Prior audit:** v18 @ `580172be`  
**Verdict:** **ACCEPT** the three named v18 guns as fixed · **PARTIAL** on “airtight / all spellings” · program guns still **OUTSTANDING** · overnight wrap OK as lock hygiene, not repo-finished

---

## Charter

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — verify Claude’s v18-gun repair |
| GAP | Claimed three fixes + receipt vs residual escapes |
| SMALLEST_COMPLETE_CHANGE | This report |
| EVIDENCE | Live gate + guard battery + ledger line |
| DECISION_PATH_EFFECT | none |
| WHY_NOW | Operator pasted Claude wrap |
| TASK_ADMISSION | audit only |

---

## What shipped (`891080b4`, 3 files, +16/−4)

| Path | Change |
|---|---|
| `tools/check_institutional_correctness.py` | `_v(\d+)` anywhere in name (was `_v(\d+)\.md$`) |
| `tools/operator_law_guard.py` | Widen blind-stage + heredoc patterns |
| `governance/root_cause_log.md` | RC-119 cell: **Audit v18 processed…** |

---

## Three v18 guns — same-turn re-proof

| Gun | Grade | Evidence |
|---|---|---|
| Suffixed inbox (`_v17_deep`) | **FIXED** | `best=18` (includes `v17_deep`); was 16 under old regex. `check_adversarial_audits_are_answered()` = `[]` |
| v18 receipt | **FIXED** | Ledger L167: `Audit v18 processed same day (PARTIAL ACCEPT with three real guns, all fixed)` — same-line `audit`+`v18` |
| Heredoc `open()` / `Path('x.py').write_text` | **FIXED** (named spellings) | Both **fire** same-turn |
| Blind `*` / `-- .` / `-u` / `--update` | **FIXED** (named variants) | All **fire**; `git add -- server.py` and explicit path **quiet** |

---

## Residual / honesty grades

| Claim | Grade | Note |
|---|---|---|
| “All spellings” / airtight | **PARTIAL** | Still escape: `Path('x.py').open('w')`, `p.write_text` after `p=Path(...)`, `cat > foo.py <<EOF`. Variable-path AST boundary **stated** (ACCEPT). `Path.open` / shell-redirect **not** named in Claude wrap |
| 9-fire / 5-quiet battery | **PARTIAL** | Reproduced in spirit (10/11 fire on widened set; 5/5 quiet). **Still no pytest** — ad-hoc `python -c` folklore |
| `17/17 controls` + gate PASS | **ACCEPT** (narrow) | `pytest tests/test_enforced_check_negative_controls_v1.py` → **17 passed**; RC-118 green for v18 |
| RC-120 committed | **FIXED** | `c62d5e9f` on branch; no longer dirty-only |
| RC-6 residue cleared | **REJECT if claimed** | Claude correctly says standing pool for 08-09 drop — residue not cleared this pass |
| Program guns untouched | **ACCEPT** | No C4/C1/Decide/LP-01 in commit |
| “Nothing needed tonight” / 24 commits | **OUT OF SCOPE** | Lock hygiene pass closed; **fork still open** when you resume |

---

## Probe matrix (Cursor, this turn)

**Fire:** `-A`, `--all`, `.`, `*`, `-- .`, `-u`, `--update`, heredoc `io.open`, `open`, `Path().write_text` → blocked.  
**Quiet:** explicit path, `git add -- server.py`, heredoc `.md`, var-path `open(p)`, `cat > foo.py` redirect.  
**Extra escape (new):** `Path('foo.py').open('w')` → **quiet** (not in widened regex).  
**Borderline:** `git add -u server.py` still fires (flag-blind; may be intended).

---

## Scorecard vs Claude narrative

| Narrative line | Cursor |
|---|---|
| Three v18 guns fixed | **ACCEPT** |
| Inbox saw its own repair (v18 red until cited) | **ACCEPT** |
| Heredoc AST/variable limit stated | **ACCEPT** |
| Blind-stage `-- path` legal | **ACCEPT** |
| Airtight / every spelling | **PARTIAL** — Path.open + shell redirect remain |
| Program guns fork-ready | **ACCEPT** — still OUTSTANDING |

---

## Status line

`CLAIM: ACCEPT three v18 guns @891080b4; PARTIAL airtight (Path.open + redirect escape; no guard pytest); RC-120 committed; program guns still open · DONE: v19 · NEXT: operator fork when ready · BLOCKER: none`
