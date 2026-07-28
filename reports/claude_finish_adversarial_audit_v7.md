# BRUTAL ADVERSARIAL AUDIT v7 — 2026-07-28 ~07:20 CT

**HEAD:** `1f147f2b` (RC-104) atop `4b8fe09e` (RC-103) atop `bd979e44` (RC-31 class + RC-102)  
**Prior audit:** v6 @ `618a3780`  
**Verdict:** **NOT ALL FIXED · NOT PRISTINE · SCOPED CREDIT on real half-fixes · GLOBAL REJECT on “repo-wide finished”**  
**Lock map (this round):** `reports/claude_finish_lock_violations_v7.md` — ENFORCED gates were GREEN while CLOSED stamps failed adversarial blast-radius checks.

---

## Headline

Claude closed three more RCs after v6 and **did fix the HAR overnight-r² smoking gun** (same-turn re-proof: `har_features(ends,closes)[3,0] != overnight_r2`). That does **not** mean all issues are fixed repo-wide.

Still blocking pristine / “finished”:

1. **Kalman overnight innovation still spikes** (Mon-open innov ≫ prior bar) — RC-31’s own named victim never got `session_safe` treatment.  
2. **RC-102 CLOSED is still theater on the operator console** — visible `#cv2-kl-trust` ignores `levels_stale`; only hidden `#tv-trust` / `#terrain-view` was wired.  
3. **Wave-1 money-path CRITICALs untouched** (dual wall books, resolve_spot≠plane, auth carry-forward / QSD strip).  
4. **Landfill only partly burned** (RC-104: 2 deletes; shell / mockups / 13 section inventories remain).  
5. **RC-58 still OPEN** (re-validation unpaid); **LP-01 still NEXT** (not started as product work).  
6. **RC-103** is a real *new-reader* door with a **38-file grandfather** — not “the table is clean.”

OPEN RC count this turn: **RC-58 only** (+ RC-55 REMEDIATED). Closed stamps ≠ pristine.

---

## Post-v6 commits (what Claude claimed)

| Commit | Claim | This-turn grade |
|---|---|---|
| `bd979e44` | RC-31 CLASS close via `session_safe_log_returns` + HAR rewrite; RC-102 console staleness + edLiveSpot delegate; scheduled-jobs inventory | RC-31 **PARTIAL**; RC-102 **FAKE_CLOSE** (visible console) |
| `4b8fe09e` | RC-103 RTH lock reaches `price_bars_1m` | **FAKE_CLOSE** vs v6 directive — `_RTH_MARKET_READ` still omits table; parallel door + 38 grandfathered |
| `1f147f2b` | RC-104 landfill: 2 proven deletions, 1 held | **PARTIAL** — honest hold; list incomplete |

Independent confirm: [post-v6 Claude fixes](626d761e-5b2d-484a-bc20-8d1ca783616d) — same grades; adds `ml_train` overnight `diff`, quantile NaN assemble, string-mention loophole on RC-103.

---

## Same-turn evidence

| Check | Result |
|---|---|
| pytest RC-31 + faucet + calendar gates | **20 passed** |
| HAR overnight r² in features | **FIXED** — `f[3,0]==overnight? False`; gap NaN’d |
| `session_safe_log_returns` | **EXISTS** — used by HAR / cross-asset / quantile / survival / cost_aware rets |
| Kalman innov at Mon open | **STILL BLEEDS** — `\|innov[2]\| ≈ 0.0178` ≫ `\|innov[1]\|` (~18×) |
| `_load_labeled_rows` session gate | **STILL ABSENT** |
| TCN `_build_xy` uses shared primitive? | **NO** — still raw `np.diff` + window exclude (OK if exclude holds; dual path) |
| `#cv2-kl-trust` reads `levels_stale`? | **NO** — `trusted = confidence === 'TRUSTED'` only (`index.html:13046–50`) |
| `#tv-trust` / `_lvStale` | **YES** — on hidden terrain-view path |
| `_RTH_MARKET_READ` includes `price_bars_1m`? | **NO** — separate `check_price_bars_readers_name_their_session` + `_PRICE_BARS_GRANDFATHERED` (38) |
| `adaptive_shadow` JSON | **DELETED** |
| `step3_benchmark_*.ps1` | **DELETED** |
| `console_v2_shell.html` | **STILL TRACKED** (17.8 KB) |
| `operator_trust_backtrack.py` | **STILL PRESENT** (held — gate config ref; Claude named it) |
| `design_mockups/` | **STILL TRACKED** (4 files) |
| `_build_section*_inventory.py` | **13** remain |
| RC table | CLOSED≈100; **OPEN: RC-58**; REMEDIATED: RC-55 |
| LP-01 | **NEXT** in `ACTIVE_PROGRAM.md` |
| Auth carry-forward → `record_quote` | **STILL** early-return without plane write (`server.py:3010/3029/3043`) |

---

## Grades (repo-wide blockers from v6 → v7)

| Item | v6 | v7 |
|---|---|---|
| RC-31 HAR overnight r² | FAKE_CLOSE | **FIXED(verified)** |
| RC-31 class (all named victims) | FAKE_CLOSE | **PARTIAL** — Kalman + labels + named NEXT-DEPTH thresholds open |
| RC-58 loader gates | PARTIAL | **PARTIAL** — still OPEN for re-validation (correct) |
| RC-101 coach commit | FIXED | FIXED (unchanged) |
| RC-102 visible console staleness | theater | **FAKE_CLOSE** — CLOSED stamp; `#cv2` / `#cv2-terrain` still blind |
| RC-103 price_bars door | OUTSTANDING | **FAKE_CLOSE** vs “extend `_RTH_MARKET_READ`”; door+grandfather theater |
| RC-104 landfill | OUTSTANDING | **PARTIAL** — 2 gone; shell/mockups/sections remain |
| Dual wall/flip books | OUTSTANDING | **OUTSTANDING** (no post-v6 touch) |
| resolve_spot ≠ plane display | OUTSTANDING | **OUTSTANDING** |
| Auth-degraded / QSD strip | OUTSTANDING | **OUTSTANDING** |
| LP-01 institutional levels | NEXT | **NEXT / not done** |
| Pristine / all fixed | REJECT | **REJECT** |

---

## Hard findings

### F1 — RC-31 “CLASS close” still incomplete (Kalman)
HAR path is fixed and locked by directed tests. **Kalman was named in the original RC-31 row** and still runs `kalman_ll_trend` over concatenated log-prices with **no** session reset / gap handling — overnight jump enters as innovation (proven this turn). `_load_labeled_rows` still session-blind. Claude’s own commit admits NEXT-DEPTH on cost_aware/survival `np.diff` thresholds.

**Directive:** reopen or open RC-31b for Kalman (+ label gating + threshold diffs). Do not leave CLASS CLOSED while a named victim bleeds.

### F2 — RC-102 CLOSED rejected for visible console
`#cv2-kl-trust` and footer still ignore `levels_stale`. Operator Console v2 is the live surface; wiring `#tv-trust` on hidden `#terrain-view` does not discharge the defect. Multi-writer paint clocks not collapsed.

**Directive:** wire staleness into `#cv2-kl-trust` + footer; demote TRUSTED when stale; then re-close.

### F3 — Money-path Wave-1/2 CRITICALs untouched (re-proven)
Independent confirm: [money-path still open](19e79538-f638-4c41-8a6b-447081efe3fe) — **all six checks OUTSTANDING, none FIXED/PARTIAL** at `1f147f2b`: dual wall books; resolve_spot→plane overwrite; auth carry-forward skips `record_quote`; QSD strip; `cv2-hd-px` multi-writer; admission blob + `final_bias` horizon paint + 5c meta bypass. Also still live: W2-C8 `_RTH_MARKET_READ` omits `price_bars_1m`; RC-6 re-ADD hazard.

### F4 — Landfill PARTIAL (RC-104 honest but thin)
Credit: 1.84MB JSON + step3 ps1 gone; hold on `operator_trust_backtrack` named with governance reason. Remaining delete-now: `console_v2_shell.html`, `design_mockups/`, `mutation_raw/`, archive tests; section inventories only with cull-ledger burn.

### F5 — RC-103 FAKE_CLOSE vs the written directive
v6/Wave-2 asked to extend `_RTH_MARKET_READ` to `price_bars_1m`. What shipped: a **separate** check with 38 grandfathered (incl. live F2 `data_loader.py` / `challenger_eval_v1`). Loopholes: string-mention of `_load_closes`/`session_safe_log_returns` passes; `# session-universe-ok` escape; scope limited to `tools/`+`research/` (not `server.py`/`ml_train.py`).

### F6 — Operator NOW (LP-01) not advanced
Queue still says LP-01 NEXT. Claude’s work was lock/landfill hygiene, not institutional VP/liquidity surface.

---

## Credit (earned)

1. Reproduced v6 HAR poison, then fixed with required `ends` + NaN exclusion + directed regression tests.  
2. Shared `session_safe_log_returns` primitive (right shape for a class fix).  
3. RC-103 grandfather list is visible and addition-prohibited (correct ratchet shape).  
4. RC-104 named the hold instead of silent skip.  
5. `governance/host_scheduled_jobs.md` inventory landed.

---

## Claude directives (ordered)

1. **Kalman (+ labels)** — session-safe or day-reset filter; reopen RC-31 class until green.  
2. **RC-102 for real** — `#cv2-kl-trust` / footer consume `levels_stale`; collapse paint writers.  
3. **P0 money-path** — one wall book + one spot clock + auth/QSD into plane (Wave-1 P0–P1).  
4. **Landfill P0** — delete shell + `design_mockups/`; plan ledger+section inventory burn.  
5. **RC-58 re-validation** or stop citing gated-era KPIs.  
6. **LP-01** when product work resumes — still operator NEXT.

---

## Parallel agents (this turn)

- Post-v6 fix audit — **merged** ([post-v6 Claude fixes](626d761e-5b2d-484a-bc20-8d1ca783616d)): RC-102/103 FAKE_CLOSE; RC-31/104 PARTIAL; LP-01 NEXT  
- Money-path re-proof — **merged** ([money-path still open](19e79538-f638-4c41-8a6b-447081efe3fe)): 6/6 CRITICAL OUTSTANDING

---

## Verdict line

`CLAIM: not all issues fixed repo-wide — HAR fixed; Kalman + cv2 staleness + Wave-1 money-path + landfill remainder open · DONE: v7 audit · NEXT: Claude directives F1–F4 · BLOCKER: pristine / finished`
