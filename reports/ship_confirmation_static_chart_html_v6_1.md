# Ship confirmation — static/chart.html v6.1 (RC-194) — FEATURE-BY-FEATURE against actual code, RENDERED-FRAME verified

Operator law (non-negotiable, 2026-08-02): "you are to always confirm first with actual code
before you ship." This document is that confirmation for the v6.1 restyle/repair of
`static/chart.html`: every clause of the approved variant (governance/ui_mockup_approvals.json)
and every operator note from the design session, mapped to a code anchor and confirmed on real
rendered frames (headless Playwright, 1600x1000): `scratchpad/_v6_chart_full.png` (page) and
`scratchpad/_v6_chart_menu.png` (LEVELS pulldown open). Re-render:
`node scratchpad/_v6_shot.js`.

RENDERED-FRAME evidence reviewed by the agent before this claim; both frames sent to the
operator in-chat this session.

## FEATURE-BY-FEATURE checklist (approved clause → code anchor → frame check)

| # | Agreed feature (source) | Code anchor in static/chart.html | On frame |
|---|---|---|---|
| 1 | Candles default + LINE toggle | `chartMode` + `setMode` + `#mode-candles`/`#mode-line` | chips row; candles painted |
| 2 | LEVELS pulldown under the timeframe row (v5 note: "right underneath... pull down menu") | `#ctlrow` relative + `toggleMenu` anchors `#lvlmenu` at the button | menu shot: opens under LEVELS ▾ |
| 3 | ON/AUTO/OFF per level family + evidence tier per row | `LVL_META` (15 rows) + `renderLvlMenu` state chips | menu shot: 4 ON / 8 AUTO / 3 OFF, evidence text |
| 4 | Engine levels merged (raw-levels card REMOVED), per-level ids kept | `renderEngineLevels` + `id="rl-${esc(r.id)}"` in the manager | menu shot: 11 real levels (PDH 748.89 …) |
| 5 | Cents proximity 5/10/15/25, default 10¢, 2× hysteresis vs LIVE recomputed levels | `PROX_CHOICES`/`proxCents`/`fireOk` in `draw()` per frame | header: "PROX 10¢"; quiet status live |
| 6 | FIRED pills w/ live cents; honest-quiet names the nearest watcher (mock) | `firedPills`/`autoNearest` → `#firedrow`/`#quietstat` | "nothing within 10¢ · nearest ON LOW 744.00 (21¢) · 17 watching" |
| 7 | Axis-hugging tags: word+price at the strike, tooltips carry the prose; NO mid-chart text | `axisTags` renderer; rangeShade/corridor/EM `fillText` removed | gutter: 750.00 ⬌WALL·PIN / 748.18 +1σ / 746.56 FLIP / spot pill / 740.24 −1σ |
| 8 | Price scale must not collide with tags (operator: "this looks horrible" frame) | `gridLabels` yield within 12px of any tag/spot | dim numbers only in free slots |
| 9 | Two-sided wall = ONE combined chip, pin merged when shared | `band()` tag `⬌WALL·PIN`; pin item skipped when == wall | single 750.00 ⬌WALL·PIN tag |
| 10 | ±1σ EM in the PERSIST set (v4 note) | `LVL_META` em default 'on' | both σ lines + tags visible |
| 11 | FORCES strip five rows below|spot|above; hover math; spot pill once (mock) | `renderForces` + `rowH` pill-once + fgrid columns | compact cluster, sources right |
| 12 | ΔOI/DEX real from banked chains; method note encoded | `/api/forces` (server.py) delta-first bucket-by-newer-spot | −157K/+105K · −7.3B/−690.1M banked 07-30→07-31 |
| 13 | ~~CHARM row locked until vote~~ **SUPERSEDED by RC-199 (operator revoked the gate, 2026-08-02): CHARM paints real numbers from /api/forces charm_below/charm_above (full_chain_banked)** | `renderForces` charm row reads the payload | numbers on the face, no lock |
| 14 | Bias LOCKED until facet-(g) + banked-progress phrasing | `#f-bias` | "study not yet registered — 0 sessions banked" |
| 15 | Gamma panel DATA + single-baseline form untouched | `drawGamma` data paths unchanged (diff scope: colors of ARROWS only) | bars/ghosts/volume identical layout |
| 16 | Arrows green-grew/red-shrank + from→to tooltips (operator strike-730 lesson) | shifts fill `#00e07a/#ff3355`; `story` in gZones tip | ▲792.8M etc. green |
| 17 | All strikes labeled while bands fit | label condition `bandW >= 12` | 726..753 all labeled |
| 18 | Scope chips live in the gamma panel header (mock) | chips markup inside `#gammacard` sechead | ALL/≤7 DTE/MONTHLY+/GHOST right of title |
| 19 | γ/STRIKE rail as a LIST (mock): strike left, bars right, wall/spot amber | `drawHist` rewritten | rail rows clean, 750 amber |
| 20 | Theme = the app's own tokens (operator: "follow the theme of the rest of the app") | `:root` = index.html tokens; IBM Plex; quiet chips; flat cards | chrome matches Console family |
| 21 | Staleness/absence honesty preserved (accrual BANKED, #gsrc, charm book labels) | untouched blocks; contract suites | gsrc STALE line renders |

Known deviations, stated: ~~CHARM vote-gate~~ REVOKED 2026-08-02 by operator order (RC-199) —
charm now renders real numbers everywhere its fields are served; no surface may re-encode the
vote lock. Coach cards keep their original floating placement (operator earlier rejected
docking); they can overlap the section-2 title at some widths — pre-existing behavior.

Arbiters: `pytest tests/test_liquidity_engine.py tests/test_chart_accrual_consumer_v1.py
tests/test_charm_scope_surface_v1.py tests/test_client_spot_single_faucet_v1.py -q` = 102
passed · script parses (node Function check) · zero console errors on load.

## v6.2 addendum (RC-195) — cv2 system port + FUNCTIONAL audit, RENDERED-FRAME both themes

Operator rejections after v6.1 ("tabs don't look right, no light/dark, fonts don't match";
"call wall missing in gamma panel"; "levels ON don't render") drove a second pass, confirmed
FEATURE-BY-FEATURE the same way and now also FUNCTIONALLY:

| # | Item | Anchor | Proof |
|---|---|---|---|
| 22 | Console's cv2 tokens, dark + body.light, shared ed_theme toggle | chart :root/body.light + toggleTheme | light frame bg rgb(244,247,251) |
| 23 | .cv-tab nav (Console·Terrain·Chart·Desk) + theme button | header markup | both frames |
| 24 | Sans chrome, mono numerics | body font + var(--mono) usages | frames |
| 25 | Canvas theme-aware via PAL (all draw colors from live tokens) | refreshPal/palRgba + sweeps | light frame canvas readable |
| 26 | Gamma-panel walls/spot as machine assertions | mark2 returns + __edChart.gamma | audit: call_wall/put_wall/spot true |
| 27 | Manager rows print LIVE values; no-data declared in amber | famLiveValues/renderLvlMenu | menu frame (ORB, VWAP bands) |
| 28 | ON-click renders — every family clicked by the audit | __edChart.chart.tags growth 4→17 | audit on-renders:* all pass |
| 29 | Second-faucet PDH fix (engine authority; client stands down) | engineHasPD guard | audit tag list: one PDH only |
| 30 | Zero-placeholder levels refused (VAH 0.00 class) | `v <= 0` ingest guard + tightened test | audit + 128 passed |

FUNCTIONAL arbiter: `node scratchpad/_v6_functional_audit.js` = **PASS 27 / FAIL 0**, zero page
errors through all interactions; RENDERED-FRAME set: `_v6_chart_full.png` (dark),
`_v6_chart_light.png` (light), `_v6_chart_menu.png` (manager open) — all three viewed by the
agent and sent to the operator. Suites: 128 passed (five suites) via turn_self_audit, clean.
