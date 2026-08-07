# Chart LEVELS — geometry research (RC-198)

**Date:** 2026-08-02  
**Authority:** operator correction + engine code + TradingView/session VWAP band standard

## Geometry classes

| Family | What it is | Correct Chart geometry |
|--------|------------|-------------------------|
| **VWAP** | Session cumulative volume-weighted typical price | **Polyline** through the session (resets each RTH day) |
| **VWAP ±1σ ±2σ** | Same session: VWAP_t ± k·σ_t where σ²_t = E[tp²]−E[tp]² (vol-weighted) | **Four polylines** tracking VWAP (widen/tighten with dispersion) — **NOT** horizontal tip lines |
| **±1σ day move (EM)** | SpotGamma-style Implied 1-Day Move from ATM IV around **live spot** | **Two horizontal** lines at spot±points (RC-113) — different from VWAP σ |
| **Call/put wall** | Single strike of max GEX mass per side | **Horizontal** level line + axis tag |
| **CALL/PUT RANGE** | Per-side 68% gamma value-area (server) | **Dashed box** lo→hi (outline; fill off per RC-196/197) |
| **Gamma pin / flip / KDS / max pain / HVP / LVP / charm walls / net Γ peak** | Single strike landmarks | **Horizontal** lines |
| **PDH/PDL/PDC, ON H/L, ORB, VAH/POC/VAL** | Session structure prices | **Horizontal** lines (ORB absent until RTH open) |

## VWAP band formula (implemented)

For each RTH bar in the session, after updating cumulative sums:

```
tp = (H+L+C)/3
VWAP = Σ(tp·vol) / Σ(vol)
σ    = sqrt( max(0, Σ(tp²·vol)/Σ(vol) − VWAP²) )
+1σ = VWAP+σ · +2σ = VWAP+2σ · (− same)
```

Engine `compute_vwap_bands` tip scalars remain for the Console liquidity card only.

## Defect fixed

Chart treated tip scalars as horizontal structure levels → operator saw "horrible" flat bands.  
Fix: Chart owns cumulative series from canonical 1m RTH bars (same faucet as VWAP polyline).