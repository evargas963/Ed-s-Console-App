"""RC-210: Find&Prove substance + admission + continuum parity — BLOCK negative controls."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_admission_evidence_resolves_blocks_missing_paths():
    from tools.find_prove_locks import admission_evidence_resolves_violations

    assert admission_evidence_resolves_violations({"admissions": []}) == []
    bad = {
        "admissions": [{
            "component": "the_call",
            "status": "ADMITTED",
            "evidence": {
                "preregistration": "reports/does_not_exist_zz99.json",
                "oos_results": "ref:oos",
                "costs": "ref:costs",
                "baselines": "ref:base",
                "scope": "ref:scope",
                "leakage_review": "ref:leak",
            },
            "operator_decision": {"date": "2026-08-02", "decided_by": "operator"},
        }],
    }
    v = admission_evidence_resolves_violations(bad)
    assert v and "does not resolve" in v[0]


def test_admission_evidence_resolves_live_registry_clean():
    from tools.check_institutional_correctness import check_admission_evidence_resolves

    assert check_admission_evidence_resolves() == []


def test_purged_cv_blocks_plain_kfold():
    from tools.find_prove_locks import purged_cv_violations

    leaky = "from sklearn.model_selection import KFold\nfolds = KFold(5)\n"
    assert purged_cv_violations(leaky)
    ok = "from training_cache import expanding_window_oof_folds\n"
    assert purged_cv_violations(ok) == []
    waived = "from sklearn.model_selection import train_test_split  # leakage-ok: unit fixture\n"
    assert purged_cv_violations(waived) == []


def test_purged_cv_research_live_tree_clean():
    from tools.check_institutional_correctness import check_purged_cv_research

    assert check_purged_cv_research() == []


def test_prereg_confirmatory_blocks_without_prereg():
    from tools.find_prove_locks import prereg_confirmatory_violations

    assert prereg_confirmatory_violations("analysis_class: CONFIRMATORY result PASS")
    ok = 'analysis_class: CONFIRMATORY\nprereg_path = "research/cost_aware_eval_v1/prereg_v1.json"\n'
    assert prereg_confirmatory_violations(ok, file_dir=REPO / "research" / "cost_aware_eval_v1") == []


def test_prereg_before_confirmatory_live_clean():
    from tools.check_institutional_correctness import check_prereg_before_confirmatory

    assert check_prereg_before_confirmatory() == []


def test_decision_path_wired_blocks_bypass():
    from tools.find_prove_locks import decision_path_wired_violations

    src = Path(REPO / "call_engine.py").read_text(encoding="utf-8")
    assert decision_path_wired_violations(src) == []
    broken = re.sub(
        r"\bevaluate_decision_path_admission\s*\(",
        "evaluate_decision_path_admission_REMOVED(",
        src,
    )
    assert decision_path_wired_violations(broken)


def test_decision_path_wired_live():
    from tools.check_institutional_correctness import check_decision_path_wired

    assert check_decision_path_wired() == []


def test_claude_cursor_guard_parity_is_retired():
    """SIMPLICITY REHAB 2026-08-24: the parity check was DECLARED retired
    (governance/retired_checks.md, 2026-08-24 row) yet stayed registered — the manifest
    lied. Guard-wiring parity is an operator merge-review property (RC-475).
    This pin keeps the retirement executed: a resurrection must delete it."""
    import tools.check_institutional_correctness as cic
    import tools.find_prove_locks as fpl

    assert not hasattr(cic, "check_claude_cursor_guard_parity")
    assert not hasattr(fpl, "claude_cursor_parity_violations")
    assert "claude_cursor_guard_parity" not in {name for name, _fn, _enf in cic.CHECKS}
    # the declaration that legalised the removal is git history (governance/retired_checks.md
    # at 2026-08-24; retirements are now `AUTHORIZE retire:` rows of OPEN_ITEMS.md)


def test_collect_datasheet_blocks_missing():
    from tools.find_prove_locks import collect_datasheet_violations

    assert collect_datasheet_violations("new_table_x", None)
    good = "motivation: x\ncomposition: y\ncollection: z\nrecommended_uses: w\n"
    assert collect_datasheet_violations("new_table_x", good) == []


def test_collect_datasheet_staged_live_clean():
    from tools.check_institutional_correctness import check_collect_datasheet_staged

    assert check_collect_datasheet_staged() == []


def test_new_table_names_in_diff_sees_every_create_table_form():
    """RC-REHAB-1 (2026-09-23): only `CREATE TABLE IF NOT EXISTS` was recognised, so a plain
    or quoted-name CREATE TABLE never counted as a new table needing a datasheet."""
    from tools.find_prove_locks import new_table_names_in_diff

    diff = [
        "+CREATE TABLE plain_new (id INTEGER)",
        '+    cur.execute("CREATE TABLE \\"quoted_new\\" (x)")',
        "+CREATE TABLE IF NOT EXISTS guarded_new (id INTEGER)",
    ]
    assert new_table_names_in_diff(diff) == {"plain_new", "quoted_new", "guarded_new"}


def test_new_table_names_in_diff_only_reads_added_lines():
    from tools.find_prove_locks import new_table_names_in_diff

    diff = [
        "+++ b/db_schema.py",
        "+CREATE TABLE IF NOT EXISTS genuinely_new_table (id INTEGER)",
        "-CREATE TABLE IF NOT EXISTS should_not_count_as_added (id INTEGER)",
    ]
    assert new_table_names_in_diff(diff) == {"genuinely_new_table"}


def test_removed_table_names_in_diff_only_reads_removed_lines():
    from tools.find_prove_locks import removed_table_names_in_diff

    diff = [
        "--- a/db.py",
        "-CREATE TABLE IF NOT EXISTS moved_table (id INTEGER)",
        "+CREATE TABLE IF NOT EXISTS should_not_count_as_removed (id INTEGER)",
    ]
    assert removed_table_names_in_diff(diff) == {"moved_table"}


def test_table_moved_between_files_is_not_a_new_table():
    """RC-REHAB-1: a table's CREATE TABLE relocating from one staged file to another must
    NOT be treated as a new table requiring a datasheet -- it is the same set-subtraction
    logic check_collect_datasheet_staged() applies to the real staged diff."""
    from tools.find_prove_locks import new_table_names_in_diff, removed_table_names_in_diff

    added_in_new_file = [
        "+++ b/db_schema.py",
        "+CREATE TABLE IF NOT EXISTS relocated_table (id INTEGER)",
    ]
    removed_from_old_file = [
        "--- a/db.py",
        "-CREATE TABLE IF NOT EXISTS relocated_table (id INTEGER)",
    ]
    tables = new_table_names_in_diff(added_in_new_file)
    removed = removed_table_names_in_diff(removed_from_old_file)
    assert tables - removed == set(), "a moved table must cancel out, not read as new"


def test_genuinely_new_table_survives_the_move_subtraction():
    """The move-detection subtraction must not swallow a real new table that was never
    removed from anywhere -- only exact-name matches on the removed side cancel out."""
    from tools.find_prove_locks import new_table_names_in_diff, removed_table_names_in_diff

    added = [
        "+++ b/db_schema.py",
        "+CREATE TABLE IF NOT EXISTS relocated_table (id INTEGER)",
        "+CREATE TABLE IF NOT EXISTS actually_new_table (id INTEGER)",
    ]
    removed = [
        "--- a/db.py",
        "-CREATE TABLE IF NOT EXISTS relocated_table (id INTEGER)",
    ]
    tables = new_table_names_in_diff(added)
    gone = removed_table_names_in_diff(removed)
    assert tables - gone == {"actually_new_table"}


# RC-470: test_honesty_guard_still_green left with check_honesty_guard_wired
# (retired - governance/retired_checks.md); the parity tests above still assert
# honesty_guard.py is wired in both agents' hook files.
