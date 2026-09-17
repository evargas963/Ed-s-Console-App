"""Proof for the no-fallback mechanical lock's candidate-identity correction (operator
point 5, 2026-09-17): "Replace unstable FB IDs ... Never apply an old verdict to a
shifted candidate." The prior scheme assigned sequential `FB-NNNNN` ids purely from scan
order -- inserting or deleting a candidate anywhere earlier in the walk silently
renumbered every later one. Identity is now a content fingerprint (file, enclosing
symbol, detector pattern, a normalized/position-independent AST dump, and the guessed
semantic field), so it survives unrelated edits and only changes when the candidate's
own expression changes. These tests call the real scanner (`scan_python`,
`_finalize_ids`) directly against hand-built source text -- never a mocked hash function
-- so a pass proves the actual production identity path, not an isolated assertion.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.fallback_discovery import _finalize_ids, scan_python  # noqa: E402


def _discover(rel: str, src: str) -> list[dict]:
    candidates = scan_python(rel, src)
    _finalize_ids(candidates)
    return candidates


_SRC_A = (
    "def build(mkt_ctx):\n"
    "    spot = mkt_ctx.spot or 100.0\n"
    "    return spot\n"
)


def test_same_source_same_id_across_reruns():
    """The most basic determinism guarantee: scanning identical content twice must
    yield the identical id, not merely a stable count."""
    first = _discover("pkg/mod.py", _SRC_A)
    second = _discover("pkg/mod.py", _SRC_A)
    assert len(first) == 1 and len(second) == 1
    assert first[0]["id"] == second[0]["id"]
    assert first[0]["fingerprint"] == second[0]["fingerprint"]


def test_id_survives_an_unrelated_insertion_earlier_in_the_same_file():
    """The exact defect named by the operator: under the OLD sequential-counter scheme,
    inserting a new candidate BEFORE an existing one in scan order silently renumbered
    the existing one, so a verdict recorded against its old id would silently point at
    whatever candidate now occupies that slot. Under fingerprint identity, prepending an
    unrelated candidate to the same file must leave the original candidate's id
    unchanged."""
    before = _discover("pkg/mod.py", _SRC_A)
    assert len(before) == 1
    original_id = before[0]["id"]

    src_with_insertion = (
        "def unrelated(vendor_ctx):\n"
        "    vendor = vendor_ctx.vendor or 'default_vendor'\n"
        "    return vendor\n"
        "\n"
    ) + _SRC_A
    after = _discover("pkg/mod.py", src_with_insertion)
    assert len(after) == 2
    ids_after = {c["id"] for c in after}
    assert original_id in ids_after, (
        "inserting an unrelated candidate earlier in the same file must not change an "
        "existing candidate's id -- this is the exact 'shifted candidate' failure mode "
        "sequential FB-NNNNN ids could not detect"
    )


def test_moving_the_candidate_to_a_different_line_does_not_change_its_id():
    """Line number is explicitly demoted to metadata, never identity -- reflowing the
    file (blank lines, comments) above the candidate must not change its id."""
    before = _discover("pkg/mod.py", _SRC_A)
    moved_src = "\n\n\n# an unrelated comment\n\n" + _SRC_A
    after = _discover("pkg/mod.py", moved_src)
    assert before[0]["line"] != after[0]["line"], "test setup should actually move the line"
    assert before[0]["id"] == after[0]["id"]


def test_same_shape_in_a_different_file_gets_a_different_id():
    """File is part of the identity basis -- the identical expression in two different
    files must not collide."""
    a = _discover("pkg/mod_a.py", _SRC_A)
    b = _discover("pkg/mod_b.py", _SRC_A)
    assert a[0]["id"] != b[0]["id"]


def test_genuinely_identical_candidates_in_one_file_get_disambiguated_not_collapsed():
    """Two literally identical OR_LADDER expressions in the same file/function (a real,
    if rare, case) must both survive as distinct candidates -- fingerprint collision is
    resolved with a stable `-2` suffix, never by silently dropping one."""
    src = (
        "def build(mkt_ctx):\n"
        "    a = mkt_ctx.spot or 100.0\n"
        "    b = mkt_ctx.spot or 100.0\n"
        "    return a, b\n"
    )
    out = _discover("pkg/dupe.py", src)
    assert len(out) == 2
    ids = [c["id"] for c in out]
    assert len(set(ids)) == 2, "both candidates must be individually addressable"
    assert any(i.endswith("-2") for i in ids), "the collision must be disambiguated with a suffix"


def test_sql_string_used_only_as_a_membership_test_is_not_flagged():
    """Discovered false positive (2026-09-17): this repo's own regression-proof tests
    assert a repair by searching for the banned pattern's ABSENCE in real source text
    (`assert "COALESCE(...)" not in code_only`), which necessarily quotes the banned
    syntax as a string literal without executing it as SQL. A string actually used as
    SQL is passed to a query call or returned/assigned, never merely compared via `in`/
    `not in` -- so excluding the membership-test shape cannot hide a real violation."""
    src = (
        "def test_repair_proof():\n"
        "    code_only = 'irrelevant'\n"
        "    assert \"COALESCE(canonical_timeframe, '1m')\" not in code_only\n"
    )
    out = scan_python("tests/test_something.py", src)
    assert out == [], "a membership-test operand must not be flagged as executable SQL"


def test_sql_string_actually_returned_is_still_flagged():
    """The membership-test exclusion must not become a blanket SQL-detector bypass --
    a COALESCE string that is actually RETURNED (i.e., could be executed as a query)
    must still be caught."""
    src = (
        "def q():\n"
        "    return \"SELECT COALESCE(canonical_timeframe, '1m') FROM snapshots\"\n"
    )
    out = scan_python("queries.py", src)
    assert len(out) == 1
    assert out[0]["pattern"] == "SQL_COALESCE_STYLE"


def test_meta_tooling_and_test_proof_namespace_are_recorded_not_silently_skipped():
    """The governance meta-tooling files and the mission's own mutation/negative-control
    proof namespace are excluded from the census (their content is prose/fixture text
    ABOUT fallback shapes, not fallback logic) -- but the exclusion must be enumerable in
    the report, never a silent drop. Runs the real driver in-process (monkeypatched argv/
    cwd) against the real repo tree, proving the actual main() skip path, not just the
    membership tests in isolation."""
    import importlib
    import json

    import tools.fallback_discovery as fd

    importlib.reload(fd)
    out_path = ROOT / "reports" / ".test_fingerprint_identity_scratch.json"
    old_argv = sys.argv
    try:
        sys.argv = ["fallback_discovery.py", "--out", str(out_path.relative_to(ROOT))]
        assert fd.main() == 0
        report = json.loads(out_path.read_text(encoding="utf-8"))
        excluded = report["meta_tooling_excluded_from_scan"]
        assert excluded.get("tools/fallback_discovery.py", 0) >= 1
        assert excluded.get("tools/apply_adjudication.py", 0) >= 1
        assert excluded.get("tests/test_no_fallback_lock_v1.py", 0) >= 1
        ids = [c["id"] for c in report["candidates"]]
        assert len(ids) == len(set(ids)), "regenerated census must have unique ids"
    finally:
        sys.argv = old_argv
        out_path.unlink(missing_ok=True)


def test_adjudication_target_validation_distinguishes_legacy_from_shifted():
    """apply_adjudication.py's own point-5 guard: a LEGACY-format (FB-NNNNN) id with no
    current match is the expected, benign steady state of a repair that deleted the
    underlying code outright -- counted, not failed. A NEW-format (fingerprint) id with
    no current match means an already-adjudicated candidate's code has changed shape
    since that verdict was recorded, and must fail loudly rather than silently drop the
    stale reference or, worse, let it coincidentally collide with a different candidate."""
    import importlib

    aa = importlib.import_module("tools.apply_adjudication")

    candidates = [{"id": "FB-abc1234567"}]

    # Legacy orphan: benign, must not raise.
    orig_adj, orig_rep = dict(aa.ADJUDICATION), dict(aa.REPAIRED)
    try:
        aa.ADJUDICATION.clear()
        aa.REPAIRED.clear()
        aa.ADJUDICATION["FB-00519"] = ("REPAIRED", "e", "r", "g")
        aa._validate_adjudication_targets_exist(candidates)  # must not raise

        # Shifted fingerprint: the exact danger this check exists to catch.
        aa.ADJUDICATION.clear()
        aa.ADJUDICATION["FB-deadbeef99"] = ("NOT_FALLBACK", "e", "r", "g")
        raised = False
        try:
            aa._validate_adjudication_targets_exist(candidates)
        except SystemExit:
            raised = True
        assert raised, "a new-format id with no matching candidate must fail loudly"
    finally:
        aa.ADJUDICATION.clear()
        aa.ADJUDICATION.update(orig_adj)
        aa.REPAIRED.clear()
        aa.REPAIRED.update(orig_rep)
