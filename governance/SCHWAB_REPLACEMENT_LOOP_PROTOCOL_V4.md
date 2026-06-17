> **Classification:** Policy Specification | **Scope:** Governance documentation `SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md`.

# Schwab replacement loop protocol (V4-B) — Deliverable 19

**Authority:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` § V4-B — **mandatory** between human disposition (sequencing step 4) and stability sweeps (step 6).

---

## Triage — identifying bare `GOVERNED_EXCEPTION` work

1. Run **`python -m tools.schwab_coverage_v4_metrics --register governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv`** and inspect **`bare_governed_exception_count`** and **`v4_a_violations`**.
2. A row is **bare** when **`disposition`** is **`GOVERNED_EXCEPTION`** without the mandated shape **`GOVERNED_EXCEPTION (O-NN)`**, or **`governed_ref`** does not cite **`O-NN`**, or the cited **`O-NN`** lacks a valid **`### O-NN`** narrative in `governance/OPERATOR_DECISION_REGISTER.md` with **`Why:`**, **`Constraint:`**, and **`Permanent or interim:`** (see Deliverable **18**).
3. For each bare row where the **Schwab CSV clearly supplies an equivalent** and **no** documented operator constraint blocks substitution, the **default** action is **refactor to canonical Schwab reference** (not a new **`O-XX`**).

---

## Edit — code-change discipline

- Work in **small slices** (one logical module or concern per pass).
- Run **unit tests** and **scanner tests** (`pytest`) before marking the slice done.
- **Commit messages** should reference affected **`register_id`** values when rows are re-dispositioned or eliminated by refactor.

---

## Rescan

```bash
python -m tools.schwab_universal_coverage_scanner_v3 --output governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv
```

(Use **`--root`** if scanning a non-default tree; default output path is the **V4** register per program Deliverable 4.)

Re-import or merge mechanical scanner output with **human disposition** columns as required by the register schema.

---

## Re-disposition

- Rows whose sites **disappear** after refactor: **drop** or mark **superseded** per closure-audit practice.
- Rows that now reference canonical Schwab fields correctly: **`REPLACED`**.
- Rows that **still** require a non-canonical shape: **`GOVERNED_EXCEPTION (O-NN)`** with matching **`governed_ref`**, and add **`### O-NN`** narrative to **`OPERATOR_DECISION_REGISTER.md`** with the **three mandatory lines**.

---

## Perf-proof bundle ↔ register (mandatory)

A validated replacement bundle under `governance/artifacts/perf_proof/replacements/pp_*.json` proves **code + pytest timing** for a landed replacement. **`scoreboard.P`** counts those bundles; **`replaced_count_d17`** (Deliverable **17**) counts **`disposition=REPLACED`** rows in the V4 register. Those signals **must** stay coherent: **no orphan bundles** and **no `REPLACED` rows for perf-proofed code without a cited bundle**.

**Merge gate (normative):**

1. Any change that **adds or materially updates** a replacement **`pp_*.json`** **must** list every affected **`register_id`** in that file’s **`register_link.replaced_register_ids`**.
2. The **same commit** **must** flip those register rows to **`REPLACED`** with:
   - **`canonical_field_citation`**: a Schwab CSV-canonical path that the bundle’s **`replacement_scope`** and landed code **actually** reference for that row. The citation **must** be copied from a **`csv_candidates`** or **`csv_lexical_topk_note`** segment that **literally contains** that path (or an approved equivalent such as `chains.callExpDateMap.*.totalVolume`). **Forbidden:** taking **`csv_candidates.split(";")[0]`**, any unsorted “first segment” default, or any path chosen only from a **token collision** (e.g. Python `return` → `returnOnAssets`). If **no** segment matches the bundle’s Schwab fields for that row, the row is **not** a site of that replacement and **must not** be flipped to **`REPLACED`** for that **`pp_*.json`**.
   - **`governed_ref`**: relative repo path to that **`pp_*.json`** (perf-proof evidence pointer). Deliverable **18** governs **`GOVERNED_EXCEPTION`** + **`O-NN`** only; **`REPLACED`** rows may use this proof path in **`governed_ref`** without an **`O-NN`**.
3. **Composite** bundles that only aggregate pytest targets of already-bound slices **must** record **`register_link.wrapped_proof_ids`** and **`replaced_register_ids`** as the **sorted union** of the wrapped bundles’ ids (no extra register flips beyond that union).

---

## When an `O-XX` is acceptable

Use **`GOVERNED_EXCEPTION (O-NN)`** only when **all** hold:

1. **Why:** derived / alternate representation is retained despite a Schwab field existing.  
2. **Constraint:** a concrete trade-off (units, consumer API, latency, precision, etc.).  
3. **Permanent or interim:** if interim, include a **target date** or successor milestone.

The gatekeeper **rejects** boilerplate operator entries missing any of the three elements.

---

## When refactor is required

If a **Schwab equivalent fits** the site and **no** operator-cited **constraint** in a valid **`O-XX`** blocks substitution, the row **must not** close as **`GOVERNED_EXCEPTION`** — **edit code** toward **`REPLACED`** or remove the emission.

---

## Evidence bar (V4-A enforcement)

**Authority:** Disposition and replacement-loop work must satisfy this bar before gatekeeper acceptance and operator **`O-XX`** sign-off. Batches group rows that share the **same disposition decision**; they do **not** merge or substitute for **per-row evidence**.

1. **Per-row evidence:** Every register row carries **individual** evidence in its register columns or a **linked artifact** (path stable under version control or cited in the closure audit). Batches share **disposition logic**, never **evidence**. The phrase *“we sampled N and the rest follow”* is **not admissible** at any closure step. Cursor’s batch memos record **per-row evidence pointers** — not aggregate “spot-checked N of M” claims.

2. **No probability language in proposals:** Dispositions are **verified** or **pending** (`UNREVIEWED`). Words and phrases such as *likely*, *often*, *high-confidence*, *cheap check*, and *common pattern* are **removed** from batch memos before gatekeeper review. Either the disposition has evidence per **(1)** or the row stays **`UNREVIEWED`**.

3. **`NO_SCHWAB_EQUIVALENT` four-channel exhaustion:** Every row closed as **`NO_SCHWAB_EQUIVALENT`** must record that **all four** search channels were exercised — **token** match, **category** match, **likely_use** match, and **embedding top-K**. That record lives in the row’s **`notes`**, **`governed_ref`**, **`canonical_field_citation`**, or a **linked exhaustion workbook** keyed by **`register_id`**. If the four-channel record is missing, the row is **not** closed as **`NO_SCHWAB_EQUIVALENT`**.

4. **`REPLACED` with generic-name origin:** When the **`surface_form`** uses a **generic** accessor (e.g. `row["…"]`, `d["…"]`, `data["…"]`, or `obj.attr` where the object name is **not** clearly Schwab-prefixed / payload-named by project convention), **`REPLACED`** requires a **recorded provenance trace** from the accessor back to a **Schwab API payload boundary** (or an equivalent documented source-of-truth chain). The trace is recorded in **`notes`** or **`governed_ref`**. **No** **`REPLACED`** may be proposed on **`csv_candidates`** / lexical match **alone** for generic-named sites.

5. **Markdown / comment / docstring `NOT_MARKET_DATA`:** Classification is **per row** via **path:line** inspection of the **actual** source context for that row’s **`surface_form`** — fenced code vs prose vs comment is a **per-occurrence** judgment, not an extension-level or file-level shortcut. If inspection is **non-trivial** (long file, tangled control flow, ambiguous fences), the row remains **`UNREVIEWED`** for manual disposition rather than auto-applying **`NOT_MARKET_DATA`**.

6. **Pre-V4 precedent inheritance (S009, S017, S008, any S0xx):** Pre-V4 contracts and **`O-XX`** entries are **not** free citations for V4 closure. Each row in a **pre-V4 precedent** batch resolves via **exactly one** of:
   - **(a)** Fresh **V4** simulation evidence in **`governance/SCHWAB_FIELD_SIMULATION_<topic>_V1.md`** (or an equivalent gatekeeper-approved path), with **`GOVERNED_EXCEPTION (O-NN)`** citing that artifact; or  
   - **(b)** An explicit **operator-signed V4 inheritance `O-XX`** in **`governance/OPERATOR_DECISION_REGISTER.md`** (under the **V4 narrative addendum**), with the **three-element** narrative (**Why:** / **Constraint:** / **Permanent or interim:**) documenting why prior contract evidence is admissible **without** fresh measurement.

   **Cursor** never self-authorizes precedent inheritance. Pre-V4 precedent batches **block** at gatekeeper review until **(a)** or **(b)** is in place.

---

## Exit

Loop until **`bare_governed_exception_count == 0`** and **`python -m tools.schwab_oxx_validator`** passes on the **V4** register.
