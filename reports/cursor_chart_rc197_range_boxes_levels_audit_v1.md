# RC-197 — CALL/PUT RANGE boxes restored + Levels full audit

**Date:** 2026-08-02  
**VERDICT:** PASS (same-turn)

## Operator correction

RC-196 over-deleted: operator rejected the **dulling translucent fill**, not the **two dashed CALL/PUT RANGE boxes**. VWAP ±1σ/±2σ ON looked dead when levels sat off-scale.

## Fixes

1. Dashed `strokeRect` CALL/PUT RANGE boxes restored; `rangeShadeFill` / `wallCorridorFill` stay false.
2. `domain()` expands to every LEVELS family in **ON** (incl. wall ranges) so series paint on the candle pane.
3. `vwb` (VWAP ±1σ ±2σ) default **ON** + one-shot auto→on migration; orange heavier dashes vs EM ±1σ.
4. Brutal audit: `rangeBoxesDrawn >= 2`; **FAIL_OFFSCALE_ONLY** if ON+data has only edge pins.

## Full Levels audit (live :8000)

`node scratchpad/_v6_brutal_ui_audit.js` → **36 pass / 0 fail**

| Family | Verdict |
|--------|---------|
| wall, pin, flip, vwap, em, pd, onhl, va, vwb, maxpain, hvplvp, netpeak, kds, charmw | PASS_RENDERED (in-pane tags) |
| orb | PASS_HONEST_ABSENCE (Sunday — no RTH open) |

## Operator action

Hard-refresh Chart (`Ctrl+F5`). Levels → **VWAP ±1σ ±2σ** (not “±1σ day move”) must show four orange dashed lines. Wall ON must show two dashed range boxes without dimming candles.