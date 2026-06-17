> **Classification:** Operational Ledger | **Scope:** Governance register/inventory `SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.md`.

# Schwab Universal Coverage Register — V4

**Program status:** V4 contract **LOCKED** 2026-05-08 (gatekeeper Step 2).  
**Contract:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md`  
**Machine-readable register:** `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` (**not tracked in git** — see `.gitignore`; regenerate after clone, see below).  
**Scanner:** `python -m tools.schwab_universal_coverage_scanner_v3` (default `--output` is the CSV above). For CI or long repos, `--embedding-mode mock` avoids per-row MiniLM encode latency; closure runs should document embedding mode in `governance/artifacts/schwab_v4_register_build_meta.json` and refresh the scoreboard.

**Walk scope (2026-05-14):** the scanner **does not descend** into **`node_modules/`**, Python envs (**`.venv/`**, **`venv/`**), **`dist/`**, **`build/`**, **`htmlcov/`**, **`.tox/`**, **`.eggs/`**, **`__pypackages__/`**, **`backups/`**, or Schwab **raw inventory dumps** under `schwab_field_inventory/{pricehistory,chains,instruments,streaming,market_hours}/` (see `tools/schwab_universal_coverage_scanner_v3/paths.py`). The dictionary CSV at `schwab_field_inventory/schwab_field_dictionary.csv` remains the vocabulary source. The output register path and `…mock_build.csv` are **never scanned as inputs** (avoids self-scan and ~12M-row artifacts).

**Large prior register:** if an old multi-GB CSV sits at the default `--output` path, disposition merge reads the whole file first. Set **`SCHWAB_SKIP_DISPOSITION_MERGE=1`** for one rescan to ignore prior dispositions, or move/delete the old CSV before rescanning.

**Retiring this CSV (directional):** long-term intent is to drop the universal line-register artifact once D17 invariants live on a **scoped** static gate (smaller surface). Until then, keep the CSV **gitignored**, delete it between runs to reclaim disk, and rely on **meta + scoreboard** pins in git.

**After clone:** run the scanner with the same flags recorded in `governance/artifacts/schwab_v4_register_build_meta.json` under `scanner_flags` (until you intentionally refresh that pin), e.g.  
`python -m tools.schwab_universal_coverage_scanner_v3 --max-files 400 --embedding-mode mock`  
so the CSV exists at the default path. The meta file pins `register_content_sha256`, `register_size_bytes`, and `scanner_commit_sha` for audit / CI reproduction.

**Deferred register work** is tracked only in **`OPEN_ITEMS.md`** (section **Schwab V4 Universal Coverage (register pipeline)**) to avoid duplicate checklists across governance files.

## Columns

Same schema as V2/V3 — see `tools/schwab_universal_coverage_scanner_v3/register.py` (`REGISTER_COLUMNS`).

**V4-A:** Rows dispositioned `GOVERNED_EXCEPTION` **must** use `GOVERNED_EXCEPTION (O-NN)` in **`disposition`** and repeat **`O-NN`** in **`governed_ref`**, with a matching `### O-NN` narrative in `governance/OPERATOR_DECISION_REGISTER.md` (Why: / Constraint: / Permanent or interim:).

## Tooling

- **Deliverable 17:** `python -m tools.schwab_coverage_v4_metrics --register governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv`
- **Scoreboard (P + Δ unreviewed):** `python -m tools.schwab_v4_scoreboard` → `governance/artifacts/schwab_v4_scoreboard.json` (requires perf proofs under `governance/artifacts/perf_proof/replacements/`)
- **Mock-build upper bound (informational):** `python -m tools.schwab_v4_scoreboard --register governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.mock_build.csv --out governance/artifacts/schwab_v4_scoreboard_<date>_mock_upper_bound.json --no-register-meta --no-update-perf-index --mock-upper-bound` — does **not** replace the production register pin. See **§ Gate II** below.
- **Deliverable 18:** `python -m tools.schwab_oxx_validator --register governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv`

## Gate II: Scanner vs file inventory scope

**Status:** Reconciliation context for numeric gaps between the scanner walk and the V4 file inventory (Gate II).  
**References:** `tools/schwab_universal_coverage_scanner_v3/` (walk + `inventory_mark_present`), `tools/build_schwab_v4_file_inventory.py`, `governance/SCHWAB_V4_FILE_INVENTORY.csv`, `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` (O-40).

The **scanner** and the **V4 file inventory** answer different questions with different filters. They are **not wired together** (zero imports of `SCHWAB_V4_FILE_INVENTORY.csv` in the scanner package). A numeric gap between “files the scanner attempted” and “files marked `pending` in the inventory” is **expected** until a reconciliation option below is adopted.

| Quantity | Source | Typical value (this repo, 2026-05-11) |
|----------|--------|----------------------------------------|
| Scanner `files_attempted` (full mock run) | `run_scan` counter after `skip_dictionary` / `skip_claude` | **9,022** |
| Inventory `status=pending` | `build_schwab_v4_file_inventory` | **3,966** |
| Approx. file-level gap | Scanner − pending | **~5,056** |
| Register rows (mock full register) | `SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.mock_build.csv` | **12,523,480** |

### Why the systems diverge

**1. Different mission**

- **Inventory (O-40):** Human **file-level** proof-of-coverage for Schwab disposition work; rows are paths with `pending` / `excluded` / `reviewed` and a **clause** explaining exclusion.
- **Scanner (V3/V4):** **Site-level** register (path, line, col, tokens) for CSV-canonical disposition; emits one row per hit, not one row per file.

**2. Walk vs classify rules (file-level mismatch drivers)**

| Mechanism | Scanner | Inventory |
|-----------|---------|-----------|
| `node_modules/` | **Walked**; if UTF-8 text decodes, file is **scanned** and rows emitted; `vendor_path_listed` may be tagged in `notes`. | **`excluded`** (`G1.1 vendored`) — not `pending`. |
| Dependency manifests (`package-lock.json`, `requirements*.txt`, …) | **Scanned** if under walk (JSON/YAML/text). | **`excluded`** (`G1.1 dependency manifest`). |
| `schwab_field_dictionary.csv` | **`skip_dictionary`** — not in `files_attempted`. | **`excluded`** (`G1.1 canonical CSV source-of-truth`). |
| `.claude/` paths | **`skip_claude`** by default (unless `--include-dot-claude`). | **`excluded`** (`G1.1 .claude worktree dedup`). |
| Binary / non-UTF-8 | Counted in `files_attempted`; excluded from **b_scanned** after probe. | **`excluded`** (`V3-B binary file`). |
| `.git` | **Not walked** (pruned); files not enumerated in `files_attempted`. | Path contains `.git` → **`excluded`**. |

**Largest practical gap:** vendor and manifest files are **inventory-excluded** but **scanner-eligible**, inflating `files_attempted` relative to `pending`.

**3. Row explosion (register vs inventory)**

The mock full run produced **~12.5M register rows** from **9k files** — multiple hits per file (catch-all + specialized parsers, long JSON, etc.). Inventory row count stays **O(files)**; register size is **O(hits)**. This is not a counting bug.

### Reconciliation options (pick one for Gate II closure)

**A. Inventory-subordinate (scanner truth for sites)**  
Treat the register as authoritative for **market-data sites**. Inventory `pending` is a **work queue** only: every `pending` path must appear in the scanner’s attempted set (or have an explicit “scanner blind spot” O-XX). Gaps (scanner-only paths) are **added to inventory** as `excluded` with clause `scanner_only_non_pending` or promoted to `pending` if humans must disposition the file.

**B. Scanner-filtered-by-inventory**  
Post-process the register to **drop** rows whose `path` is not `pending` (or not `pending|reviewed`) in `SCHWAB_V4_FILE_INVENTORY.csv`. Committed register = filtered artifact; full scan remains local. Requires stable CSV join and version pinning.

**C. Independent with documented bridge (status quo, not closure-ready)**  
Keep both systems; publish a periodic diff job: `scanner_attempted_paths ⊖ inventory_pending_paths` by reason. **Not** admissible for “100% reconciled” claims until a bridge is automated.

### Blocked until decided

- Promoting `SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.mock_build.csv` (or any full mock dump) to **the** production register pin without **Gate III** (aggregate/hash vs Git LFS).
- Treating **mock** embedding top-K as Channel-4 evidence (**Gate I**).
- Claiming line-by-line closure at **12.5M rows** without **Gate IV** (context-dump / classifier evidence per row).

### Artifact cross-link

Upper-bound scoreboard JSON (informational only):  
`governance/artifacts/schwab_v4_scoreboard_20260511_mock_upper_bound.json`

Partial-register CI pin (example): see `governance/artifacts/schwab_v4_register_build_meta.json` (`scanner_flags`, `register_content_sha256`).
