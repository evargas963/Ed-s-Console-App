"""TEST_SYSTEM_REHAB_V2 — the two mechanical recurrence locks this rehab requires:
an exact-duplicate test body must not silently reappear, and a new independent
whole-repo scan in a test must not silently reappear once the shared `repo_index`
observation could supply the same facts.

Both check cores are pure functions over a `root` directory
(tools/check_institutional_correctness.py: `_find_duplicate_test_groups`,
`_find_new_repo_scans`), so these controls run against a SYNTHETIC tmp_path tree —
never the real repository — proving the detection logic itself, positive and
negative, independent of whatever the real tree currently contains.
"""
from __future__ import annotations

from tools.check_institutional_correctness import (
    _find_duplicate_test_groups,
    _find_new_repo_scans,
)


# ─────────────────────────────────────────────────────────────────────────────
# Lock 1 — duplicate test body
# ─────────────────────────────────────────────────────────────────────────────

def test_renamed_reformatted_duplicate_is_blocked(tmp_path):
    (tmp_path / "test_a.py").write_text(
        "def test_one():\n"
        "    x = compute_thing(1, 2)\n"
        "    assert x == 3\n",
        encoding="utf-8",
    )
    # Same body, different name AND different whitespace/formatting -- still an
    # identical AST once parsed.
    (tmp_path / "test_b.py").write_text(
        "def test_two():\n"
        "    x = compute_thing(1, 2)\n"
        "    assert x == 3\n",
        encoding="utf-8",
    )
    groups = _find_duplicate_test_groups(tmp_path)
    assert len(groups) == 1
    names = {n for _p, _ln, n in groups[0]}
    assert names == {"test_one", "test_two"}


def test_same_shape_different_production_seam_is_not_blocked(tmp_path):
    """The challenger/structural-eval precedent: identical shape, different target
    module referenced inside the body -- a genuinely distinct production seam, not a
    duplicate."""
    (tmp_path / "test_a.py").write_text(
        "def test_write_report(tmp_path):\n"
        "    from module_a import runner\n"
        "    report = runner.run_study(tmp_path)\n"
        "    assert report\n",
        encoding="utf-8",
    )
    (tmp_path / "test_b.py").write_text(
        "def test_write_report(tmp_path):\n"
        "    from module_b import runner\n"
        "    report = runner.run_study(tmp_path)\n"
        "    assert report\n",
        encoding="utf-8",
    )
    assert _find_duplicate_test_groups(tmp_path) == []


def test_exemption_marker_excludes_a_real_duplicate(tmp_path):
    (tmp_path / "test_a.py").write_text(
        "def test_one():\n"
        "    # institutional-duplicate-ok: deliberate, see docstring\n"
        "    assert compute_thing(1, 2) == 3\n",
        encoding="utf-8",
    )
    (tmp_path / "test_b.py").write_text(
        "def test_two():\n"
        "    assert compute_thing(1, 2) == 3\n",
        encoding="utf-8",
    )
    # test_one carries the marker and is excluded from grouping entirely, so even
    # though test_two's body is identical, there is no PAIR left to flag.
    assert _find_duplicate_test_groups(tmp_path) == []


# ─────────────────────────────────────────────────────────────────────────────
# Lock 2 — independent repo scan
# ─────────────────────────────────────────────────────────────────────────────

def test_new_independent_rglob_walker_is_blocked(tmp_path):
    (tmp_path / "test_scan.py").write_text(
        "from pathlib import Path\n"
        "def test_something():\n"
        "    root = Path('.')\n"
        "    for p in root.rglob('*.py'):\n"
        "        pass\n",
        encoding="utf-8",
    )
    hits = _find_new_repo_scans(tmp_path)
    assert len(hits) == 1
    assert hits[0][0].name == "test_scan.py"


def test_canonical_shared_observation_consumer_is_not_blocked(tmp_path):
    """A file that already consumes `repo_index` is never flagged, even if it also
    happens to mention `.rglob(` in a comment or elsewhere -- it is a consumer of
    the shared observation, not an independent scan."""
    (tmp_path / "test_scan.py").write_text(
        "def test_something(repo_index):\n"
        "    for rel, text, tree in repo_index.items():\n"
        "        pass\n"
        "    # note: repo_index itself uses .rglob( internally, that's fine\n",
        encoding="utf-8",
    )
    assert _find_new_repo_scans(tmp_path) == []


def test_genuinely_specialized_scan_is_exempted(tmp_path):
    (tmp_path / "test_scan.py").write_text(
        "from pathlib import Path\n"
        "def test_something():\n"
        "    # institutional-scan-ok: scans a DIFFERENT root (fixtures/), not the repo\n"
        "    root = Path('fixtures')\n"
        "    for p in root.rglob('*.json'):\n"
        "        pass\n",
        encoding="utf-8",
    )
    assert _find_new_repo_scans(tmp_path) == []


def test_a_file_with_no_rglob_at_all_is_not_flagged(tmp_path):
    (tmp_path / "test_plain.py").write_text(
        "def test_something():\n"
        "    assert 1 == 1\n",
        encoding="utf-8",
    )
    assert _find_new_repo_scans(tmp_path) == []


# ─────────────────────────────────────────────────────────────────────────────
# Real-tree sanity: both ENFORCED-scoped checks currently PASS on the actual repo
# (the scan lock is ADVISORY -- known pre-existing debt, not asserted at zero here).
# ─────────────────────────────────────────────────────────────────────────────

def test_real_tree_has_zero_duplicate_tests():
    from tools.check_institutional_correctness import check_no_duplicate_tests
    violations = check_no_duplicate_tests()
    assert violations == [], "\n".join(str(v) for v in violations)
