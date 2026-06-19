> **Classification:** Audit Report | **Scope:** Guest/core ticker switch SLA

**Branch:** `fix/ui-transport-guest-switch-sla`  
**Date:** 2026-06-18 (offline_static)

## Classifications

- `CORE_SWITCH_STATIC_MET`
- `GUEST_SWITCH_STATIC_MET`
- `SPECIAL_INDEX_SWITCH_STATIC_MET`
- `GUEST_COLD_START_UX_GAP_FIXED`
- `WRONG_TICKER_REJECTION_COUNTED`
- `STALE_GENERATION_REJECTION_COUNTED`
- `DB_DEGRADED_DURING_SWITCH_SURFACED`
- `LIVE_GUEST_SLA_NOT_PROVEN`

## Operator states (transport only — not model direction)

- SWITCHING
- GUEST DATA WARMING
- GUEST DATA INCOMPLETE
- ANALYTICS PENDING
- CACHE STALE — REFRESHING
- DB DEGRADED — CARDS MAY LAG
- READY

## Summary

Static transport guards remain tier-agnostic for core and guest tickers. This branch adds per-tier switch timing fields on client diagnostics (`fast_quote_first_seen_ms`, `analytics_light_first_seen_ms`, `tier_c_first_seen_ms`, `cards_first_render_ms`), rejection counters (`wrong_ticker_payload_rejected_count`, `stale_generation_payload_rejected_count`), and an operator switch-state chip (`dr-switch-state-chip`). No model, fusion, histogram, or card direction semantics changed.

## Live RTH validation required

- core→guest and guest→core switch with `ED_SWITCH_TIMING=1` under RTH
- guest cold start (no cache) shows pending/warming/incomplete — not prior core cards
- SPX/$VIX/$TNX switch if operator uses them in UI
- correlate switch diag timings with `/api/diagnostics/ticker-switch` buffer

**Recommended next branch:** `fix/card-price-conflict-explainability`
