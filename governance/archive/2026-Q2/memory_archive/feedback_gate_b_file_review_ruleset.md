> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: gate-b-file-review-ruleset
description: "Binding consolidated Gate B file-review ruleset — 7-artifact sign-off contract, 16-dim verification matrix, 5-section audit brief schema, process rules"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 071babb7-1523-48b7-aaa0-c35a11911a10
---

Adhere to the consolidated Gate B file-review ruleset on every audit brief, verification, and sign-off in this project. Binding, no exceptions. This is the operational implementation of [[gate-b-file-review-ruleset]]'s parent: [[feedback-schwab-full-repo-directive]].

**Why:** Operator delivered this as a single consolidated ruleset on 2026-05-20 after MADA lane closed. Drift from any of these rules in prior slices required re-verification turns; the rules name the failure modes (independent full-Read verification, retract sign-off on re-verification gaps retract+re-Read; "tests lock it" lesson surfaced during MADA cross-wire dispute).

**How to apply:** Before drafting any brief, verifying any commit, or producing any sign-off, mentally walk the 7-artifact contract + 16-dim matrix below. If any artifact/dimension is unmet, fix or refuse sign-off — do not narrate around the gap. See [[feedback-strict-gatekeeping-role]].

---

## Gate B cadence (no drift)

1. Claude drafts canonical audit brief (binding scope)
2. Cursor implements paired-fix (no parallel brief from Cursor — see [[feedback-cursor-drafts-claude-verifies]])
3. Claude verifies at commit SHA against 7-artifact contract
4. Operator signs or rejects

**Alternation:** AUDIT_LANE → OPEN_ITEM_FIX (lane FINDs) → REPO_SWEEP (one category) → OPEN_ITEM_FIX (sweep FINDs) → repeat. **No CONSOLIDATION until the current audit lane is brief + fix closed.**

## Audit brief schema (5 sections, every file)

| § | Content |
|---|---|
| 1 | Identity — entry functions, line ranges, upstream/downstream consumers |
| 2 | FIND / OBS — line-cited; severity (FIND = must fix, OBS = note/defer) |
| 3 | Cross-cutting (mandatory) — UI, provenance, consumers not in this slice |
| 4 | Display / freshness — staleness, bundle age, transport if UI touched |
| 5 | Scope disclosure — what was NOT verified, by name |

## Verification matrix (16 dimensions, every touched file)

1. Schwab-first / derivation — wire→leaf, no synthetic substitutes
2. Fail-closed numerics — no silent 0, 0.33, "flat", "neutral"
3. Single-authority module per contract (`numeric_contract`, `fusion_contract`, `time_et`, …)
4. Time / session / DST — `time_et` only for ET
5. Fusion / canonical tradability — `fusion_is_authoritative`, `canonical_provenance_is_tradable`
6. Coherence audit lanes — full Read of queued files (see [[feedback-full-read-verification-protocol]])
7. Live vs replay parity
8. UI honesty / transport / bundle age
9. Calibration timestamp integrity
10. Stack integrity / degradation visibility
11. Magic thresholds → policy table (when in scope)
12. Regression grep — banned patterns must not reappear
13. Operator scenario tests (when built)
14. V4 governance gate (register / scanner)
15. Cross-cutting block present in brief
16. Complete fix vs patch — contract + tests, not one-liner (see [[feedback-no-patches-solid-fixes]])

## 7-artifact sign-off contract (every SHA)

1. **Ancestry** — parent chain correct
2. **Commit body** — `Slice:` tag + FIND IDs (Slice tag in commit body)
3. **Line-cited fixes** — each FIND → exact lines (cite from same-turn Read; see [[feedback-verification-self-check-against-read-output]])
4. **Imports / single-authority** — no duplicate governance predicates
5. **Tests** — new + regression pass (operator runs; see [[feedback-significant-runs-in-operator-powershell]])
6. **OPEN_ITEMS** — `[x]` with SHA, or open row preserved
7. **Regression / arithmetic** — grep guards, audit JSON counts, no deferred FINDs without ledger

## Process rules (#1–#27, key clauses)

- #3 — every FIND → fix in same commit OR OPEN_ITEMS row before next slice
- #4 — cross-cutting block required; refuse sign-off if missing
- #7 — list what was NOT verified
- #14 — new authority modules = CONSOLIDATION slice only
- #17 — adjacent grep hits → fix-as-we-find or OPEN_ITEMS same turn (see [[feedback-fix-as-we-find-scope-policy]])
- #18 — commit body: `Slice: AUDIT_LANE / OPEN_ITEM_FIX / REPO_SWEEP / …`
- #19 — docs-only commits cannot close code FINDs
- #20 — new dict mappings → grep consumer keys same turn
- independent full-Read verification — independent re-Read at tip; no sign-off from other agent's summary alone (see [[feedback-worktree-staleness-check]])
- retract sign-off on re-verification gaps — retract sign-off if re-verification finds gaps
- #24 — audit JSON counts must match enumerated FINDs
- #25 — money-path domain fully enumerated, not just touched files (see [[feedback-no-audit-deferral-across-walks]])
- #26 — N-site fix → ≥ N regression tests
- #27 — no sampling when operator requires 100% discipline

## Schwab full-repo trace (every market field)

CANOPY (UI/API/DB/log) → TRUNK (ms_dict key / JSON / column) → BRANCH (file:fn:line chain) → LEAF (Schwab wire path from `schwab_field_inventory/schwab_field_dictionary.csv`, OR `NO_SCHWAB_EQUIVALENT`).

Stopping at ms_dict / cache / fusion without reaching LEAF = rejection-grade.

Per market-field reference, exactly one of:
- **REPLACE** with Schwab leaf via adapter
- **O-NN** in `governance/OPERATOR_DECISION_REGISTER.md` (Why / Constraint / Permanent-or-interim) + V4 register row
- **CONFIRM** already on Schwab leaf; cite path in diff

## Forbidden phrases (rejection-grade; extends [[feedback-schwab-full-repo-directive]])

- "scope of current section" / "for this section only"
- "scanner capability" / "the scanner doesn't walk that"
- "ms_dict is the source" (without continuing to leaf)
- "based on the files I've reviewed" (narrowing scope)
- **"tests lock it"** as excuse to skip a semantic cross-wire (MADA lesson, 2026-05-20)
- "fail-closed in [one place]" without canopy→leaf trace
- Any wording that narrows scope below full repo / full file Read

## Module rosters (current, treat as living — re-confirm at brief time)

**Money-path modules:** `signals.py`, `call_engine.py`, `prediction_engine.py`, `realized_contract_eval.py`, `bayesian_fusion.py`, `mc_fusion_adjustment.py`, `market_state.py`, `live_decision_bundle.py`, `features/signal_layer_v1.py`, `features/inference_snapshot.py`, `features/fusion_policy_contract.py`

**Authority modules (single source per contract):** `time_et.py`, `numeric_contract.py`, `fusion_contract.py`, `replay_hold_bars.py`, `position_sizing_policy.py`

## Coherence audit addendum (post–stack walks)

Even when not "in slice," flag in the brief:
- **LIVE-UI** — multi-transport staleness, `decision_generation_id` mismatch
- **Canonical 1/3 triplet** — consumers must check provenance
- **Stack integrity** — `authority_intact=False` must be visible
- **Tri-state None** — withheld vs unavailable vs loading

## Pairing rule

- Audit commit does **NOT** close code FINDs
- Following OPEN_ITEM_FIX / paired-fix commit closes them
- No partial deferrals of `numeric_contract` bypasses as "next pass"
