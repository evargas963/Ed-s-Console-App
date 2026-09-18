> **Classification:** Policy Specification | **Scope:** Repository documentation `tools/legacy/README.md`.

# Legacy one-off diagnostic/migration/study scripts (quarantined)

Repo-wide architectural rehab audit (2026-09-18): `tools/` had grown to 213 files, 104 of
them underscore-prefixed (`_phase4_bar_check.py`) or version-suffixed (`study_pin_direction_v1.py`)
by their own naming convention — a signal of one-off, point-in-time diagnostic, backfill,
migration, or research-study scripts rather than live enforcement machinery.

81 of those 104 are relocated here. Each was verified, not assumed, to have:
- zero cross-file `import`/`from ... import` callers anywhere in the repo;
- zero references in `.github/workflows/*.yml`, `.pre-commit-config.yaml`, `Makefile`,
  or `package.json`;
- a full pytest collection pass (6578 tests) with zero import errors after the move.

23 of the original 104 candidates were kept in `tools/` after this same verification
found real callers the naming convention alone did not predict (live test imports via
`from tools.<name> import ...`, `from tools import <name>`, or a bare `import <name>`
reached through `sys.path` — a different, valid dependency shape the "diagnostic script"
naming convention does not distinguish from a genuinely dead one).

**Do not import from here.** Nothing outside `tools/legacy/` (including `tools/legacy/horizon_7/`,
relocated separately in Phase E (a), 2026-05-18, see its own README) depends on these
scripts. They are kept for historical/audit reference, not maintained, and not guaranteed
to run against the current schema or runtime layout.

Relocated in the architectural rehab, Phase 0e, 2026-09-18.
