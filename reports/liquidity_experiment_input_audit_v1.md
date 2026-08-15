# Liquidity experiment input audit v1

**MISSION_CLASS:** Find & Prove — audit only (no Decide, no UI, no experiment “fix”)  
**GAP:** Operator ambiguity: “OI” vs options volume vs what Chart yellow bars / offline gamma packs actually consume  
**SMALLEST_COMPLETE_CHANGE:** This report (evidence from code + same-turn DB/API)  
**MINIMUM_SUFFICIENT_EVIDENCE:** Code cites + `COUNT(*)` / live payload shown below  
**DECISION_PATH_EFFECT:** None — WAIT  
**WHY_NOW:** Operator interrupt: Chart yellow bars first; then experiment input soundness  
**TASK_ADMISSION:** Audit admitted; no admission of gamma/volume as edge

Reproduce:
```
python -u scratchpad/_audit_liq_inputs_v1.py
python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/terrain/strikes?ticker=SPY'))['today']['all'][0])"
```

---

## 0) Chart yellow bars — answer first

**Plain English: the yellow bars are today’s options volume by strike — not Open Interest, not gamma, not a blend.**

| Layer | Field | Meaning |
|---|---|---|
| UI legend | `#ffc400` → “today's option volume” | Label on Chart |
| UI paint | `r[2]` as `vol`, fill `#ffc400` | Lower histogram only |
| API row | `[strike, net_gex, volume]` | Index 0/1/2 |
| Producer | Schwab `totalVolume` summed per strike | Session options contracts traded |
| Blue/red bars (same panel) | `r[1]` = `net_gex_1pct$` | Dealer gamma $ — separate series |

**PROVEN same-turn (live server):** `/api/terrain/strikes?ticker=SPY` → `today_source=terrain_live_cache`, `n=201`, sample row `[520.0, -10500747.0, 26]`, `sum(r[2])=12,217,796`. Third element is volume height; second is signed GEX (blue/red).

Code:
- `static/chart.html` legend: “today's option volume”; paint uses `vol` from `const [k, gx, vol] = vis[i]` with `g.fillStyle = '#ffc400'`.
- `terrain_engine._per_strike_rows`: shape `[[strike, net_gex_1pct$, session_volume], …]`; volume from `ct.get("totalVolume")`.

**Not OI.** Open Interest is `openInterest` and is used to *build* GEX for the blue/red bars and walls; it is not what the yellow series plots.

---

## 1) When reports said “OI” — Open Interest or Options Volume?

| Context | What “OI” meant | What was actually used |
|---|---|---|
| Desk discussion (`liquidity_gamma_storm_discussion_v1.md`) | Open Interest (standing inventory), often written “volume/OI” as a *lore* combo | Discussion only — not an experiment input |
| Vendor confusion (PROVEN in `governance/unproven_register.md`) | Barchart’s intraday column labeled “Open Interest” was **session VOLUME** on our SPY check | Product-label trap; Ed terrain GEX uses Schwab `openInterest` |
| Gamma **experiments** (levels / hold / horizon) | Do **not** score OI walls or volume walls | Levels = **GEX$** walls/pin/flip via `compute_terrain` → `gamma * OI * mult * …` |
| Chart yellow bars | People may say “OI” loosely | **Options volume** (`totalVolume`) — see §0 |
| Synthesis pack A/B/D/E | N/A (no chain OI/volume) | Price bars + prior-day / overnight / ORB geometry only |

**Rule of thumb for this repo:**  
- **OI** = Schwab `openInterest` (static within session; updates overnight).  
- **Options volume** = Schwab `totalVolume` (session cumulative).  
- **Walls/pin in experiments** = dollar GEX / total-GEX built from **gamma × OI**, not from volume.

---

## 2) Offline liquidity / gamma experiment inputs

### Scripts

| Script | Role |
|---|---|
| `tools/liquidity_synthesis_experiments_v1.py` | Bar geometry (families, width, OB, FVG); gamma regime **BLOCKED** |
| `tools/liquidity_gamma_levels_experiment_v1.py` | Touch → triple-barrier bounce at CALL/PUT wall, flip, pin |
| `tools/liquidity_gamma_hold_horizon_experiments_v1.py` | Session respect / touch-hold / multi-horizon / flip+regime |
| Helpers | `terrain_engine.compute_terrain`, `math_exposure_core.compute_exposures_by_strike` / `pick_gamma_wall_strikes` / `pick_pin_and_strength`; synthesis also `liquidity_value_engine` + `liquidity_models.PlaybookConfig` |

### Exact data sources

| Input | Table / API | Used by |
|---|---|---|
| 1m OHLCV bars | `price_bars_1m` (`bar_start_ts_utc, open, high, low, close, volume`) | All three packs (equity bar volume ≠ options volume) |
| Morning wide chain | `option_chain_morning_full` (`et_date, ts_utc, spot, chain_json, n_contracts`) | Gamma packs prefer; synthesis Exp C gate only |
| Snapshot chain ~10:00 ET | `snapshots` (`timeframe='1m'`, `option_chain_json`, `spot`) window **09:45–10:15 ET** | Gamma packs fill days without morning_full |
| Level math | In-process `compute_terrain` on stored chain JSON | Not a separate DB table of walls |
| Live Chart (not experiments) | `/api/terrain/strikes` | Yellow = volume; blue/red = net GEX |

**No live Schwab API inside the offline experiment scripts** — DB only.

### Session filter / clock

- Clock: **America/New_York (ET)** via `time_et.ET`.
- Touch / barrier scan: **RTH bars only** `09:30 ≤ min_of_day < 16:00`.
- Observation window for snapshot walls: **09:45–10:15 ET**; nearest to 10:00.
- Touch start: **≥ 10:15 ET** (after obs — stated causal rule).
- Trading-day filter: `is_trading_day_et` (weekend morning_full rows exist in SQL but are dropped).
- Overnight levels (synthesis): prior RTH close → session RTH open (extended window by design); PD levels RTH-only.

### Missing / blank / drops (PROVEN this turn)

Command: `python -u scratchpad/_audit_liq_inputs_v1.py`

| Check | Result |
|---|---|
| `option_chain_morning_full` raw COUNT(*) | SPY=12, QQQ=11, IWM=12; empty/null chain = **0** |
| Same after `is_trading_day_et` | **SPY=9, QQQ=9, IWM=9** (matches hold-pack report) |
| `price_bars_1m` null OHLC | SPY/QQQ/IWM = **0 / 0%** |
| Snapshots with chain in 09:45–10:15 ET | SPY 69 days / QQQ 64 / IWM 64 |
| Obs faucet mix (prefer morning_full) | `morning_full=27`, `snapshots_1000et=175` (202 ticker-days) |
| Obs days with RTH bars ≥40 | **201**; skip short session **1** |
| Prior gamma-levels report (committed) | recon OK 198; empty levels 3; fail 0; scored sessions **195** |

Silent skips in code (no invented levels):
- null OHLC bar rows dropped;
- `len(sb) < 40` session skip;
- bad/empty JSON → recon fail/empty;
- barrier events already past stop → `label=None` skip;
- `atr <= 0` skip.

### Are gamma levels from OI, volume, both, or GEX$?

**PROVEN from code: GEX$ (gamma × Open Interest), not options volume.**

1. `compute_exposures_by_strike(..., require_oi=True)`:  
   `call_gex_1pct += gamma * oi * mult * spot * spot * 0.01`  
   Contracts with `oi is None or oi <= 0` are skipped for exposure.
2. `pick_gamma_wall_strikes`: max `|call_gex_1pct|` / `|put_gex_1pct|` (fallback raw side gamma).
3. `pick_pin_and_strength`: max **total** GEX$ (call+put) — Absolute Gamma pin.
4. `totalVolume` is aggregated for Chart histogram only; **not** an argument to wall pickers.

Illustrative same-turn chain (SPY morning_full 2026-07-30): `n_contracts=3060`, `openInterest>0=2319`, `totalVolume>0=1790` — both fields present; experiments weight by OI×gamma, Chart yellow by volume.

### Lookahead / as-of

| Rule | Status |
|---|---|
| Walls fixed from morning_full or ≤10:15 ET snapshot | Causal for level *location* |
| Touches only after 10:15 ET | Causal for event time |
| Zone half-width = `0.25 × session ATR` where session ATR = **full-day** RTH median range | **Intraday lookahead on width** (same for real & placebo) |
| Placebo centers uniform in **full-session** RTH high/low | **Intraday lookahead on placebo placement** (can use afternoon extremes unknown at 10:15) |
| Barrier target ATR | Causal window before event (`_causal_atr`) |
| Costs | **ABSENT** (stated) |

### Sample sizes / selection bias

From committed reports + this-turn census:

- Synthesis: **298** RTH sessions; Exp C gamma **BLOCKED** (morning_full thinnest &lt;20 days at run time).
- Gamma levels / hold: **195** scored sessions; faucet **~87% snapshots_1000et**, **~13% morning_full TRUSTED**.
- Confidence: UNAVAILABLE 171 vs TRUSTED 27 (levels report).
- `GAMMA_FLIP` present ~26 ticker-days; **0 post-10:15 touches** scored.
- Regime: essentially **SHORT_GAMMA only** in reconstructable sample; LONG_GAMMA = 0 days → regime-conditional claims blocked/descriptive.
- Tickers: SPY/QQQ/IWM only — sentinel selection, not full operable surface.
- Snapshot chains are often **narrow money-path** (flip/regime weak); walls/pin still emit — so the pack mostly tests **narrow-chain GEX landmarks**, not full TRUSTED morning books.

### Verdict on scientific soundness

| Claim the pack can honestly support | Sound? |
|---|---|
| “These reconstructed GEX wall/pin zones beat random same-width zones on cost-absent bounce/hold labels in this sample” | Method is a fair **null test of that proxy** (and it **FAIL**ed). Causal obs/touch split is real. |
| “We tested open-interest walls” or “options-volume magnets” | **No** — thin proxy relative to that claim. Walls are **GEX$**, yellow Chart is **volume**, OI is the *scaler inside GEX*, not the plotted/tested level family. |
| “Vendor-style perfect storm (OI + volume + regime + multi-family)” | **Not tested.** Discussion lore; experiments never joined volume mass or multi-family with walls. |
| Regime / flip behavior | **Underpowered / BLOCKED** — thin morning_full, 0 flip touches, one-sided SHORT_GAMMA. |

**Input gaps (do not defend):**
1. Dominance of narrow snapshot chains vs TRUSTED morning_full.  
2. No options-volume-by-strike series in the offline packs.  
3. No pure OI-wall arm (separate from GEX).  
4. Full-session ATR / placebo range = mild same-day lookahead on geometry (symmetric, still not pure as-of).  
5. Costs absent → not economic edge.  
6. Flip + LONG_GAMMA effectively untested.  
7. Synthesis never ran gamma regime join (Exp C BLOCKED).

---

## 3) Parent plain-English summary

1. **Chart yellow bars = today’s options volume by strike** (`totalVolume`). Not OI. Not gamma. Blue/red = dealer net GEX$.  
2. **“OI” in discussion** usually means Open Interest; experiments used **GEX$ (gamma × OI)** for walls/pin, not volume bars.  
3. **Data:** RTH 1m equity bars + morning_full (prefer) or snapshots@~10:00 ET chains; ET clock; touches after 10:15.  
4. **Blanks:** bar nulls ~0%; morning_full chains non-empty; ~1 short session skipped; empty levels rare (3 in prior run).  
5. **Soundness:** Honest fail test of a **GEX-landmark proxy**, not of OI walls or Chart yellow volume magnets; sample skewed to narrow snapshots and SHORT_GAMMA.
