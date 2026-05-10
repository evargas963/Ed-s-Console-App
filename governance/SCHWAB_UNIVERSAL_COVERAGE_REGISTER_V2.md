> **Contract note:** `SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V2.md` is **SUPERSEDED_BY_V3**. New closure work uses **`SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md`** and **`SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V3`**.

# Schwab Universal Coverage Register V2 — Index

**Status:** Placeholder index — populated CSV is produced by the scanner (`Step 3` in program sequencing). **Historical** under V3 supersession.  
**Contract (historical):** `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V2.md`  
**Scanner:** `tools/schwab_universal_coverage_scanner_v2/` (see `TRACEABILITY_V2.md`)

## Data artifact

- **`governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V2.csv`** — generate with:

```text
python -m tools.schwab_universal_coverage_scanner_v2
```

(Optional: `--max-files N` for smoke; `--include-dot-claude` only if dedup policy requires.)

## Columns (machine schema)

Defined in `tools/schwab_universal_coverage_scanner_v2/register.py` → `REGISTER_COLUMNS`.

| Column | Role |
|--------|------|
| `register_id` | Stable hash id |
| `language` | `python`, `cross_validator`, `json`, `yaml_regex`, `sql`, `javascript`, `typescript`, extension for catch-all text, … |
| `path` | Repo-relative path |
| `line` / `col` | Source location |
| `pattern_kind` | Visitor / cross-validator kind (must map to V2 G1/G2) |
| `surface_form` | Short excerpt |
| `tokens` | Extracted tokens for CSV lookup |
| `csv_candidates` | Heuristic matches (never auto-disposition) |
| `csv_lexical_topk_note` | Lexical placeholder for G3 embedding slot |
| `v2_trace` | Contract clause pointer |
| `disposition` | Scanner emits **`UNREVIEWED` only** |
| `canonical_field_citation` / `governed_ref` / `notes` | Human / audit |

## Honest limits (scanner v0.1)

See `tools/schwab_universal_coverage_scanner_v2/TRACEABILITY_V2.md`: JS/TS uses **regex heuristics** (`tree_sitter_pending` in `notes`); G3 **embeddings** use **difflib** lexical fallback until a real embedding pipeline is integrated; YAML full-structure walk prefers **PyYAML** when installed, else **line regex**.
