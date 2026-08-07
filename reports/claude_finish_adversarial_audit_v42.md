# Claude Finish Adversarial Audit v42 — LP-01 Step 4 RESIDUAL CLOSE

**Target commit:** `0d1a3e781f74444d637d9d08086bbf94205dcdc8` (no push; local HEAD)  
**Auditor:** Cursor (adversarial), 2026-07-30 ~17:13–17:25 CT  
**Protocol:** `reports/lp01_step_protocol_v1.md` — Step 4 residual close only  
**Prior:** v41 **PARTIAL** @ `e581447e` (flex-collapse gun at 1280×700)  
**Claude claim:** residual gun closed @ `0d1a3e78`; SHA parity after restart; Playwright two-viewport unclipped 19/19; 51 tests; RC-157 CLOSED; Enter-UX absent from commit blob; does **not** self-ACCEPT.

**Admission preamble (AGENTS.md):** MISSION_CLASS=Collect / Find & Prove (structure surface) · GAP=verify v41 residual “#rawlevels readable at 1280×700” closed · SMALLEST_COMPLETE_CHANGE=adversarial audit + protocol Step 4 ACCEPT · MINIMUM_SUFFICIENT_EVIDENCE=live PID/SHA + independent two-viewport CDP + API match + pytest 51 + commit purity · DECISION_PATH_EFFECT=none (structure-context only; Decide still WAIT) · WHY_NOW=Step 4 ACCEPT gate before Step 5 · TASK_ADMISSION=audit only; no Step 5 impl; no push.

**drift-audit run:** phases 1–7 this turn. Intent = protocol Step 4 Done (“Surface **raw** levels … on Chart (**visible**, not hidden `#main`)”) — residual gun was flex-collapse/clip at short desktop viewport, not canvas overlays, not Step 5. Mechanical: `/api/build` SHA; Chrome headless CDP census (`scratchpad/_audit_v42_viewport.js`, `_audit_v42_census2.js`) at 1600×1000 **and** 1280×700 (+ attack 1024×600); `/api/liquidity-snapshot` SPY/QQQ/RTY value match; `pytest tests/test_liquidity_engine.py` (auditor) → 51; `git show --stat 0d1a3e78`; Enter-UX symbol counts on commit blob; RC-157 FIXED reach; `check_five_why_recursive_lock` → 0 violations. `tools/enforce_all_rules.py --ast-callsites` N/A (CSS-only residual). Findings below. No product code correction (audit-only). Gate hardened: n/a (auditor).

---

## Verdict: **ACCEPT**

| Claim | Result |
|---|---|
| Commit `0d1a3e78` == HEAD == `/api/build` running_code; PID started after commit | **ACCEPT** |
| `#rawlevels` non-shrink CSS in committed blob (`flex:none; overflow:visible; min-height:fit-content`) | **ACCEPT** |
| Independent CDP @ 1600×1000: h≫2, unclipped, 19/19 in bounds | **ACCEPT** |
| Independent CDP @ 1280×700: h≫2, unclipped, 19/19 in bounds | **ACCEPT** |
| SPY DOM values match `/api/liquidity-snapshot`; QQQ settles; RTY honest empty | **ACCEPT** |
| Structure-only (no Decide/signal vocab on card) | **ACCEPT** |
| Step-4-residual-only commit (3 files, +31/−1); `commitChartTicker` / Enter `keydown` **ABSENT** from commit | **ACCEPT** |
| Steps 1–3 untouched; Step 5 not started | **ACCEPT** |
| pytest → 51; source non-shrink contract test present | **ACCEPT** |
| RC-157 CLOSED with FIXED reach; RC-156 VISIBLE_SURFACE honesty; five_why clean | **ACCEPT** |
| Canvas price-line overlays | **OBSERVED OK** — still readout card, not required by protocol |

**Why ACCEPT:** the v41 P0 gun (flex-collapse → h=2 + overflow:hidden clip at 1280×700) is closed with same-turn independent two-viewport proof. Presence is now capability: non-trivial height, `flex: 0 0 auto`, `overflow: visible`, `clipped_inside: false`, 19/19 `#rl-*` rows present and in-viewport at both required sizes.

**Why not PARTIAL:** residual Done word (“visible”) no longer fails at the named short desktop viewport.

**Soft residuals (do not reopen Step 4):** see §5.

---

## 1) LIVE / VIEWPORT FIRST (PROVEN this turn)

### Process / SHA

| Fact | Value | Method |
|---|---|---|
| uvicorn PID | `14704` | `/api/build` `process_id` + `Get-Process` |
| CommandLine | `python -m uvicorn server:app --host 0.0.0.0 --port 8000 …` | `Win32_Process` |
| process start | 2026-07-30 **16:47:10** CT | CreationDate / `process_started_at_utc=1785448030.318…` → 16:47:10−05:00 |
| commit AuthorDate | 2026-07-30 **16:46:15** −0500 | `git log -1 0d1a3e78` |
| start after commit | **yes** | 16:47:10 > 16:46:15 |
| HEAD | `0d1a3e781f74444d637d9d08086bbf94205dcdc8` | `git rev-parse HEAD` |
| `/api/build` | `running_code` = `checked_out_code` = `0d1a3e78…`; `repo_moved_past_process=false` | GET this turn |
| `startup_git_dirty` | `true` | worktree still has foreign Enter-UX hunk (served live; **not** in `0d1a3e78`) |
| Push | not performed | no `git push` |

### Independent two-viewport CDP (auditor this turn)

Method: `node scratchpad/_audit_v42_census2.js` against `http://127.0.0.1:8000/chart?ticker=SPY` (Chrome headless CDP). Claude’s `rl_viewport_proof.mjs` was **not** in-repo; numbers below are **not** Claude’s — re-measured.

| Viewport | `#rawlevels` h | flex | overflow | clipped_inside | required present | in_viewport | display/visibility |
|---|---|---|---|---|---|---|---|
| **1600×1000** | **179** | `0 0 auto` | `visible` | **false** | **19/19** | **19/19** | block / visible |
| **1280×700** | **211** | `0 0 auto` | `visible` | **false** | **19/19** | **19/19** | block / visible |
| attack 1024×600 | 237 | `0 0 auto` | `visible` | **false** | 19/19 | 12→**19** after `scrollIntoView` | block / visible |

v41 baseline at 1280×700 was h=**2**, overflow=hidden, clipped=true, rows_visible=false. That gun is closed.

At 1280×700 the card chrome bottom can sit slightly past the fold (`partially_below_fold:true` before scroll; bottom 716 vs vh 700) while **all 19 rows remain in-viewport** (`rows_out_of_view: []`). After `scrollIntoView`, card fully in frame (top 489, bottom 700). Body scroll recovers content — unlike v41 clip-inside-card.

**SPY value match** (DOM vs `/api/liquidity-snapshot?ticker=SPY&snapshot=live` via RL_SPEC path) — `spy_match_all: true` this turn, including overnight/ORB/VWAP±σ. Sample:

| id | API→DOM |
|---|---|
| rl-PDH | 742.68 |
| rl-PDL | 729.10 |
| rl-TODAY_POC / VAH / VAL | 741.59 / 742.42 / 737.44 |
| rl-ORB_HIGH / LOW | 736.79 / 734.63 |
| rl-VWAP / ±1σ / ±2σ | 738.78 / 740.99 / 736.56 / 743.21 / 734.35 |
| rl-OVERNIGHT_HIGH / LOW | 737.28 / 725.98 |

**QQQ after settle:** 19 rows; `pdh=680.05`, `poc=683.60`, `vwap=680.88` — `qqq_match_all: true`; not stale SPY.

**RTY absence:** API HTTP 404 (`No bar data for RTY…`). DOM: `empty="no structure levels for RTY in this session yet"`, `rl_src=unavailable`, `rows=0`, `required_present=0`, all values null — honest empty, zero stale.

**Structure-only:** `decide_vocab=false` (no TRADE/WAIT/AVOID/pool/sweep on `#rawlevels` text). Header still “reference prices, not a trade signal”.

---

## 2) CODE / COMMIT (PROVEN)

### Commit purity — Step-4-residual-only

`git show --stat 0d1a3e78`:

```
governance/root_cause_log.md   |  3 ++-
static/chart.html              |  9 +++++++++
tests/test_liquidity_engine.py | 20 ++++++++++++++++++++
3 files changed, 31 insertions(+), 1 deletion(-)
```

Committed CSS (blob):

```css
#rawlevels { flex:none; overflow:visible; min-height:fit-content; }
```

Enter-UX on **committed** blob (`git show 0d1a3e78:static/chart.html`):

| Symbol | Count |
|---|---|
| `commitChartTicker` | **0** |
| `keydown` | **0** |
| `_chartCommitInflight` | 2 (dangling clear left from `e581447e` strip — see soft) |

Worktree still dirty with full Enter-UX (`commitChartTicker` count=3) — **OK** per residual prompt; not in commit.

No `liquidity_value_engine.py` / overnight / zone-taxonomy edits → Steps 1–3 untouched.  
No Step 5 harness / touch-study files in the commit.  
`check_five_why_recursive_lock()` → **0 violations**.

### RC-157 FIXED reach

CLOSED row names FIXED victim: `#rawlevels` flex-collapse in `static/chart.html` CSS; END-TO-END CSS → card → 19 rows at every viewport; Steps 1–3 untouched; Decide unchanged. RC-156 amended with VISIBLE_SURFACE honesty (`#rl-empty` runtime-injected) and pointer to RC-157 residual close.

---

## 3) TESTS (PROVEN this turn)

```
.venv\Scripts\python.exe -m pytest tests/test_liquidity_engine.py -q
→ 51 passed in 5.44s
```

`test_chart_raw_levels_card_cannot_be_flex_collapsed` parses the `#rawlevels {…}` rule and requires `flex:none` **or** `flex-shrink:0` **and** `overflow:visible`. Not comment-only (regex on rule body). Soft: source-only — does not exercise live layout; live CDP this turn closes that gap.

---

## 4) ATTACKS

| Attack | Result |
|---|---|
| Other viewports still clip? | **No** at 1280×700 (required). Attack 1024×600: unclipped h=237; 7 rows briefly below fold until scroll — recoverable, not v41-class clip. |
| `#gammacard` eats space / pushes rawlevels off-screen without clip? | Soft yes at very short heights: gammacard stays `flex:1` (~280px); can push card partially below fold. **Not** the residual gun — content not clipped inside card; scroll recovers. |
| Test gameable (comments only)? | **No** — asserts tokens inside the CSS rule match. Still source-only. |
| Canvas still OBSERVED OK? | **Yes** — readout card; no price-line overlay in this residual. Protocol does not require canvas. |

---

## 5) Soft residuals (non-blocking)

1. **Dangling `_chartCommitInflight`** in committed `e581447e`/`0d1a3e78` blob (2 refs, no `let` / no `commitChartTicker`) — latent `ReferenceError` on clean checkout if that load path runs; worktree dirt masks it live. Out of residual-gun scope; clean separately if desired.  
2. **Very short viewports (e.g. 1024×600):** some rows below fold until scroll — acceptable vs clip-inside; not a Step 4 reopen.  
3. **Source test ≠ live layout** — CDP this turn is the live proof.  
4. **Canvas overlays** — still OBSERVED not-required.  
5. **Worktree Enter-UX dirt** — keep out of Step 5 commits unless that slice owns it.

---

## 6) Protocol update

- Step 4 → **ACCEPT** @ `0d1a3e78` — this file (`v42`)  
- Step 5 → **NEXT** (was BLOCKED)

---

## 7) Step 5 copy-paste prompt (exact protocol wording)

```
LP-01 Step 5 ONLY. Prior Steps 1–4 ACCEPT (Step 4 residual @ 0d1a3e78 — audit v42). No push.
Do NOT reopen Steps 1–4. Do NOT admit anything to Decide.

Protocol Step 5 (exact):
  End-to-end slice: Find & Prove gate: touch→5/15/30m vs TOD base, no lookahead;
  until PASS stay structure-only.
  Done when: Harness + report; money-path unchanged (WAIT); RC + commit.

Out of scope until Step 5 ACCEPT (protocol): Decide admission, RTY/XXT eviction,
$SPX full-basis, narrow Chart layout.

BINDING:
- Structure-only until the gate PASSes — no TRADE shaping, no decision-path admission.
- No lookahead. Touch→forward 5/15/30m vs time-of-day baseline.
- Money path unchanged (WAIT).
- Evidence-before-assertion; five-why + FIXED reach on any RC; close contract if CLOSED.
- Do not sweep foreign worktree Enter-UX into this commit unless it is required for
  the Step 5 harness (prefer leave dirty / hunk-stage).

PROOF required same turn:
1) Harness runs and writes a report artifact under reports/
2) PASS/FAIL criteria stated; if FAIL, stay structure-only (explicit)
3) pytest for the harness/gate green; RC CLOSED with FIXED reach
4) Commit Step-5-only; report SHA; do not self-ACCEPT
5) PID/SHA parity if any live surface is claimed

Cursor audits before any further step.
```

---

## Status line

`CLAIM:` Step 4 residual flex-collapse gun CLOSED — independent CDP 1600×1000 & 1280×700 unclipped 19/19; SHA `0d1a3e78`; 51 tests · `DONE:` v42 ACCEPT · `NEXT:` Step 5 (F&P touch→5/15/30m vs TOD; structure-only until PASS) · `BLOCKER:` none
