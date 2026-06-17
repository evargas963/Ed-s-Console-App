> **Classification:** Policy Specification | **Scope:** UI design system reference.

# EdWebConsole — Design System Reference
# Lock this in. Apply consistently across ALL cards.

---

## FONTS

Primary:  JetBrains Mono (monospace — all data, labels, values)
Display:  Space Grotesk  (headlines, verdict text, large numbers only)

Import:
  https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Space+Grotesk:wght@300;400;500;600;700

---

## FONT SIZE — HARD RULE

Minimum: 10px — NO exceptions, anywhere in the app
* Set on body/universal selector so it inherits everywhere
* Labels:        10px
* Values:        10–12px
* Section titles: 10px (uppercase + letter-spacing)
* Card headlines: 20–38px (Space Grotesk)
* Large numbers:  22–28px (Space Grotesk)

---

## COLOR PALETTE

### Backgrounds (dark to light)
--bg0: #080a0e      /* page background */
--bg1: #0c0f14      /* card background */
--bg2: #111520      /* tag strips, alternate rows */
--bg3: #161b26      /* input fields, bar tracks, inset elements */

### Borders
--border:  rgba(255,255,255,0.07)   /* card borders */
--border2: rgba(255,255,255,0.04)   /* section dividers */
--divider: rgba(255,255,255,0.10)   /* zone separators (thick) */

### Directional — BRIGHT, high contrast
--bull: #00ff88     /* bullish / long / up / bid */
--bear: #ff2244     /* bearish / short / down / ask */

Bull glow:  rgba(0,255,136,0.5)
Bear glow:  rgba(255,34,68,0.5)
Bull dim:   rgba(0,255,136,0.12)    /* badge backgrounds */
Bear dim:   rgba(255,34,68,0.12)

### Text — WHITE hierarchy
--text:  #ffffff    /* primary values, important numbers */
--text2: #c8d0e0    /* secondary labels, field names */
--text3: #7a8499    /* dim labels, section titles, metadata */

### Neutral / flat direction
--neutral: #6a7590
--neutral-dim: rgba(106,117,144,0.2)

### Accent
--gold: #ffd060     /* moderate confidence, warnings */

---

## DIRECTIONAL COLOR RULES

Anything that expresses direction MUST use --bull or --bear:
- Arrows (▲ ▼ →)
- Verdict text and headline
- Field values when directional
- Chart lines, fills, glows
- Bar segments (up = bull, down = bear, flat = neutral)
- Book depth bars
- Percentage labels over bars
- Model direction text
- Pill/badge borders

Static text (non-directional) = --text or --text2
Dim metadata = --text3

NEVER use red/green variants other than --bull and --bear.
NO amber, orange, or muted reds for directional signals.

---

## CARD STRUCTURE

### Header
- Height: ~40px
- Left: card title (10px, uppercase, letter-spacing 0.16em, --text2)
- Right: status badge (10px, bold, colored by state)
- Bottom border: --border2
- Background: subtle gradient rgba(255,255,255,0.025) → transparent

### Zone 1 — Verdict / Summary (top)
- Left accent bar: 4px wide, --bull or --bear with glow
- Background tint: bull-dim or bear-dim gradient
- Contains: direction headline, probability, model agreement pills
- Font: Space Grotesk for headline, JetBrains Mono for everything else
- Separated from Zone 2 by: 2px solid --divider

### Zone 2 — Evidence / Data (bottom)
- Background: --bg1
- Sections separated by: 1px solid --border2
- Section title: 10px, uppercase, letter-spacing 0.12em, --text3

### Footer
- Italic metadata (samples, accuracy)
- --text3 for keys, --text2 for values

---

## COMPONENTS

### Model Stack Row
[name 110px] [arrow 14px] [direction 60px] [conf 40px] [pct flex right] [mini bar 90px]
- Bar height: 4px
- Bar track: --bg3

### Probability Bar
- Bar height: 6px
- Bar track: --bg3, border-radius 3px
- Segments: up=bull 80% opacity, flat=neutral 50% opacity, dn=bear 80% opacity
- Labels: float ABOVE bar, anchored to right edge of each segment
- Label color matches segment color
- Hide labels on segments < 11% width

### Confidence Badge (header right)
- HIGH:     bull-dim bg, --bull text
- MODERATE: gold dim bg,  --gold text
- LOW:      bear-dim bg,  --bear text

### Directional Pills (model agreement)
- agree:    bull-dim bg, --bull text
- disagree: bear-dim bg, --bear text
- neutral:  neutral-dim bg, --text2 text

### Tags (regime, fusion, agreement)
- Background: --bg3
- Border: --border2
- Key: --text2, Value: --text bold white

### LIVE indicator
- 5px dot, --bull color, pulse animation 2s
- Box shadow: 0 0 8px bull-glow
- Text: 10px, --bull, 0.9 opacity

---

## CHART STYLE (Cum Delta / future charts)

- Line: 1.5px, directional color
- Glow pass: 4–5px, directional color at 12–15% opacity
- Fill gradient: directional color, 0% → 22% opacity
- End dot: 4px radius, directional color, white 1.8px center
- End dot glow: shadowBlur 12–14, directional color
- Zero line: dashed [2,5], rgba(255,255,255,0.08)
- Grid lines: rgba(255,255,255,0.03)
- Background: --bg1

---

## SPACING

Card padding:    18px sides, 13–14px top/bottom per section
Section gap:     14px padding top/bottom
Row gap (data):  5px top/bottom padding per row
Pill gap:        5px
Tag gap:         7px
Stats grid:      4 columns, equal width

---

## SSE LIVE INDICATOR

Position: header bar, left of status elements
States:
  LIVE:       green dot + "LIVE"   (--bull)
  CONNECTING: yellow dot           (#ffd060)
  OFFLINE:    red dot + "OFFLINE"  (--bear)
Dot size: 5px, pulse animation when LIVE

---

## LOCKED BASELINE — March 12 2026

The WTDS card redesign is the visual reference for the entire app.
Every card must match this aesthetic. Screenshot confirmed:
- Three equal-width top cards (Right Now / WTDS / The Call)
- WTDS two-zone layout working correctly
- Green #00ff88 bull / Red #ff2244 bear throughout
- White text hierarchy on dark backgrounds
- Probability bars with labels above at segment boundaries
- Model stack rows compact and readable
- Footer accuracy on two rows (1c·3c·5c / 8c·13c)
- DB snapshot count visible in Training Data section
- Cards compact but scannable — this density is the target

---

## RULES TO ENFORCE IN EVERY CURSOR PROMPT

1.  Minimum 10px font — set on * selector, never override below 10px
2.  All directional elements use --bull (#00ff88) or --bear (#ff2244) only
3.  Static text = --text (#ffffff) or --text2 (#c8d0e0)
4.  Dim labels = --text3 (#7a8499) — never for values
5.  Cards have Zone 1 (verdict) + Zone 2 (evidence) two-zone structure
6.  No inline styles for colors — use CSS variables
7.  JetBrains Mono for data, Space Grotesk for headlines only
8.  Bar tracks always --bg3, never transparent
9.  Chart lines always have a glow pass before the main line
10. Every card header has a status badge on the right
11. Card padding: 4–6px top/bottom per section, 18px sides
12. Line height: 1.1–1.2 throughout — no loose spacing
13. Three top cards always equal width (flex: 1 1 0)
14. Accuracy footer: grid 3 columns so 8c falls under 1c
15. All new cards must match WTDS density before delivery

---

## RIGHT NOW CARD — COMPLETED (March 12 2026)

### New CSS Classes
**Narrative:** `.narrative-section` `.regime-badge` `.headline-5m` `.headline-1m` `.price-context` `.alert` `.alert-icon` `.alert-text`
**Order Flow:** `.of-section` `.of-header` `.of-title` `.live-dot-wrap` `.live-dot` `.live-txt` `.of-verdict` `.of-verdict-top` `.of-arrow` `.of-verdict-label` `.of-agreement`
**Fields:** `.of-fields` `.of-field` `.of-fname` `.of-farrow` `.of-fval` `.of-flabel`
**Chart:** `.of-chart` `.of-chart-top` `.of-chart-label` `.of-chart-label-wrap` `.of-chart-right` `.of-chart-price` `.of-price-val` `.of-price-arrow` `.of-chart-val` `.canvas-wrap` `.chart-time-row`
**Interpretation:** `.of-interp` `.interp-dot` `.interp-text`
**Tooltip:** `.cd-tooltip` `.cd-help-icon` `.cd-tt-title` `.cd-tt-row` `.cd-tt-icon` `.cd-tt-body` `.cd-tt-divider`
**Depth:** `.of-depth` `.depth-bar-wrap` `.depth-bid` `.depth-ask` `.depth-labels` `.depth-bid-label` `.depth-ask-label` `.depth-imb`
**Footer:** `.of-footer` `.of-meta` `.of-meta-key` `.of-meta-val`
**Animation:** `.live-dot` uses `@keyframes pulse`

### Data Bindings
- Regime badge: `regime_primary` / `zone_label`, `zone_badge_css` / `regime_color`
- Headlines: `rules_headline` / `micro_5m_headline`, `rules_headline_1m` / `micro_1m_headline`
- Price context: `rules_detail` / `narrative`
- Alerts: `rules_alerts` / `warnings`
- OF verdict: `order_flow_verdict`, `order_flow_arrow`, `order_flow_verdict_color`
- OF agreement: `order_flow_strength` + `order_flow_agreement`
- Fields: score, book_imbalance, cum_delta_proxy, opt_flow_score with arrows/labels
- Footer: `order_flow_regime`, `order_flow_readiness`
- Chart price + arrow: `last_price` vs previous `last_price`

### Chart Spec
- Canvas cum delta: glow pass + main line + gradient fill + end dot + dashed zero line + grid
- History: 220 points max, accumulated from `cum_delta_proxy` on each SSE update
- Reset on ticker change
- Time labels: 09:30 / 11:00 / 12:30 / 14:00 / now

### Interpretation Line (5 states)
- Price ↑ + Delta ↑ → "confirmed buying — delta confirms price move" (bull)
- Price ↓ + Delta ↓ → "confirmed selling — delta confirms price move" (bear)
- Price ↑ + Delta ↓ → "⚠ divergence — price up on weak buying · watch for reversal" (warn)
- Price ↓ + Delta ↑ → "⚠ divergence — price down on weak selling · watch for bounce" (warn)
- Delta flat → "neutral — neither side dominant · chop likely" (neutral)

### Book Depth Bar
- `book_imbalance > 0` → `bid% = 50 + (imbalance × 30)`
- `book_imbalance < 0` → `ask% = 50 + (|imbalance| × 30)`

---

## THE CALL CARD — COMPLETED (March 12 2026)

### Design philosophy
Fusion output leads — The Call decision is downstream of it.
Zone 1 = what fusion sees. Zone 2 = what the system decides to do. Zone 3 = why.

### New CSS Classes
**Zone Fusion:** `.zone-fusion`, `.zone-fusion.up/down/flat` + `::before` accent bar
**Fusion header:** `.fusion-top`, `.fusion-direction.up/down/flat`, `.fusion-conf-row`
**Outcome pills:** `.outcome-pill` + variants (breakout, reversal, continuation, pinning, mean_reversion, vol_expansion)
**Prob bars:** `.prob-bars`, `.prob-row`, `.prob-key`, `.prob-track`, `.prob-fill.up/down/flat`, `.prob-pct.up/down/flat`
**Agreement:** `.fusion-meta`, `.fusion-meta-item`, `.fusion-meta-key`, `.fusion-meta-val`, `.agree-track`, `.agree-fill.high/mid/low`
**Evidence:** `.evcon-row`, `.ev-item`, `.ev-dot.agree/contra`, `.ev-txt`
**Call section:** `.zone-call`, `.call-top`, `.call-signal.long/short/wait`, `.call-type`
**Override:** `.override-reason`, `.override-icon`, `.override-text`
**Levels:** `.levels-grid`, `.level-item`, `.level-key`, `.level-val.entry/stop/t1/t2/rr`
**R:R bar:** `.rr-visual`, `.rr-stop-seg`, `.rr-entry-dot`, `.rr-target-seg.long/short`, `.rr-label`
**Sizing:** `.sizing-row`, `.size-label`, `.size-cue.full/half/quarter/skip`
**Exec badge:** `.exec-badge.standard/reduced/probe/no_trade/max`
**Evidence zone:** `.zone-evidence`, `.fusion-summary`, `.invalidation`
**Badges:** `.badge-long`, `.badge-short`, `.badge-watch`, `.badge-wait`, `.badge-medium`, `.badge-high`, `.badge-low`

### Data Bindings
- Direction + accent bar: `d.fusion_dominant_direction` → up/down/flat
- Confidence badge: `d.fusion_confidence` → high/medium/low
- Outcome pill: `d.fusion_dominant` → breakout/reversal/continuation/pinning/mean_reversion/vol_expansion
- Prob bars: `d.fusion_prob_up`, `d.fusion_prob_down`, `d.fusion_prob_flat`
- Agreement bar: `d.fusion_model_agreement` (≥0.75 green, 0.4–0.75 gold, <0.4 neutral)
- Evidence/contradiction: `d.fusion_n_models_active`
- Signal: `d.call_signal` → long/short/wait
- Conviction: `d.call_conviction`
- Trade type: `d.trade_type_label`
- Override block: shown when `call_signal === 'wait'` AND `fusion_dominant_direction !== 'flat'`
- Levels: `d.entry_disp`, `d.stop_disp`, `d.target_disp`, `d.target2_disp`
- R:R: `d.rr_disp`, `d.rr2_disp`
- Size cue: `d.size_cue`
- Exec mode: `d.execution_mode`
- Summary: `d.fusion_summary` or `d.call_reasoning`
- Invalidation: `d.invalidation`

### Show/Hide Rules
- Levels grid + R:R bar + sizing row: hidden when `call_signal === 'wait'`
- Override block: shown when wait AND fusion not flat
- Invalidation: shown when active AND non-empty

### Header Badge Logic
- `call_signal === 'long'` → badge-long "LONG"
- `call_signal === 'short'` → badge-short "SHORT"
- `call_signal === 'wait'` + `call_state === 'WATCH'` → badge-watch "WATCH"
- else → badge-wait "WAIT"
