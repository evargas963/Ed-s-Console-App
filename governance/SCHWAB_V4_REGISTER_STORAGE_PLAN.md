# Schwab V4 register storage plan

**Status:** proposal — operator / gatekeeper pick before implementation  
**Authority:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` (Deliverable 4: default scanner output path)  
**Related:** `governance/SCHWAB_V4_SCANNER_VS_INVENTORY_SCOPE.md`, `tools/schwab_v4_scoreboard.py`, `.github/workflows/schwab-csv-first.yml`

---

## Problem

- `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` is **~52 MB** text; GitHub warns above **50 MB** and blocks pushes above **100 MB** per file.
- A **full-repo rescan** with real embeddings (`--embedding-mode minilm`, no `--max-files`) will **grow** row count and CSV size; `schwab_v4_register_build_meta.json` and scoreboard JSON may also grow.
- CI and clones must remain **reproducible** without surprise multi‑GB downloads for casual contributors.

---

## Constraints

1. **Program path:** V4 program names `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` as the default scanner `--output` and the register CI tools use today. Any strategy either **keeps that path in git** (possibly as LFS pointer) or updates **program + all tool defaults + docs + CI** in one coordinated change.
2. **Human columns:** Disposition, `canonical_field_citation`, `governed_ref`, and operator narratives must stay **merge-reviewable** (diffs must remain usable; avoid opaque binary-only payloads without a text review path).
3. **Deliverable 18 / D17:** Anything that reads the register by path must keep working in **local dev**, **CI**, and **gatekeeper** workflows after the change.

---

## Options (summary)

| Approach | Pros | Cons |
|----------|------|------|
| **Git LFS** for register (+ large meta JSON if needed) | Same paths; small git objects; GitHub-supported | Every clone needs `git lfs pull`; CI must install LFS; bandwidth still scales with size |
| **Release / artifact store** (register built in CI, uploaded; repo holds checksum + fetch script) | Tiny git repo | Drift if fetch fails; harder to review full CSV in PR; more moving parts |
| **Split register** (sharded CSV + manifest row id → shard) | Smaller per-file size | Scanner/writer/CI all need shard logic; high implementation cost |
| **Compress in repo** (e.g. `.csv.gz` committed) | Smaller bytes | Poor `git diff` for human columns; program today expects `.csv` |

---

## Recommended direction (phased)

**Phase A — Git LFS (default recommendation)**  
- Track `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` under **Git LFS**.  
- If `governance/artifacts/schwab_v4_register_build_meta.json` or other scan artifacts exceed comfortable git size, **LFS those too** or generate them only in CI and `.gitignore` locally (only if program explicitly allows — today scoreboard merges meta from disk; keep one source of truth).  
- Document in `README` or `governance/OPERATOR_PREFLIGHT.md`: `git lfs install` and `git lfs pull` after clone.  
- Update `.github/workflows/schwab-csv-first.yml` (and any workflow touching the register) to **checkout LFS** and fail clearly if LFS objects are missing.

**Phase B — Full-rescan policy (#3)**  
- After LFS is in place, run **authoritative** full-repo scan; commit register + `register_build_meta` + refreshed `schwab_v4_scoreboard.json` in **bounded** slices if needed to keep PR review manageable (or one gatekeeper-approved bulk with evidence).  
- Keep **semantic perf_proof ↔ register** rules from `f59581c` unchanged.

**Phase C — Revisit only if LFS is rejected**  
- Re-evaluate release-artifact or sharded strategies with explicit **program amendment** for non-default register paths.

---

## Implementation checklist (when operator picks LFS)

1. Install/configure LFS; `git lfs track '*.csv'` (narrow pattern if other CSVs must stay normal git).  
2. Migrate existing register file into LFS (migrate import history or accept forward-only from a cut commit — gatekeeper decides).  
3. CI: `actions/checkout` with `lfs: true` (or explicit `git lfs pull`).  
4. Verify `python -m tools.schwab_coverage_v4_metrics`, `python -m tools.schwab_v4_scoreboard`, `python -m tools.schwab_oxx_validator`, and scanner CLI on a **fresh clone** after `lfs pull`.  
5. Note GitHub **bandwidth / storage** limits for LFS on the org plan.

---

## Open decisions (Ed / gatekeeper)

- **LFS vs artifact:** Accept LFS operational cost for all developers, or mandate artifact fetch for non-operator clones?  
- **History migration:** `git lfs migrate import` rewriting history vs **forward-only** LFS from a tagged baseline (simpler audit).  
- **Meta JSON:** Keep in normal git until size forces LFS, or LFS together with the register in one change.

---

## Out of scope (this document)

- `prior_P` / `delta_P` on the scoreboard (optional symmetry; defer until a scoreboard schema slice).  
- Cursor brief handoff line updates for `prior_git_ref` / `delta_replaced_count_d17` (bundle with next brief edit).
