> **Classification:** Operational Ledger | **Scope:** Operator-trust open risks — transport, DB, data, validation, card meaning

# Open items — operator trust register

**Purpose:** Prevent “documented but forgotten” risks. Every known gap from merged PRs and audit reports must appear here with an explicit disposition. Loose “remaining risks” in PR bodies are **not** closure — this ledger is.

**Status vocabulary (binding):**

| Status | Meaning |
|--------|---------|
| `OPEN` | Not validated, not fixed, not consciously accepted |
| `NEEDS_RTH_VALIDATION` | Code/audit landed; live RTH evidence still required |
| `FIX_BRANCH_PLANNED` | Named branch owns the fix; not started or in flight |
| `ACCEPTED_LIMITATION_WITH_REASON` | Operator-visible limit documented with evidence; not a bug claim |
| `CLOSED_WITH_EVIDENCE` | Resolved with commit SHA + test or live evidence cite |

**Planned branch sequence (do not skip ledger updates):**

1. RTH validation checklist (post PR #16) — operator / host lane
2. `fix/card-price-conflict-explainability`
3. `investigate/fusion-empirical-override-policy`
4. `audit/market-session-tradeability-guard`
5. CI debt: `hardening` / `pytest-full` / `schwab-csv-first` — separate fix or audit branch

**Governing docs:** [`docs/CARD_TRUST_CONTRACT.md`](CARD_TRUST_CONTRACT.md), [`OPEN_ITEMS.md`](../OPEN_ITEMS.md) (repo-wide), reports under `reports/ui_transport/` and `reports/db_contention/`.

---

## Closed with evidence (reference — do not reopen without new FIND)

| Item | Source | Evidence |
|------|--------|----------|
| UI transport static guard map | PR #11 | `reports/ui_transport/ui_realtime_transport_audit_2026-06-18.md`; tier-agnostic guards in `static/index.html` |
| Tier C duplicate render dedup | PR #12 @ `4129a96` | `_tierCCardRenderFingerprint` / `_shouldSkipTierCCardRender` |
| Card Trust Contract | PR #13 @ `2b417ec` | `docs/CARD_TRUST_CONTRACT.md` |
| SQLite contention instrumentation | PR #14 @ `2ad4882` | `GET /api/diagnostics/sqlite-contention`; `reports/db_contention/db_sqlite_contention_impact_2026-06-18.md` |
| DB contention operator surface | PR #15 @ `db99d24` | `ub-pill-db`, `dr-db-contention-chip`, `db_contention_operator` on Tier C |
| Guest switch SLA diagnostics (static) | PR #16 @ `b621075` | Per-tier switch diag schema v2; `dr-switch-state-chip`; `reports/ui_transport/ui_guest_switch_sla_2026-06-18.md` |

---

## Open register (active)

### LIVE_GUEST_SLA_NOT_PROVEN

| Field | Value |
|-------|-------|
| **Status** | `NEEDS_RTH_VALIDATION` |
| **Source PR / report** | PR #16; `reports/ui_transport/ui_guest_switch_sla_2026-06-18.md` (`LIVE_GUEST_SLA_NOT_PROVEN`) |
| **Why it matters** | Static guards prove safety; they do not prove guest warm-switch meets operator SLA (&lt;2s quote, &lt;15s cold cards per `ED_UI_MAXIMIZE_SLA_MS`) |
| **Operator risk** | Guest switches feel “broken” or show stale cards without the new switch-state chip explaining transport delay |
| **Evidence currently available** | `simulate_switch_guard_matrix` all pairs; switch diag schema; `ED_SWITCH_TIMING` hooks in `static/index.html` |
| **Evidence still needed** | RTH matrix: core→guest, guest→core, guest→guest, special/index; `GET /api/diagnostics/ticker-switch` samples with `fast_quote_first_seen_ms`, `cards_first_render_ms` |
| **Owner branch** | RTH validation checklist (operator host); then tune thresholds if breach proven |
| **Do not close until** | RTH session log + switch diag buffer shows p50/p95 for guest pairs OR explicit SLA breach filed as `FIX_BRANCH_PLANNED` |

---

### DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN

| Field | Value |
|-------|-------|
| **Status** | `NEEDS_RTH_VALIDATION` |
| **Source PR / report** | PR #14, PR #15; `reports/db_contention/db_sqlite_contention_impact_2026-06-18.md` |
| **Why it matters** | DB degradation is now visible, but causality vs STALE / LOADING / switch delay is unproven offline |
| **Operator risk** | Operator attributes card lag to “model wrong” when root cause is SQLite lock wait |
| **Evidence currently available** | Process-local counters; `db_contention_operator` surface; audit classifications |
| **Evidence still needed** | Concurrent scrape: `sqlite_tier1_*` logs + `/api/diagnostics/sqlite-contention` deltas + lane STALE / switch diag timestamps |
| **Owner branch** | RTH validation checklist; possible follow-up `fix/db-tier1-write-isolation` only if impact proven |
| **Do not close until** | Timestamp-joined correlation sample OR audit row `NO_IMPACT_PROVEN` with live negative |

---

### BASE_CAPTURE_NORMALIZATION_RTH_PROOF_NOT_COMPLETE

| Field | Value |
|-------|-------|
| **Status** | `NEEDS_RTH_VALIDATION` |
| **Source PR / report** | Base money-path program; `governance/artifacts/base_ticker_money_path_contract.json` |
| **Why it matters** | SPY/QQQ/IWM capture and normalized rows must rise during RTH for trustworthy training and guest contrast |
| **Operator risk** | Cards/analytics appear fresh while underlying snapshot/normalized pipeline is stale |
| **Evidence currently available** | `base_money_path_logger` wiring; scheduler anchor roster tests |
| **Evidence still needed** | RTH: raw `snapshots_1m` + `snapshots_1m_normalized` row counts/min for SPY/QQQ/IWM during session |
| **Owner branch** | Operator observability lane; fix branch only if capture gap proven |
| **Do not close until** | Row-rate audit during RTH or documented capture outage with fix branch |

---

### HARDENING_CI_FAILING_NON_BLOCKING

| Field | Value |
|-------|-------|
| **Status** | `OPEN` |
| **Source PR / report** | CI on PRs #14–#16; merge gate = `objective-audit` only |
| **Why it matters** | Hardening workflow may catch rule drift not covered by objective-audit |
| **Operator risk** | Silent regression in institutional locks until someone runs hardening locally |
| **Evidence currently available** | `gh pr checks` → `hardening` fail on recent PRs |
| **Evidence still needed** | Root-cause per failing job; green run on main |
| **Owner branch** | Separate CI fix/audit branch (after card explainability sequence item 5) |
| **Do not close until** | `hardening` green on main @ tip |

---

### PYTEST_FULL_CI_FAILING_NON_BLOCKING

| Field | Value |
|-------|-------|
| **Status** | `OPEN` |
| **Source PR / report** | CI on PRs #14–#16 |
| **Why it matters** | Full suite may cover cones not in PR-scoped pytest |
| **Operator risk** | Production-only test failures undetected until full CI fixed |
| **Evidence currently available** | `pytest-full` fail on recent PRs |
| **Evidence still needed** | Failing test list from CI log; fix or quarantine with evidence |
| **Owner branch** | Separate CI fix branch (sequence item 5) |
| **Do not close until** | `pytest-full` green on main @ tip |

---

### SCHWAB_CSV_FIRST_CI_MIXED_OR_FAILING_NON_BLOCKING

| Field | Value |
|-------|-------|
| **Status** | `OPEN` |
| **Source PR / report** | `schwab-csv-first` workflow; PRs #14–#16 |
| **Why it matters** | Schwab market-field diff-emission gate must stay live for new market-fact sites |
| **Operator risk** | New market reads land without register row / leaf trace |
| **Evidence currently available** | `schwab-csv-first` fail on recent PRs (may be env/register artifact) |
| **Evidence still needed** | CI log disposition per failure class |
| **Owner branch** | Schwab CI lane (sequence item 5) |
| **Do not close until** | `schwab-csv-first` green or failures classified with operator narrative |

---

### PROCESS_LOCAL_SQLITE_COUNTERS_ONLY

| Field | Value |
|-------|-------|
| **Status** | `ACCEPTED_LIMITATION_WITH_REASON` |
| **Source PR / report** | PR #14, PR #15 |
| **Why it matters** | `sqlite_contention_metrics_snapshot()` is in-process; multi-worker uvicorn would double-count or miss |
| **Operator risk** | DB pill under-reports contention in multi-worker deploy |
| **Evidence currently available** | Single-process deployment today; counters in `db.py` |
| **Evidence still needed** | Only if operator moves to multi-worker — aggregate design |
| **Owner branch** | `fix/db-contention-aggregate` when/if multi-worker deploy is chosen |
| **Do not close until** | N/A for single-process; upgrade status if architecture changes |

---

### CARD_EXPLAINABILITY_NOT_IMPLEMENTED

| Field | Value |
|-------|-------|
| **Status** | `FIX_BRANCH_PLANNED` |
| **Source PR / report** | PR #13 Card Trust Contract; operator trust gap (price down, cards up) |
| **Why it matters** | Contract defines what cards may mean; UI does not yet explain fusion vs histogram vs tape conflict |
| **Operator risk** | Operator cannot reconcile apparent contradictions — trust erosion |
| **Evidence currently available** | `docs/CARD_TRUST_CONTRACT.md`; transport surfaces from PRs #11–#16 |
| **Evidence still needed** | Implementation + paired UI tests |
| **Owner branch** | `fix/card-price-conflict-explainability` (next code branch after RTH checklist) |
| **Do not close until** | Branch merged with tests + contract section cite |

---

### FUSION_HISTOGRAM_OVERRIDE_POLICY_UNDECIDED

| Field | Value |
|-------|-------|
| **Status** | `FIX_BRANCH_PLANNED` |
| **Source PR / report** | Card Trust Contract; `ACTIVE_PROGRAM.md` fusion-only cards |
| **Why it matters** | Empirical histogram vs fusion authority when they disagree is not operator-resolved |
| **Operator risk** | Silent blend or ambiguous chip implies wrong semantic |
| **Evidence currently available** | Fusion-only defaults (`ED_MH_EMPIRICAL_SUPPORT=0.0`); contract text |
| **Evidence still needed** | Policy decision + code path if override allowed |
| **Owner branch** | `investigate/fusion-empirical-override-policy` |
| **Do not close until** | Governed policy row + mechanical lock or explicit O-NN |

---

### MARKET_SESSION_TRADEABILITY_GUARD_NOT_AUDITED

| Field | Value |
|-------|-------|
| **Status** | `FIX_BRANCH_PLANNED` |
| **Source PR / report** | Card Trust Contract § session boundaries; `call_engine` session warnings |
| **Why it matters** | After-hours / holiday / closed-session cards may imply tradeability incorrectly |
| **Operator risk** | Actionable-looking cards when session is not RTH |
| **Evidence currently available** | `dr-session-boundary-chip`; partial session logic in money path |
| **Evidence still needed** | End-to-end audit: session state → card chips → operator copy |
| **Owner branch** | `audit/market-session-tradeability-guard` |
| **Do not close until** | Audit report + fix branch or `ACCEPTED_LIMITATION_WITH_REASON` with evidence |

---

## RTH validation checklist (operator host — post PR #16)

Run before closing `LIVE_GUEST_SLA_NOT_PROVEN` or `DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN`:

- [ ] `ED_SWITCH_TIMING=1` — switch SPY→NVDA→QQQ→SPY; capture `[SWITCH_TIMING]` console + `GET /api/diagnostics/ticker-switch`
- [ ] Same session: `GET /api/diagnostics/sqlite-contention` every 5s during concurrent base capture
- [ ] Correlate `dr-switch-state-chip` / `dr-db-contention-chip` / `dr-lane-stale-chip` timestamps in screen recording or log
- [ ] Verify guest cold start (no cache) shows `GUEST DATA WARMING` or `ANALYTICS PENDING`, not prior ticker cards
- [ ] SPY/QQQ/IWM: snapshot + normalized row counts during RTH window
- [ ] Optional: SPX / `$VIX` switch if operator uses index symbols

**Record results in:** this file (append dated subsection under the relevant item) or `OPEN_ITEMS.md` row with SHA / log path.

---

**Last updated:** 2026-06-11 — ledger created post PR #16 merge (`b621075`). Next code branch: `fix/card-price-conflict-explainability` only after RTH checklist attempted or explicitly `[REAL-GATE: host-only]` row added in `OPEN_ITEMS.md`.
