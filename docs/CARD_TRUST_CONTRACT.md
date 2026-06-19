> **Classification:** Governing Contract | **Scope:** Operator-facing card truth, freshness, and evidence hierarchy

# Card Trust Contract

**Status:** Governing target for card, fusion, histogram, transport, and explainability work.  
**Binding on:** All future UI card semantics, explainability chips, fusion/histogram policy, and market-session tradeability changes.  
**Non-binding on:** Current production behavior until a named fix branch explicitly implements a section marked *target future*.

---

## 1. Purpose

Ed Console must move from **signal display** to an **operator decision system**. Cards are the visible endpoint of a chain of custody — not standalone predictions.

The operator must be able to answer, for every visible signal:

| Question | Contract owner |
|----------|----------------|
| Is this signal **fresh**? | §8 Freshness / stale / loading |
| Is it **forecast** or **current tape**? | §5 Forecast vs current tape |
| Does **histogram** agree? | §6 Fusion vs histogram conflict |
| Does **tape** agree? | §5, §11 reason classes |
| Is **ALL** tradeable? | §7 ALL and PLAN tradeability |
| Is **PLAN** actionable? | §7 ALL and PLAN tradeability |
| **Why** LONG / SHORT / WAIT? | §11 Operator-facing reason classes |
| What would **invalidate** it? | §11, §13 |

**Operating conclusion (preserved from audits):**

> The trust gap — price down, all cards up — is real; it is mostly **hidden reconciliation**, not necessarily a broken fusion read.

Horizon chips today show **fusion forecast direction**. They do not automatically reconcile trailing price, empirical histogram, or call-engine veto. The UI must not imply that reconciliation has already occurred unless a surface explicitly says so.

---

## 2. Definitions

| Term | Definition |
|------|------------|
| **Horizon cards (1M / 5M / 15M / 60M)** | Per-horizon product surfaces (`#tf-signal-1c`, `5c`, `15c`, `60c`) showing direction and confidence from `mhap_rows` for that horizon. |
| **Fusion forecast** | Seven-layer stack posterior per horizon: fusion probability triplet (`fusion_prob_up/down/flat`) → dominant direction on the horizon card. Default product authority (`ED_MH_EMPIRICAL_SUPPORT=0`, fusion-only contract). |
| **Empirical histogram / similar setups** | `horizon_prob_bars` — trailing similar-setup outcome distribution (up/down/flat). Signal-rail **context** by default; not the product triplet arbiter unless operator explicitly opts into blend. |
| **Tape stack** | Current market structure context used by rules/call-engine (zone, microstructure headlines, trailing tape direction, confluence). Participates in ALL/PLAN veto; not the horizon card direction source. |
| **ALL** | Consolidated tradeability direction (`#tf-signal-consolidated`) from `final_bias` + `final_tradeable` / multi-horizon synthesis. |
| **PLAN** | Actionable execution state (`#tf-signal-plan`) — entry, stop, targets, invalidation, size when tradeable setup exists. |
| **STALE** | Data or transport freshness warning — payload age, quote ahead of bundle, lane behind decision generation, or feed age beyond threshold. Does not by itself change model direction; may withhold or dim direction. |
| **LOADING** | Transport or backend pending — analytics shell, Tier C in flight, `ANALYTICS…` status. Not a trading signal. |
| **Tradeable** | Call-engine and policy gates pass; ALL/PLAN may show actionable bias/setup. |
| **Informational-only** | Signal may display for context but must not imply actionable entry (after-hours, blocked ALL, non-RTH, guest sparse data). |
| **Core tickers** | Money-path anchors: **SPY, QQQ, IWM** — strongest base capture and normalization parity expectations. |
| **Guest tickers** | All other symbols (NVDA, AAPL, TSLA, PLTR, …) — same transport guards; weaker capture/normalization parity unless promoted. |
| **Special/index tickers** | SPX, `$SPX`, `$VIX`, `$TNX`, etc. — supported where Schwab/DB wire exists; storage key normalization via `instrument_identity.ticker_storage_key`. |

---

## 3. Visible UI element contract

| UI element | Allowed to mean | Must not mean |
|------------|-----------------|---------------|
| **1M / 5M / 15M / 60M chips** | Fusion **forecast** direction + confidence for that horizon | Trailing price direction, guaranteed trade, or histogram-final verdict |
| **Histogram rail / bars** | Empirical similar-setup evidence | Silent override of fusion product triplets (unless explicit blend opt-in) |
| **Tape / structure context** | Current market structure for operator context | Horizon card direction unless a future reason class says so |
| **ALL pill** | Reconciled tradeability direction (may be FLAT/WAIT while horizons disagree) | “All horizons agree — go trade” |
| **PLAN pill** | Actionable setup state when tradeable | Actionable when call-engine blocked or session invalid |
| **FEED pill** | Quote/transport freshness (LIVE/SYNCED/DELAY/STALE/DOWN) | Model confidence or card direction |
| **UI ACTIVE chip** | Analytics bundle version accepted | Cards are RTH-tradeable |
| **LANE STALE chip** | Quote ahead, cards painting, pending analytics, syncing | Model is wrong |
| **STALE CSS on cards** | Direction withheld — freshness/coherence | Broken pipeline (without error-bar context) |
| **LOADING on cards** | Awaiting Tier C / auth / partial analytics | LONG or SHORT forecast |

---

## 4. Evidence hierarchy

Evidence flows **up** the stack; operator explanation flows **down**:

```
Primitive market data (Schwab quotes, chain, snapshots)
        ↓
Engineered features (MVP, inference_snapshot, zone/vwap distances, similar-set filters)
        ↓
Model / fusion forecast (seven-layer stack → per-horizon fusion triplet)
        ↓
Empirical histogram / similar-setup evidence (horizon_prob_bars)
        ↓
Tape / current structure (rules, microstructure, trailing returns)
        ↓
ALL / PLAN tradeability (multi_horizon_decision, call_engine veto)
        ↓
Operator-facing explanation (reason class + provenance)
```

**Rule:** No card may show a naked **LONG** or **SHORT** without a traceable **reason class** (§11) once explainability work lands. Until then, audits document the hidden reconciliation gap explicitly.

---

## 5. Forecast vs current tape

| Layer | Time semantics | June 2026 production truth |
|-------|----------------|----------------------------|
| **Horizon cards** | Forward **forecast** | `mhap_rows.call` = fusion argmax — **not** trailing price sign |
| **Trailing price** | What tape did recently | Shown in utility bar / sidebar — separate from horizon chip |
| **Histogram** | Historical similar-setup outcomes | Context rail — may disagree with fusion |
| **ALL/PLAN** | Tradeability now | May **block** while all horizons show LONG |

**Operator rule:** If price is down and horizon cards are up, assume **forecast vs tape conflict** until a reason class proves otherwise — not necessarily a broken fusion read.

---

## 6. Fusion vs histogram conflict

**Current policy (production):**

- Product horizon direction = **fusion only** (default blend weight 0).
- Histogram disagreement is **visible on signal rail** but does **not** change product triplets.
- June 17 SPY decline audit: histogram often SHORT on 1m/5m while fusion/card LONG; 1c forward hit rate ~72% — valid reversal forecasts exist.

**Conflict is real and must not be hidden.** Audits found:

- 73 cells: histogram SHORT + fusion LONG (128-cell shape audit)
- 52 fusion overrides bearish histogram
- 17 valid reversals despite bearish histogram
- 36 underconditioned histogram cells
- 14 too-flat histogram cells

**Policy decision** — owned by branch `investigate/fusion-empirical-override-policy` (not settled in this contract):

- Show conflict only?
- Confidence haircut?
- Force WAIT on conflict?
- Horizon-specific rules (1M reversal allowed, 60M not)?

**This contract does not decide the policy.** It requires any future policy change to be explicit, measured, and surfaced on cards.

---

## 7. ALL and PLAN tradeability rules

| Surface | Source | Independence |
|---------|--------|--------------|
| **ALL** | `final_bias`, `final_tradeable`, multi-horizon synthesis | May be FLAT/WAIT when all horizon cards LONG |
| **PLAN** | `entry_state`, plan text fields when `engineTradeableSetup(d)` | Blocked when call-engine veto active |

**June 17 example:** All horizons LONG during SPY decline; ALL/PLAN blocked via call-engine veto (`wait_reason`: tape stack disagrees).

**Contract:**

- Horizon LONG does **not** imply ALL tradeable or PLAN actionable.
- When blocked, operator must see **why** (wait_reason / blocker), not silent FLAT on horizons only.

---

## 8. Freshness / stale / loading contract

| State | Meaning | Primary drivers |
|-------|---------|-----------------|
| **FRESH** | Bundle/quote within trust window | `dr-freshness-pill`, feed age ≤3s |
| **STALE (feed)** | Quote age >30s or plane misaligned | `computeFeedState` |
| **LANE STALE** | Quote ahead of bundle, cards painting behind gen, pending analytics | `laneStaleOperatorLabel` |
| **LOADING** | Tier C pending, partial shell, refresh in progress | `analytics_pending_shell`, status `ANALYTICS…` |
| **Direction withheld** | Do not paint direction as authoritative | `data-direction-withhold`, bundle trust window |

**Transport audits (PR #11, PR #12):**

- Hybrid SSE + REST + poll; tier-agnostic ticker guards.
- Tier C duplicate render skip landed PR #12 — render efficiency only, not semantics.
- SQLite lock contention observed June 18 — may delay Tier C; audit pending (`audit/db-sqlite-contention-impact`).
- Live RTH switch SLA not yet proven.

**Operator rule:** STALE/LOADING describe **freshness or transport**, not model correctness.

---

## 9. Core vs guest ticker expectations

| Tier | Symbols | Capture parity | UI contract |
|------|---------|----------------|-------------|
| **Core** | SPY, QQQ, IWM | Base money-path capture ~1/min RTH; normalization debounce (PR #9) | Full analytics expected warm |
| **Guest** | NVDA, AAPL, TSLA, PLTR, … | Weaker/sparse normalized history unless promoted | Same transport guards; must show **degraded/pending** when data sparse — never fake fresh |
| **Special/index** | SPX, $VIX, $TNX | Wire-dependent | Same guards; informational when chain/models sparse |

**Ticker switching (PR #11):** Must be seamless, guarded, fast for **core and guest** — wrong-ticker discard, generation guards, stale cache restore marked `analytics_stale`.

---

## 10. Market session modes

**Target contract** (not fully enforced in UI today — audit pending `audit/market-session-tradeability-guard`):

| Mode | Operator expectation |
|------|----------------------|
| **RTH live** | Full transport + tradeability surfaces honest |
| **Premarket** | Informational bias; PLAN likely non-actionable |
| **After-hours** | **Informational-only** — PLAN disabled, options may be invalid |
| **Closed / holiday** | No implied RTH tradeability; cards must not look “armed” |

**Observed gap:** Active-looking cards after hours — unresolved; requires session guard audit.

---

## 11. Operator-facing reason classes

### Current production (implicit)

Horizon chips show direction only — reconciliation with tape/histogram/ALL is **hidden**.

### Target future card language

Each LONG/SHORT/WAIT must map to a **reason class** (chip or subtitle):

| Class | Meaning |
|-------|---------|
| `LONG — momentum confirmation` | Forecast aligns with trailing tape / structure |
| `LONG — reversal forecast` | Forecast up against bearish tape/histogram with valid forward edge |
| `LONG — histogram conflict` | Fusion LONG, empirical histogram disagrees |
| `LONG — tape conflict` | Fusion LONG, trailing tape down |
| `LONG — low empirical support` | Sparse or flat histogram |
| `LONG — ALL blocked / no setup` | Horizon LONG but ALL/PLAN not tradeable |
| `SHORT — momentum confirmation` | Forecast aligns with bearish tape |
| `SHORT — reversal forecast` | Forecast down against bullish context |
| `WAIT — fusion/histogram conflict` | Product withheld or FLAT due to conflict policy |
| `WAIT — stale inputs` | Freshness gate — not a directional call |
| `WAIT — no tradeable setup` | Call-engine or PLAN gate |

**Invalidation** must be visible on PLAN (already has invalidation field) and linked to reason class when explainability lands.

---

## 12. Required provenance for every card

Every card-driving payload must carry (transport audit):

| Field | Purpose |
|-------|---------|
| `ticker` | Ownership / mismatch discard |
| `_server_build_ts` | Freshness / monotonic render |
| `decision_generation_id` | Out-of-order discard |
| `_update_source` | SSE vs REST vs cache |
| `mhap_rows[]` | Per-horizon fusion direction + confidence |
| `horizon_prob_bars` | Empirical context |
| `fusion_triplets` / fusion fields | Forecast provenance |
| `wait_reason` / blockers | ALL/PLAN veto |
| `analytics_stale`, `analytics_refresh_in_progress` | Degraded state |

**Audit artifacts:**

- `reports/money_path/direction_integrity_2026-06-17.{md,json}`
- `reports/card_fidelity/card_signal_fidelity_2026-06-17.{md,json}`
- `reports/ui_transport/ui_realtime_transport_audit_2026-06-18.{md,json}`

---

## 13. What the UI must never imply

1. Horizon LONG = price will go up (it is a **forecast**, not a guarantee).
2. All green horizon cards = safe to trade (ALL/PLAN may block).
3. Histogram rail direction = product card direction (fusion-only default).
4. STALE or LOADING = model says WAIT (freshness ≠ forecast).
5. Guest ticker cards are as fresh as core without degraded markers.
6. After-hours display = same tradeability as RTH.
7. Reconciliation already happened because cards look uniform.
8. Transport delay = model wrong (may be SQLite, SSE, or Tier C compute).

---

## 14. Future fix branches governed by this contract

| Branch | Governs | Contract sections |
|--------|---------|-------------------|
| `audit/db-sqlite-contention-impact` | DB lock → UI stale | §8, §9 |
| `fix/ui-transport-guest-switch-sla` | Guest switch UX | §8, §9 |
| `fix/card-price-conflict-explainability` | Reason classes on cards | §3, §6, §11 |
| `investigate/fusion-empirical-override-policy` | Histogram vs fusion policy | §6, §11 |
| `audit/market-session-tradeability-guard` | RTH / after-hours | §10, §7 |

**Completed (reference only):**

- `audit/ui-realtime-transport-fidelity` (PR #11)
- `fix/ui-transport-tier-c-dedup` (PR #12)

---

## Audit findings referenced (main @ post PR #12)

| Audit | Key finding |
|-------|-------------|
| **Card direction integrity** (`reports/money_path/direction_integrity_2026-06-17.md`) | Horizon direction traces to fusion; trailing conflict measurable |
| **Card signal fidelity** (`reports/card_fidelity/card_signal_fidelity_2026-06-17.md`) | Fusion-only product; empirical conflicts common; explainability gap |
| **Histogram shape** (same fidelity report) | 52 fusion-over-bearish-histogram; 36 underconditioned; 14 too-flat |
| **UI transport** (`reports/ui_transport/ui_realtime_transport_audit_2026-06-18.md`) | Hybrid transport; tier-agnostic guards; Tier C dedup fixed PR #12 |

---

## Amendment path

Changes to this contract require:

1. Named fix branch citing section(s) amended.
2. Paired test or audit artifact where behavior changes.
3. No silent drift — card meaning changes must be explicit in PR body and operator release notes.

**This document does not authorize model, threshold, fusion-weight, or rendering changes by itself.**
