> **EVIDENCE / CONTRACT — not a second "now."** Outstanding work from this file, if material, lives on `OPEN_ITEMS.md` PA-48. Pointer: `ACTIVE_PROGRAM.md` → PA-46. Do not open a parallel program from this file.

# Production Claims Register

**Status:** COMPLETE (pre-INF lock audit)  
**Scope:** `server.py` module docstring, `static/index.html` (full semantic grep), `static/governance.html`, `static/ops.html`, key API field names from Tier C contract  
**Date:** 2026-05-01  

**Support legend:** YES = enforcement exists in code for the claim as stated; PARTIAL = some checks/docs; NO = marketing or client label without INF proof; N/A = not an enforcement claim.

---

## A. API / server module claims (`server.py` header + handlers)

| Claim ID | Location | Claim text (exact or faithful paraphrase) | Type | Supported? | Invariant / note | Bounding if unsupported |
|----------|----------|---------------------------------------------|------|------------|------------------|-------------------------|
| **C-SRV-01** | `server.py` L9 | Tier A “no chain, **DB**, or heavy compute” | scope | **YES** (by design) | — | — |
| **C-SRV-02** | `server.py` L10–11 | L1 “**authoritative** cache read” | governed / live | **PARTIAL** | I-20, I-01 | Label as “L1 cache read per server policy” until env + determinism proof |
| **C-SRV-03** | `server.py` L12 | Tier C “full analytical **MarketState**” | completeness | **PARTIAL** | I-15 | Clarify “full when refresh completes; may be stale” |
| **C-SRV-04** | `server.py` L23–24 | Governance panel “**read-only** + optional manual actions” | governed | **PARTIAL** | I-02, §14.6 | — |
| **C-SRV-05** | `GET /api/analytics/state` contract (code comments) | `analytics_stale`, `decision_generation_id`, freshness fields | live / trace | **PARTIAL** | I-19 | Expose clock skew state when INF-2 exists |

---

## B. `static/index.html` — visible copy, titles, and client logic strings

| Claim ID | Location | Claim text | Type | Supported? | Invariant | Bounding |
|----------|----------|------------|------|------------|-----------|----------|
| **C-UI-01** | L2768 `title` on Model Health | “**LIVE** = binary + metadata + **provenance compliant**; **NON-COMPLIANT** = exists but lacks provenance” | governed / live | **PARTIAL** | I-06, I-05, G4 paths | Tooltip → “per server checks; not V3 CONFORMS” until audit green |
| **C-UI-02** | L2773 `model-sync-warning` | Binaries copied from parallel/cascade — “**promotion may not have run**” | risk disclosure | **YES** (warning) | I-02 | Keep; strengthens honesty |
| **C-UI-03** | L2863 | “**FRESH**” pill — “Analytical bundle freshness” | live | **PARTIAL** | I-19 | Tie to server `analytics_*` fields only |
| **C-UI-04** | L2869 | “**CONF**” — “Desk conviction / **confidence**” | confidence | **PARTIAL** | I-17 | Not “model confidence certificate” |
| **C-UI-05** | retired 2026-06-10 (`dr-live-ready-chip` removed with rail Why/gates block; verdict surfaces are the ALL/PLAN pills + `dr-stack-mode-chip`) | “**LIVE_READY**” / “**NOT_LIVE_READY**” | live / readiness | **N/A** (element removed) | I-15 | Negative lock `tests/test_issue18_ui_contract.py::test_signal_rail_card_removed_negative_lock` |
| **C-UI-06** | retired 2026-06-10 (Readiness/trust + Stack-behind-the-call rail blocks removed; per-layer liveness on signal-chain bar) | “**Live readiness**”, “**ML stack layers live**” | live | **N/A** (elements removed) | I-20 | Negative lock `tests/test_live_ui_integrity_v1.py::test_dr_trust_stack_compliance_semantic_preserved` |
| **C-UI-07** | L3268–3269 JS comment | “**authoritative** ticker / expiry” | governed | **NO** (client-side) | — | Rename to “selected ticker” or “UI selection” |
| **C-UI-08** | L3337–3387 telemetry schema | Multiple fields suffixed **`_authoritative`** | trace / governed | **PARTIAL** | I-17 | Rename to `server_confirmed_*` or document as client telemetry vocabulary |
| **C-UI-09** | L4346+ `authFromProvenance` / `signal_chain.authoritative` | “**authoritative**” stage for signal chain bar | governed | **PARTIAL** | I-02 | Server must define authoritative; client only displays |
| **C-UI-10** | retired 2026-06-10 (`actionableNow` / ACTION chip removed with rail Why/gates block; entry state on PLAN pill `tf-plan-state`) | “**actionableNow**” combines tradeable + validation + liveReady | trade signal | **N/A** (code removed) | I-15 | Negative lock `tests/test_issue18_ui_contract.py::test_signal_rail_card_removed_negative_lock` |
| **C-UI-11** | retired 2026-06-10 (`dr-trust-stack` / `active_compliant` readout removed with Readiness/trust block; compliance enforced at train/promote + `verify_active_models.py`) | “**OK (active artifacts compliant)**” / “**DEGRADED**” | governed | **N/A** (element removed) | verify vs runtime split | Negative lock `tests/test_live_ui_integrity_v1.py::test_dr_trust_stack_compliance_semantic_preserved` |
| **C-UI-12** | L4866 comment | “**Real-time** spot authority” | real-time | **PARTIAL** | I-19 | Quote latency ≠ decision determinism |
| **C-UI-13** | L4985–4988 | “**authoritative** quote fields” | live | **PARTIAL** | I-19 | Same as C-UI-12 |
| **C-UI-14** | L5171–5172 | “single **authority** … **SSE_LIVE**” | live | **PARTIAL** | I-19 | Transport authority only |
| **C-UI-15** | L5198 `authoritative_cache_read` | L1 mode label in UI tail | governed | **PARTIAL** | I-20 | Clarify “cache read” not “cryptographic attestation” |
| **C-UI-16** | L7819 | “**Deterministic** FEED thresholds” | deterministic | **NO** (UI-only constants) | I-17 | Rename to “fixed thresholds” or document client-only |
| **C-UI-17** | L7521–7522, L7614+, L7736+, L8483+ | Status dot / SSE “**LIVE**” | live | **PARTIAL** | I-19 | Disambiguate quote-live vs decision-live |
| **C-UI-18** | L7218 `lm-live-meta` | “**Live snapshot** — load ticker…” | live | **PARTIAL** | — | OK if liquidity card labeled advisory |
| **C-UI-19** | L7051 | “**two signals**” (charm drift) | signal | **NO** (descriptive) | — | — |
| **C-UI-20** | L7070–7072 Model Health render | “`LIVE` / `NON-COMPLIANT` / `BINARY MISSING`” pills | governed | **PARTIAL** | Same as C-UI-01 | — |
| **C-UI-21** | L6265–6271 WDS model pills | Client `govTitle(name)` builds tooltip from `d.model_health[]` (`status`, `status_reason`) | governed | **PARTIAL** | Server field `model_health` | Same bounding as C-UI-01 |
| **C-UI-22** | `aria-live` regions L2806, L3197 | Polite live regions | a11y | N/A | — | — |

---

## C. `static/governance.html`

| Claim ID | Location | Claim text | Type | Supported? | Invariant | Bounding |
|----------|----------|------------|------|------------|-----------|----------|
| **C-GOV-01** | L75–77 lead | “data comes only from `/api/governance/panel` (**governed payloads**). **No client-side drift**” | governed | **PARTIAL** | I-02 | True for panel; manual POST still server-side |
| **C-GOV-02** | L77 | “**Production default runtime** remains **parallel** unless manually changed” | architecture | **YES** (descriptive) | — | — |
| **C-GOV-03** | L172 comment | “**Colors map only from explicit boolean** / state strings in **governed payloads** — **no drift math**” | governed | **YES** (UI constraint) | — | — |
| **C-GOV-04** | L411 banner | “**Governed payloads loaded.** Schema v…” | governed | **PARTIAL** | Schema ≠ conformance | — |
| **C-GOV-05** | L366–367 actions-meta | “**Governed controls**: POST … only” | governed | **PARTIAL** | ED_GOVERNANCE_UI_ACTIONS | — |

---

## D. `static/ops.html`

| Claim ID | Location | Claim text | Type | Supported? | Invariant | Bounding |
|----------|----------|------------|------|------------|-----------|----------|
| **C-OPS-01** | L67–69 lead | “**whitelisted** Python maintenance and training scripts” | ops | **PARTIAL** | — | — |
| **C-OPS-02** | L103–110 banner | localhost / remote runner warnings | safety | **YES** | — | — |

---

## E. Logs (representative — not exhaustive line-by-line)

| Claim ID | Location | Pattern | Type | Supported? | Note |
|----------|----------|---------|------|------------|------|
| **C-LOG-01** | `server.py` | `MC_EM_PRE_BMS` trace | diagnostic | **PARTIAL** | Not a conformance claim; avoid reading as proof |

**Rule:** Log lines must be scanned in a follow-on pass for “ready”, “promoted”, “active”, “conforms” language — none added as UNKNOWN here; treat **future** unknown log strings as **PARTIAL** until reviewed.

---

## F. Resolved prior UNKNOWNs

| Prior ID | Resolution |
|----------|------------|
| R-UNK governance/ops HTML | **R-029**, **R-030** — no server `compute_call`; governance is panel JSON; ops is subprocess runner. |
| signal_layer_v1 HTTP | **R-003** — only inside `compute_signals`, not a separate public decision route. |

---

## Register completeness

All **explicit** high-signal UI/API claims in the three static HTML files and server module header are listed. **Line-by-line** `index.html` (9000+ lines) may contain additional minor strings; a scripted extractor is recommended for v2 of this register.

**RESULT:** **PASS** (claims register complete for audited surfaces; optional v2 for exhaustive HTML text nodes).
