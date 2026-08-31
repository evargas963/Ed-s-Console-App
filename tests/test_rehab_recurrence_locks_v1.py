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
    """Identical shape, different target module imported INSIDE the function body --
    already distinguishable by a plain AST diff (the import statement text itself
    differs), no resolution needed."""
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


def test_same_shape_different_module_level_import_target_is_resolved_not_blocked(tmp_path):
    """TEST_SYSTEM_REHAB_V2 (real precedent: test_challenger_eval_v1.py /
    test_structural_eval_v1.py): identical function body text, but `runner` is bound
    to a DIFFERENT module by a MODULE-LEVEL import in each file -- the function body
    alone is byte-identical AST, so this requires resolving the import binding, not
    just diffing the body. Previously needed a '# institutional-duplicate-ok:'
    marker; now correctly distinguished with no marker at all."""
    (tmp_path / "test_a.py").write_text(
        "from module_a import runner\n"
        "def test_write_report(tmp_path):\n"
        "    report = runner.run_study(tmp_path)\n"
        "    assert report\n",
        encoding="utf-8",
    )
    (tmp_path / "test_b.py").write_text(
        "from module_b import runner\n"
        "def test_write_report(tmp_path):\n"
        "    report = runner.run_study(tmp_path)\n"
        "    assert report\n",
        encoding="utf-8",
    )
    assert _find_duplicate_test_groups(tmp_path) == []


def test_same_module_level_import_target_with_identical_body_is_still_blocked(tmp_path):
    """The resolution logic must not become an accidental blanket pass -- if the
    module-level import ALSO resolves to the SAME target in both files, the
    duplicate is still caught."""
    (tmp_path / "test_a.py").write_text(
        "from module_a import runner\n"
        "def test_one():\n"
        "    report = runner.run_study()\n"
        "    assert report\n",
        encoding="utf-8",
    )
    (tmp_path / "test_b.py").write_text(
        "from module_a import runner\n"
        "def test_two():\n"
        "    report = runner.run_study()\n"
        "    assert report\n",
        encoding="utf-8",
    )
    groups = _find_duplicate_test_groups(tmp_path)
    assert len(groups) == 1


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


def test_os_walk_alternate_form_is_blocked(tmp_path):
    """G: alternate independent-scan forms must be caught too, not only .rglob."""
    (tmp_path / "test_walk.py").write_text(
        "import os\n"
        "def test_something():\n"
        "    for dirpath, dirs, files in os.walk('.'):\n"
        "        pass\n",
        encoding="utf-8",
    )
    hits = _find_new_repo_scans(tmp_path)
    assert len(hits) == 1
    assert hits[0][0].name == "test_walk.py"


def test_bare_from_os_import_walk_is_also_blocked(tmp_path):
    (tmp_path / "test_walk2.py").write_text(
        "from os import walk\n"
        "def test_something():\n"
        "    for dirpath, dirs, files in walk('.'):\n"
        "        pass\n",
        encoding="utf-8",
    )
    hits = _find_new_repo_scans(tmp_path)
    assert len(hits) == 1


def test_non_py_glob_pattern_is_never_flagged_no_marker_needed(tmp_path):
    """A scan for a non-.py artifact type (temp-dir cleanup, model files, etc.) is a
    DIFFERENT observation from repo_index (which only indexes .py files) -- it is
    excluded outright, not merely exempted, so no marker is required."""
    (tmp_path / "test_cleanup.py").write_text(
        "def test_something(tmp_path):\n"
        "    assert not list(tmp_path.rglob('*.json'))\n",
        encoding="utf-8",
    )
    assert _find_new_repo_scans(tmp_path) == []


def test_exemption_marker_is_scoped_to_its_own_function_not_the_whole_file(tmp_path):
    """G: a marker in ONE function must not silence a genuine independent .py-source
    scan in a SIBLING function in the same file -- the old file-wide bypass would
    have hidden exactly this."""
    (tmp_path / "test_scan.py").write_text(
        "from pathlib import Path\n"
        "def test_one():\n"
        "    # institutional-scan-ok: this one is genuinely justified\n"
        "    for p in Path('fixtures').rglob('*.py'):\n"
        "        pass\n"
        "def test_two():\n"
        "    for p in Path('.').rglob('*.py'):\n"
        "        pass\n",
        encoding="utf-8",
    )
    hits = _find_new_repo_scans(tmp_path)
    assert len(hits) == 1, "test_two's unmarked scan must still be caught"


def test_repo_index_consumer_can_still_be_caught_for_a_second_independent_scan(tmp_path):
    """G: consuming `repo_index` for one purpose must not blanket-exempt an
    ADDITIONAL independent .py-source scan in the same function -- the old
    file-wide 'repo_index appears somewhere' bypass would have hidden this."""
    (tmp_path / "test_mixed.py").write_text(
        "from pathlib import Path\n"
        "def test_something(repo_index):\n"
        "    for rel, text, tree in repo_index.items():\n"
        "        pass\n"
        "    for p in Path('.').rglob('*.py'):\n"
        "        pass\n",
        encoding="utf-8",
    )
    hits = _find_new_repo_scans(tmp_path)
    assert len(hits) == 1, "the second, independent .py scan must still be flagged"


def test_real_tree_has_zero_redundant_repo_scans():
    from tools.check_institutional_correctness import check_no_new_independent_repo_scan_in_tests
    violations = check_no_new_independent_repo_scan_in_tests()
    assert violations == [], "\n".join(str(v) for v in violations)


# ─────────────────────────────────────────────────────────────────────────────
# Real-tree sanity: both ENFORCED-scoped checks currently PASS on the actual repo
# (the scan lock is ADVISORY -- known pre-existing debt, not asserted at zero here).
# ─────────────────────────────────────────────────────────────────────────────

def test_real_tree_has_zero_duplicate_tests():
    from tools.check_institutional_correctness import check_no_duplicate_tests
    violations = check_no_duplicate_tests()
    assert violations == [], "\n".join(str(v) for v in violations)
