> **SUPERSEDED:** This artifact is **superseded** by `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V2.md` (**SUPERSEDED_BY_V2**). **Do not** use V1 for scope, closure, or gatekeeping. Retained for history only. V1’s Python-only carve-out (former § scope) was **incorrect** under the verbatim mission and is **not** binding. **Active program:** V2 is **SUPERSEDED_BY_V3**; the current contract is `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md`.

# Schwab Universal Coverage Proof Program V1

**Status:** SUPERSEDED_BY_V2  
**Artifact:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V1.md`  
**Created:** 2026-05-09  
**Superseded:** 2026-05-09 → **V2**  
**Authority:** Operator execution brief (universal coverage proof; no scope carve-outs) — **historical**

---

## Mission (verbatim bar)

> Global, universal, complete, 100% through the entire, whole, entirety, no stone left unturned repo, any and all living files, every line, every sentence needs to be consistent.

**Operationalized:** Build a register where **every line of code** in **every Python file in the repository** that touches a **market-data field, derivation, computation, default, fallback, or substitution** has been **cross-referenced against the Schwab canonical field dictionary** and **explicitly dispositioned**. **Empty `UNREVIEWED` across the entire register** is the proof.

---

## Scope — no exclusions

**Every `.py` file in the repository.** Including but not limited to:

- Root-level modules (`server.py`, `db.py`, `market_state.py`, `signals.py`, `ml_predict.py`, `ml_train.py`, `ml_scheduler.py`, `monte_carlo.py`, `mc_fusion_adjustment.py`, `chains.py`, `market_context.py`, `market_data_adapter.py`, `live_market_plane.py`, `realized_contract_eval.py`, `snapshot_normalizer.py`, `signal_types.py`, `order_flow_engine.py`, `order_flow_streaming.py`, `order_flow_live_state.py`, `liquidity_value_engine.py`, `prediction_engine.py`, `transformer_train.py`, `transformer_model.py`, `lstm_data.py`, `lstm_model.py`, `bayesian_fusion.py`, `governed_stack_contract.py`, `call_engine.py`, and **every other** repository-root `.py` file).
- `calibration/**/*.py`
- `features/**/*.py`
- `v2_decision/**/*.py`
- `arch_competition/**/*.py`
- `planes/**/*.py`
- `verification/**/*.py`
- `research/**/*.py`
- `tests/**/*.py` — **in scope**
- `tools/**/*.py` — **in scope**
- `schwab_field_inventory/**/*.py` — **in scope** (including inventory tooling)
- **Any other directory** under the repository tree that contains `.py` files

**No carve-outs.** No “production only.” No “decision-relevant only.” No “tests excluded.” No “tools excluded.” If a `.py` file exists in the repository tree, it is in scope.

**`.claude/worktrees/*`:** Treated as duplicate of main-repo content by construction. **Scan once** per logical main path; **deduplicate** in post-processing so each unique source line is examined once. The bar is **universal coverage of unique repository code**, not duplicate worktree bytes.

**Non-Python:** Out of scope for **this** program’s line-level register unless explicitly added in a future program revision. (This contract does **not** claim HTML/JS/SQL coverage.)

---

## Deliverables (build order)

| # | Deliverable | Owner |
|---|-------------|--------|
| 1 | `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V1.md` (this contract) | Cursor draft → operator + gatekeeper approve before scanner |
| 2 | `tools/schwab_universal_coverage_scanner_v1.py` — AST scanner + CSV cross-reference + register writer | Cursor |
| 3 | `tests/test_schwab_universal_coverage_scanner_v1.py` — **minimum one test per visitor pattern kind** | Cursor |
| 4 | `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V1.csv` — one row per market-data-touching site; initial `disposition=UNREVIEWED` | Cursor (mechanical generation) |
| 5 | `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V1.md` — governance index pointing to the CSV | Cursor |
| 6 | `tools/check_schwab_csv_first.py` extended with **`--all-files`** mode — whole-repo scan; flags any line not covered by the register per contract rules | Cursor |
| 7 | **GitHub Actions workflow** — runs `--all-files` (or equivalent) on every commit | Cursor |
| 8 | `governance/SCHWAB_COVERAGE_PROOF_CLOSURE_AUDIT_V1.md` — closure record with evidence pointers | Cursor draft; operator signs |

---

## Visitor pattern requirements (minimum)

The AST visitor must emit **one register row per match** for each kind below (non-exhaustive of *future* expansion until stability — see **Visitor stability**).

**Direct field reads**

- Subscript access with market-token string key (`row["spread"]`, `chain["theta"]`)
- Attribute access on market-token names (`ms.spot`, `oe.spread`)
- Dict literal keys with market-token names

**Derivations / computations**

- `BinOp` with market-tokened operands (`ask - bid`, `(bid + ask) / 2`, `volume / oi`)
- Function calls computing market values (`compute_spread(...)`, `_mid(...)`)
- Comprehensions producing market-tokened collections

**Defaults / fallbacks**

- `BoolOp` `or` with literal default (`x or 0`, `field or 0.0`, `multiplier or 100`)
- `IfExp` ternary with default in else (`x if x is not None else 0.0`)
- `dict.get(key, default)` with market-token key and literal default
- `getattr(obj, "spot", default)` with market-token attribute

**Time / clock**

- `time.time()`, `datetime.now()`, `time.monotonic()` — **every** such call cataloged; disposition distinguishes tape-time vs operational use
- Wall-clock used as **decision** timestamp (same visitor obligation; disposition clarifies)

**Imputations / coercions**

- `float(... or 0.0)`, `int(... or 0)`
- `nan_to_num`, `fillna`, median fill
- Magic numerical defaults bound to market-token names (`default_iv = 0.20`, `OPTION_MULTIPLIER = 100`)

**Schwab-canonical reads**

- Correct Schwab field usage **still produces a row**. Disposition **`REPLACED`** with citation. Correct usage **counts toward proof**.

---

## Visitor stability

The visitor is **stable** when **three consecutive** full-repo disposition cycles surface **zero new pattern kinds** (no new `pattern_kind` values requiring new visitor logic). Until then, the visitor is **incomplete by definition**.

Process: scanner run → disposition pass → expand visitor for any missed pattern kind → re-run → repeat until stability.

---

## Disposition schema

Each row has **exactly one** disposition:

| Disposition | Meaning | Required evidence |
|-------------|---------|-------------------|
| **REPLACED** | Code uses Schwab canonical field correctly | Cite `canonical_field` row from CSV |
| **GOVERNED_EXCEPTION** | Derived kept despite Schwab equivalent | Named **O-XX** or **DFR-XX** with rationale |
| **NO_SCHWAB_EQUIVALENT** | No CSV row fits | Cite CSV search performed |
| **NOT_MARKET_DATA** | Visitor false positive | Reason citing actual semantics |
| **UNREVIEWED** | Initial / pending | **Disallowed at program closure** |

**Scanner rule:** The tool **never** auto-writes `REPLACED`, `GOVERNED_EXCEPTION`, or `NO_SCHWAB_EQUIVALENT`. The only allowed mechanical auto-assist is **`NOT_MARKET_DATA`** where the contract permits hard semantic false-positive rules **explicitly listed in the scanner docstring and in this program** (if none listed, mechanical auto-assist is **zero**).

---

## CSV cross-reference (`csv_candidates`)

For each row, the scanner emits `csv_candidates` using **at least**:

1. **Token match** — code tokens vs `canonical_field` tokens  
2. **Category match** — contextual keywords vs CSV `category`  
3. **Likely-use match** — contextual keywords vs CSV `likely_use`

`csv_candidates` is **informational only**. Human disposition is required for all non-mechanical rows.

**Canonical dictionary:** `schwab_field_inventory/schwab_field_dictionary.csv` (2,393 canonical rows as of program baseline; row count updates if CSV changes).

---

## Completion criteria — ALL must hold

1. AST visitor has scanned **every** in-scope `.py` file; **file count recorded** and auditable.  
2. Visitor has reached **stability** (three consecutive runs, **zero new pattern kinds**).  
3. **Every** register row has a disposition **other than** `UNREVIEWED`.  
4. `python tools/check_schwab_csv_first.py --all-files` **passes** on the whole repo (no line flagged without register coverage per contract).  
5. **CI** runs the `--all-files` property check on **every commit**.  
6. `governance/SCHWAB_COVERAGE_PROOF_CLOSURE_AUDIT_V1.md` exists with **evidence pointers**.  
7. New **O-XX** recorded in `governance/OPERATOR_DECISION_REGISTER.md` declaring the program closed.

---

## Sequencing — strictly sequential

1. Cursor drafts **this** program contract → operator + gatekeeper **approve** before scanner code.  
2. Cursor drafts **scanner + tests** against the locked contract.  
3. Cursor **runs** scanner on entire repo → initial register (all `UNREVIEWED`).  
4. Operator + Cursor **disposition** every row out of `UNREVIEWED`.  
5. **Visitor expansion** loop until **stability** (three consecutive runs, zero new pattern kinds).  
6. Cursor extends **`check_schwab_csv_first.py`** with `--all-files`.  
7. Run `--all-files`; any gap → return to step 5.  
8. **CI integration** (workflow on every commit).  
9. Cursor drafts **closure audit**; operator records **O-XX**; program closes.

---

## Roles

| Role | Responsibility |
|------|----------------|
| **Cursor** | Draft contract; build scanner + tests; populate register mechanically; expand visitor; implement `--all-files`; draft closure audit; **never** auto-`REPLACED` / `GOVERNED_EXCEPTION` / `NO_SCHWAB_EQUIVALENT` |
| **Operator** | Approve contract; per-row disposition for proof buckets; **O-XX** for governed exceptions; closure authorization when all criteria hold |
| **Gatekeeper** | Reject scope filters; verify visitor pattern coverage; verify no forbidden auto-classification; verify stability claim; verify all completion criteria before closure |

---

## Forbidden — MUST NOT

- Curated lists of “important” or “decision-relevant” files as **scope**  
- File-type or directory **exclusions** from universal `.py` scope (except dedup of `.claude` worktree mirrors as specified)  
- Auto-classification to `REPLACED` / `GOVERNED_EXCEPTION` / `NO_SCHWAB_EQUIVALENT`  
- Closure framing before **all** completion criteria hold  
- Skipping visitor iteration to stability  
- Language such as “approximately complete,” “effectively complete,” or “comprehensive within scope” for **program closure**  
- Gatekeeper or operator **approval for closure** while **any** row remains `UNREVIEWED`

---

## Status until closure

```text
PROGRAM: COVERAGE PROOF v1 — IN PROGRESS
COVERAGE PROOF: OPEN — every row UNREVIEWED until human disposition complete
SYSTEM: FAIL
```

These lines do **not** change until **completion criteria 1–7** all hold **simultaneously**.

---

## Relation to other artifacts

- **`SCHWAB_TRADE_DECISION_ENDPOINTS_V1.yaml`** and any **decision-only** dependency tool are **orthogonal** lineage aids; they **do not** satisfy and **do not** replace this universal program.  
- **`ENGINEERING_GATEKEEPING_POLICY.md`** § Active Status should remain consistent with **OPEN** coverage proof until this program closes.

---

## Revision

Amendments require operator + gatekeeper acknowledgment and a **version bump** (`V2`, etc.) or dated addendum recorded in `OPERATOR_DECISION_REGISTER.md`.
