> **SUPERSEDED:** This artifact is **superseded** by `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md` (**SUPERSEDED_BY_V3**); V3 is **superseded** by `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` (**SUPERSEDED_BY_V4**). **Do not** use V2 for scope, closure, or gatekeeping. Retained for history only. **Active program (LOCKED 2026-05-08):** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md`.

# Schwab Universal Coverage Proof Program V2

**Status:** SUPERSEDED_BY_V3 (**chain continues:** **SUPERSEDED_BY_V4**)  
**Artifact:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V2.md`  
**Created:** 2026-05-09  
**Supersedes:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V1.md` (**SUPERSEDED_BY_V2**)  
**Superseded:** 2026-05-09 → **V3** → **V4** (`SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md`)  
**Authority:** Operator V2 directive — **historical** (no language carve-outs, no Phase 2 deferrals for G1–G7)

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

### G1.1 — Generated, third-party, and source-of-truth artifacts

**Schwab canonical CSV (source-of-truth):** The committed canonical dictionary (e.g. `schwab_field_inventory/schwab_field_dictionary.csv`) is the **authority** for field names — **not** an in-scope “derivation” target to be dispositioned like application code. The scanner **does not** treat the CSV’s own rows as code sites requiring `REPLACED` / `NO_SCHWAB_EQUIVALENT` in the application register. **Rationale:** self-scan would be nonsensical; provenance and hash are governed under **G7** instead.

**Vendored third-party code** (e.g. `node_modules/`, `vendor/`, or other vendored trees): **In scope for token presence** — a Schwab field referenced in vendored code **matters** for completeness. **Vendor-path declarations** live in **`governance/schwab_vendor_paths.yaml`**. The scanner treats a path as vendored **only** if it matches an entry in that file.

**Authority (parallel to G3 / synonym table):** Changes to `governance/schwab_vendor_paths.yaml` require **gatekeeper review** on the same bar as **contract** changes. **Each** entry **must** include: the **glob or prefix path**, a **one-line provenance citation** (origin URL, package name + version, or vendoring commit SHA), and the **contract clause** invoked (e.g. `G1.1`). **Removal or modification** of an entry **triggers** a **re-disposition pass** on **every** register row that **previously cited** that path under **`NOT_MARKET_DATA — third_party`** (tooling must support query by vendor path key).

Disposition: **`NOT_MARKET_DATA — third_party`** only when the match is **genuinely unrelated** to this product’s market-data obligations **and** the path is **listed** in `schwab_vendor_paths.yaml` (enumerated mechanical path per § Disposition schema); otherwise **`GOVERNED_EXCEPTION`** with **O-XX** (vendor patch policy, fork, or replacement).

**Auto-generated / minified output** (bundles, transpiled JS): **Out of scope** **only when** the **human-authored generating source** is **in repo**, **in scope**, and **scanned**; the closure audit **links** generator output to covered sources. If source is missing or not scanned, generated output is **in scope**. **Any commit** that **touches** an in-scope generator **source** file **forces** **re-verification** of the **link** between that source and its generated artifact(s) in the next closure-relevant audit step (or CI check) before stability is re-claimed.

**Lock files / dependency manifests** (`package-lock.json`, `requirements.txt`, etc.): **In scope** for **token / string scan** as required by G1. Expected disposition is typically **`NOT_MARKET_DATA — dependency_manifest`** when that subtype is **enumerated** in the scanner + this contract (mechanical); otherwise **human-dispositioned**.

---

### G2 — Visitor stability (strengthened)

**Baseline (from V1):** The primary visitor set is **stable** only after **three consecutive** full-repo disposition cycles surface **zero new `pattern_kind`** values requiring new visitor logic.

**Additions (mandatory):**

1. **Cross-validator:** An **independent** regex (or non-AST) scanner runs on the **same** files. Any **token-bearing line** that **does not** map to an AST (or primary-parser) register row produces a **`pattern_kind_miss`** finding. **Stability cannot be claimed** until **`pattern_kind_miss` count is zero** after full reconciliation (expand visitors or document each miss with a **non-UNREVIEWED** disposition and tool version bump — **no silent drops**).

2. **Decorator / dynamic-dispatch sweep (per language family):** The scanner **enumerates** decorators and dynamic dispatch **in each language family** covered by G1.

   - **Python:** `getattr` / `setattr` / `__getattr__` (and equivalent reflection). Each site emits **`DYNAMIC_DISPATCH`** unless a more specific `pattern_kind` below applies.

   - **JavaScript / TypeScript / JSX / TSX:** The following each emit register rows with the given **`pattern_kind`** (all require **human disposition** unless later enumerated otherwise): computed member access **`obj[expr]`** where the property is not a compile-time literal → **`COMPUTED_PROPERTY`**; **`Proxy`** constructions / handler traps relevant to property access → **`PROXY_TRAP`**; **`Reflect.get` / `Reflect.set` / `Reflect.has` / `Reflect.ownKeys`** → **`REFLECT_API`**; **`eval(...)`** / **`new Function(...)`** → **`DYNAMIC_EVAL`**; **`Object.defineProperty`** (or `defineProperties`) with **computed** keys → **`COMPUTED_DEFINE_PROPERTY`**; **`import(expr)`** (dynamic import) → **`DYNAMIC_IMPORT`**.

   - **SQL:** Dynamic SQL built via concatenation or formatting such that Schwab / market tokens may appear in runtime-built strings → **`DYNAMIC_SQL_BUILD`**.

3. **Registry / factory sweep (per language family):** Any **string-keyed** dispatch structure (`HANDLERS = {...}`, `REGISTRY[key]`, object literals used as registries, factories keyed by string) that can route market-data handling emits **`REGISTRY_DISPATCH`** (distinct from **`DYNAMIC_DISPATCH`** for audit clarity). Applies to Python **and** JS/TS **and** any other in-scope language with equivalent patterns.

**Closure:** Stability requires **three-run rule** **AND** **zero cross-validator misses** **AND** **completed** sweeps for **every language family**: Python decorators + `DYNAMIC_DISPATCH` / `REGISTRY_DISPATCH`; **all** JS/TS reflection kinds listed above **where applicable**; **`DYNAMIC_SQL_BUILD`** where applicable; **all** such rows dispositioned. **Stability must not be claimed** until **per-language-family reflection sweep** completion is evidenced in the closure audit.

---

### G3 — CSV cross-reference (multi-strategy)

Beyond token / `category` / `likely-use` matching, **all** of the following are **required**:

1. **Embedding similarity:** Code identifiers (and short contexts) vs `canonical_field` and/or CSV **description** text; emit **top-K** `csv_candidates` (K fixed in scanner doc; minimum 3).

2. **Manual synonym table:** `governance/schwab_field_synonyms.yaml` maps common code names to canonical fields (e.g. `iv` → volatility family, `oi` → `openInterest`). **Maintained alongside** the register; scanner **must** consult it for candidate generation.

   **Authority (attack-surface control):** Changes to `governance/schwab_field_synonyms.yaml` require **gatekeeper review** on the same bar as **contract** changes (no silent edits). **Each** synonym row **must** carry an **inline citation** to the target **`canonical_field`** CSV row (or explicit “multi-row family” rationale approved in review) and a **one-line rationale** for the mapping. **Removal or modification** of a synonym row **triggers** a **re-disposition pass** on **every** register row that **previously cited** that synonym (tooling must support query by synonym key).

3. **Reverse lookup:** For **each** CSV `canonical_field` row, the tooling reports **which** register rows cite it. **Orphan canonical fields** (zero citing sites) are an **audit signal** recorded in the closure audit (explain: unused primitive vs scanner gap).

`csv_candidates` remain **informational**; **human** disposition required except where the contract explicitly allows mechanical `NOT_MARKET_DATA` (see § Disposition schema — enumerated subtypes only).

---

### G4 — Adversarial falsification pass

After initial human disposition, a **second pass** **re-examines every** `NO_SCHWAB_EQUIVALENT` row and **attempts** to find a CSV match (including synonyms, embeddings, reverse index).

**Independence (mandatory):** The second pass **must** be conducted by **either**:

- **(A)** An **actor distinct from the first-pass disposer** (among Cursor, operator, gatekeeper — whoever performed the **first-pass** disposition for a given row **must not** perform the **second-pass** falsification review for that row), **or**
- **(B)** A **tool path** that employs **at least one match strategy** that was **not** used in the first pass for that row (e.g. first pass: embeddings + synonym table; second pass: full reverse-lookup index walk + manual canonical-field list scan).

**Same-actor-and-same-strategy** second passes are **not** admissible as falsification evidence.

The **`SCHWAB_COVERAGE_PROOF_CLOSURE_AUDIT_V2.md`** **records**, for **each** pass: **actor(s)**, **tool version(s)**, and **strategies** applied.

- Any flip **`NO_SCHWAB_EQUIVALENT` → `REPLACED`** is a **falsification hit** (logged with before/after evidence).
- **Closure requires zero falsification hits** in the **final** adversarial pass run recorded in the closure audit.

---

### G5 — CSV baseline auto-refresh

The contract requires the Schwab canonical CSV baseline to stay current:

- **Per-commit refresh is REQUIRED by default** on the CI path: re-pull or verify freshness against the authoritative source; **fail-closed** if the Schwab API (or other **approved** authoritative refresh path) is **unavailable**, unless a **stale-baseline exception** is explicitly recorded in `governance/OPERATOR_DECISION_REGISTER.md` for that commit window.
- **Weekly cadence** (or any cadence **weaker** than per-commit) is allowed **only** with an **explicit O-XX downgrade** in `governance/OPERATOR_DECISION_REGISTER.md` citing **technical infeasibility** of per-commit refresh. The **provenance** doc **states** the active cadence and the governing **O-XX**.

**Diff gate:** Any **new** `canonical_field` in the refreshed CSV vs committed baseline **forces** a **full-register re-scan** before the commit can land (CI blocks).

---

### G6 — Scheduled re-audit cadence

In addition to per-commit CI:

- A **scheduled** CI job runs **at least weekly** on `main`, executing the full **`--all-files`** (language-universal) scan regardless of commit activity.
- The workflow file **commits an explicit `cron` schedule** (e.g. `0 12 * * 1` for weekly); **gatekeeper reviews** that the committed schedule **fires at least weekly** at **V2 lock** and on any subsequent workflow edit that changes the schedule.
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
| 9 | `governance/schwab_field_synonyms.yaml` — **seed** + maintenance process (G3) |
| 13 | `governance/schwab_vendor_paths.yaml` — vendor path registry (G1.1 authority) |
| 10 | Adversarial falsification tool / **second-pass protocol** (G4) |
| 11 | `governance/SCHWAB_FIELD_DICTIONARY_PROVENANCE_V1.md` (G7) |
| 12 | `governance/SCHWAB_COVERAGE_PROOF_CLOSURE_AUDIT_V2.md` — closure evidence (version matches V2 program) |

---

## Disposition schema (unchanged semantics)

Each row: **exactly one** of `REPLACED`, `GOVERNED_EXCEPTION`, `NO_SCHWAB_EQUIVALENT`, `NOT_MARKET_DATA`, `UNREVIEWED`.

**Scanner:** **Never** auto-writes `REPLACED`, `GOVERNED_EXCEPTION`, or `NO_SCHWAB_EQUIVALENT`. **`NOT_MARKET_DATA`** only if **explicitly** enumerated in scanner documentation **and** this contract.

**Enumerated mechanical `NOT_MARKET_DATA` subtypes (V2):** `NOT_MARKET_DATA — third_party`, `NOT_MARKET_DATA — dependency_manifest` — **only** when the scanner proves the site class matches **G1.1**; all other `NOT_MARKET_DATA` rows require **human** disposition with semantic reason. Additional mechanical subtypes require a **contract amendment** + gatekeeper approval.

Additional row kinds for **tooling / process** (e.g. `pattern_kind_miss`, `DYNAMIC_DISPATCH`, `COMPUTED_PROPERTY`, `PROXY_TRAP`, `REFLECT_API`, `DYNAMIC_EVAL`, `COMPUTED_DEFINE_PROPERTY`, `DYNAMIC_IMPORT`, `DYNAMIC_SQL_BUILD`, `REGISTRY_DISPATCH`) must still end in a **non-UNREVIEWED** disposition before closure.

---

## Completion criteria — ALL must hold (nine)

1. Every in-scope file scanned across **all** listed languages; coverage is **falsifiable**: for each extension / language family, the closure audit records **(a)** total files of that type **present in the repo**, **(b)** count **scanned**, **(c)** count **excluded** with **reason** and **contract clause citation** (e.g. G1.1 generated-source exemption, `.claude` dedup), and **(d)** **reconciliation** proving **(a) = (b) + (c)** with **zero unexplained gap**.  
2. Visitor stability: **three consecutive** runs with **zero new pattern kinds** **AND** **zero cross-validator misses** **AND** **per-language-family** reflection / registry / decorator sweeps (**G2**, including JS/TS/SQL kinds) **complete** and dispositioned.  
3. Every register row has disposition **other than** `UNREVIEWED`.  
4. `check_schwab_csv_first.py --all-files` passes **whole-repo** (language-universal).  
5. **CI commit-gate** green on representative merge to `main`.  
6. **Scheduled** CI job has run **at least one** full pass on `main` **post-disposition** with **zero** new undocumented rows; the workflow file’s explicit **`cron`** has been **gatekeeper-reviewed** at lock (G6).  
7. **Adversarial falsification** pass complete with **zero** hits, satisfying **G4 independence** (distinct actor **or** distinct strategy); closure audit records actors and strategies.  
8. **CSV provenance** hash matches committed canonical CSV.  
9. **Closure audit** (`SCHWAB_COVERAGE_PROOF_CLOSURE_AUDIT_V2.md`) committed; **O-XX** recorded in `governance/OPERATOR_DECISION_REGISTER.md`.

---

## Sequencing — strictly sequential (no skipping)

1. Cursor drafts **V2** → operator + gatekeeper **approve**. *(Draft initial 2026-05-09; T1–T4 + polish 2026-05-09; H1–H3 + H4–H5 polish 2026-05-09 — awaiting final lock.)*  
2. Cursor builds **multi-language scanner** + tests.  
3. Run scanner; populate **V2** register (`UNREVIEWED`).  
4. **Human** disposition pass.  
5. Cross-validator + **per-language-family** reflection / registry / decorator sweeps → expand until **stability** (G2).  
6. **CSV re-pull** tooling + **provenance** doc (G5, G7).  
7. **Adversarial falsification** pass (G4).  
8. **`--all-files`** whole-repo guard (language-universal).  
9. **CI** commit-gate + **scheduled** job (G6).  
10. **`SCHWAB_COVERAGE_PROOF_CLOSURE_AUDIT_V2.md`** + **O-XX**.

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
- **CSV refresh cadence weaker than per-commit** without **O-XX** downgrade (G5)  
- **Silent exclusion** of vendored / generated / lock-file paths without **G1.1** citation in the reconciliation (criterion 1)  
- **Unreviewed edits** to `schwab_field_synonyms.yaml` (violates G3 authority)  
- **Unreviewed edits** to `schwab_vendor_paths.yaml` (violates G1.1 authority)  
- **Stability claimed** without **per-language-family reflection sweep** completion (G2)  
- **Adversarial second pass** performed by the **same actor** with the **same strategies** as the first pass (violates G4)  
- **Scheduled audit workflow** without a **committed, gatekeeper-reviewed** `cron` meeting the weekly minimum (G6)

---

## Status (historical — V2 superseded)

V2 closure criteria are **not** pursued under the active program. The operator **V3** contract governs new work.

```text
PROGRAM: COVERAGE PROOF v2 — SUPERSEDED_BY_V3 → SUPERSEDED_BY_V4
COVERAGE PROOF: CLOSED AS A TARGET — see V4 (active)
SYSTEM: N/A (historical artifact)
```

---

## Relation to other artifacts

- `SCHWAB_TRADE_DECISION_ENDPOINTS_V1.yaml` and decision-dependency tooling are **lineage aids only**; they **do not** satisfy this program.  
- `ENGINEERING_GATEKEEPING_POLICY.md` § Active Status tracks the **active** universal coverage program, which is now **V4** (`SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md`, LOCKED 2026-05-08). V2 and V3 are historical.

---

## Revision

V2 amendments are **frozen** under supersession. The active successor is **V4** (`SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md`, LOCKED 2026-05-08); **V3** (`SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md`) is itself superseded. Further changes use **V4** revision rules or **O-XX** against **V4**.
