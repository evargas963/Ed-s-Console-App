# Operator preflight (governance)

**Status:** **ACTIVE** — mandatory before any commit that changes `governance/**/*.md`.  
**Audience:** Program operator, reviewers, automation (CI).

---

## Purpose

- **Mechanical integrity** of governance Markdown (encoding, merge-gate `Commit / PR` shape, high-confidence template leakage in the merge gate) is enforced by **`tools/governance_preflight.py`**.
- **Semantic alignment** (register ↔ phase plan ↔ merge gate ↔ event model, append-only history, G1–G7 truth) remains **operator-attested** via the checklist below and **`governance/GOVERNANCE_MERGE_GATE.md`**.

---

## When to run

Run **before** `git commit` whenever **any** path under `governance/` ending in `.md` is modified or staged.

Same command should be wired into **CI** later when pull requests touch `governance/**/*.md` (see § CI).

---

## Command

From the **repository root**:

```bash
python tools/governance_preflight.py
```

To scan only specific paths (e.g. staged files):

```bash
python tools/governance_preflight.py --paths governance/GOVERNANCE_MERGE_GATE.md
```

**Requirements:** Python 3.9+ (stdlib only).

---

## Exit code interpretation

| Exit | Meaning |
|------|--------|
| **0** | No **hard** failures. **Warnings** may be printed; review them against the semantic checklist. |
| **1** | At least one **hard** failure — **do not commit** until resolved. |

---

## Definition: `Commit / PR` (merge gate run history)

**Normative:** In **`governance/GOVERNANCE_MERGE_GATE.md`** **Run history** (append-only subsections), **`Commit / PR`** is the **governed bundle commit**: the **40-character lowercase** git commit SHA of the commit whose **governance artifact changes** this merge-gate run **primarily certifies** (G1–G7 / Scope).

- It **need not** equal **`HEAD`** at sign-off.
- It **need not** equal the commit that **only** records or amends the merge-gate Markdown (follow-up log commit).
- When **bundle commit ≠ merge-gate log commit**, **Scope** must state the relationship clearly (both SHAs if helpful).

**Legacy:** The frozen **“Run log (operator fills)”** snapshot and any **Run history** dated **before 2026-05-02** may retain **short** SHAs; the preflight tool does **not** fail those retroactively.

---

## Mechanical checklist (mirrors the script)

- [ ] Ran `python tools/governance_preflight.py` from repo root — **exit 0**.
- [ ] No **`[FAIL]`** lines in output.
- [ ] All **`[WARN]`** lines reviewed (may be acceptable; see tool output).

---

## Semantic checklist (human — not proven by the script)

- [ ] Merge gate **run history** documents the **intended** governed bundle; **`Commit / PR`** is that bundle’s **40-character** SHA (policy above).
- [ ] **Scope** explains **bundle vs. log** commits when they differ.
- [ ] **`PHASE_PLAN_INFRASTRUCTURE.md`** §18 version / changelog / operator approval row is correct if the phase plan changed.
- [ ] Register **O-** rows cited by the phase plan / merge gate are correct.
- [ ] **`GOVERNANCE_EVENT_MODEL.md`** status / types align with the register where relevant.
- [ ] **Run history** remains **append-only** (prior runs not rewritten).
- [ ] **Governance-only** commits do not include unexplained **runtime / application** file churn (see merge gate **G5**).
- [ ] No known closure residuals (placeholders, wrong dates, wrong SHAs) remain.

---

## CI (future)

Add a pipeline step: if `governance/**/*.md` changed, run the **same** command from repo root. Reuse **`tools/governance_preflight.py`** — do not duplicate rules in YAML.

---

## Non-goals

- Proving **semantic** cross-document equivalence or G1–G7 truth.
- Detecting a **missing** merge-gate run for every possible edit pattern (heuristics only; operator discipline + merge gate protocol remain authoritative).
- Verifying **append-only** history via git (out of scope for v1).
- Linting paths **outside** `governance/**/*.md` (application code, `OPEN_ITEMS.md` at repo root, etc.).

---

## Schwab V4 register (CSV)

The universal register CSV is **gitignored** (generated). Regeneration, pins, metrics, and Gate II scope notes live in **`governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.md`** — follow that file; do not duplicate commands here.

---

## Revision history

| Revision | Date | Notes |
|----------|------|--------|
| 1 | 2026-05-02 | Initial preflight policy + script contract (`governance_preflight.py`). |

---

*End of operator preflight.*
