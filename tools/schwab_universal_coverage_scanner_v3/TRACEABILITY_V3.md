> **Classification:** Policy Specification | **Scope:** Repository documentation `tools/schwab_universal_coverage_scanner_v3/TRACEABILITY_V3.md`.

# Traceability: scanner modules → `SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md`

| Module | V3 clauses |
|--------|------------|
| `paths.py` | V3-B — no extension whitelist; prune dirs with explicit reconciliation; UTF-8 + null-byte classification |
| `vocabulary.py` | V3-A — CSV-derived `frozenset` vocabulary |
| `schwab_csv.py` | V3-A vocabulary + G3 embeddings / token index |
| `reconciliation.py` | Criterion 1 — (a)(b)(c)(d); `.claude` / G1.1 dictionary; no silent dir skips |
| `catch_all.py` | V3-B — mandatory minimum path for every decoded text file |
| `register.py` | Disposition schema (columns unchanged) |
| `synonyms.py` | G3 |
| `vendor_paths.py` | G1.1 |
| `python_scanner.py` | V3-A + G2 Python + cross-validator hook |
| `cross_validate.py` | G2 — CSV-vocabulary line sweep |
| `js_ts_scanner.py` | G2 JS/TS tree-sitter |
| `html_scanner.py` | G1 HTML |
| `sql_scan.py` | G1/G2 SQL |
| `structured_scan.py` | G1 JSON/YAML/TOML/INI walks |
| `markdown_scan.py` | G1 Markdown fences |
| `reverse_coverage.py` | V3-C / Deliverable 13 |
| `cli.py` | Deliverable 2 — orchestration, `b_scanned` only after successful read + parse |
| `V3_DYNAMIC_PATTERNS.md` | V3-D normative dynamic-site `pattern_kind` list |

**Scanner version:** `3.0.0` (Step 2 initial; gatekeeper review before closure claims).

**V4 note:** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` is the active coverage contract; scanner package path and architecture stay **`schwab_universal_coverage_scanner_v3/`** (no rename, no version bump).
