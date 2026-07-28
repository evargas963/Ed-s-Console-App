# BRUTAL ADVERSARIAL AUDIT v5 — 2026-07-27 ~22:16 CT

**HEAD:** `2c214142` (RC-100 orphan deletes) on top of `9d67ff27`  
**Verdict:** **SCOPED ACCEPT on lock-set + scorecard producer path · GLOBAL REJECT on “finished.”**

---

## Headline

Lock-failure set remains **35/35 CLOSED** (re-confirmed). Claude’s RC-100 work is **partially honest** (challenged our “safe delete” list with measurement). The repo is **not finished**: RC-31 / RC-58 still open with unfinished markers, coach sample still thin, scorecard artifact is now **gitignored** (works only where a local run left a file), and Wave-1 dual-faucet / UI multi-writer defects are untouched.

---

## Same-turn evidence

| Check | Result |
|---|---|
| Lock monitor | `ALL_FIXED closed=35/35` |
| Scorecard API | `stale=false`, `age_trading_days=0` |
| Evening UTC age | `0` (ET conversion still holds) |
| Wall hold sample | **call_n=1, put_n=2** — thin; 100% rates are noise |
| Scorecard on disk | True (local leftover) |
| Scorecard **git tracked** | **False** — removed + gitignored in `2c214142` |
| Task Last Result | 0; next run 2026-07-28 16:45 |
| `rc_citations_resolve` / inert / agents_laws / root_cause_log / faucet | all **0** |
| Scorecard stale tests | **5 passed** |
| Deleted orphans claimed | `_tmp_ablation_*`, `_enumerate_all_defs`, `_phase_b_*`, `_build_section10/16`, etc. **gone** |
| `_build_section1_inventory.py` | **still present** (provenance-blocked — matches Claude’s claim) |
| RC-58 residual studies | `study_card2_am_pm`, `timeslice_reversal`, `card_lateday`, `gex_r1_screen`, `gamma_conditioned` — **calendarish=False** |
| RC-31 TCN `_load_closes` | still present; **no RTH/session filter in load window** |
| UI | `consoleSpot` + `edLiveSpot` both exist; **`levels_stale` absent from index.html** |

---

## What Claude did well (credit ≠ discharge)

1. **RC-100 measurement beat the audit list** — only 8 deletable now; 20 blocked by provenance ledger. Correct distinction: mention ≠ dependency; dangling ledger pointers are RC-99-class.
2. Named the AGENTS.md SOFT **E-14** failure (gate green on uncommitted tree). SOFT labels now committed.
3. Added `tools/verify_dead_code_orphans_v1.py` — mechanism for removal, not only a one-shot delete.
4. Locked scorecard producer path still green locally.

---

## Hard findings (blocking a global “finished”)

### F1 — OPEN debt with unfinished markers
- **RC-31 OPEN / NOT FIXED** — overnight bleed into TCN/HAR/Kalman loaders. Confirmed still open in code.
- **RC-58 OPEN / PARTIALLY FIXED** — five listed study/research tools still lack trading-day gates (`calendarish=False` this turn).
- **RC-55 REMEDIATED** with fix text starting **REFUTED** — ledger hygiene smell (not OPEN, but not clean).

### F2 — Scorecard artifact untracked (new fragility)
Commit `2c214142` **deleted** `reports/terrain_backtest_latest.json|.md` from git and gitignored them (RC-89 credential path).  
Local API still serves because a file remains on disk from an earlier run. A fresh clone / clean CI machine has **no artifact** until the bat runs → coach empty/`stale` until ops runs. Producer path is live; **committed evidence of coach data is gone**. That is a real tradeoff — acceptable only if explicitly owned as “ops generates, git never stores.”

### F3 — Coach still not fixed (Claude’s own honest limit still true)
`call_n=1`, `put_n=2`. Do not let “scorecard producer fixed” read as “coach is trustworthy.”

### F4 — Wave-1 pristine CRITICAL backlog untouched
Still present by static re-check:
- Dual client spot helpers (`consoleSpot` + `edLiveSpot`)
- Console never reads `levels_stale`
- (Prior money-path dual wall books / resolve_spot vs plane — not re-disproven this turn; not closed either)

### F5 — RC-100 not a full Wave-A clear
13 `_build_section*` generators remain (e.g. section1). Closure of RC-100 as “wave A done” is only true if the row’s acceptance was “8 proven orphans,” not “safe cluster cleared.” Read the RC-100 close text carefully before accepting.

---

## Verdict table

| Claim | Grade |
|---|---|
| Lock-set 35/35 done | **FIXED(verified)** |
| Scorecard producer + age math | **FIXED(verified)** locally |
| Phantom RC citations locked | **FIXED(verified)** |
| Dead-code Wave A complete | **PARTIAL** — 8 deleted, 20 blocked, RC closed on that scope |
| Overnight feature bleed (RC-31) | **OUTSTANDING** |
| Market-closed study set (RC-58) | **OUTSTANDING** |
| Pristine / world-class codebase | **REJECT** |
| “Finished” globally | **REJECT** |

---

## Paste for Claude

```
ADVERSARIAL v5 — GLOBAL FINISH REJECTED.

Lock-set 35/35 and scorecard producer path still verify. RC-100's "8 deleted /
20 provenance-blocked" measurement is honest and better than the audit's "safe"
list — credit that.

STILL NOT FINISHED:
1. RC-31 NOT FIXED — TCN _load_closes still session-blind.
2. RC-58 PARTIAL — study_card2_am_pm / timeslice / lateday / gex_r1 / gamma_conditioned
   still calendarish=False this turn.
3. Coach thin — call_n=1 put_n=2; your own honest limit still binds.
4. Scorecard JSON/MD gitignored+untracked — local leftover serves API; fresh tree has no
   committed coach artifact. Own that explicitly or restore a path-scrubbed committed sample.
5. Wave-1 UI: consoleSpot+edLiveSpot both live; index has no levels_stale.

Do not say finished until RC-31/58 are closed with MEASURED proof or left OPEN with
concrete next work — not a wrap-up.
```
