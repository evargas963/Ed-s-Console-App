# Schwab Universal Coverage Proof Program V2

**Status:** DRAFT CONTRACT — operator + gatekeeper review required before scanner suite code  
**Artifact:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V2.md`  
**Created:** 2026-05-09  
**Supersedes:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V1.md` (**SUPERSEDED_BY_V2**)  
**Authority:** Operator V2 directive — **no language carve-outs, no Phase 2 deferrals** for G1–G7

---

## Mission (verbatim, unchanged)

> Global, universal, complete, 100% through the entire, whole, entirety, no stone left unturned repo, any and all living files, every line, every sentence needs to be consistent.

**Operationalized:** Build a **language-universal** register where **every relevant line** in **every in-scope file** that touches a **market-data field, derivation, computation, default, fallback, or substitution** is **cross-referenced against the Schwab canonical field dictionary** (and supporting synonym / embedding / reverse maps defined herein) and **explicitly dispositioned**. **Empty `UNREVIEWED` across the entire register**, together with **all completion criteria below**, is the only admissible closure claim.

---

## Gap closures (G1–G7) — all mandatory in V2

### G1 — Language-universal scope

**In scope:** Every file matching, at minimum, these extensions anywhere in the repository tree:

- `.py`
- `.html`, `.js`, `.ts`, `.jsx`, `.tsx`
- `.css` (where field names appear in selectors or content)
- `.sql`
- `.yaml`, `.yml`
- `.json`
- `.md`
- `.toml`, `.ini`
- `.txt` and other **config / text** files that can name market-data fields
- **Any other text file** that can name a market-data field (explicit catch-all; no “Phase 2” expansion)

**Per-language scanner modules** (minimum):

| Language / family | Module requirement |
|-------------------|-------------------|
| Python | AST visitor (V1 design carried forward; expanded per stability rules) |
| HTML / JS / TS / JSX / TSX | Tree-sitter **or comparable** parse; scan `data-*` attributes, JS string literals, template bindings, fetch/XHR field references |
| SQL | Parse `SELECT` / `WHERE` / `ORDER BY` (and related clauses) for field tokens; scan **inline SQL** inside Python/JS strings (cross-language embedding) |
| YAML / JSON / TOML / INI | Walk **all** string values and keys |
| Markdown | Scan **code fences** and **inline code** spans |
| Catch-all | Regex (or equivalent) pass on remaining text files (e.g. `.txt`, extensionless text) for Schwab-token / market-token strings |

**No language carve-outs.** There is **no** “Python only,” “no tests,” “no tools,” and **no** “Phase 2” for broader languages.

**`.claude/worktrees/*`:** Duplicate of main-repo content by construction. **Scan once** per logical path; **deduplicate** in post-processing so each **unique** source line is examined once.

---

### G2 — Visitor stability (strengthened)

**Baseline (from V1):** The primary visitor set is **stable** only after **three consecutive** full-repo disposition cycles surface **zero new `pattern_kind`** values requiring new visitor logic.

**Additions (mandatory):**

1. **Cross-validator:** An **independent** regex (or non-AST) scanner runs on the **same** files. Any **token-bearing line** that **does not** map to an AST (or primary-parser) register row produces a **`pattern_kind_miss`** finding. **Stability cannot be claimed** until **`pattern_kind_miss` count is zero** after full reconciliation (expand visitors or document each miss with a **non-UNREVIEWED** disposition and tool version bump — **no silent drops**).

2. **Decorator / dynamic-dispatch sweep:** The scanner **enumerates** all **decorators** and all sites using **`getattr` / `setattr` / `__getattr__`** (and equivalent reflection). Each site emits a **`DYNAMIC_DISPATCH`** register row requiring **human disposition**.

3. **Registry / factory sweep:** Any **string-keyed** dispatch structure (`HANDLERS = {...}`, `REGISTRY[key]`, factories keyed by string) that can route market-data handling emits a register row (**`REGISTRY_DISPATCH`** or unified under `DYNAMIC_DISPATCH` — **one enum** must be fixed in the scanner spec; default: separate kinds for audit clarity).

**Closure:** Stability requires **three-run rule** **AND** **zero cross-validator misses** **AND** **completed** decorator/dynamic-dispatch and registry sweeps (all such rows dispositioned).

---

### G3 — CSV cross-reference (multi-strategy)

Beyond token / `category` / `likely-use` matching, **all** of the following are **required**:

1. **Embedding similarity:** Code identifiers (and short contexts) vs `canonical_field` and/or CSV **description** text; emit **top-K** `csv_candidates` (K fixed in scanner doc; minimum 3).

2. **Manual synonym table:** `governance/schwab_field_synonyms.yaml` maps common code names to canonical fields (e.g. `iv` → volatility family, `oi` → `openInterest`). **Maintained alongside** the register; scanner **must** consult it for candidate generation.

3. **Reverse lookup:** For **each** CSV `canonical_field` row, the tooling reports **which** register rows cite it. **Orphan canonical fields** (zero citing sites) are an **audit signal** recorded in the closure audit (explain: unused primitive vs scanner gap).

`csv_candidates` remain **informational**; **human** disposition required except where the contract explicitly allows mechanical `NOT_MARKET_DATA` (default: **none** unless enumerated in scanner + contract addendum).

---

### G4 — Adversarial falsification pass

After initial human disposition, a **second pass** (separate tool run or disposer) **re-examines every** `NO_SCHWAB_EQUIVALENT` row and **attempts** to find a CSV match (including synonyms, embeddings, reverse index).

- Any flip **`NO_SCHWAB_EQUIVALENT` → `REPLACED`** is a **falsification hit** (logged with before/after evidence).
- **Closure requires zero falsification hits** in the **final** adversarial pass run recorded in the closure audit.

---

### G5 — CSV baseline auto-refresh

The contract requires the Schwab canonical CSV baseline to stay current:

- **Stated cadence:** **Every commit** via CI **recommended**: re-pull or verify freshness; **fail-closed** if Schwab API (or authoritative refresh path) is **unavailable** and no approved stale baseline exception is recorded in `OPERATOR_DECISION_REGISTER.md`.
- **Minimum:** **Weekly** refresh if per-commit is not technically feasible — **operator documents** the chosen mode in the **provenance** doc; gatekeeper rejects “weaker than weekly” without O-XX.

**Diff gate:** Any **new** `canonical_field` in the refreshed CSV vs committed baseline **forces** a **full-register re-scan** before the commit can land (CI blocks).

---

### G6 — Scheduled re-audit cadence

In addition to per-commit CI:

- A **scheduled** CI job runs **at least weekly** on `main`, executing the full **`--all-files`** (language-universal) scan regardless of commit activity.
- Outputs append under `governance/SCHWAB_COVERAGE_AUDIT_LOG/` (path + naming convention fixed in workflow).
- **Any new register row** surfaced only on scheduled run is **P0** until dispositioned and root-caused.

**Completion criterion:** Scheduled job has run **at least one** full pass on `main` **post-disposition** with **zero** new undocumented rows (see completion criteria).

---

### G7 — CSV provenance audit

**New deliverable:** `governance/SCHWAB_FIELD_DICTIONARY_PROVENANCE_V1.md` documenting:

- How the **2,393-row** (or current) baseline was assembled  
- Source endpoints / inputs scraped or ingested  
- Date(s) of capture  
- Tooling used  
- Any pages / rows **skipped** and why  
- **Cryptographic hash** (e.g. SHA-256) of the committed CSV at baseline  

**Closure:** Hash in provenance doc **matches** the committed `schwab_field_inventory/schwab_field_dictionary.csv` (or the governed canonical path) **at closure time**.

---

## Deliverables (V2)

| # | Deliverable |
|---|-------------|
| 1 | `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V2.md` (this contract) |
| 2 | Multi-language scanner suite: `tools/schwab_universal_coverage_scanner_v2/` (**package**) |
| 3 | Tests — **minimum one per pattern kind per language** (or per language family where kinds are shared — **documented**; gatekeeper rejects under-counting) |
| 4 | `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V2.csv` — language-universal |
| 5 | `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V2.md` — index to CSV + column dictionary |
| 6 | `tools/check_schwab_csv_first.py` **`--all-files`** — **language-universal** enforcement per this contract |
| 7 | CI workflow — **commit gate** and **scheduled** job (G6) |
| 8 | CSV re-pull tool + **diff-on-commit** gate (G5) |
| 9 | `governance/schwab_field_synonyms.yaml` — **seed** + maintenance process |
| 10 | Adversarial falsification tool / **second-pass protocol** (G4) |
| 11 | `governance/SCHWAB_FIELD_DICTIONARY_PROVENANCE_V1.md` (G7) |
| 12 | `governance/SCHWAB_COVERAGE_PROOF_CLOSURE_AUDIT_V1.md` (or `_V2` if versioned) — closure evidence |

---

## Disposition schema (unchanged semantics)

Each row: **exactly one** of `REPLACED`, `GOVERNED_EXCEPTION`, `NO_SCHWAB_EQUIVALENT`, `NOT_MARKET_DATA`, `UNREVIEWED`.

**Scanner:** **Never** auto-writes `REPLACED`, `GOVERNED_EXCEPTION`, or `NO_SCHWAB_EQUIVALENT`. **`NOT_MARKET_DATA`** only if **explicitly** enumerated in scanner documentation **and** this contract (default: **no** mechanical dispositions).

Additional row kinds for **tooling / process** (e.g. `pattern_kind_miss`, `DYNAMIC_DISPATCH`) must still end in a **non-UNREVIEWED** disposition before closure.

---

## Completion criteria — ALL must hold (nine)

1. Every in-scope file scanned across **all** listed languages; **per-language file counts** recorded and auditable.  
2. Visitor stability: **three consecutive** runs with **zero new pattern kinds** **AND** **zero cross-validator misses** **AND** decorator/dynamic-dispatch **and** registry sweeps **complete** and dispositioned.  
3. Every register row has disposition **other than** `UNREVIEWED`.  
4. `check_schwab_csv_first.py --all-files` passes **whole-repo** (language-universal).  
5. **CI commit-gate** green on representative merge to `main`.  
6. **Scheduled** CI job has run **at least one** full pass on `main` **post-disposition** with **zero** new undocumented rows.  
7. **Adversarial falsification** pass complete with **zero** hits.  
8. **CSV provenance** hash matches committed canonical CSV.  
9. **Closure audit** committed; **O-XX** recorded in `governance/OPERATOR_DECISION_REGISTER.md`.

---

## Sequencing — strictly sequential (no skipping)

1. Cursor drafts **V2** → operator + gatekeeper **approve**.  
2. Cursor builds **multi-language scanner** + tests.  
3. Run scanner; populate **V2** register (`UNREVIEWED`).  
4. **Human** disposition pass.  
5. Cross-validator + dynamic-dispatch + registry sweep → expand until **stability** (G2).  
6. **CSV re-pull** tooling + **provenance** doc (G5, G7).  
7. **Adversarial falsification** pass (G4).  
8. **`--all-files`** whole-repo guard (language-universal).  
9. **CI** commit-gate + **scheduled** job (G6).  
10. **Closure audit** + **O-XX**.

---

## Forbidden (V1 list plus V2 additions)

**V1 forbiddens remain in force** (no curated scope lists, no auto proof buckets, no premature closure language).

**V2 additions — MUST NOT:**

- **Language carve-outs** of any kind  
- **Phase 2** deferrals for **any** of G1–G7  
- **“Future work”** framing for G1–G7 requirements  
- **Closure** without **all nine** completion criteria  
- Claiming stability with **non-zero** `pattern_kind_miss`  
- Skipping **adversarial** pass or **provenance** hash check  

---

## Status until V2 closure

```text
PROGRAM: COVERAGE PROOF v2 — IN PROGRESS
COVERAGE PROOF: OPEN — language-universal, every row UNREVIEWED until disposition complete
SYSTEM: FAIL
```

These lines do **not** change until **completion criteria 1–9** all hold **simultaneously**.

---

## Relation to other artifacts

- `SCHWAB_TRADE_DECISION_ENDPOINTS_V1.yaml` and decision-dependency tooling are **lineage aids only**; they **do not** satisfy this program.  
- `ENGINEERING_GATEKEEPING_POLICY.md` § Active Status must stay consistent with **OPEN** universal coverage proof until V2 closes.

---

## Revision

V2 amendments require operator + gatekeeper acknowledgment and version bump (`V3`) or O-XX addendum.
