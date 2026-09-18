"""Proof for the no-fallback mechanical lock's JSON SQL-registry discovery (PR #254
point 7 / original mission point 6: "discover executable content by loader, not
extension"). Confirmed real, not hypothetical: db.py's get_snapshot_sql() loads every
snapshot_sql/*.json file and returns its string VALUES as literal SQL text, executed
as-is by 60+ callers across the repo -- a JSON value here is exactly as executable as a
Python string literal passed to conn.execute(), but no extension-based dispatch table
ever looked inside a .json file for a banned fallback shape before this scanner.

Regenerating the census under this scanner found 23 real, previously-invisible
COALESCE occurrences in snapshot_sql/*.json (not a planted example) -- and, in the same
pass, a genuine self-reference hazard: this mission's own governance artifacts
(reports/no_fallback_inventory.json etc.) quote real COALESCE findings as evidence
prose, and scanning them as SQL manufactured ~90 fake candidates pointing at nothing
real. Both are proven here: the real registry is discovered, and reports/ is excluded
without hiding that exclusion (it is counted, not silently dropped).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.fallback_discovery import scan_json_file  # noqa: E402


def test_planted_json_sql_fallback_is_discovered():
    src = (
        '{"get_widget_count": '
        '"SELECT COUNT(*) FROM widgets WHERE status = COALESCE(?, \'active\')"}'
    )
    hits = scan_json_file("fixture_registry.json", src)
    assert len(hits) == 1
    assert hits[0]["pattern"] == "SQL_COALESCE_STYLE"
    assert hits[0]["language"] == "sql-in-json"
    assert hits[0]["context"] == "get_widget_count"


def test_json_without_sql_produces_no_candidates():
    src = '{"a": "just some ordinary text", "b": 42, "c": null, "d": true}'
    assert scan_json_file("ordinary.json", src) == []


def test_nested_dict_and_list_values_are_walked():
    src = (
        '{"queries": {"by_ticker": ["SELECT 1", '
        '"SELECT COALESCE(spot, 0) FROM snapshots"]}}'
    )
    hits = scan_json_file("nested.json", src)
    assert len(hits) == 1
    assert hits[0]["context"] == "queries.by_ticker[1]"


def test_json_keys_are_never_treated_as_sql_only_values():
    """A dict KEY happening to contain the substring 'COALESCE' (e.g. a handle name
    someone chose poorly) must never itself be flagged -- only string VALUES are SQL
    here, per db.get_snapshot_sql's actual (key -> sql text) contract."""
    src = '{"legacy_coalesce_migration_note": "this key name is not SQL"}'
    assert scan_json_file("keyname.json", src) == []


def test_malformed_json_reports_parse_failure_not_silent_skip():
    hits = scan_json_file("broken.json", "{not valid json")
    assert len(hits) == 1
    assert hits[0]["pattern"] == "PARSE_FAILURE"


def test_real_snapshot_sql_registry_is_now_clean_a_regression_guard():
    """Not a planted fixture: scans the ACTUAL snapshot_sql/*.json files this repo
    ships. This scanner's very first real run against these files found 23 genuine
    COALESCE occurrences (all now repaired -- see reports/no_fallback_repair_plan.md,
    PR #254 point 7), proving the discovery gap was real, not hypothetical. Now that
    they are fixed, this test's job flips to a regression guard: the real registry
    must STAY clean. A future COALESCE reintroduced here would be caught by the
    census (SQL_COALESCE_STYLE, now correctly discoverable) long before this
    assertion -- this test exists so a silent regression in the registry itself
    fails loudly and specifically, not just as one more line in a 1000+-candidate
    census."""
    for name in ("registry_full_a.json", "registry_full_b.json",
                 "registry_full_c.json", "_auto_extracted.json"):
        path = ROOT / "snapshot_sql" / name
        if not path.exists():
            continue
        hits = scan_json_file(f"snapshot_sql/{name}", path.read_text(encoding="utf-8"))
        assert hits == [], (
            f"{name} reintroduced a SQL fallback shape after the point-7 repair: {hits}"
        )


def test_scanner_still_detects_a_real_looking_reintroduction():
    """Companion to the regression guard above: proves the scanner's detection
    capability itself is still live (not merely that the registry happens to be
    clean right now) by mutating a real registry file's actual content in memory --
    never touching the file on disk -- and confirming the mutation IS caught."""
    path = ROOT / "snapshot_sql" / "registry_full_b.json"
    src = path.read_text(encoding="utf-8")
    mutated = src.replace(
        '"tools/phase2_forward_write_verify.py:87": "SELECT MAX(snapshot_id) FROM snapshots"',
        '"tools/phase2_forward_write_verify.py:87": '
        '"SELECT COALESCE(MAX(snapshot_id), 0) FROM snapshots"',
    )
    assert mutated != src, "fixture assumption stale -- the source line this test mutates has moved"
    hits = scan_json_file("snapshot_sql/registry_full_b.json", mutated)
    assert any(h["pattern"] == "SQL_COALESCE_STYLE" for h in hits)


def test_reports_directory_json_is_excluded_from_sql_scan_but_enumerated():
    """The real driver (main(), in-process) must exclude reports/*.json from SQL
    scanning -- proven against this repo's actual reports/no_fallback_inventory.json,
    which genuinely contains COALESCE-quoting evidence prose and would otherwise
    self-pollute the census -- while still reporting the exclusion count, never a
    silent drop."""
    import importlib
    import json as _json

    import tools.fallback_discovery as fd

    importlib.reload(fd)
    out_path = ROOT / "reports" / ".test_json_sql_scratch.json"
    old_argv = sys.argv
    try:
        sys.argv = ["fallback_discovery.py", "--out", str(out_path.relative_to(ROOT))]
        assert fd.main() == 0
        report = _json.loads(out_path.read_text(encoding="utf-8"))
        assert report["reports_dir_json_excluded_from_sql_scan"], (
            "reports/ contains many .json files -- the exclusion bucket must be non-empty"
        )
        json_sql_candidates = [
            c for c in report["candidates"] if c.get("language") == "sql-in-json"
        ]
        assert all(
            c["file"].startswith("snapshot_sql/") for c in json_sql_candidates
        ), "every real json-sql candidate in the live census must come from snapshot_sql/, never reports/"
    finally:
        sys.argv = old_argv
        out_path.unlink(missing_ok=True)
