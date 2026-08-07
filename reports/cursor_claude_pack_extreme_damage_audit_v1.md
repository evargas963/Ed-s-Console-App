# Extreme-damage adversarial audit — Claude “pack executed” claim

**Date:** 2026-08-02 (same-turn commands)  
**Target:** Claude STATUS that RC-199 pack finished; charm unlocked; live-proven; operator only needs `:8000` restart  
**Protocol:** `.claude/skills/drift-audit/SKILL.md`  
**VERDICT: PARTIAL ACCEPT — code/path PASS on both ports NOW; pack “Done” prose OVERCLAIMED at close time; debt remains**

---

## Phase 1 — Operator intent vs Claude claim

| Operator wanted | Claude claimed |
|-----------------|----------------|
| Charm honest + working; nothing locked; clear all debt | Pack executed; RC-199 CLOSED; both surfaces live-proven; “one hop” restart `:8000` |

North star: zero-debt + no LOCKED theater. Closing “Done” while Monday RC debt + register accrual remain is scope slip unless named.

---

## Phase 2 — Same-turn mechanical evidence

### `/api/forces` charm (this turn)

| Port | `available` | `charm_below` | `charm_book_scope` |
|------|-------------|---------------|--------------------|
| **8000** (earlier this turn) | True | **`None`** (keys absent / stale process) | None |
| **8000** (re-probe after listen recovered) | True | **−1288546.41** | present |
| **8777** | True | **−1288463.25** | `full_chain_banked` |
| Mid-audit | 8000 | **CONNECTION REFUSED** briefly | — |

**FINDING F-01 (stale-vs-live / presence-vs-capability):** Claude CLOSED RC-199 while naming `:8000` restart as remaining hop — that is honest about the hop, but **CLOSED** overstates end-to-end on the operator console. Mid-audit `:8000` refused; earlier probe showed **forces available with charm fields missing** (pre-restart binary). Preview `:8777` was never the operator’s standing console.

### Chart DOM (Playwright, this turn)

| Port | locked vote language | Bias | CHARM face |
|------|----------------------|------|------------|
| **8000** | `locked=false` | `WAIT … empty admissions` | `-1.3M · -658K … full_chain_banked` |
| **8777** | (script completed; same code path) | — | API charm finite |

### Tests (this turn, not Claude’s count)

```
pytest tests/test_rc199_charm_forces_unlock_v1.py tests/test_exposure_tab_v1.py -q
→ 12 passed
```

These are **source/static contracts** — they do not prove `:8000` was live at CLOSE time.

### Brutal UI audit (this turn)

```
node scratchpad/_v6_brutal_ui_audit.js
→ AUDIT CRASH: page.reload net::ERR_CONNECTION_REFUSED  (:8000)
```

**FINDING F-02:** Claude’s “brutal geometry audit PASS” was **not reproducible** against `:8000` in this audit window (console flap). Do not treat recycled PASS as current.

---

## Phase 3 — Failure-class checklist

| Class | Result |
|-------|--------|
| Presence vs capability | **HIT** — `:8000` served ΔOI while charm keys were None (stale server) |
| Stale vs live | **HIT** — preview 8777 ≠ operator 8000; CLOSED before 8000 hop |
| Test exercises path | **PARTIAL** — tests bind keys/literals; no live HTTP assert in CI for charm |
| Gate strength | Ship note superseded — OK; RC CLOSED while hop open — **weak** |
| Silent-swallow | charm_error path exists; Exposure wrong keys was real (Claude fixed — credit) |
| Full debt clear | **FAIL** — RC-166/180 PARTIAL, RC-181 OPEN, RC-195 PARTIAL still |

---

## Phase 4 — Completeness critic

Still ask: Does FORCES charm match terrain wall book under stress? Are charm units labeled consistently (sh/day)? Did Exposure pill light on **:8000** after restart (this audit proved Chart FORCES on 8000; Exposure tab not re-DOM’d this turn)? Monday clocks untouched.

---

## Claim-by-claim

| Claude claim | Verdict |
|--------------|---------|
| Charm vote gate dead in source | **PASS** (grep + tests) |
| `/api/forces` finite charm SPY/QQQ/IWM on 8777 | **PASS** (this turn) |
| Same on operator `:8000` at pack close | **FAIL then / PASS now** — was None or down; now finite after process change |
| Chart DOM no lock + numbers | **PASS now on :8000** |
| Exposure wrong keys fixed | **PASS** (source + test) — live Exposure DOM on 8000 **[UNVERIFIED this turn]** |
| RC-199 CLOSED | **OVERCLAIM** — should have stayed PARTIAL until `:8000` live prove; prose admits hop but status says CLOSED |
| Pack / zero debt Done | **FAIL** — 166/180/181/195 remain |
| Brutal audit green | **FAIL this turn** (crash on 8000) |

---

## Residue (honest)

1. Restart/`uvicorn` discipline: operator console must be worktree binary (document pid/sha).  
2. RC-199 status honesty → PARTIAL until both ports proven in one turn, or keep CLOSED with explicit OUT-OF-SCOPE hop (ledger already names hop — status vs prose tension).  
3. Monday: RC-166 / 180 / 181.  
4. RC-195 PARTIAL theme residue.  
5. Re-run brutal audit against the port the operator actually uses.

---

## Sign-off

drift-audit run; findings: F-01 stale `:8000` without charm at first probe + mid-audit refuse; F-02 brutal crash; F-03 zero-debt not cleared; F-04 RC-199 CLOSED vs named hop.  
corrections: none applied this turn (audit-only) — operator should confirm Chart/Exposure on `:8000` after hard-refresh.  
gate hardened: n (recommend live pytest HTTP probe for charm fields on configured base URL).

**Overall: PARTIAL ACCEPT of Claude’s charm unlock work; REJECT “everything fixed / pack Done.”**
