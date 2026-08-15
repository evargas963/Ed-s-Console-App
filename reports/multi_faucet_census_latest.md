# Multi-faucet census — latest (mission multi-faucet-census-v1, RH-F1)

Census only: every named operator field with >=2 producers or clocks, ranked, with
current-line evidence (re-scanned at generation) and the proposed kill. Kill missions
run one concept end-to-end — one authority, old path REMOVED or hard-failing, never a
fallback patch.

| # | concept | severity | producers | proposed kill |
|---|---------|----------|-----------|---------------|
| 1 | prior_day (PDH/PDL/PDC/PD_POC/PD_VAH/PD_VAL) | P2 | 3 | B3 (design §7): chart.html consumes /api/levels prior_day ids; computeDaily DELETED (not fallback-patched) — a |
| 2 | vwap (+bands) | P2 | 3 | TIERB_DONE — residue is consumer migration off /api/price-levels (B6), not a second compute. |
| 3 | opening_range (ORB H/L/mid) | P2 | 2 | TIERB_DONE — B6 retires /api/price-levels as a second HTTP surface, not a second formula. |
| 4 | overnight (high/low) | P2 | 2 | TIERB_DONE. |
| 5 | today value_area (POC/VAH/VAL) + today profile | P2 | 2 | TIERB_DONE for today VA; prior_day profile entry-point collapse is a later residue. |
| 6 | charm / greeks formulas | P1 | 2 | CHARM_DONE — migrate + delete inline + clear grandfather (RC-224). |
| 7 | clocks (session date / display time) | P1 | 3 | CLOCKS_DONE — explicit timeZone binding + static ban (RC-223). |
| 8 | spot | P2 | 3 | SPOT_DONE — single per-screen binding + visible as_of (RC-225). |
| 9 | walls / gamma flip | P2 | 2 | none needed — layered single stack. Census pointer: research entries at the primitive bypass v2's confidence g |
| 10 | per-strike volume / strikes | P2 | 2 | Strip consumes server-aggregated rows (or /api/levels gamma family) — no in-browser re-derivation of served nu |
| 11 | display precision (prior-day family) | P2 | 2 | Payloads carry RAW; rounding happens at render only (one display rule). |
| 12 | expected_move (EM bands) | P2 | 1 | none needed — keep the lock. |

## 1. prior_day (PDH/PDL/PDC/PD_POC/PD_VAH/PD_VAL) — P2 (PHASE1_DONE + P2 residue)

- **liquidity_value_engine.get_previous_day_levels (AUTHORITY, RC-153/RC-213)**
  - `liquidity_value_engine.py:282: def get_previous_day_levels(`
- **market_context.fetch_price_levels (DELEGATES to authority since 91d38623)**
  - `market_context.py:1066: from liquidity_value_engine import prior_trading_session_date`
  - `market_context.py:1067: prior_date = prior_trading_session_date(`
- **static/chart.html computeDaily (JS FALLBACK faucet — browser-local clock, buffer-group window)**
  - `static/chart.html:419: function computeDaily() {`

**Evidence:** LIVE 2026-08-03 18:0x CT PID 39720: /api/price-levels PDL 737.68 == /api/levels PDL 737.68 (was 737.68 vs 734.59 at 09:41). Residue: computeDaily derives pdh/pdl/pdc client-side when engine values absent — browser timezone, no RTH filter, days[length-2] window.
**Reproduce:** `curl /api/price-levels?ticker=SPY + /api/levels?ticker=SPY; read chart.html computeDaily`
**Proposed kill:** B3 (design §7): chart.html consumes /api/levels prior_day ids; computeDaily DELETED (not fallback-patched) — absent engine values render as absent (RC-68).

## 2. vwap (+bands) — P2 (TIERB_DONE)

- **liquidity_value_engine.compute_session_vwap (AUTHORITY; /api/levels Tier-B)**
  - `liquidity_value_engine.py:426: def compute_session_vwap(bars: list, session_date: date, cutoff_dt: Optional[datetime] = None) -> Optional[flo`
  - `liquidity_value_engine.py:445: def compute_vwap_bands(`
- **market_context.fetch_price_levels (DELEGATES to compute_session_vwap)**
  - `market_context.py:1089: compute_session_vwap,`
  - `market_context.py:1100: pl.vwap = compute_session_vwap(engine_bars, today_date)`
- **backfill_snapshot_derived eff_vwap (real/forward-fill only; typical-price SUBSTITUTION deleted)**
  - `backfill_snapshot_derived.py:64: eff_vwap = None`
  - `backfill_snapshot_derived.py:69: eff_vwap = vf`
  - `backfill_snapshot_derived.py:73: if eff_vwap is None:`
  - `backfill_snapshot_derived.py:77: eff_vwap = last_vwap_by_ticker.get(tkr)`
  - `backfill_snapshot_derived.py:78: if eff_vwap is not None:`
  - `backfill_snapshot_derived.py:79: last_vwap_by_ticker[tkr] = eff_vwap`

**Evidence:** Mission levels-tierb-session-collapse-v1: inline cum_tpv loop DELETED; fetch_price_levels + /api/levels call compute_session_vwap; typical-price substitution hard-failed to absent.
**Reproduce:** `read market_context.fetch_price_levels; curl /api/levels?ticker=SPY | jq '.levels[]|select(.family=="vwap")'`
**Proposed kill:** TIERB_DONE — residue is consumer migration off /api/price-levels (B6), not a second compute.

## 3. opening_range (ORB H/L/mid) — P2 (TIERB_DONE)

- **liquidity_value_engine.compute_opening_range (AUTHORITY)**
  - `liquidity_value_engine.py:392: def compute_opening_range(`
- **market_context.fetch_price_levels (DELEGATES to compute_opening_range)**
  - `market_context.py:1088: compute_opening_range,`
  - `market_context.py:1105: orb = compute_opening_range(engine_bars, today_date, cfg)`

**Evidence:** Mission levels-tierb-session-collapse-v1: inline ORB loop DELETED; both serve paths use engine.
**Reproduce:** `read fetch_price_levels; curl /api/levels?ticker=SPY | jq '.levels[]|select(.family=="opening_range")'`
**Proposed kill:** TIERB_DONE — B6 retires /api/price-levels as a second HTTP surface, not a second formula.

## 4. overnight (high/low) — P2 (TIERB_DONE)

- **liquidity_value_engine.get_overnight_levels (AUTHORITY, RC-153 window)**
  - `liquidity_value_engine.py:334: def get_overnight_levels(`
- **market_context.fetch_price_levels (DELEGATES to get_overnight_levels)**
  - `market_context.py:1092: get_overnight_levels,`
  - `market_context.py:1095: on = get_overnight_levels(engine_bars, today_date)`

**Evidence:** Mission levels-tierb-session-collapse-v1: today-premarket overnight_bars dual DELETED; fetch_price_levels uses the RC-153 interval via the engine.
**Reproduce:** `read fetch_price_levels; curl /api/levels?ticker=SPY | jq '.levels[]|select(.family=="overnight")'`
**Proposed kill:** TIERB_DONE.

## 5. today value_area (POC/VAH/VAL) + today profile — P2 (TIERB_DONE)

- **liquidity_value_engine.compute_volume_profile_levels (AUTHORITY for today)**
  - `liquidity_value_engine.py:511: def compute_volume_profile_levels(`
- **market_context.fetch_price_levels today VA (DELEGATES to compute_volume_profile_levels)**
  - `market_context.py:1090: compute_volume_profile_levels,`
  - `market_context.py:1109: pl.today_poc, pl.today_vah, pl.today_val = compute_volume_profile_levels(`

**Evidence:** Mission levels-tierb-session-collapse-v1: today profile uses engine; market_context._volume_profile_poc_vah_val remains only for prior_day pd_* (Phase-1 residue, not this slice).
**Reproduce:** `read fetch_price_levels; curl /api/levels?ticker=SPY | jq '.levels[]|select(.family=="value_area")'`
**Proposed kill:** TIERB_DONE for today VA; prior_day profile entry-point collapse is a later residue.

## 6. charm / greeks formulas — P1

- **math_levels bs_* faucet (AUTHORITY per registry greek_formula_faucet)**
  - `math_levels.py:681: def bs_gamma(spot: float, strike: float, t_years: float, sigma: float,`
  - `math_levels.py:695: def bs_vanna(spot: float, strike: float, t_years: float, sigma: float,`
  - `math_levels.py:721: def bs_charm(spot: float, strike: float, t_years: float, sigma: float,`
- **math_exposure_core.compute_net_charm (DELEGATES to bs_charm; RC-224)**
  - `math_exposure_core.py:756: def compute_net_charm(`
  - `math_exposure_core.py:790: 70-79% of real SPY/QQQ/IWM states, exact-negation of the per-strike bs_charm path). A`

**Evidence:** CHARM_DONE (RC-224 / charm-bs-faucet-migrate-v1): compute_net_charm calls math_levels.bs_charm(rate=0); grandfathered_inline_greeks cleared; RC-179 parity locks remain green.
**Reproduce:** `python -m pytest tests/test_charm_sign_finite_difference.py -q; python -c "import json; assert not json.load(open('governance/level_faucets.json'))['grandfathered_inline_greeks']"`
**Proposed kill:** CHARM_DONE — migrate + delete inline + clear grandfather (RC-224).

## 7. clocks (session date / display time) — P1

- **time_et (ET market-logic authority) / America-Chicago display law**
  - `time_et.py:8: ET = ZoneInfo("America/New_York")`
  - `time_et.py:25: def now_et() -> datetime:`
- **static/chart.html SESSION_TZ+DISPLAY_TZ (RC-223 killed ambient regroup)**
  - `static/chart.html:377: const SESSION_TZ = 'America/New_York';`
  - `static/chart.html:378: const DISPLAY_TZ = 'America/Chicago';`
  - `static/chart.html:380: function etDateKey(tsSec) {`
  - `static/chart.html:382: timeZone: SESSION_TZ, year: 'numeric', month: '2-digit', day: '2-digit',`
  - `static/chart.html:392: timeZone: DISPLAY_TZ, month: 'short', day: 'numeric',`
  - `static/chart.html:398: timeZone: DISPLAY_TZ, hour: '2-digit', minute: '2-digit', hour12: false,`
- **tools/clocks_tz_lock.py bare toLocaleDateString ban**
  - `tools/clocks_tz_lock.py:13: SESSION_TZ = "America/New_York"`
  - `tools/clocks_tz_lock.py:43: def bare_locale_date_violations(text: str, *, rel: str = "snippet") -> list[str]:`
  - `tools/clocks_tz_lock.py:57: f"session keys use {SESSION_TZ}; display uses {DISPLAY_TZ} (RC-223)"`
  - `tools/clocks_tz_lock.py:63: """Chart must bind daily grouping to SESSION_TZ and labels to DISPLAY_TZ."""`
  - `tools/clocks_tz_lock.py:65: if f"SESSION_TZ = '{SESSION_TZ}'" not in text and f'SESSION_TZ = "{SESSION_TZ}"' not in text:`
  - `tools/clocks_tz_lock.py:67: f"static/chart.html: missing SESSION_TZ={SESSION_TZ!r} "`

**Evidence:** CLOCKS_DONE (RC-223 / clocks-tz-explicit-v1): session keys America/New_York, display labels America/Chicago, bare toLocaleDateString banned by tools/clocks_tz_lock.py + T1. Residue: untracked exposure.html axis times; computeDaily prior_day B3 is a later mission.
**Reproduce:** `python -m pytest tests/test_clocks_tz_explicit_v1.py -q; python -c "from tools.clocks_tz_lock import scan_tracked_static; assert scan_tracked_static()==[]"`
**Proposed kill:** CLOCKS_DONE — explicit timeZone binding + static ban (RC-223).

## 8. spot — P2 (SPOT_DONE)

- **server.resolve_spot (THE authority, RC-14; every payload carries spot_source)**
  - `server.py:755: def resolve_spot(ticker: str, *, chain_json: dict | None = None,`
- **client /api/spot binding + as_of (RC-225; cycle fallback DELETED)**
  - `static/chart.html:733: src.textContent = spotBindingAgeLabel();`
  - `static/chart.html:826: ` <span id="spotage" class="src">${esc(spotBindingAgeLabel())}</span> · regime ${esc(t.regime || '—')} · ` +`
  - `static/chart.html:1419: if (_mage) _mage.textContent = spotBindingAgeLabel();`
- **tools/spot_binding_lock.py dual-age ban**
  - `tools/spot_binding_lock.py:38: def chart_binding_violations(text: str) -> list[str]:`
  - `tools/spot_binding_lock.py:130: def scan_tracked_static(repo: Path | None = None) -> list[str]:`
  - `tools/spot_binding_lock.py:134: "static/chart.html": chart_binding_violations,`

**Evidence:** SPOT_DONE (RC-225 / spot-binding-single-payload-v1): chart+exposure bind ONLY /api/spot with spot_as_of age visible (STALE >30s); consoleSpot drops last_price/quote_mid fallback; _cycleSpot DELETED; T1 + spot_binding_lock. Residue: desk.html dist.spot sample surface (OUT-OF-SCOPE this slice).
**Reproduce:** `python -m pytest tests/test_spot_binding_single_payload_v1.py -q; python -c "from tools.spot_binding_lock import scan_tracked_static; assert scan_tracked_static()==[]"`
**Proposed kill:** SPOT_DONE — single per-screen binding + visible as_of (RC-225).

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
  - `server.py:11974: @app.get("/api/terrain/strikes")`
- **chart FORCES strip client-side rows (GEX/OV derived in-browser from the same payload)**
  - `server.py:12164: #: strip's GEX/OV rows come from the live strikes payload client-side; ΔOI and DEX need the`

**Evidence:** One data source, two aggregation sites (server payload vs in-browser derivation for the strip). Binding-level duality: a payload change breaks the strip silently.
**Reproduce:** `read chart.html strip builder vs /api/terrain/strikes payload contract`
**Proposed kill:** Strip consumes server-aggregated rows (or /api/levels gamma family) — no in-browser re-derivation of served numbers.

## 11. display precision (prior-day family) — P2

- **state payload rounds (pdh 748.89)**
  - `server.py:8790: ms_dict["pdh"]      = _fv(getattr(price_levels, "pdh",      None))`
- **/api/levels + /api/price-levels serve raw (748.895)**
  - `server.py:14143: degraded.append({"family": "prior_day",`

**Evidence:** MEASURED same instant: state pdh=748.89 vs levels PDH=748.895 — same number, two precisions on two surfaces. Not a producer split; a payload-rounding faucet.
**Reproduce:** `curl /api/analytics/state | jq .pdh; curl /api/levels | jq '.levels[] | select(.id=="PDH").price'`
**Proposed kill:** Payloads carry RAW; rounding happens at render only (one display rule).

## 12. expected_move (EM bands) — P2

- **terrain sigma band (kl_em_upper/lower, E-34 locked to payload spot)**
  - `server.py:10801: md["kl_em_upper"] = round(float(_em_spot) + float(_em_pts), 2)`
  - `server.py:10804: md["kl_em_upper"] = md["kl_em_lower"] = None`

**Evidence:** Single producer, lock-tested (test_levels_single_producer_v1 E-34 assertions). Census pointer only — no second producer found this run.
**Reproduce:** `pytest tests/test_levels_single_producer_v1.py -k em`
**Proposed kill:** none needed — keep the lock.
