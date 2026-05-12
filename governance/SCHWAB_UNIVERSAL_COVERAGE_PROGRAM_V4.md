# Schwab Universal Coverage Proof Program V4

**Status:** **LOCKED** — gatekeeper Step 2 final review **APPROVED**; binding for sequencing steps **3–12** and all V4 closure claims under this contract  
**Artifact:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md`  
**Created:** 2026-05-09  
**Locked:** 2026-05-08 — gatekeeper end-to-end directive verification matrix; **LOCK V4** verdict recorded below  
**Supersedes:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md` (**SUPERSEDED_BY_V4**)  
**Authority:** Operator V4 directive — **CSV-canonical universal review-and-replacement**; **no carve-outs**, **no “Phase 2”** deferrals for scope covered herein  
**Executor brief:** see [`CURSOR_V4_AGENT_BRIEF.md`](CURSOR_V4_AGENT_BRIEF.md) for the agent-side workflow and handoff template.

---

## Mission (verbatim)

> Global, universal, complete, 100% through the entire, whole, entirety, no stone left unturned repo, any and all living files, every line, every sentence needs to be consistent.

**Operationalized (V4):** The committed Schwab canonical dictionary (`schwab_field_inventory/schwab_field_dictionary.csv`) is the **universe of field identity**. The repository is the **search space**. V4 requires a **CSV-canonical** register and proof artifacts where **actual checked-in code** uses Schwab canonical fields **wherever a dictionary equivalent fits**, unless an **operator-signed `O-XX`** with mandatory narrative (see **V4-A**) documents retention of a derived or alternate form. **Bare `GOVERNED_EXCEPTION`** is **not admissible** at closure. **Empty `UNREVIEWED`**, **zero `bare_governed_exception_count`**, and **all completion criteria** below must hold simultaneously for any closure claim.

---

## Architectural shift: V3 → V4

| Dimension | V3 | V4 |
|-----------|----|----|
| Primary closure lens | CSV-canonical **review** and disposition | CSV-canonical **review-and-replacement** — code must move toward canonical Schwab references unless a valid **`O-XX`** documents retention |
| `GOVERNED_EXCEPTION` | Allowed under V3-D resolution paths | **`governed_ref`** **MUST** cite **`O-NN`**; disposition **MUST** be **`GOVERNED_EXCEPTION (O-NN)`**; operator register **MUST** contain matching **`### O-NN`** narrative (**V4-A**) |
| Sequencing | Step 5 disposition → Step 6 stability | **Step 5b (mandatory)** — replacement loop until **zero** bare **`GOVERNED_EXCEPTION`** (**V4-B**) |
| Closure metrics | Narrative + register review | **Deliverable 17** JSON counts; **`bare_governed_exception_count` MUST be 0** (**V4-C**) |

**Scanner package (unchanged):** `tools/schwab_universal_coverage_scanner_v3/` — path name, **version `3.0.0`**, and **V3-A–D mechanics** are inherited **verbatim**; V4 changes **disposition law**, **closure bar**, and **tooling** (Deliverables **17–19**).

---

## V4 mandates

### V4-A — Replacement enforcement

- Every register row dispositioned **`GOVERNED_EXCEPTION`** **MUST** cite an explicit operator-signed **`O-NN`** ID in the **`governed_ref`** column.
- **`disposition`** **MUST** use the form **`GOVERNED_EXCEPTION (O-NN)`** with the **same** id as **`governed_ref`**.
- The **`O-NN`** entry in `governance/OPERATOR_DECISION_REGISTER.md` **MUST** appear as a markdown **heading** `### O-NN` (or equivalent ATX level; optional bold on the id) in the **V4 narrative addendum**, and the body **until the next same-or-higher-level heading** **MUST** contain exactly these line prefixes: **`Why:`**, **`Constraint:`**, **`Permanent or interim:`**.
- The narrative **MUST** document: **(i)** why the derived form is retained despite a Schwab equivalent existing in the CSV; **(ii)** the constraint or trade-off justifying non-replacement; **(iii)** permanent vs interim (with target date if interim).
- **Bare `GOVERNED_EXCEPTION`** (missing **`(O-NN)`**, missing **`governed_ref`**, missing/invalid operator narrative) is **not admissible** at V4 closure. **Deliverable 18** enforces this on every commit touching the register (CI).

### V4-B — Replacement loop (sequencing step 5b)

**Insert between** human disposition (step 4) and cross-validator / stability (step 6):

> **5b. Replacement pass.** For every register row dispositioned **bare `GOVERNED_EXCEPTION`** (or otherwise failing **V4-A**), **edit code** to swap **derived → canonical Schwab reference**, **rescan**, and **re-disposition**. Each iteration yields: emission eliminated, **`REPLACED`**, or **`GOVERNED_EXCEPTION (O-NN)`** with valid operator narrative. **Loop terminates** when the scanner + register state produces **zero** bare **`GOVERNED_EXCEPTION`** rows (**`bare_governed_exception_count` = 0**).

This step is **mandatory**, not optional.

### V4-C — Closure metrics

**Deliverable 17** (`tools/schwab_coverage_v4_metrics.py`) emits JSON including at minimum:

- **`replaced_count`**, **`governed_exception_with_oxx_count`**, **`bare_governed_exception_count`**
- **`no_schwab_equivalent_count`**, **`not_market_data_count`**, **`unreviewed_count`**
- **`v4_a_violations`** (register_id list), **`closure_admissible`**

**Closure** requires **`bare_governed_exception_count == 0`** and **`unreviewed_count == 0`**. Counts are recorded in the **V4 closure audit** (Deliverable **16**).

### V4-D — Inherited from V3 (verbatim)

The following **V3** clauses apply **unchanged** to the **v3** scanner package and program inheritance (**V3-E** scope):

#### V3-A — CSV-derived detection vocabulary (replaces V2 hand-curated lists)

- All token vocabularies implemented as **module-level hand-curated market-token lists** in the scanner — including but not limited to regex keyword sets, `MARKET_IDENTS`, `MARKET_STRING_KEYS`, `NAMED_DERIVATION`, SQL token regexes, JS “fallback” token lists, and parallel duplicates — are **forbidden** in **V3** scanner source.
- At scanner init, a single **uniform vocabulary** is **derived** from the CSV: primarily `canonical_field`, plus textual material from `description`, `category`, and `likely_use`.
- **Tokenization rules (normative):** split on `.`; split **camelCase** boundaries; split on snake_case `_` and hyphen `-`; lowercase; drop tokens shorter than a **configurable floor** (default **3**). Store the result as an immutable set (e.g. `frozenset`) for matching.
- **Synonyms** (`governance/schwab_field_synonyms.yaml`) **extend** the trigger set; **embeddings** refine candidate ranking; the **base trigger** for “does this site relate to dictionary vocabulary?” remains **CSV-derived**.
- **Forbidden:** any second source-of-truth token list in scanner modules. A **static analysis test** (Deliverable **14**) fails the build if forbidden patterns are present.
- **CSV refresh at scan time** rebuilds vocabulary automatically.

#### V3-B — Universal file coverage (replaces V2 G1 extension whitelist)

- The V2 **`G1_EXTENSIONS` whitelist** (and any equivalent skip-by-extension logic) is **deleted** from the V3 scanner’s path layer.
- **Text vs binary:** classify files using a **null-byte heuristic** and a **UTF-8 decode** test (policy: failed decode or null-byte presence → **binary** unless a stricter scanner doc says otherwise — doc must be gatekeeper-reviewed at lock).
- **Every** text file under the repo root, **regardless of extension or path**, receives at minimum the **universal catch-all** scan path (token / surface hits against **V3-A** vocabulary and downstream G3 strategies).
- Files that **also** match specialized parsers (Python AST, JS/TS tree-sitter, HTML tree-sitter, SQL heuristics, structured config walks, Markdown fences, etc.) are scanned **additionally** by those parsers — **not exclusively**.
- **Binary** files appear in reconciliation **(c)** with **`clause: "V3-B binary file"`** and **`reason: "non-text content"`** (or a gatekeeper-approved alias recorded in the closure audit).
- The mission’s “any other text file” requirement becomes a **mandatory code path**, not an aspirational clause.

#### V3-C — Symmetric coverage proof

For **each** row of `schwab_field_dictionary.csv` (keyed by `canonical_field`), the tooling emits exactly one of:

- **`field_referenced`** — at least one register row (or cited evidence row) references that canonical field; artifact lists **register_id** pointers (or equivalent stable IDs).
- **`field_orphaned`** — zero references; the **closure audit** explains each orphan (unused canonical primitive, scanner blind spot, or product genuinely does not use the field).

**Closure** requires **every** CSV row to be classified, and **`field_orphaned` entries** to be **individually** reviewed and recorded. Deliverable **13** implements the reverse-coverage report shape.

#### V3-D — Dynamic site field-name capture

The **normative** set of V3-D dynamic-site `pattern_kind` values is maintained in **`tools/schwab_universal_coverage_scanner_v3/V3_DYNAMIC_PATTERNS.md`**. **Register rows whose `pattern_kind` appears in that enumeration** are **V3-D dynamic-site rows** and are subject to the resolution paths below. *(Non-binding illustrations: **`DYNAMIC_DISPATCH`**, **`COMPUTED_PROPERTY`**, **`DYNAMIC_SQL_BUILD`**, **`DYNAMIC_EVAL`**, **`REFLECT_API`**. The **binding** list is **only** the committed enumeration file.)*

**Closure** requires **exactly one** of:

1. **Static disposition:** **`GOVERNED_EXCEPTION (O-NN)`** **with** a **written restriction** on which fields may flow through the site — including an explicit **allow-list** or equivalent contractually bounded description; **or**
2. **Runtime tracing:** instrumented production capture of **resolved** field names **appended** to the register (or linked artifact) per **Deliverable 15** (`SCHWAB_DYNAMIC_SITE_RUNTIME_TRACING_PROTOCOL_V3.md`); **or**
3. **Refactor:** replace dynamic dispatch with **static** field references and **rescan**.

**Authority:** **`V3_DYNAMIC_PATTERNS.md`** is **normative**. **Changes** require **gatekeeper review** on the same bar as contract changes.

**Not admissible at closure:**

- `UNREVIEWED` on V3-D dynamic-site rows.
- **`GOVERNED_EXCEPTION`** without V3-D resolution paths — and under **V4**, without valid **`O-NN`** + narrative (**V4-A**).

#### V3-E — Inherited from V2 (unchanged unless superseded above)

- **G1.1** — Schwab canonical CSV is not dispositioned as application code; vendored paths registry; lock files / manifests; generated output rules; vendor disposition mechanics.
- **G2** — Cross-validator + per-language-family reflection / registry / decorator sweeps — **trigger vocabulary** must be **V3-A CSV-derived** (not curated lists).
- **G3** — Multi-strategy cross-reference (token, category, likely_use, synonym table, embeddings, top-K candidates).
- **G4** — Adversarial falsification independence.
- **G5** — Per-commit CSV refresh cadence; O-XX downgrade discipline.
- **G6** — CI commit-gate + scheduled job; **gatekeeper-reviewed** `cron` at lock.
- **G7** — CSV provenance hash and provenance doc.
- **H1** — Vendor YAML authority (parallel to G3 / synonyms).
- **H4** — Cron review.
- **H5** — Generator-source link re-verification when generator sources change.

---

## Disposition schema (V4)

Each register row: exactly one of **`REPLACED`**, **`GOVERNED_EXCEPTION`**, **`NO_SCHWAB_EQUIVALENT`**, **`NOT_MARKET_DATA`**, **`UNREVIEWED`** — subject to **V3-D** and **V4-A**.

- **`GOVERNED_EXCEPTION (O-NN)`** + **`governed_ref = O-NN`** is the **only** admissible governed form at **V4** closure.
- **`REPLACED`** — canonical Schwab reference is used correctly post-replacement pass.

**Scanner:** Never auto-writes human disposition values except mechanical **`NOT_MARKET_DATA`** subtypes per inherited rules.

---

## Deliverables

| # | Deliverable |
|---|-------------|
| 1 | `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` (this contract) |
| 2 | `tools/schwab_universal_coverage_scanner_v3/` — scanner package (**unchanged** name/version **3.0.0**); includes **`V3_DYNAMIC_PATTERNS.md`** |
| 3 | Tests — Deliverable **3** bar + **14** + **13** / V3-C + **M1** pattern_kind matrix + **17–18** tests |
| 4 | `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` — default **`--output`** for the scanner CLI |
| 5 | `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.md` — index + column dictionary |
| 6 | `tools/check_schwab_csv_first.py` **`--all-files`** |
| 7 | CI — commit gate + **Deliverable 18** + **Deliverable 17** exit semantics (this workflow) + scheduled **cron** (G6) |
| 8 | CSV re-pull tool + diff-on-commit gate (G5) |
| 9 | `governance/schwab_field_synonyms.yaml` (G3) |
| 10 | Adversarial falsification / second-pass protocol (G4) |
| 11 | `governance/SCHWAB_FIELD_DICTIONARY_PROVENANCE_V1.md` (G7) |
| 12 | `governance/schwab_vendor_paths.yaml` (G1.1) |
| 13 | Reverse coverage tooling (V3-C) |
| 14 | V3-A static analysis test |
| 15 | `governance/SCHWAB_DYNAMIC_SITE_RUNTIME_TRACING_PROTOCOL_V3.md` |
| 16 | `governance/SCHWAB_COVERAGE_PROOF_CLOSURE_AUDIT_V4.md` |
| **17** | `tools/schwab_coverage_v4_metrics.py` — JSON metrics; non-zero exit if **`bare_governed_exception_count > 0`** or **`unreviewed_count > 0`** |
| **18** | `tools/schwab_oxx_validator.py` — **`governed_ref`** / disposition / operator narrative validation; **CI** |
| **19** | `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` |

---

## Completion criteria — ALL must hold (fourteen)

1. **Universal reconciliation:** Every file **classified**: text **scanned** (minimum catch-all), **excluded** with **clause**, and **(a) = (b) + (c)** per reconciliation families **without unexplained gap**.
2. **Visitor stability (V2 G2):** Three consecutive runs — **zero** new `pattern_kind` values **and** **zero** cross-validator misses **and** per-language-family sweeps **complete** and dispositioned.
3. **Register completeness:** Every register row dispositioned — **no** `UNREVIEWED`.
4. **V3-A:** Scanner contains **zero** forbidden hand-curated market-token lists; Deliverable **14** passes.
5. **V3-B:** Extension whitelist **absent**; **every** text file hits at least the catch-all path; binary exclusions **cited** as **V3-B**.
6. **V3-C:** Every CSV `canonical_field` row classified **`field_referenced`** or **`field_orphaned`**; orphans **explained** in Deliverable **16**.
7. **V3-D:** Every row whose `pattern_kind` is listed in **`V3_DYNAMIC_PATTERNS.md`** satisfies V3-D resolution — **no** `UNREVIEWED`; **V4-A** governs **`GOVERNED_EXCEPTION`** form and **`O-NN`** narrative.
8. **CI commit-gate** green; CSV refresh per **G5**.
9. **Scheduled** CI on `main` **post-disposition** per **G6**.
10. **Adversarial falsification (G4)** complete with **zero** hits.
11. **CSV provenance** hash matches committed canonical CSV (**G7**).
12. **Closure audit** (Deliverable **16**) committed; program closure recorded under **`O-XX`** in `governance/OPERATOR_DECISION_REGISTER.md`.
13. **V4-A enforcement:** **`bare_governed_exception_count == 0`** and **`unreviewed_count == 0`** per Deliverable **17**; every **`GOVERNED_EXCEPTION`** row has valid **`governed_ref`** and operator **`### O-NN`** narrative with **`Why:`** / **`Constraint:`** / **`Permanent or interim:`**.
14. **File inventory completeness:** `governance/SCHWAB_V4_FILE_INVENTORY.csv` has **zero** rows with **`status=pending`**; every **`reviewed`** row has a **`memo_ref`** pointing to an **existing** memo file; every **`excluded`** row has a **non-empty** **`clause`**; bulk-exclusion clauses trace to **V4** / **V3-B** / **G1.1** contract clauses (operator **O-40**).

---

## Forbidden — non-negotiable

**V3 forbiddens remain in force** where not superseded.

**V4 additions — MUST NOT:**

- Hand-curated market-token lists in scanner source (**V3-A**).
- Extension whitelists (**V3-B**).
- **`field_orphaned`** without per-field explanation in the closure audit (**V3-C**).
- **Bare `GOVERNED_EXCEPTION`** at closure (**V4-A**).
- **Skipping the V4-B replacement loop.**
- **`O-XX` narratives** missing **`Why:`** / **`Constraint:`** / **`Permanent or interim:`**.
- **Inflating `(b)_files_scanned`** with parse errors / `OSError` / binary misclassification (**V3** reconciliation law).
- **Unreviewed edits** to **`V3_DYNAMIC_PATTERNS.md`**, **`governance/schwab_field_synonyms.yaml`**, **`governance/schwab_vendor_paths.yaml`**.
- Treating **V3** register or **V3** closure audit as **V4** closure evidence.
- **Sampling-based dispositions** or **precedent inheritance without operator authorization** (per **`governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md`** § **Evidence bar (V4-A enforcement)**).
- **Skipping any file** in **`governance/SCHWAB_V4_FILE_INVENTORY.csv`** without an **explicit clause citation**; every file row reaches **`status=reviewed`** or **`status=excluded`** with a populated **`clause`** (inventory pivot, **O-40**).

---

## Sequencing — strictly ordered, no skipping

1. Lock **V4** contract (gatekeeper review).  
2. Build **M1** tests + Deliverables **17**, **18**, **19**; all tests green.  
3. Run scanner on **full repo**: `python -m tools.schwab_universal_coverage_scanner_v3 --output governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv`; populate **V4** register.  
4. Human disposition pass — every row **`REPLACED`**, **`GOVERNED_EXCEPTION (O-NN)`**, **`NO_SCHWAB_EQUIVALENT`**, or **`NOT_MARKET_DATA`**; **no** `UNREVIEWED`.  
5. **Replacement pass (V4-B)** — loop until **`bare_governed_exception_count == 0`**.  
6. Cross-validator + per-language-family sweeps → **stability** (three consecutive clean runs).  
7. CSV refresh + provenance hash (**G5**, **G7**).  
8. Adversarial falsification on **`NO_SCHWAB_EQUIVALENT`** rows (**G4**) — zero hits.  
9. **`--all-files`** whole-repo guard green.  
10. CI commit-gate + scheduled **cron** + Deliverable **18** on every commit.  
11. Closure audit **`governance/SCHWAB_COVERAGE_PROOF_CLOSURE_AUDIT_V4.md`** committed.  
12. **`O-XX`** program closure recorded in **`OPERATOR_DECISION_REGISTER.md`**.

---

## Status until V4 closure

```text
PROGRAM: COVERAGE PROOF v4 — IN PROGRESS
COVERAGE PROOF: OPEN — replacement-enforced
SYSTEM: FAIL
```

---

## Relation to other artifacts

- **`SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V1.md`**, **`_V2.md`**, **`_V3.md`** are **historical** for closure claims; **V4** is the active program after lock.  
- **`ENGINEERING_GATEKEEPING_POLICY.md`** must stay consistent with **OPEN** coverage proof until **V4** closes.  
- **`governance/SCHWAB_V4_FILE_INVENTORY.csv`** + **`governance/SCHWAB_V4_REVIEW_MEMOS/`** — file-level proof-of-coverage under operator **O-40** (completion criterion **14**); the V4 register remains a **parallel** completeness cross-check vs scanner emissions.

---

## Lock record

| Event | Detail |
|-------|--------|
| **Draft** | 2026-05-09 — ready for gatekeeper first read |
| **Lock** | **2026-05-08** — Step 2 final gatekeeper review **VERDICT: LOCK**; directive verification matrix complete; no material gaps; M1 + Deliverables **17–19** + CI wiring approved |
| **Gatekeeper** | V4 Step 2 closure: contract, banners, scanner v3 package (unchanged path), tests (**78** green), operator-register V4 addendum |

---

## Revision

**V5** or operator **`O-XX`** program addendum in `governance/OPERATOR_DECISION_REGISTER.md`.
