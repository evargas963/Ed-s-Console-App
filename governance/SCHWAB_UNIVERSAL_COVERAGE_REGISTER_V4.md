# Schwab Universal Coverage Register — V4

**Program status:** V4 contract **LOCKED** 2026-05-08 (gatekeeper Step 2).  
**Contract:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md`  
**Machine-readable register:** `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv`  
**Scanner:** `python -m tools.schwab_universal_coverage_scanner_v3` (default `--output` is the CSV above). For CI or long repos, `--embedding-mode mock` avoids per-row MiniLM encode latency; closure runs should document embedding mode in `governance/artifacts/schwab_v4_register_build_meta.json` and refresh the scoreboard.

## Columns

Same schema as V2/V3 — see `tools/schwab_universal_coverage_scanner_v3/register.py` (`REGISTER_COLUMNS`).

**V4-A:** Rows dispositioned `GOVERNED_EXCEPTION` **must** use `GOVERNED_EXCEPTION (O-NN)` in **`disposition`** and repeat **`O-NN`** in **`governed_ref`**, with a matching `### O-NN` narrative in `governance/OPERATOR_DECISION_REGISTER.md` (Why: / Constraint: / Permanent or interim:).

## Tooling

- **Deliverable 17:** `python -m tools.schwab_coverage_v4_metrics --register governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv`
- **Scoreboard (P + Δ unreviewed):** `python -m tools.schwab_v4_scoreboard` → `governance/artifacts/schwab_v4_scoreboard.json` (requires perf proofs under `governance/artifacts/perf_proof/replacements/`)
- **Deliverable 18:** `python -m tools.schwab_oxx_validator --register governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv`
