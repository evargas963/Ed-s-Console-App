# Chart v6 brutal UI audit v1 — Cursor vs Claude 27/27

**Date:** 2026-08-02 (Sunday ET) · **NEXT_RTH_PROOF:** 2026-08-03 Monday  
**Authority:** operator eyes (Levels VWAP+2σ blank; call wall missing; old-UI feature gap) over Claude ship claim  
**Surfaces:** `static/chart.html`, `liquidity_value_engine.py`, live `http://127.0.0.1:8000/chart`  
**Drift-audit:** executed this turn (skill `.claude/skills/drift-audit/SKILL.md`)  
**OUT-OF-SCOPE:** Decide path (WAIT). Enrolled-universe multi-ticker click matrix — SPY sentinel used for render wiring; engine/API contracts are ticker-parameterized.  
`# universal-scope-ok:` sentinel smoke for Chart render class; `# next-rth-ok: 2026-08-03`; `# chart-intent-ok:` Chart consumer is the product under audit.

---

## VERDICT

**FAIL** on Claude’s “finished / 27/27” claim.

**Post-repair (same turn):** operator P0s **FIXED** and re-proven in Playwright (`scratchpad/_v6_brutal_ui_audit.js` → **31 pass / 0 fail**). Named residue remains (parity + Sunday ORB). **Decide WAIT.**

Claude’s harness (`scratchpad/_v6_functional_audit.js`) auto-passed `no-data-declared:*` without proving honesty, and scored `on-renders:*` with global `tags >= 4` instead of per-family series. That is presence theater, not operator-visible render proof.

---

## A) Control inventory (click + evidence)

| Control | Result | Evidence |
|--------|--------|----------|
| Ticker `#tk` | PASS | SPY loads bars/terrain/levels |
| TF chips 1m–D | PASS | present + wired (`data-tf`) |
| Theme `#theme-btn` | PASS | light `rgb(244,247,251)`; dark restores (`_brutal_03_light.png`) |
| Nav cv2 tabs | PASS | Console/Terrain/Chart/Desk match Console component |
| CANDLES / LINE | PASS | mode `candles → line` |
| LEVELS manager (15 families) | see §B | each row cycled ON |
| PROX 5/10/15/25¢ | PASS | chip click |
| FIT / COACH | PASS | present |
| FIRED / quietstat | PASS | quiet line paints |
| FORCES strip | PASS | GEX/OV/ΔOI/DEX; CHARM locked (vote) |
| Gamma scope ALL / ≤7 DTE / MONTHLY+ | PASS | `__edChart.gamma.call_wall/put_wall/spot === true` all three |
| GHOST | PASS | prior outlines paint |
| γ/STRIKE rail | PASS | canvas nonzero |

**Controls FAIL (pre-fix):** VWAP family (value, no tag/series contract), VWAP ±σ family (null laundered as “no data”), HVP/LVP + Net Γ peak (off-scale not in audit handle). **Post-fix FAIL count: 0** on this matrix.

---

## B) LEVELS — VWAP / ±2σ (operator bug)

### Pre-fix (PROVEN same turn)

```
GET /api/liquidity-snapshot?ticker=SPY&snapshot=live
session_date=2026-08-02  vwap=null  vwap_bands=null
prev.pdh=748.895  overnight high/low present  orb={}
```

`build_live_snapshot` on a **non-trading** calendar day after wall-clock 09:30 ET took the **live RTH** branch, filtered zero Sunday RTH bars, and served null VWAP/σ while Friday RTH still sat in the bar buffer. Chart menu amber “no data this session” was therefore a **lie covering an engine weekend path hole**, not honest absence.

Client bugs stacked on that:

1. VWAP polyline drew **ungated** by `lvlState('vwap')` and never pushed an **axis tag** from the client tip → manager showed `744.46 ON` with no gutter name (Claude still counted “tags exist” elsewhere).
2. Functional audit treated menu “no data” as PASS without payload honesty check.

### Root cause

| Layer | Defect |
|-------|--------|
| Engine | Weekend/holiday `session_date == today` + `now >= 09:30` → fake live RTH → null VWAP/σ |
| Premarket raw | `prev_day` only (Chart reads `prev`); no prior-session VWAP/σ |
| Client | VWAP series not manager-gated; no VWAP axis tag; `__edChart` omitted `vwapDrawn` / `offScale` |
| Audit | Soft no-data auto-pass; tag-count proxy |

### Fix (landed this turn)

1. `liquidity_value_engine.build_live_snapshot` — non-trading today → premarket path (not fake RTH).
2. `build_premarket_snapshot` — prior-session VWAP + ±1σ/±2σ; `prev` key for Chart RL_SPEC.
3. Live path null-VWAP → prior RTH VWAP/σ fallback (pre-open trading days).
4. `static/chart.html` — `_vwapWanted` + `lvlVisible('vwap')`; axis tag; `__edChart.chart.vwapDrawn` + `offScale`; gamma window widens to wall strikes; CALL/PUT RANGE axis tags restored under wall family.

### Post-fix proof

```
session 2026-08-02 snap premarket
vwap 744.12
bands +2σ 750.08 / +1σ 747.10 / −1σ 741.14 / −2σ 738.16
```

Playwright family results (all ON): `vwap` → `744.12 VWAP`; `vwb` → all four VWAP σ tags. Frames: `scratchpad/_brutal_02_all_families_on.png`.

ORB “no data” on Sunday remains **honest** (no Sunday RTH open) — not a cover story.

---

## C) Gamma panel — call / put wall / spot

| Scope | call_wall | put_wall | spot |
|-------|-----------|----------|------|
| ALL | true | true | true |
| ≤7 DTE (near) | true | true | true |
| MONTHLY+ (far) | true | true | true |

Live terrain: `call_wall=put_wall=750` on banked book; markers paint (coincident). Pre-fix risk: walls outside `gWin` slice returned false from `mark2` — window now expands to wall indices. Operator miss may also have been pre-restart `:8000` / zoom; machine now asserts under all scope chips.

---

## D) Feature parity vs old UI screenshot

| Feature | Status | Notes |
|---------|--------|-------|
| VWAP orange series | PRESENT (fixed) | Manager-gated + tag |
| VWAP ±1σ ±2σ | PRESENT (fixed) | Was null on Sunday |
| EM ±1σ | PRESENT | Implied 1-day move |
| CALL/PUT WALL (chart + gamma) | PRESENT | Coincident → `⬌WALL·PIN` |
| CALL/PUT RANGE | PRESENT (tags/banners; shade ABSENT) | RC-196: no translucent fillRect; axis edge tag + left-edge banner; coverage in tip |
| FLIP / PIN / MAX PAIN | PRESENT | Axis tags |
| HVP / LVP / NET Γ PEAK | PRESENT | Off-scale pin row when outside day range |
| C-CHARM / P-CHARM | PRESENT | P-CHARM often off-scale |
| PDH/PDL/PDC / ON H/L / PD VA | PRESENT | |
| ORB | ABSENT Sunday | Honest — no RTH open (`NEXT_RTH_PROOF` 2026-08-03 Mon) |
| RDS | FIXED as **KDS** | Audit OCR of Key Delta Strike; default ON; tag `750.00 KDS` |
| Mid-chart prose labels | RESTORED (left edge) | CALL/PUT RANGE + TWO-SIDED at PADL; axis tags kept |
| RAW STRUCTURE strip card | REMOVED | Merged into LEVELS manager (v6 GO) |
| Ghost bars | PRESENT | |
| Coach cards | PRESENT | |
| STALE line | PRESENT | |
| Regime chip / narrator | PRESENT | |
| Forces CHARM numbers | LOCKED | Vote gate DIR-01(i) — intentional |
| Two-viewport Chart consumer | PARTIAL | Candles + gamma; yellow GEX bars = gamma panel |

---

## E) Theme

Dark + light toggle shares Console `ed_theme` / cv2 tokens. Light background measured `rgb(244, 247, 251)`. Canvas `PAL` refreshes on toggle. Frames: `_brutal_01_initial.png`, `_brutal_03_light.png`.

---

## F) Claude claims — attack results

| Claim | Result |
|-------|--------|
| 27/27 functional | **REJECT** — soft no-data + tag-count proxy; missed VWAP/σ class |
| call_wall/put_wall/spot true | **HELD** on current ALL scope after repair; was brittle to gWin |
| levels 4→17 tags | **INSUFFICIENT** — did not prove VWAP/σ series |
| Sunday no-data amber | **WAS A LIE** for VWAP/σ; honest for ORB |
| PDH double-faucet / VAH 0 | Prior fixes kept |
| cv2 ported | **HELD** (theme/tabs) |
| RC-195 CLOSED | **PREMATURE** → reopened **PARTIAL** |
| 128 tests | Not re-cited as Chart finish; new tests added for this class |
| /api/forces needs :8000 restart | Ops note; forces available after restart this turn |

---

## G) Tests added

- `test_weekend_live_snapshot_serves_prior_session_vwap_bands`
- `test_premarket_raw_levels_expose_prev_key_and_prior_vwap`
- `test_chart_vwap_family_gates_series_and_exposes_drawn_flag`
- `test_chart_gamma_widens_window_to_include_walls`

Measured: `.venv/Scripts/python.exe -m pytest` (those four + surface) = **5 passed**.

Brutal harness: `node scratchpad/_v6_brutal_ui_audit.js` = **31/0**.

---

## Named residue (not closed)

1. ~~**RDS** label from old UI — no producer on Chart path.~~ → **FIXED** as KDS (see §H).
2. **ORB** empty until next RTH (`2026-08-03` Monday) — honest (no Sunday RTH open).
3. ~~**Mid-chart banners** (TWO-SIDED prose, range % headlines)~~ → **FIXED** left-edge PADL banners (§H).
4. **CHARM forces numbers** — locked on vote DIR-01(i).
5. **Claude soft audit** still in tree — do not trust; use `_v6_brutal_ui_audit.js`.

---

## H) Follow-up 2026-08-02 — RDS → KDS restore (same Sunday)

**Authority:** old-UI screenshot cyan tag at 750 beside PIN + pre-v6 `static/chart.html` levels array.

| Claim | Result | Evidence |
|-------|--------|----------|
| "RDS" is a missing producer | **REJECT — OCR** | Pre-v6 / live Chart label is **KDS** (`key_delta_strike`, cyan `#00e5ff`). Same strike cluster as PIN/walls in the screenshot. No `RDS` string ever existed in Chart history. |
| KDS on Chart path | **FIXED** | LVL_META default `off` → `on`; axis tag `750.00 KDS`; `__edChart.chart.kdsDrawn` + `kdsValue` |
| Gamma/context | **HELD** | Terrain serves `key_delta_strike=750`; tip names total-DEX$ magnet (UNPROVEN register); coincident with wall/pin stack kept (not merged away) |
| CALL/PUT RANGE + TWO-SIDED banners | **FIXED** | Left-edge (`PADL+8`) prose restored; right-gutter axis tags kept (RC-194 collision preserved) |
| CALL/PUT RANGE + WALL RANGE canvas shade | **REMOVED (RC-196)** | Operator: shade dulled candles / no purpose. Assert `rangeShadeFill===false` + `wallCorridorFill===false`; wall lines/tags/gamma marks kept |
| ORB | **HONEST ABSENCE** | `PASS_HONEST_ABSENCE`; `NEXT_RTH_PROOF` **2026-08-03 Monday** |
| Theme / cv2 | **NO REGRESS** | brutal theme-light + theme-dark still PASS |

### Post-fix proof (same turn)

```
GET /api/terrain?ticker=SPY → key_delta_strike=750.0  (with gamma_pin=call_wall=put_wall=750)
node scratchpad/_v6_brutal_ui_audit.js → 33 pass / 0 fail
  kds-default-on :: state=on values=1
  kds-drawn-default :: kds=750 tags=["750.00 KDS"]
family:kds → PASS_RENDERED 750.00 KDS
family:orb → PASS_HONEST_ABSENCE
pytest test_chart_kds_defaults_on_and_exposes_drawn_flag (+ vwap/gamma) → 3 passed
```

`# next-rth-ok: 2026-08-03` · `# chart-intent-ok:` Chart consumer under proof · `# universal-scope-ok:` SPY sentinel for render wiring.

### Residue after follow-up (clock / vote only)

1. **ORB** — live paint at `NEXT_RTH_PROOF` 2026-08-03 Monday (Sunday has no RTH open).
2. **Forces CHARM numbers** — vote gate DIR-01(i).

RC-195 updated with FIXED reach for KDS + banners; remains **PARTIAL** solely for those OUT-OF-SCOPE clock/vote items.

---

## Drift-audit (this turn + follow-up)

- **Intent:** operator wanted Levels ON to draw VWAP/σ and gamma walls visible; Claude over-claimed finish; follow-up ordered RDS + non-clock omissions restored today.
- **Presence vs capability:** FAIL class found (menu value ≠ series); follow-up found KDS default-OFF omission mislabeled "RDS".
- **Silent-swallow:** weekend null VWAP.
- **Gate strength:** hardened with `vwapDrawn`/`offScale`/`kdsDrawn` + weekend engine + KDS default tests.
- **Completeness critic:** RDS was KDS; banners restored; only ORB (clock) + CHARM forces (vote) remain.
- **Findings → corrections:** engine weekend path + chart VWAP wiring + gamma window + KDS default ON + left banners + tests + RC-195 PARTIAL (clock/vote only).
- **Sign-off:** drift-audit run; findings: weekend VWAP null + ungated VWAP tags + KDS default-OFF (OCR'd RDS) + soft audit; corrections: landed; gate hardened: y.

**Decide WAIT.** No commit (operator).
