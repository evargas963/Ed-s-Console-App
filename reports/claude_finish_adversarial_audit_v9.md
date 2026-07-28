# BRUTAL ADVERSARIAL AUDIT v9 — 2026-07-28 ~09:05 CT

**HEAD:** `5418054f` — `RC-106: close contract — declared, checkable reach (operator lock directive) + v8 victims.`  
**Prior audit:** v8 @ `235ebb3a`  
**Verdict:** **REAL progress on the meta-lock + several v8 victims · NOT “finished” · several claimed locks are still optional / word-shaped / cutover-blind**

Focus this turn: (1) site fixes Claude shipped, (2) **every mechanical lock he claims is in place**, (3) **what he admits is not**, (4) **holes the claim still hides**.

---

## Headline

| Claim | Grade |
|---|---|
| RC-106 close contract mechanized | **PARTIAL** — real ENFORCED cutover schema; still tag-presence + cutover-scoped; does **not** require symptom victims ⊆ `FIXED:` |
| v8 victims: cv2/ct-trust tests + paint | **FIXED** (surface + surface-bound tests) — RC-102 correctly **PARTIAL** until DOM proof |
| v8: price_bars comment mention loophole | **PARTIAL** — comments stripped; **file-wide code mention** still passes; **38** grandfathered |
| v8: Kalman continuous API | **FIXED** as rename/privatize (`_kalman_ll_trend_one_day`) — session wrapper already existed |
| v8: flip_drift landfill | **FIXED (git)** — removed from index + `.gitignore`; file may still exist on disk as live sink |
| `verify_dead_code --check` as a lock | **FAKE_AS_LOCK / OPTIONAL** — exit 2 only with `--check`; **not** in ENFORCED `CHECKS` |
| Thresholds / RC-31 class remainder | **HONEST OPEN** as **RC-107** |
| Money-path Wave-1/2 (6 CRITICALs) | **OUTSTANDING** — commit did not touch `server.py` / plane / gate |
| Repo / “finished” | **REJECT** |

Same-turn gates: `five_why` / `rc_schema` / `price_bars` = **0** (GREEN). Close-contract negative control + surface-bound faucet tests = **3 passed**.

Independent confirm: [v9 lock holes prove](a934ce34-e800-46af-9645-6df2a3557029) — same grades; adds Stop-hook escapes (`ED_STOP_GUARD=off`, `stop_hook_active` one-shot) and **no AST lock** against reintroducing public `kalman_ll_trend`.

---

## 1. What Claude shipped (`5418054f`)

| Path | Change |
|---|---|
| `tools/check_institutional_correctness.py` | RC-106 close-contract rules inside `_five_why_lock_violations`; price_bars comment-strip |
| `tests/test_enforced_check_negative_controls_v1.py` | 9 close-contract shapes |
| `tests/test_client_spot_single_faucet_v1.py` | `#cv2-kl-trust` window bind + enumerate all `*trust*` chips |
| `static/index.html` | `#ct-trust` fail-closed on `levels_stale` |
| `research/kalman_eval_v1/runner.py` | privatize continuous filter |
| `tools/stop_guard.py` | front-end close-contract blockers |
| `tools/verify_dead_code_orphans_v1.py` | `--check` → exit 2 if `deletable_now` |
| `AGENTS.md` | close-contract law naming enforcer |
| `reports/flip_drift_log.jsonl` | untracked + gitignored |
| `governance/root_cause_log.md` | RC-106 CLOSED; RC-102 → PARTIAL; RC-107 OPEN; RC-31 OUT-OF-SCOPE → RC-107 |

---

## 2. Mechanical locks — claimed vs actual

| Lock | Claude claim | Actual enforcement | Grade | Smoking gun |
|---|---|---|---|---|
| Close contract `FIXED:` | ENFORCED post cutover | ENFORCED for rows **opened ≥ 2026-07-28** — requires **tag presence**, not victim coverage | **PARTIAL** | Injected `FIXED: labels only` with symptom “Kalman bleeds” → **0 hits** (same-turn) |
| Close contract ban `pending` on CLOSED | ENFORCED | ENFORCED post-cutover (backticks stripped) | **FIXED** (narrow) | Negative control fires; RC-102 flipped to PARTIAL |
| `VISIBLE_SURFACE:` + id in static + id in tests | ENFORCED | ENFORCED when hyphenated `#dom-id` appears in row; “test binds” = **id substring anywhere in tests corpus** | **PARTIAL** | Injected tests_corpus=`mentions cv2-kl-trust somewhere` → **0 hits** |
| `OUT-OF-SCOPE:` needs RC/register | ENFORCED | ENFORCED post-cutover | **FIXED** (narrow) | Negative control + RC-106 uses RC-107 |
| Pre-cutover CLOSED rows | (implied covered by “the lock”) | **Exempt** from RC-106 rules | **HOLE** | **RC-103** opened `2026-07-27`, status CLOSED, fix cell has **pending**, **no `FIXED:`** — five_why still GREEN |
| END-TO-END substring | still required | Still required | **unchanged word check** | Lines ~294–299 |
| price_bars authorities in CODE not comments | closed mention loophole | Comment lines stripped before `_PRICE_BARS_CAL_RE` | **PARTIAL** | File-wide **code** mention of `_load_closes` still satisfies; grandfather **EXACT 38** |
| `verify_dead_code_orphans_v1 --check` | “gains --check (exit 2)” as lock | **Opt-in CLI only**; default still exit 0; **not** in `CHECKS` | **FAKE_AS_LOCK** | `dead_in_CHECKS` same-turn = only `orphan_dict_keys`; no `verify_dead_code` |
| stop_guard close contract | front-end blocks turn | Calls `check_five_why_recursive_lock()` | **FIXED** (front) | `tools/stop_guard.py` `close_contract_blockers` |
| Trust-chip class tests | surface-bound | Real window asserts + class enumeration | **FIXED** | `test_visible_cv2…`, `test_every_trust_chip…` |
| RC-105 7-cell schema | (prior) | ENFORCED | **FIXED** | unchanged |
| Symptom⊆FIXED∪OUT-OF-SCOPE auto | (operator directive ideal) | **ABSENT** | **ABSENT** | Not implemented; Claude’s FIXED: is author-declared |
| Money-path single-faucet / walls / QSD | not claimed this commit | Untouched | **OUTSTANDING** | Diff excludes `server.py`, `live_market_plane.py`, `decision_gate.py` |
| Agent truth / fair-method | still SOFT in AGENTS.md | SOFT by design | **HONEST SOFT** | AGENTS.md labels |

---

## 3. What Claude explicitly says is NOT done (credit for honesty)

| Admission | Status | Grade of honesty |
|---|---|---|
| RC-102 rendered-DOM proof | status **PARTIAL** | **GOOD** — matches v8 |
| Session-blind thresholds | **RC-107 OPEN** (due 2026-08-07) | **GOOD** |
| OUT-OF-SCOPE on RC-106 → RC-107 | declared with tracker | **GOOD** |
| AGENTS SOFT laws (goodwill, fair-method, agent truth, immune) | still marked SOFT | **GOOD** (unchanged) |
| RC-103 burn-down / 38 grandfather | remainder named | **PARTIAL honesty** — row still **CLOSED** with **VERIFICATION PENDING** text pre-cutover, so new lock cannot see it |

---

## 4. Site-fix re-proof (v8 victims)

| Victim | Result |
|---|---|
| `#cv2-kl-trust` + `levels_stale` | Still wired; **new** test binds paint window (not file-wide substring) — **FIXED** vs v8 theater |
| `#ct-trust` | Now `_ctStale = !!t.levels_stale` — **FIXED** |
| Class enumeration test | Finds every `id="…trust…"` — **FIXED** shape |
| Kalman continuous public API | Renamed `_kalman_ll_trend_one_day` — **PARTIAL** hygiene (no AST/CHECKS lock against a public `kalman_ll_trend` returning) |
| flip_drift in git | Untracked + gitignored — **FIXED**; on-disk 530KB file may remain as live sink (expected) |

---

## 5. Residual blast radius (still blocking “finished”)

1. **FIXED: does not measure coverage** — author can omit named victims; machine only sees the word `FIXED:`.  
2. **Cutover blind spot** — every CLOSED row opened before 2026-07-28 (incl. RC-103 with PENDING) skips the contract.  
3. **Test bind is still a substring** at the lock layer (better *tests* exist for RC-102, but the *gate* accepts any mention).  
4. **`verify_dead_code --check` is not a commit gate** — calling it a lock overclaims.  
5. **RC-107 + money-path 6/6 + 38 grandfather + 13 section inventories** still open/landfill.  
6. **Perf:** `check_five_why_recursive_lock` concatenates all `tests/**/*.py` each run (~90s measured) — real cost, not a correctness fail.

---

## Status line

`CLAIM: RC-106 is a real step from word→declared-reach, with honest PARTIAL/RC-107; FIXED coverage + pre-cutover PENDING + dead_code --check-as-lock are still holes; money-path untouched · DONE: v9 audit · NEXT: either tighten FIXED⊇symptom + wire --check into CHECKS or stop saying finished · BLOCKER: “finished” over PARTIAL meta-lock`
