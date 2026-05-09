# Engineering Gatekeeping Policy

**Status:** Binding engineering operating policy  
**Created:** 2026-05-06  
**Scope:** All code, data-plane, governance, model, calibration, and tooling changes  
**Related references:** `governance/DERIVED_ANALYTICS_REGISTRY.md`, `docs/SCHWAB_FIELD_REFERENCE.md`, `schwab_field_inventory/schwab_field_dictionary.csv`  
**Status axes (GOVERNANCE vs SYSTEM):** § Status Language (canonical; registers/runbooks point here — do not duplicate definitions)

---

## Purpose

This is a hard operating policy, not aspirational guidance. The project must prefer durable architectural fixes over workaround-shaped changes, must consume Schwab-native fields when Schwab provides them, and must reduce dead-code drift as files are touched.

Policy violations must be stopped before commit. If a violation is committed locally, it must be rolled back, rewritten, or superseded before it reaches durable shared history.

---

## Patch Rejection

A change is patch-shaped when it routes around the architectural cause instead of fixing it. Before endorsing or implementing any non-trivial change, the reviewer and implementer must answer:

```text
Does this address the actual architectural issue, or route around it?
Will a future reader ask "why is this here?" If yes, what is the answer?
```

If the answer is "because an upstream layer did not anticipate a later layer," the change is presumed to be a patch and must be rejected unless the operator explicitly approves a temporary exception.

Examples from project history:

- `716abe3` introduced a Black-Scholes theta fallback. It was patch-shaped because the real issue was that `chains.contract_fields()` did not normalize Schwab-native `theta`. The durable fix landed in `286aa65`: normalize Schwab fields first, then use raw Schwab fallback, then derived fallback only when Schwab is unavailable.
- The two-phase live v2 logging proposal was rejected as patch-shaped because it updated a v1-created calibration row later only because the v1 logger ran before `v2_decision` existed. The durable history contains `ed8806f`, which logs live advisory v2 snapshots via a single-phase write after the v2 adapter runs.

Borderline cases must be biased toward rejection until the architectural shape is explicitly approved.

---

## Schwab-Native First

Any code that reads, derives, computes, normalizes, serializes, displays, or gates on a market-data field must first verify whether Schwab provides the field.

Required check:

```text
1. Search `schwab_field_inventory/schwab_field_dictionary.csv`.
2. Confirm the exact `canonical_field` row, endpoint, category, and likely use.
3. Check `docs/SCHWAB_FIELD_REFERENCE.md` and the relevant normalization boundary.
4. If Schwab provides the primitive, normalize and consume the Schwab-native value first.
5. Use derived values only as governed fallbacks or legitimate analytics.
```

The CSV is the canonical field authority. Text references, prior audit notes, and memory are subordinate to the CSV. `schwab_field_inventory/schwab_canonical_fields.txt` may be used as a quick index, but a durable code change must cite or check the CSV row.

Every non-trivial market-data code change must include a CSV-first declaration in the review note, commit body, PR body, or governing slice artifact:

```text
Schwab CSV authority checked: yes
CSV row(s): <canonical_field rows or NO_SCHWAB_EQUIVALENT>
Derived-field disposition: REPLACE_WITH_SCHWAB | KEEP_DERIVED_WITH_PROVENANCE | GATE_FAIL_CLOSED | REDESIGN
  (KEEP_DERIVED_WITH_PROVENANCE requires citation of either
   (a) "no Schwab primitive at this site", or
   (b) named governed exception per §Schwab Same-or-Better Rule;
   "Schwab looked worse" alone is not sufficient)
All consumers checked: yes/no + disposition list
```

Minimum standard for implementation work:

```text
1. If a new field is read, derived, defaulted, renamed, displayed, serialized, or used in a model/gate, search the CSV first.
2. If the CSV has a native primitive, use that field at the normalization boundary and pass it downstream with source/provenance.
3. If no CSV field exists, register or cite the derived analytic before relying on it.
4. If the change touches an existing field, grep all consumers and update or disposition them in the same slice.
5. If a future-slice deferral remains, add it to the appropriate Schwab register before commit.
```

## Schwab Same-or-Better Rule

**Default:** For a given site, if the appropriate Schwab field for that context would yield an answer that is the same as the derived path, or strictly more accurate (closer to exchange- or vendor-authoritative truth, fewer assumptions, correct units/plane), you must use the Schwab field — not derived, not "derived + provenance."

**If Schwab looks worse:** That does not silently authorize staying on derived. It means something is wrong or mis-scoped: wrong field choice, wrong plane, stale snapshot, rounding, timing, bad merge order, bug, or a mistaken assumption in the "appropriate" Schwab mapping. That state requires explicit investigation (trace, repro, measurement) and a governed outcome: either fix the integration so Schwab wins, document a temporary blocker with a named gap and owner, or prove with evidence that the comparison was invalid (e.g. comparing unlike things). "Worse" without investigation is not a standing exception.

**Restated:** Same-or-better → Schwab. Worse → stop and investigate, not default to derived.

Using a derived field as a substitute for a Schwab-provided primitive is a policy violation.

This rule applies to live paths, replay paths, calibration/backfill paths, UI payloads, and tests.

---

## Derived Field Justification

Derived analytics are allowed only when Schwab does not provide the analytic directly, or when the derivation is a governed strategy transform over Schwab-provided primitives.

Every durable derived analytic that influences decisions, gates, replay labels, model features, calibration artifacts, or v2 outputs must be registered in `governance/DERIVED_ANALYTICS_REGISTRY.md` with:

```text
analytic_name
schwab_inputs_consumed
why_derivation_is_legitimate
source_classification
provenance_contract
```

If a new derivation is needed and no registry entry exists, add or update the registry before relying on the derived field.

When both Schwab and a derived fallback produce a value, disagreement monitoring should compare them under a governed threshold and surface `FIELD_SOURCE_DISAGREEMENT` when residuals exceed the threshold.

---

## Dead Code Discipline

The repo must be cleaned as it evolves. When a commit modifies a file, the author must scan the touched file for:

- unused imports;
- unused helpers;
- dead branches;
- stale comments;
- obsolete references;
- abandoned temporary paths;
- duplicated code made unnecessary by the change.

If cleanup is safe and in scope, remove the dead code in the same commit or a small accompanying cleanup commit. If cleanup is not safe or requires broader review, add the finding to `governance/REPO_CLEANUP_QUEUE.md` with a disposition reason.

Dead-code cleanup must not become an excuse for unrelated refactors. Keep cleanup scoped to touched files unless the operator approves a broader sweep.

---

## No Opportunistic Bloat

Helper scripts, probes, temporary runners, one-off validation tools, and ad hoc reports must not accumulate by default.

Each such artifact must be handled one of three ways:

```text
1. Promote to a documented `tools/` entry with explicit purpose and usage.
2. Delete after one-off use.
3. Add to `governance/REPO_CLEANUP_QUEUE.md` with a retention reason and owner/next action.
```

"We might use this again" is not a valid retention reason.

Temporary files and generated reports must not be committed unless the governance record explains why they are durable artifacts.

---

## Enforcement Mechanism

When Claude, Cursor, the operator, or another reviewer flags patch risk or a policy violation, no commit may be made until one of these occurs:

```text
a. The operator explicitly approves the architectural shape; or
b. The flagging tool/reviewer retracts the concern with a stated reason.
```

Silent override is a policy violation.

If a concern is raised after a local commit but before push, fix the durable history before pushing. For unpushed local commits, history rewrite is acceptable when it removes a rejected patch from shared history and preserves the approved final state.

---

## Cleanup Queue

Deferred cleanup findings are tracked in `governance/REPO_CLEANUP_QUEUE.md`.

Every queue entry must include:

```text
file_path
why_flagged
date_flagged
recommended_resolution
status
notes
```

The cleanup queue is not a graveyard. Entries must be resolved, archived with rationale, or revalidated during planned cleanup sweeps.

---

## Status Language

**Canonical pair (do not conflate):**

```text
GOVERNANCE: COMPLETE
SYSTEM: FAIL (S008 measurement pending)
```

The parenthetical names the **specific gate** blocking SYSTEM PASS when one exists (e.g. calendar-driven data accumulation, operator-only measurement, external apply window). Replace `S008 measurement` with the active gate when documenting another program phase.

Two status axes are tracked separately and never merged into a single “green” without evidence:

- **GOVERNANCE: COMPLETE** — Every code-addressable, governance-addressable, and production-migration-addressable item **in scope** has been completed and verified. No remaining work that can be done by writing code, drafting governance, or running a migration.

- **SYSTEM: FAIL** — form `SYSTEM: FAIL (<named gate> pending)`. System-level evidence is not yet in. Used when SYSTEM PASS depends on calendar-driven or external events (data accumulation, measurement windows, operator-only actions) that no further engineering work can replace. The parenthetical names the specific gate.

- **SYSTEM: PASS** — All evidence in, all gates closed. Reserved.

**Banner forms:**

- Top-level: `FAIL until <gate>` — tight, scannable, no confusion with PASS.
- Standard: `GOVERNANCE: COMPLETE / SYSTEM: FAIL (<gate> pending)` — literal.
- Long form: full sentence for footnotes / runbook closure sections.

The avoided phrase **“effectively green”** is a soft synonym for GOVERNANCE: COMPLETE that risks lipstick reads (premature victory vs SYSTEM PASS). Prefer the literal pair above in durable governance.
