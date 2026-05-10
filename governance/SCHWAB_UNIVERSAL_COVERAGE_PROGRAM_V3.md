# Schwab Universal Coverage Proof Program V3

**Status:** **LOCKED** — gatekeeper-approved; binding for Step 2 scanner build (`tools/schwab_universal_coverage_scanner_v3/`) and all V3 closure claims  
**Artifact:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md`  
**Created:** 2026-05-09  
**Locked:** 2026-05-09 — gatekeeper final end-to-end re-read (T1 V3-D enumeration authority, C1 dates, C2/C3 deliverables 1–16); **APPROVED** for implementation  
**Supersedes:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V2.md` (**SUPERSEDED_BY_V3**)  
**Authority:** Operator V3 directive — **CSV-canonical** coverage; **no hand-curated scanner token lists**; **no extension whitelist**

---

## Mission (verbatim, unchanged from V1/V2)

> Global, universal, complete, 100% through the entire, whole, entirety, no stone left unturned repo, any and all living files, every line, every sentence needs to be consistent.

**Operationalized (V3):** The committed Schwab canonical dictionary (`schwab_field_inventory/schwab_field_dictionary.csv`) is the **universe of field identity**. The repository is the **search space**. Build a **CSV-canonical** register and proof artifacts where **every text file** is examined (with exclusions **only** as cited in reconciliation), **every** dictionary row participates in a **symmetric** proof (file → field and field → files), and **every** cited site is **explicitly dispositioned** under this contract. **Empty `UNREVIEWED` across the entire register**, together with **all V3 completion criteria below**, is the only admissible closure claim.

---

## Architectural shift: V2 → V3

| Dimension | V2 | V3 |
|-----------|----|----|
| Detection vocabulary | Hand-curated token / ident lists in scanner source | **Derived at init** from CSV columns (`canonical_field`, `description`, `category`, `likely_use`) — **V3-A** |
| File scope | Extension whitelist (`G1_EXTENSIONS`) + catch-all clause | **Universal text detection** — no skip-by-extension; specialized parsers **add** signal, they do not define membership — **V3-B** |
| Proof direction | Primarily file → register / CSV candidates | **Bidirectional** — each CSV row classified `field_referenced` or `field_orphaned` with audit — **V3-C** |
| Dynamic sites | Disposition schema as in V2 | **V3-D** — dynamic-site rows require a **resolved** path (static allow-list, runtime trace protocol, or refactor); not closable on `UNREVIEWED` or bare `GOVERNED_EXCEPTION` |

V2’s G1.1 (vendor, generated, lock files, CSV self-scan), G2 (cross-validator, reflection sweeps), G3 (multi-strategy cross-reference), G4 (adversarial independence), G5 (CSV cadence / O-XX), G6 (cron gatekeeper review), G7 (provenance hash), and H1 / H4 / H5 obligations are **inherited** **unless** this document explicitly **replaces** them (**V3-E**).

---

## V3 mandates

### V3-A — CSV-derived detection vocabulary (replaces V2 hand-curated lists)

- All token vocabularies implemented as **module-level hand-curated market-token lists** in the scanner — including but not limited to regex keyword sets, `MARKET_IDENTS`, `MARKET_STRING_KEYS`, `NAMED_DERIVATION`, SQL token regexes, JS “fallback” token lists, and parallel duplicates — are **forbidden** in **V3** scanner source.
- At scanner init, a single **uniform vocabulary** is **derived** from the CSV: primarily `canonical_field`, plus textual material from `description`, `category`, and `likely_use`.
- **Tokenization rules (normative):** split on `.`; split **camelCase** boundaries; split on snake_case `_` and hyphen `-`; lowercase; drop tokens shorter than a **configurable floor** (default **3**). Store the result as an immutable set (e.g. `frozenset`) for matching.
- **Synonyms** (`governance/schwab_field_synonyms.yaml`) **extend** the trigger set; **embeddings** refine candidate ranking; the **base trigger** for “does this site relate to dictionary vocabulary?” remains **CSV-derived**.
- **Forbidden:** any second source-of-truth token list in scanner modules. A **static analysis test** (Deliverable **14**) fails the build if forbidden patterns are present.
- **CSV refresh at scan time** rebuilds vocabulary automatically.

### V3-B — Universal file coverage (replaces V2 G1 extension whitelist)

- The V2 **`G1_EXTENSIONS` whitelist** (and any equivalent skip-by-extension logic) is **deleted** from the V3 scanner’s path layer.
- **Text vs binary:** classify files using a **null-byte heuristic** and a **UTF-8 decode** test (policy: failed decode or null-byte presence → **binary** unless a stricter scanner doc says otherwise — doc must be gatekeeper-reviewed at lock).
- **Every** text file under the repo root, **regardless of extension or path**, receives at minimum the **universal catch-all** scan path (token / surface hits against **V3-A** vocabulary and downstream G3 strategies).
- Files that **also** match specialized parsers (Python AST, JS/TS tree-sitter, HTML tree-sitter, SQL heuristics, structured config walks, Markdown fences, etc.) are scanned **additionally** by those parsers — **not exclusively**.
- **Binary** files appear in reconciliation **(c)** with **`clause: "V3-B binary file"`** and **`reason: "non-text content"`** (or a gatekeeper-approved alias recorded in the closure audit).
- The mission’s “any other text file” requirement becomes a **mandatory code path**, not an aspirational clause.

### V3-C — Symmetric coverage proof (new completion criterion)

For **each** row of `schwab_field_dictionary.csv` (keyed by `canonical_field`), the tooling emits exactly one of:

- **`field_referenced`** — at least one register row (or cited evidence row) references that canonical field; artifact lists **register_id** pointers (or equivalent stable IDs).
- **`field_orphaned`** — zero references; the **closure audit** explains each orphan (unused canonical primitive, scanner blind spot, or product genuinely does not use the field).

**Closure** requires **every** CSV row to be classified, and **`field_orphaned` entries** to be **individually** reviewed and recorded. A non-zero orphan count is **not** a silent failure: each orphan must have an **explicit** audit explanation. Deliverable **13** implements the reverse-coverage report shape.

### V3-D — Dynamic site field-name capture (new G2 sub-clause)

The **normative** set of V3-D dynamic-site `pattern_kind` values is maintained in **`tools/schwab_universal_coverage_scanner_v3/V3_DYNAMIC_PATTERNS.md`** (the **V3-D dynamic-pattern enumeration**). **Register rows whose `pattern_kind` appears in that enumeration** are **V3-D dynamic-site rows** and are subject to the resolution paths below. *(Non-binding illustrations of the risk class: reflection and runtime-built access, e.g. **`DYNAMIC_DISPATCH`**, **`COMPUTED_PROPERTY`**, **`DYNAMIC_SQL_BUILD`**, **`DYNAMIC_EVAL`**, **`REFLECT_API`**. The **binding** list is **only** the committed enumeration file.)*

**V3 closure** requires **exactly one** of:

1. **Static disposition:** **`GOVERNED_EXCEPTION`** (or successor) **with** a **written restriction** on which fields may flow through the site — including an explicit **allow-list** or equivalent contractually bounded description; **or**
2. **Runtime tracing:** instrumented production capture of **resolved** field names **appended** to the register (or linked artifact) per **Deliverable 15** (`SCHWAB_DYNAMIC_SITE_RUNTIME_TRACING_PROTOCOL_V3.md`); **or**
3. **Refactor:** replace dynamic dispatch with **static** field references and **rescan**.

**Authority (enumeration file — parallel attack-surface to G3 synonym YAML and G1.1 vendor YAML):** **`V3_DYNAMIC_PATTERNS.md`** is **normative** for which `pattern_kind` values fall under V3-D. **Changes** to that enumeration require **gatekeeper review on the same bar as contract changes**. **Each** entry **must** include: the **`pattern_kind`** value, a **one-line** description of the **runtime-resolution risk**, and the **contract clause** invoked (**V3-D**). **Removal** or **modification** of an entry **triggers** a **re-disposition pass** on **every** register row that **previously** cited the affected `pattern_kind` under V3-D.

**Not admissible at closure:**

- `UNREVIEWED` on V3-D dynamic-site rows.
- **`GOVERNED_EXCEPTION` without** one of the three resolution paths above (i.e. no bare “we accept dynamic dispatch” without allow-list, trace protocol execution, or refactor).

### V3-E — Inherited from V2, unchanged (unless superseded above)

- **G1.1** — Schwab canonical CSV is not dispositioned as application code; vendored paths registry; lock files / manifests; generated output rules; vendor disposition mechanics.
- **G2** — Cross-validator (**independent** of primary AST/parser path) + per-language-family reflection / registry / decorator sweeps — **trigger vocabulary** must be **V3-A CSV-derived** (not curated lists).
- **G3** — Multi-strategy cross-reference (token, category, likely_use, synonym table, embeddings, top-K candidates).
- **G4** — Adversarial falsification independence.
- **G5** — Per-commit CSV refresh cadence; O-XX downgrade discipline.
- **G6** — CI commit-gate + scheduled job; **gatekeeper-reviewed** `cron` at lock.
- **G7** — CSV provenance hash and provenance doc.
- **H1** — Vendor YAML authority (parallel to G3 / synonyms).
- **H4** — Cron review.
- **H5** — Generator-source link re-verification when generator sources change.

---

## Disposition schema (V2 semantics + V3-D overlay)

Each register row: **exactly one** of `REPLACED`, `GOVERNED_EXCEPTION`, `NO_SCHWAB_EQUIVALENT`, `NOT_MARKET_DATA`, `UNREVIEWED` — **except** V3-D dynamic-site rows **cannot** remain `UNREVIEWED` at closure, and **`GOVERNED_EXCEPTION`** there must satisfy V3-D.

**Scanner:** Never auto-writes `REPLACED`, `GOVERNED_EXCEPTION`, or `NO_SCHWAB_EQUIVALENT`. **`NOT_MARKET_DATA`** only when **explicitly** enumerated in scanner documentation **and** this contract.

**Enumerated mechanical `NOT_MARKET_DATA` subtypes:** inherit V2 (`NOT_MARKET_DATA — third_party`, `NOT_MARKET_DATA — dependency_manifest`) with the same **G1.1** proof burden; additional mechanical subtypes require **contract amendment** + gatekeeper approval.

**Tooling / process `pattern_kind` values** (non-exhaustive; inherit V2 enumerations; **V3-D subset** is **only** per **`V3_DYNAMIC_PATTERNS.md`**): must end in **non-`UNREVIEWED`** disposition before closure, **subject to V3-D** where applicable.

---

## Deliverables

| # | Deliverable |
|---|-------------|
| 1 | `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md` (this contract) |
| 2 | `tools/schwab_universal_coverage_scanner_v3/` — scanner package (**replaces** `schwab_universal_coverage_scanner_v2/` for V3 closure), **including** **`V3_DYNAMIC_PATTERNS.md`** — normative V3-D `pattern_kind` enumeration (**V3-D** authority; gatekeeper-reviewed edits only) |
| 3 | Tests — **minimum one per pattern kind per language family** (shared kinds documented); gatekeeper rejects under-counting |
| 4 | `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V3.csv` — **CSV- and language-universal** |
| 5 | `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V3.md` — index to CSV + column dictionary |
| 6 | `tools/check_schwab_csv_first.py` **`--all-files`** — enforcement per this contract (whole repo, **no extension carve-out**) |
| 7 | CI workflow — **commit gate** and **scheduled** job (G6) |
| 8 | CSV re-pull tool + **diff-on-commit** gate (G5) |
| 9 | `governance/schwab_field_synonyms.yaml` — **seed** + maintenance process (G3) |
| 10 | Adversarial falsification tool / **second-pass protocol** (G4) |
| 11 | `governance/SCHWAB_FIELD_DICTIONARY_PROVENANCE_V1.md` (G7) — amended if needed for V3 artifacts |
| 12 | `governance/schwab_vendor_paths.yaml` — vendor path registry (G1.1 authority) |
| 13 | **Reverse coverage report** tooling (V3-C) — per-`canonical_field`: `field_referenced` **or** `field_orphaned`, with register ID pointers or audit fields |
| 14 | **Static analysis test** (V3-A) — **zero** hand-curated market-token list modules / patterns as defined in scanner doc |
| 15 | `governance/SCHWAB_DYNAMIC_SITE_RUNTIME_TRACING_PROTOCOL_V3.md` — runtime tracing protocol for V3-D (protocol required at contract lock even if instrumentation ships later) |
| 16 | `governance/SCHWAB_COVERAGE_PROOF_CLOSURE_AUDIT_V3.md` — closure evidence (version matches V3 program) |

**Note:** **V2** register, **V2** closure audit, and **`schwab_universal_coverage_scanner_v2`** are **not** V3 closure evidence.

---

## Completion criteria — ALL must hold (twelve)

1. **Universal reconciliation:** Every file **classified**: text **scanned** (minimum catch-all), **excluded** with **clause** (binary / V3-B, `.git` hygiene, `.claude` dedup, G1.1 generated-with-source, etc.), and **(a) = (b) + (c)** per reconciliation families **without unexplained gap**.
2. **Visitor stability (V2 G2):** Three consecutive runs — **zero** new `pattern_kind` values **and** **zero** cross-validator misses **and** per-language-family reflection / registry / decorator sweeps **complete** and dispositioned.
3. **Register completeness:** Every register row dispositioned — **no** `UNREVIEWED`.
4. **V3-A:** Scanner contains **zero** forbidden hand-curated market-token lists; static-analysis test (**Deliverable 14**) passes.
5. **V3-B:** Extension whitelist **absent**; **every** text file hits at least the catch-all path; binary exclusions **cited** as **V3-B**.
6. **V3-C:** Every CSV `canonical_field` row classified **`field_referenced`** or **`field_orphaned`**; orphans **explained** in **Deliverable 16**.
7. **V3-D:** Every row whose `pattern_kind` is listed in **`V3_DYNAMIC_PATTERNS.md`** has **one** of: static allow-list **in** disposition text, runtime trace evidence per **Deliverable 15**, or refactor + rescan — **no** bare `GOVERNED_EXCEPTION`, **no** `UNREVIEWED`.
8. **CI commit-gate** green; CSV refresh per **G5** cadence.
9. **Scheduled** CI on `main` **post-disposition**: at least one full pass with **zero** new undocumented rows; workflow **`cron`** **gatekeeper-reviewed** at lock (G6).
10. **Adversarial falsification (G4)** complete with **zero** hits; independence documented in closure audit.
11. **CSV provenance** hash matches committed canonical CSV (G7).
12. **Closure audit** (**Deliverable 16**) committed; **O-XX** in `governance/OPERATOR_DECISION_REGISTER.md`.

---

## Forbidden — V2 list plus V3 additions

**V2 forbiddens remain in force** where not superseded by V3 (no premature closure language; no silent vendor exclusion without G1.1 citation; synonym/vendor YAML authority; G4 actor independence; G6 cron review; etc.).

**V3 additions — MUST NOT:**

- Hand-curated market-token lists in scanner source (**V3-A**)
- Extension whitelists or **skip-by-extension** path logic (**V3-B**)
- **Closure** with **`field_orphaned`** rows lacking **per-field** explanation in the closure audit (**V3-C**)
- **`GOVERNED_EXCEPTION`** on V3-D dynamic-site rows **without** allow-list / runtime trace / refactor (**V3-D**)
- **Unreviewed edits** to **`V3_DYNAMIC_PATTERNS.md`** (violates **V3-D** enumeration authority — parallel to G3 synonym YAML and G1.1 vendor YAML)
- Treating **V2** register, **V2** closure audit, or **`schwab_universal_coverage_scanner_v2`** artifacts as **V3** closure evidence
- **Inflating `(b)_files_scanned`** via silent treatment of **parse errors**, **`OSError`**, or **misclassified** binary/text without reconciliation **(c)** or **failure** semantics documented in scanner doc and closure audit

---

## Sequencing — strictly sequential (no skipping)

1. Cursor drafts **V3** contract → operator + gatekeeper **approve** (lock).  
2. Cursor builds **`schwab_universal_coverage_scanner_v3/`** (carry forward tree-sitter, embeddings, reconciliation; implement **V3-A** vocabulary; remove **V3-B** whitelist; add **V3-C** reverse tooling).  
3. Tests — Deliverable **3** bar **plus** Deliverable **14** (V3-A static analysis) **plus** Deliverable **13** / **V3-C** tests **plus** binary exclusion / reconciliation cases.  
4. Run scanner on **full repo**; populate **V3** register.  
5. **Human** disposition pass (**V3-D** compliance).  
6. Cross-validator + per-language-family sweeps → **stability**.  
7. CSV re-pull + provenance (**G5**, **G7**).  
8. Adversarial pass (**G4**).  
9. **`--all-files`** whole-repo guard.  
10. CI commit-gate + scheduled **cron**.  
11. **Deliverable 16** + **O-XX**.

---

## Status until V3 closure

```text
PROGRAM: COVERAGE PROOF v3 — IN PROGRESS
COVERAGE PROOF: OPEN — CSV-canonical, every file, every canonical_field
SYSTEM: FAIL
```

These lines do **not** change until **completion criteria 1–12** all hold **simultaneously**.

---

## Relation to other artifacts

- `SCHWAB_TRADE_DECISION_ENDPOINTS_V1.yaml` and decision-dependency tooling are **lineage aids only**; they do **not** satisfy this program.  
- `ENGINEERING_GATEKEEPING_POLICY.md` § Active Status must stay consistent with **OPEN** universal coverage proof until **V3** closes.  
- `SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V1.md` and **`_V2.md`** are **historical** after supersession; **V3** is the **sole** active contract for new closure work.

---

## Lock record

| Event | Detail |
|-------|--------|
| **Lock** | V3 contract text frozen for build under **Sequencing** step 2 |
| **Gatekeeper** | Final verification: cumulative (V3-E / V2 inheritance), global (V3-B), universal (V3-A + V3-C); T1–C3; no third-pass holes |
| **Acknowledged limits** | CSV completeness (committed dictionary only), V3-D alternatives to runtime tracing, human disposition limits beyond G4 — out of scope for V3 enforcement |

Amendments after lock follow **Revision** below (version bump or O-XX).

---

## Revision

V3 amendments require operator + gatekeeper acknowledgment and version bump (**V4**) or **O-XX** addendum recorded in `governance/OPERATOR_DECISION_REGISTER.md`.
