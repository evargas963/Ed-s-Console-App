# Put / Call Walls — Live Audit v1

**When:** 2026-07-29 ~09:51–09:56 ET (RTH)  
**Live process:** `uvicorn` on `127.0.0.1:8000` (not 8765)  
**Repo HEAD at probe:** `1b93e229`  
**Scope:** Are call/put **gamma** walls live, and working as the repo defines them?

---

## Verdict

| Question | Answer |
|---|---|
| Live? | **YES** — fresh wide-chain terrain book, `levels_stale=false`, age typically &lt;60s |
| Working as coded? | **YES** — max `|call_gex_1pct|` / `|put_gex_1pct|` on the key-level strike set; overlay matches terrain |
| Working as the UI narrative implies? | **PARTIAL** — tips say put wall = support below / call wall = resistance above; math has **no side-of-spot gate**, so put wall can sit **above** spot |

---

## Live measurements (same turn)

| Ticker | spot | call_wall | put_wall | age_sec | source | confidence | chain_basis | contracts |
|---|---:|---:|---:|---:|---|---|---|---:|
| SPY | ~734.4 | **750** | **740** | ~11–43 | `wide_chain_loop` | TRUSTED | full | 5094 |
| QQQ | ~667.3 | **700** | **660** | ~49 | `wide_chain_loop` | TRUSTED | full | ~4899 |
| IWM | ~289.7 | **300** | **290** | ~41 | `wide_chain_loop` | TRUSTED | full | 1932 |

Analytics overlay (SPY): `kl_call_gamma_wall=750`, `kl_put_gamma_wall=740`, `kl_levels_source=terrain_wide_chain` — **exact match** to `/api/terrain` in the same window.

Independent rebuild from today’s `option_chain_morning_full` SPY row (`pick_gamma_wall_strikes` on dollar GEX): **call 750 / put 740** — matches live. Top put mass at 740 (~$1.97B), top call at 750 (~$0.96B).

---

## Producer → payload → UI

1. **Producer (sole SSOT):** `terrain_engine.compute_terrain` → `pick_gamma_wall_strikes` (`math_exposure_core.py`) on wide-chain exposures (`require_oi=True`).
2. **Cache stamp:** `_terrain_refresh_one` sets `levels_source=wide_chain_loop`, `computed_ts_utc`, `chain_basis`.
3. **KL carriage:** `_terrain_kl_overlay` is the only writer of `kl_call_gamma_wall` / `kl_put_gamma_wall` (RC-122/128).
4. **UI:**
   - Terrain cards / chart / `edLevelSet`: `d.call_wall` / `d.put_wall`
   - Key Levels table: `kl_call_gamma_wall` / `kl_put_gamma_wall`
   - Dual **bind sites**, one **book** when overlay is healthy (Lock 3 reframed — not one global paint path).

Definition (code): max absolute call-side / put-side GEX$ (fallback raw γ). **No** constraint that call wall &gt; spot or put wall &lt; spot.

---

## Findings

### F1 — Put wall above spot (narrative mismatch) — LIVE TODAY
SPY `put_wall=740` with `spot≈734.4` → put wall is **above** spot. IWM `put_wall=290` ≈ at/above spot.  
UI copy (`edLevelSet` / KL tips) still frames put wall as dip support below. That is **not** what the picker guarantees.  
**Coded behavior is consistent; operator-facing geography claim is overstated.**

### F2 — Generation stamp missing on live Tier-C JSON
On-disk overlay assigns `kl_levels_from_computed_ts` from `computed_ts_utc`. Live `/api/analytics/state` for SPY returned walls + `kl_gamma_flip_confidence=TRUSTED` + `kl_levels_source=terrain_wide_chain` but **did not include** `kl_levels_from_computed_ts` at all. Walls still matched terrain; skew visibility is broken on the wire. (UI does not paint the stamp anyway — known from audit v24.)

### F3 — Known non-wall residuals (out of walls PASS scope)
- Chart volume/histogram can still ride a different clock than walls (RC-68 class).
- QQQ `gamma_flip=null` while walls present — flip path, not wall picker.
- OI/vanna walls intentionally blanked until terrain owns them.

---

## What “working as they should” means here

Under repo law (RC-33 / RC-122 / RC-128): walls should be **one wide-chain book**, fresh, on terrain + KL, blank when stale — **MET** on this probe.

Under SpotGamma-style **OTM geography** intuition (call wall above, put wall below): **not enforced** by `pick_gamma_wall_strikes`; today’s SPY print fails that intuition while still matching the max-put-GEX definition.

---

## Evidence commands (re-run)

```text
python _tmp_wall_audit.py          # if present
curl http://127.0.0.1:8000/api/terrain?ticker=SPY
curl http://127.0.0.1:8000/api/analytics/state?ticker=SPY
python _tmp_wall_rebuild.py        # morning_full independent pick
```

**drift-audit (walls claim):** intent = live operative walls; presence+freshness+rebuild match proven; narrative/geography not coded; stamp key absent on wire = FINDING F2; no false “all levels one faucet globally” claim.

---

## Institutional grade (MIT / Bloomberg / SpotGamma bar) — 2026-07-29 addendum

**Verdict: research-desk competent, not institutional Call/Put Wall product grade.**

Rough score as *named Call/Put Walls for operator S/R*: **~5/10**.  
As *faithful OI-weighted side-GEX concentration on a wide chain*: **~8/10**.

### What clears a serious quant bar
- Dollar GEX `$ = γ · OI · mult · S² · 0.01` with call−put net sign — SqueezeMetrics / SpotGamma-family formula, not a toy.
- Greek plausibility gates (reject Schwab garbage γ).
- Wide multi-expiry book (not the ATM 0DTE slice that previously lied about structure).
- Aggregation fidelity previously reconstructed 25/25 on walls (`reports/gex_gamma_flip_audit.md`).
- OI kept for walls after a head-to-head where **OI walls held better than volume walls** (unproven_register 2026-07-22: OI hold ~70.6/72.1% vs VOL ~62/66%).
- Value-area ranges named to Market Profile 68.2% mass (RC-115) — method-honest vs invented grid bands.

### What fails the institutional Call/Put Wall standard

| Gap | Why it matters |
|---|---|
| **No side-of-spot / OTM gate in the picker** | SpotGamma-style Call/Put Walls are a **containment geometry** (PW below, CW above). Our picker is max `|side GEX$|` anywhere. Live 2026-07-29: SPY PW **740 > spot ~734**. |
| **Scorecard assumes the geometry the picker omits** | `wall_hold_stats` only scores `cw > spot` and `pw < spot` — today's SPY put wall is **dropped from put-hold evidence**. Definition and KPI disagree. |
| **UI claims mechanism + geography** | Tips: resistance above / support below / “dealer hedging tends to…”. Institutional labeling would say: “strike of max call/put GEX$; hold rates only when on the working side of spot.” |
| **Prior-night OI as sole intraday weight** | Correct structural choice for *walls* per own study, but Bloomberg-grade desks disclose OI lag and often show a volume companion. Production has no labeled vol-wall twin. |
| **Tenor stack unlabeled** | All DTEs summed into one strike; no “front / weekly / all” stamp on the level. |
| **Not decision-path proven** | Hold rates exist as a KPI (~70% class on history) but are below SpotGamma’s published SPX benchmarks; break-follow-through still UNPROVEN; walls are **structure**, not admitted TRADE edge. |

### Bottom line
Correct **engineering** of a standard GEX concentration statistic ≠ correct **product definition** of institutional Call/Put Walls. Until the picker (or the labels) enforce working-side geography and the UI stops overclaiming support/resistance, this is desk-useful structure — not MIT/Bloomberg wall product.
