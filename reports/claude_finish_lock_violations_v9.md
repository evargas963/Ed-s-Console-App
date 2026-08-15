# Mechanical lock violations — Claude RC-106 “finished” (v9)

**HEAD:** `5418054f` · **Paired audit:** `reports/claude_finish_adversarial_audit_v9.md`  
**Same-turn:** `five_why` / `rc_schema` / `price_bars` = **0 GREEN**; close-contract + trust-chip tests **3 passed**.

Point: Claude **did** put a reach-shaped contract in place. Several things he calls locks are still **optional**, **tag-only**, or **cutover-exempt**. Green ≠ finished.

---

## 1. Locks Claude says are in place

| Claimed lock | ENFORCED commit gate? | Intent held? | Notes |
|---|---|---|---|
| Close contract `FIXED:` / ban pending / `VISIBLE_SURFACE` / tracked `OUT-OF-SCOPE` | **YES** (post `2026-07-28` open date) via `check_five_why_recursive_lock` | **PARTIAL** | Tag presence; no symptom⊆FIXED; test-bind = corpus substring |
| stop_guard front-end | **YES** (Claude Stop) | **YES** for post-cutover CLOSED rows | Same checker; escapes `ED_STOP_GUARD=off` / `stop_hook_active` ([v9 lock holes](a934ce34-e800-46af-9645-6df2a3557029)) |
| price_bars authorities in CODE not comments | **YES** (same price_bars check) | **PARTIAL** | Comment strip real; file-wide code mention + 38 grandfather remain |
| `verify_dead_code_orphans_v1 --check` | **NO** | **NO as lock** | Opt-in; not in `CHECKS`; default exit 0 |
| Trust-chip surface tests | pytest only | **YES** for those tests | Stronger than the gate’s substring bind |
| RC-105 schema | **YES** | **YES** (cells) | Not blast radius |

---

## 2. Locks / gaps Claude admits are NOT done (honest)

| Item | Where admitted | Still true? |
|---|---|---|
| RC-102 DOM proof | status PARTIAL | **YES** |
| Thresholds `np.diff` | RC-107 OPEN | **YES** |
| SOFT AGENTS laws | AGENTS.md | **YES** |
| RC-103 burn-down | prose remainder | **YES** (38 files) |

---

## 3. Gaps Claude under-states (machine still green)

| Gap | Why green | Why intent fails |
|---|---|---|
| Pre-cutover CLOSED+PENDING | RC-106 only if `opened >= 2026-07-28` | **RC-103** CLOSED 2026-07-27 with pending, no FIXED |
| `FIXED: labels only` while symptom names Kalman | Only checks `"FIXED:" in fix` | Coverage not measured (same-turn injection → 0 hits) |
| Test “binds” DOM id | `did[1:] in tests_corpus` | Mention theater at gate layer |
| dead_code “lock” | Not registered ENFORCED | Must pass `--check` manually |

---

## 4. Verdict line

`CLAIM: meta-lock moved from pure END-TO-END words to declared tags — real; finished claim fails on FIXED coverage, cutover blind spot, and dead_code --check theater · DONE: lock map v9 · NEXT: FIXED⊇symptom + CHECKS wiring or keep saying PARTIAL · BLOCKER: equating RC-106 land with repo finished`
