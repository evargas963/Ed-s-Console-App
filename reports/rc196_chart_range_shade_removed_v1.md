# RC-196 — Chart price-canvas range shade removed

**Date:** 2026-08-02  
**Decide:** WAIT (display-only Chart consumer; no decision-path influence)  
**# chart-intent-ok:** Chart consumer still paints candles + wall lines/tags + gamma panel; only translucent range fills removed.

## What changed

Removed translucent **fill** overlays on the main price canvas in `static/chart.html`:

1. **CALL/PUT RANGE** (`rangeMark`, ex-`rangeShade`) — dropped `g.fillStyle = palRgba(col, 0.05)` + `g.fillRect(...)` over the per-side gamma value-area band (RC-115).
2. **WALL RANGE corridor** (RC-113) — dropped `g.fillStyle = 'rgba(143,168,255,0.055)'` + full-height `fillRect` between put/call walls.
3. **Wall strike histogram box** (`band()`) — dropped `fillRect` + `strokeRect` bucket shade (± half median strike spacing); walls now draw as a single horizontal LEVEL LINE. Bucket width remains tip-only (RC-86 honesty).

## Kept

- Call/put **wall LEVEL LINES** + axis tags (`CWALL` / `PWALL` / `⬌WALL·PIN`) + lean/TWO-SIDED banners
- Left-edge CALL/PUT RANGE banners + range axis tags (no fill)
- Gamma-panel CALL WALL / PUT WALL marks
- LEVELS manager ON/AUTO/OFF behavior
- EM ±1σ dashed lines (not a fill)

## Honest supersession

RC-113 / RC-115 / RC-194 previously treated faint range/corridor **shade** as the institutional affordance. Operator 2026-08-02: shade dulls candles and serves no purpose — tags/lines carry the meaning. Brutal audit row flipped from “Shade + axis edge tag” to **shade ABSENT**.

## Proof

- Source: `static/chart.html` has zero `rgba(143,168,255,0.055)` and zero `palRgba(col, 0.05)` fillRect in the range path.
- Runtime: `__edChart.chart.rangeShadeFill === false` and `__edChart.chart.wallCorridorFill === false`.
- Harness: `node scratchpad/_v6_brutal_ui_audit.js` asserts those flags.
