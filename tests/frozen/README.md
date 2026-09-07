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
- (`filesystem_scanner_files.txt` and its test were DELETED 2026-09-06, bedrock step 3: a
  frozen census of scanner call sites is a ratchet over code shape, not a correctness lock —
  the independent-repo-scan rule for tests is enforced directly by
  `no_new_independent_repo_scan_in_tests`.)

There is intentionally no `__init__.py`: this directory holds data, not code.
