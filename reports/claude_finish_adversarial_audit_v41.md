# Claude Finish Adversarial Audit v41 — LP-01 Step 4

**Target commit:** `e581447e3f870a58d41c8dc1912a51df07d6c00d` (no push; local HEAD)  
**Auditor:** Cursor (adversarial), 2026-07-30 ~16:28–16:45 CT  
**Protocol:** `reports/lp01_step_protocol_v1.md` — Step 4 only  
**Prior ACCEPT:** Step 1 `6b1d0a9a` (v37) · Step 2 `5de6f568` (v38) · Step 3 `d320252c` (v40) — not reopened  
**Claude claim:** DONE @ `e581447e`; SHA parity; DOM proof; 50 tests; RC-156 CLOSED. OBSERVED by operator: readout card, not canvas overlay.

**Admission preamble (AGENTS.md):** MISSION_CLASS=Collect / Find & Prove (structure surface) · GAP=verify Step 4 “raw levels visible on Chart” · SMALLEST_COMPLETE_CHANGE=adversarial audit + protocol status · MINIMUM_SUFFICIENT_EVIDENCE=live PID/SHA + Chrome CDP DOM census + API value match + pytest re-run + commit purity · DECISION_PATH_EFFECT=none (structure-context only; Decide still WAIT) · WHY_NOW=Step 4 ACCEPT gate before Step 5 · TASK_ADMISSION=audit only; no Step 5 impl; no push.

**drift-audit run:** phases 1–7 this turn. Intent = protocol Step 4 (“Surface **raw** levels … on Chart (**visible**, not hidden `#main`)” / structure-context only) — not canvas overlays, not Step 5. Mechanical: `/api/build` SHA; Chrome headless CDP census (`scratchpad/_audit_v41_dom.js`, `_audit_v41_dom3.js`); `/api/liquidity-snapshot` SPY/QQQ/RTY; `pytest tests/test_liquidity_engine.py` (auditor); `git show --stat e581447e`; RC-156 VISIBLE_SURFACE vs static ids; test attack (id-bound vs substring). `tools/enforce_all_rules.py --ast-callsites` N/A (no Python arity change). Findings below. No product code correction (audit-only). Gate hardened: n/a (auditor).

---

## Verdict: **PARTIAL**

| Claim | Result |
|---|---|
| Commit `e581447e` == HEAD == `/api/build` running_code; PID started after commit | **ACCEPT** |
| Step-4-only commit (3 files, +242/−0); Enter-UX hunk **not** in commit | **ACCEPT** |
| Steps 1–3 untouched; Step 5 not started | **ACCEPT** |
| Chart fetches `/api/liquidity-snapshot`; `RL_SPEC` explicit unique ids; one spot authority | **ACCEPT** |
| Live SPY: 19 `#rl-*` rows; values match API; dupes `[]`; not under `#main` | **ACCEPT** (1600×1000) |
| Live QQQ after settle: levels match API (not stale SPY) | **ACCEPT** |
| RTY absence: honest empty, zero stale rows | **ACCEPT** |
| Structure-context only — no TRADE/WAIT/AVOID/pool/sweep on card | **ACCEPT** |
| pytest `tests/test_liquidity_engine.py` → 50 passed (auditor this turn) | **ACCEPT** |
| RC-156 CLOSED; VISIBLE_SURFACE static ids mostly honest; runtime ids test-bound | **ACCEPT** w/ soft wording note on `#rl-empty` |
| Readout card (not canvas lines) sufficient for protocol text | **ACCEPT** — protocol does **not** require canvas overlays |
| Card **reliably** operator-visible at desktop-ish viewports | **PARTIAL / FAIL** — at 1280×700 `#rawlevels` collapses to **h=2** with `.card{overflow:hidden}` → content **clipped** |

**Why PARTIAL (not ACCEPT):** protocol Done criterion is **visible**. Same-turn CDP at 1600×1000 reproduces Claude’s 1576×157 proof, but at 1280×700 (common desktop-ish) `#rawlevels` flex-shrinks to height **2px**, `overflow:hidden`, `clipped:true`, `rows_visible_estimate:false`. Presence in DOM ≠ readable surface (drift-audit presence-vs-capability). Body scroll cannot reveal content clipped inside a 2px card.

**Why not REJECT:** engine→API→DOM path works; SHA/commit purity; SPY/QQQ value match; RTY fail-closed; structure-only; 50 tests; canvas-overlay absence is **not** a protocol miss.

**Why not ACCEPT:** residual is on the Done word itself (“visible”), not a soft cosmetic.

---

## 1) LIVE FIRST (PROVEN this turn)

### Process / SHA

| Fact | Value | Method |
|---|---|---|
| uvicorn PID | `5436` | `Get-Process` / `/api/build` `process_id` |
| CommandLine | `python -m uvicorn server:app --host 0.0.0.0 --port 8000 …` | `Win32_Process` |
| process start | 2026-07-30 **16:13:56** CT | process CreationDate / `process_started_at_utc` |
| commit AuthorDate | 2026-07-30 **16:13:03** −0500 | `git log -1 e581447e` |
| start after commit | **yes** | 16:13:56 > 16:13:03 |
| HEAD | `e581447e3f870a58d41c8dc1912a51df07d6c00d` | `git rev-parse HEAD` |
| `/api/build` | `running_code` = `checked_out_code` = `e581447e…`; `repo_moved_past_process=false` | GET this turn |
| `startup_git_dirty` | `true` | worktree has **uncommitted** Enter-UX hunk in `static/chart.html` (served live from disk; **not** in `e581447e`) |
| Push | not performed | no `git push` |

Chart URL: `/chart` (and `/static/chart.html`). `/chart.html` → 404.

### Live DOM census (Chrome headless CDP, 1600×1000)

Method: `node scratchpad/_audit_v41_dom3.js` against `http://127.0.0.1:8000/chart?ticker=SPY`.

| Check | SPY result |
|---|---|
| `#rawlevels` computed style | `display:block`, `visibility:visible`, rect **1576×157**, top 505 |
| inside `#main` | **false** (`#main` absent on Chart) |
| `#rl-src` | `19 levels · live · 16:00 ET cutoff` |
| row count / duplicate ids | **19** / `[]` |
| All RL ids present | `rl-PDH`…`rl-VWAP_M2` (19/19) including VWAP ±1σ ±2σ |
| Header | `RAW STRUCTURE LEVELS — reference prices, not a trade signal` |
| Decide vocab on card | TRADE/WAIT/AVOID/pool/sweep = **false** |

**SPY value match** (DOM `.rl-val` vs `/api/liquidity-snapshot?ticker=SPY&snapshot=live` `raw_levels`, this turn):

| id | API | DOM | ok |
|---|---|---|---|
| rl-PDH | 742.68 | 742.68 | ✓ |
| rl-PDL | 729.1 | 729.10 | ✓ |
| rl-TODAY_POC | 741.59 | 741.59 | ✓ |
| rl-TODAY_VAH | 742.42 | 742.42 | ✓ |
| rl-TODAY_VAL | 737.44 | 737.44 | ✓ |
| rl-ORB_HIGH / LOW | 736.79 / 734.63 | same | ✓ |
| rl-VWAP / P1 / M1 / P2 / M2 | 738.7788 / 740.9936 / 736.564 / 743.2084 / 734.3492 | 738.78 / 740.99 / 736.56 / 743.21 / 734.35 | ✓ (fmt) |

**QQQ after ticker settle** (change → load): `pdh=680.05`, `poc=683.60`, `vwap=680.88`, 19 rows, `rl_src=19 levels · live · 16:00 ET cutoff` — matches QQQ API; **not** stale SPY.

**RTY absence:** API `404` `{"error":"No bar data for RTY on 2026-07-30"}`. DOM: `empty="no structure levels for RTY in this session yet"`, `rl_src=unavailable`, `rows=0`, `pdh/poc/vwap=null`, no stale SPY rows. (Note: `j = async u => (await fetch(u)).json()` does **not** throw on HTTP 404, so the err-branch string is unused; absence still fail-closed via missing `raw_levels`.)

### Visibility gun (PARTIAL)

| Viewport | `#rawlevels` h | overflow | clipped | readable? |
|---|---|---|---|---|
| 1600×1000 | **157** | hidden | no | **yes** |
| 1280×700 | **2** | hidden | **yes** (`scrollH=225`) | **no** |

Cause: `body` is a column flex packing `#layout` (`flex:1.4`) + `#gammacard` (`flex:1`) into `html,body{height:100%}`; `#rawlevels` defaults to `flex: 0 1 auto` (shrinkable) under `.card{overflow:hidden}`. Content is **clipped inside the card**, not merely below the fold — body scroll does not recover it. `checkFold()` / `#foldwarn` only watches `#gammacard`, not `#rawlevels`.

---

## 2) CODE (PROVEN)

### Commit purity — Step 4 only

`git show --stat e581447e`:

```
governance/root_cause_log.md   |   1 +
static/chart.html              | 130 +++++++++
tests/test_liquidity_engine.py | 111 +++++++++
3 files changed, 242 insertions(+)
```

- No `liquidity_value_engine.py` / overnight / zone-taxonomy edits → Steps 1–3 untouched.  
- No Step 5 harness.  
- `git show e581447e:static/chart.html` has **no** `commitChartTicker` / Enter `keydown` (stripped as claimed).  
- **OBSERVED:** worktree `static/chart.html` still carries that foreign Enter-UX hunk (`git diff e581447e -- static/chart.html` = +20/−6). Live uvicorn serves the dirty file. Does not pollute the commit blob; does affect live listeners.

### Spot authority / no derivation

- Fetch: `/api/liquidity-snapshot?ticker=${tk}&snapshot=live` in `load()`, separate promise.  
- `RL_SPEC` 5th column explicit ids (19 unique).  
- Distance uses `currentSpot()` only; `renderRawLevels` does not recompute level prices.  
- Ticker switch: `rawLevelsTicker` pending reset → `loading {tk} levels…` before fetch.

### RC-156 VISIBLE_SURFACE

Claims static: `#rawlevels` `#rl-grid` `#rl-src` `#rl-empty`.  
- First three are static body elements.  
- `#rl-empty` appears only inside JS `innerHTML` strings (not a body element until absence/loading). Close-contract “exist in static/” is file-true; wording “STATICALLY” is slightly overstated. Runtime `#rl-*` ids bound by `test_chart_declares_every_raw_level_row_with_a_unique_id` — honest.

---

## 3) TESTS (PROVEN this turn)

```
.venv\Scripts\python.exe -m pytest tests/test_liquidity_engine.py -q
→ 50 passed in 2.57s
```

### Attack on the 5 new tests

| Test | Strength | Gap |
|---|---|---|
| `test_chart_declares_every_raw_level_row_with_a_unique_id` | **Id-bound** — parses `RL_SPEC` last column; uniqueness; required set | Source-only (no live DOM) |
| `test_chart_raw_levels_card_is_visible_not_buried` | Asserts ids in file; not nested after `#main`; no `display:none` on open tag | **Does not** prove computed visibility / non-collapse; `#rl-empty` matched as substring in JS |
| `test_chart_reads_levels_from_the_engine_never_recomputes_them` | Bans `Math.max/min`, `reduce`, `* 2`, `/ 2` in renderer | Substring ban list (acceptable for this slice) |
| `test_chart_raw_levels_are_structure_context_not_a_signal` | Bans TRADE / pool / sweep / stop-run on surface slice | Source substring |
| `test_chart_raw_levels_fail_closed_on_absence` | Requires `!isFinite` omit, absence copy, `rawLevelsTicker` | Source-only; no runtime race test |

No test binds “`#rawlevels` must not flex-shrink under overflow:hidden” — the residual this audit found.

---

## 4) ADVERSARIAL answers

| Question | Answer |
|---|---|
| Readout card vs canvas overlays? | **Protocol accepts readout.** Exact Done text: “visible, not hidden `#main`” + “Rendered DOM proof; structure-context only”. Canvas lines are OBSERVED-not-required (RC-156 already notes this). |
| VWAP±σ distinct ids? | **Yes** — `rl-VWAP_P2/P1/M1/M2` + `rl-VWAP` live. |
| POC/VAH/VAL + PDH/PDL + ORB? | **Yes** — today + prior-day + ORB high/mid/low. |
| Hidden via CSS collapse / zero height / off-tab? | **Yes at 1280×700** — h=2 + overflow hidden. Not off-tab; not `display:none`. |
| Cache/stale ticker races remaining? | Pending reset works when `change`/`load` fires (RTY→QQQ proven). Soft: `j()` ignores HTTP status; dirty Enter-UX `_chartCommitInflight` never cleared (worktree-only). |
| Decide path influence? | **None.** No admission; card disclaimer; vocab clean. |

---

## 5) Residuals (block ACCEPT)

1. **P0 — `#rawlevels` flex-collapse:** give `#rawlevels { flex: none; }` (and/or stop clipping): must remain readable at 1280×700 with non-trivial height and non-clipped rows. Re-prove with CDP at 1600×1000 **and** 1280×700.  
2. **Soft — RC wording:** `#rl-empty` is runtime-injected; say so (or add a static empty node).  
3. **Soft — worktree dirt:** Enter-UX hunk still uncommitted in `static/chart.html`; keep it out of any Step-4 residual commit (hunk-stage).  
4. **Soft — `j()` HTTP status:** 404 JSON is treated as empty payload; acceptable fail-closed, but err message path is dead for HTTP errors.  
5. **Out of scope:** canvas price-line overlays; Step 5 touch study; RC-152/153 snapshot labelling.

---

## 6) Residual-close prompt (copy-paste for Claude) — **no Step 5**

```
LP-01 Step 4 RESIDUAL CLOSE only (v41 PARTIAL @ e581447e). Do NOT start Step 5. No push.

GUN (only): #rawlevels is not reliably operator-visible. Cursor CDP at 1280×700:
#rawlevels height=2, overflow:hidden (from .card), scrollHeight≈225, clipped=true,
rows_visible_estimate=false. At 1600×1000 it is fine (1576×157). body flex-packs
#layout+#gammacard into height:100%; #rawlevels shrinks (flex 0 1 auto) and clips.

FIX (smallest): in static/chart.html CSS, make #rawlevels non-shrinkable, e.g.
  #rawlevels { flex: none; }
Optionally also ensure the ladder is not clipped (overflow visible on that card only,
or min-height). Do NOT implement canvas overlays. Do NOT sweep the dirty Enter-UX
commitChartTicker/keydown hunk into this commit — stage hunks / verify git show --stat.

PROOF required same turn:
1) PID start after residual commit; /api/build running == HEAD == residual SHA
2) Chrome/CDP (or equivalent) at 1600×1000 AND 1280×700:
   - #rawlevels display block, visibility visible, height >> 2, not clipped
   - 19 SPY rows, values match /api/liquidity-snapshot
   - RTY honest empty, zero stale rows; QQQ settles to QQQ prices
3) pytest tests/test_liquidity_engine.py — still green; ADD a source test that
   #rawlevels CSS includes flex:none (or equivalent non-shrink contract)
4) RC-156 amend or tiny RC: FIXED names the flex-collapse victim; VISIBLE_SURFACE
   honest about #rl-empty runtime injection if you touch the row
5) Commit Step-4-residual-only; report SHA; do not self-ACCEPT

Prior ACCEPT Steps 1–3 stand. Cursor audits again before Step 5.
```

---

## Status line

`CLAIM:` Step 4 surface path works (API→DOM, SHA, 50 tests) but visibility fails at 1280×700 flex-collapse · `DONE:` v41 audit artifact · `NEXT:` Step 4 residual close (not Step 5) · `BLOCKER:` `#rawlevels` clipped at short desktop viewport
