# Multi-faucet census — latest (mission multi-faucet-census-v1, RH-F1)

Census only: every named operator field with >=2 producers or clocks, ranked, with
current-line evidence (re-scanned at generation) and the proposed kill. Kill missions
run one concept end-to-end — one authority, old path REMOVED or hard-failing, never a
fallback patch.

| # | concept | severity | producers | proposed kill |
|---|---------|----------|-----------|---------------|
| 1 | prior_day (PDH/PDL/PDC/PD_POC/PD_VAH/PD_VAL) | P2 | 3 | B3 (design §7): chart.html consumes /api/levels prior_day ids; computeDaily DELETED (not fallback-patched) — a |
| 2 | vwap (+bands) | P1 | 3 | NEXT KILL SLICE (highest leverage): vwap family collapses onto compute_session_vwap served via /api/levels Tie |
| 3 | opening_range (ORB H/L/mid) | P1 | 2 | Same slice as vwap: ORB collapses onto the engine via /api/levels; market_context inline loop deleted with fet |
| 4 | overnight (high/low) | P1 | 2 | Same slice: overnight collapses onto get_overnight_levels via /api/levels. |
| 5 | today value_area (POC/VAH/VAL) + today profile | P1 | 2 | Same slice: ONE profile implementation (engine's, config-carrying) serves both; market_context copy deleted. |
| 6 | charm / greeks formulas | P1 | 2 | Migrate compute_net_charm onto bs_charm; delete the inline formula; registry grandfather entry removed (its ow |
| 7 | clocks (session date / display time) | P1 | 3 | All JS date grouping/labels take an explicit timeZone (America/Chicago display, ET session logic served by the |
| 8 | spot | P2 | 2 | Consumers render spot ONLY from a single shared payload field per screen with its as_of age visible; stale spo |
| 9 | walls / gamma flip | P2 | 2 | none needed — layered single stack. Census pointer: research entries at the primitive bypass v2's confidence g |
| 10 | per-strike volume / strikes | P2 | 2 | Strip consumes server-aggregated rows (or /api/levels gamma family) — no in-browser re-derivation of served nu |
| 11 | display precision (prior-day family) | P2 | 2 | Payloads carry RAW; rounding happens at render only (one display rule). |
| 12 | expected_move (EM bands) | P2 | 1 | none needed — keep the lock. |

## 1. prior_day (PDH/PDL/PDC/PD_POC/PD_VAH/PD_VAL) — P2 (PHASE1_DONE + P2 residue)

- **liquidity_value_engine.get_previous_day_levels (AUTHORITY, RC-153/RC-213)**
  - `liquidity_value_engine.py:282: def get_previous_day_levels(`
- **market_context.fetch_price_levels (DELEGATES to authority since 91d38623)**
  - `market_context.py:1085: from liquidity_value_engine import prior_trading_session_date`
  - `market_context.py:1086: prior_date = prior_trading_session_date(`
- **static/chart.html computeDaily (JS FALLBACK faucet — browser-local clock, buffer-group window)**
  - `static/chart.html:377: ? new Date(t * 1000).toLocaleDateString()`
  - `static/chart.html:391: function computeDaily() {`
  - `static/chart.html:396: const dkey = t => new Date(t * 1000).toLocaleDateString();`

**Evidence:** LIVE 2026-08-03 18:0x CT PID 39720: /api/price-levels PDL 737.68 == /api/levels PDL 737.68 (was 737.68 vs 734.59 at 09:41). Residue: computeDaily derives pdh/pdl/pdc client-side when engine values absent — browser timezone, no RTH filter, days[length-2] window.
**Reproduce:** `curl /api/price-levels?ticker=SPY + /api/levels?ticker=SPY; read chart.html computeDaily`
**Proposed kill:** B3 (design §7): chart.html consumes /api/levels prior_day ids; computeDaily DELETED (not fallback-patched) — absent engine values render as absent (RC-68).

## 2. vwap (+bands) — P1

- **liquidity_value_engine.compute_session_vwap (session bars, cutoff-aware)**
  - `liquidity_value_engine.py:426: def compute_session_vwap(bars: list, session_date: date, cutoff_dt: Optional[datetime] = None) -> Optional[flo`
  - `liquidity_value_engine.py:445: def compute_vwap_bands(`
- **market_context.fetch_price_levels inline cum_tpv loop (vendor TWO_DAYS window)**
  - `market_context.py:1111: cum_tpv = 0.0`
  - `market_context.py:1124: cum_tpv += typical * vol`
  - `market_context.py:1135: pl.vwap = cum_tpv / cum_vol`
- **backfill_snapshot_derived eff_vwap fallback chain (typical-price SUBSTITUTION)**
  - `backfill_snapshot_derived.py:98: eff_vwap = None`
  - `backfill_snapshot_derived.py:103: eff_vwap = vf`
  - `backfill_snapshot_derived.py:107: if eff_vwap is None:`
  - `backfill_snapshot_derived.py:108: eff_vwap = last_vwap_by_ticker.get(tkr)`
  - `backfill_snapshot_derived.py:109: if eff_vwap is None:`
  - `backfill_snapshot_derived.py:110: eff_vwap = _typical_price(r)`

**Evidence:** MEASURED 2026-08-03 18:1x CT same instant: /api/analytics/state vwap=None while /api/liquidity-snapshot raw_levels.vwap=755.8154 — one concept, one tab absent, one tab valued. Structural: three computes, three windows/bases (session+cutoff vs vendor-2day vs typical-price substitute).
**Reproduce:** `curl /api/analytics/state?ticker=SPY | jq .vwap; curl '/api/liquidity-snapshot?ticker=SPY&snapshot=live' | jq .raw_levels.vwap`
**Proposed kill:** NEXT KILL SLICE (highest leverage): vwap family collapses onto compute_session_vwap served via /api/levels Tier-B cache (design §5.4); market_context inline compute DELETED; backfill typical-price substitution HARD-FAILS to absent (a fabricated vwap is worse than no vwap).

## 3. opening_range (ORB H/L/mid) — P1

- **liquidity_value_engine ORB family (raw_levels.orb)**
  - `liquidity_value_engine.py:401: orb_min = config.opening_range_minutes`
  - `liquidity_value_engine.py:403: orb_bars = []`
  - `liquidity_value_engine.py:409: if 0 <= mins_since_open < orb_min:`
- **market_context.fetch_price_levels inline ORB loop**
  - `market_context.py:1130: orb_h = max(orb_h, h)`
  - `market_context.py:1139: pl.orb_high = orb_h`

**Evidence:** MEASURED same instant: state orb_high=None while liquidity raw_levels.orb={751.94/748.8/750.37} — same absence-vs-value split as vwap, same producers.
**Reproduce:** `curl /api/analytics/state?ticker=SPY | jq .orb_high; curl '/api/liquidity-snapshot?ticker=SPY&snapshot=live' | jq .raw_levels.orb`
**Proposed kill:** Same slice as vwap: ORB collapses onto the engine via /api/levels; market_context inline loop deleted with fetch_price_levels retirement (B6).

## 4. overnight (high/low) — P1

- **liquidity_value_engine.get_overnight_levels (RC-153-corrected interval window)**
  - `liquidity_value_engine.py:334: def get_overnight_levels(`
- **market_context.fetch_price_levels overnight_bars (today-premarket only window)**
  - `market_context.py:1050: overnight_bars = []`
  - `market_context.py:1069: overnight_bars.append((dt_et, c))`
  - `market_context.py:1103: if overnight_bars:`
  - `market_context.py:1104: pl.overnight_high = max(c["high"] for _, c in overnight_bars)`
  - `market_context.py:1105: pl.overnight_low  = min(c["low"] for _, c in overnight_bars)`

**Evidence:** Two windows for one name: engine = prior close -> today open interval (holiday-safe, RC-153); market_context = today's premarket bars only (extended_hours flag). Different answers whenever the overnight range formed before midnight.
**Reproduce:** `read both functions; compare on a Monday tape`
**Proposed kill:** Same slice: overnight collapses onto get_overnight_levels via /api/levels.

## 5. today value_area (POC/VAH/VAL) + today profile — P1

- **liquidity_value_engine profile (raw_levels.poc/vah/val)**
  - `liquidity_value_engine.py:329: poc, vah, val = _volume_profile_poc_vah_val(prev_bars, config.value_area_percent, config.tick_size)`
  - `liquidity_value_engine.py:496: def _volume_profile_poc_vah_val(`
  - `liquidity_value_engine.py:520: return _volume_profile_poc_vah_val(rth_bars, config.value_area_percent, config.tick_size)`
- **market_context._volume_profile_poc_vah_val (separate copy)**
  - `market_context.py:870: def _volume_profile_poc_vah_val(bars: list, value_area_pct: float = 0.70,`
  - `market_context.py:1100: pl.pd_poc, pl.pd_vah, pl.pd_val = _volume_profile_poc_vah_val(prev_candles)`
  - `market_context.py:1143: pl.today_poc, pl.today_vah, pl.today_val = _volume_profile_poc_vah_val(today_candles)`

**Evidence:** Two same-named profile implementations, one per module — value-area math forked at module boundary; divergence follows bar-source/window differences exactly as prior_day did.
**Reproduce:** `read both _volume_profile_poc_vah_val implementations; diff parameters (value-area %, tick size)`
**Proposed kill:** Same slice: ONE profile implementation (engine's, config-carrying) serves both; market_context copy deleted.

## 6. charm / greeks formulas — P1

- **math_levels bs_* faucet (AUTHORITY per registry greek_formula_faucet)**
  - `math_levels.py:681: def bs_gamma(spot: float, strike: float, t_years: float, sigma: float,`
  - `math_levels.py:695: def bs_vanna(spot: float, strike: float, t_years: float, sigma: float,`
  - `math_levels.py:721: def bs_charm(spot: float, strike: float, t_years: float, sigma: float,`
- **math_exposure_core.compute_net_charm inline formula (GRANDFATHERED, RC-179 parity-locked)**
  - `math_exposure_core.py:756: def compute_net_charm(`

**Evidence:** Registry names the grandfather explicitly; RC-179 parity locks pin sign/magnitude. Structural residue: one concept, two formula sites — the vanna defect (RC-211) was exactly this class before its kill.
**Reproduce:** `python tools/check_institutional_correctness.py (charm parity checks); read registry grandfathered_inline_greeks`
**Proposed kill:** Migrate compute_net_charm onto bs_charm; delete the inline formula; registry grandfather entry removed (its own stated destiny: 'migrate to the bs_* faucet').

## 7. clocks (session date / display time) — P1

- **time_et (ET market-logic authority) / America-Chicago display law**
  - `time_et.py:8: ET = ZoneInfo("America/New_York")`
  - `time_et.py:25: def now_et() -> datetime:`
- **static/chart.html bare toLocaleDateString (BROWSER-LOCAL clock in bar grouping + axis)**
  - `static/chart.html:377: ? new Date(t * 1000).toLocaleDateString()`
  - `static/chart.html:396: const dkey = t => new Date(t * 1000).toLocaleDateString();`
  - `static/chart.html:1362: const lab = tf === 'D' ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })`
- **static/index.html toLocaleDateString('en-CA') date stamp (browser-local)**
  - `static/index.html:11710: ubD.textContent = now.toLocaleDateString('en-CA');`

**Evidence:** chart.html groups daily bars by the BROWSER's timezone (computeDaily dkey + axis labels) while every server window is ET and the display law is CT — a traveling operator's chart would regroup sessions. index.html carries one browser-local date stamp beside CT-explicit stamps.
**Reproduce:** `read chart.html L377/L396/L1362 + index.html L11710; compare with UI clock law (CT)`
**Proposed kill:** All JS date grouping/labels take an explicit timeZone (America/Chicago display, ET session logic served by the API, e.g. /api/levels provenance.window); bare toLocaleDateString banned by a static check.

## 8. spot — P2

- **server.resolve_spot (THE authority, RC-14; every payload carries spot_source)**
  - `server.py:707: def resolve_spot(ticker: str, *, chain_json: dict | None = None,`
- **client bindings (chart/exposure/index render spot from different payloads' spot fields)**
  - `static/chart.html:174: /* v6.1 (RC-194) # ui-mockup-ok: the mock's compact below|spot|above cluster — values hug`
  - `static/chart.html:224: <span class="chip" id="lvlbtn" title="every level: ON always &middot; AUTO fires near spot &middot; OFF">LEVEL`
  - `static/chart.html:323: let liveSpot = null;      // 2.5s fast-poll spot (/api/spot); 15s cycle is the fallback`

**Evidence:** Compute side is single-faucet (RC-14). Residue is BINDING-level: each tab renders the spot of whichever payload it last fetched, so tabs can show different ages of the one authority. FORCES strip spot honesty is the PM-named instance.
**Reproduce:** `compare spot + spot_source + as_of across /api/terrain, /api/analytics/state, /api/levels`
**Proposed kill:** Consumers render spot ONLY from a single shared payload field per screen with its as_of age visible; stale spot renders as stale, not as current.

## 9. walls / gamma flip — P2

- **terrain_engine (single producer since RC-80)**
  - `terrain_engine.py:505: put_wall=put_wall, call_wall=call_wall,`
  - `terrain_engine.py:519: call_wall=call_wall,`
- **math_levels gamma_flip_from_profile AND compute_gamma_flip_v2 (two flip formula generations)**
  - `math_levels.py:873: def gamma_flip_from_profile(`
  - `math_levels.py:1027: def compute_gamma_flip_v2(`

**Evidence:** Wall/flip VALUES have one producer (RC-80 kill held). MEASURED this census: the two flip functions are LAYERED, not parallel — compute_gamma_flip_v2 calls gamma_flip_from_profile internally (math_levels.py:1054); production (server.py, terrain_engine.py) enters ONLY via v2; research tools (flip_iv_sensitivity_v1, study_flip_span_convergence_v1) enter at the primitive. One formula stack, two entry depths — not a dual faucet.
**Reproduce:** `referrer trace of both names across *.py + tools/ (6 lines each; v1's non-tool referrer is v2 itself)`
**Proposed kill:** none needed — layered single stack. Census pointer: research entries at the primitive bypass v2's confidence gate BY DESIGN (they study the raw crossing).

## 10. per-strike volume / strikes — P2

- **/api/terrain/strikes (per-strike GEX$/volume payload)**
  - `server.py:11926: @app.get("/api/terrain/strikes")`
- **chart FORCES strip client-side rows (GEX/OV derived in-browser from the same payload)**
  - `server.py:12116: #: strip's GEX/OV rows come from the live strikes payload client-side; ΔOI and DEX need the`

**Evidence:** One data source, two aggregation sites (server payload vs in-browser derivation for the strip). Binding-level duality: a payload change breaks the strip silently.
**Reproduce:** `read chart.html strip builder vs /api/terrain/strikes payload contract`
**Proposed kill:** Strip consumes server-aggregated rows (or /api/levels gamma family) — no in-browser re-derivation of served numbers.

## 11. display precision (prior-day family) — P2

- **state payload rounds (pdh 748.89)**
  - `server.py:8742: ms_dict["pdh"]      = _fv(getattr(price_levels, "pdh",      None))`
- **/api/levels + /api/price-levels serve raw (748.895)**
  - `server.py:14120: "id": lid, "price": float(val), "family": "prior_day", "label": lid,`

**Evidence:** MEASURED same instant: state pdh=748.89 vs levels PDH=748.895 — same number, two precisions on two surfaces. Not a producer split; a payload-rounding faucet.
**Reproduce:** `curl /api/analytics/state | jq .pdh; curl /api/levels | jq '.levels[] | select(.id=="PDH").price'`
**Proposed kill:** Payloads carry RAW; rounding happens at render only (one display rule).

## 12. expected_move (EM bands) — P2

- **terrain sigma band (kl_em_upper/lower, E-34 locked to payload spot)**
  - `server.py:10753: md["kl_em_upper"] = round(float(_em_spot) + float(_em_pts), 2)`
  - `server.py:10756: md["kl_em_upper"] = md["kl_em_lower"] = None`

**Evidence:** Single producer, lock-tested (test_levels_single_producer_v1 E-34 assertions). Census pointer only — no second producer found this run.
**Reproduce:** `pytest tests/test_levels_single_producer_v1.py -k em`
**Proposed kill:** none needed — keep the lock.
