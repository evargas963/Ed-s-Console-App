# Frozen name sets (audit T2-4, 2026-08-24)

Each `*.txt` file here freezes a governed census BY NAME — one entry per line, sorted,
LF newlines. The paired test computes the live set and asserts set equality against the
frozen file, printing `ARRIVED` / `LEFT` names on any move. This replaces the exact-COUNT
pins that forced integer archaeology (measured: ~10-12% of recent commits were pure pin
re-accounting).

A legitimate arrival or departure is a ONE-LINE edit to the matching file in the same
commit, reviewed by name. Do not bulk-regenerate these files: a regenerated file hides
the very diff this pattern exists to show.

Formats:

- `mega2_inventory_names.txt`, `mega3_inventory_names.txt`, `mega4_inventory_names.txt` —
  `file.py::qualified_name` per traceable-inventory row
  (tests/test_mega2_traceable_audit.py and siblings).
- `claims_source_text_only_names.txt` — `tests/file.py::test_name` per source-text-only
  census entry; line numbers are stripped ON PURPOSE so line drift cannot churn the file
  (tests/test_claims_are_executed_gate_v1.py).
- `filesystem_scanner_files.txt` — `path.py::N` where N is the count of `.rglob("*.py")`
  sites in that file; line numbers are stripped, but N keeps a NEW site inside an
  already-listed file visible as a one-line diff
  (tests/test_gate_scope_is_the_git_index_v1.py).

There is intentionally no `__init__.py`: this directory holds data, not code.
