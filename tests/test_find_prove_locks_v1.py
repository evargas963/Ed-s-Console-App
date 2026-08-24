"""RC-210: Find&Prove substance + admission + continuum parity — BLOCK negative controls."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_significance_substance_blocks_bare_claim():
    from tools.find_prove_locks import significance_substance_violations

    bad = "The strategy Sharpe is 1.4 and statistically significant at p<0.05."
    assert significance_substance_violations(bad)
    good = (
        "Sharpe 1.4; n_trials: 12; multiple_testing_method: dsr; adjusted_p: 0.02."
    )
    assert significance_substance_violations(good) == []
    tagged = "Sharpe might work [UNVERIFIED] pending trial ledger."
    assert significance_substance_violations(tagged) == []


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
    lied. Both hook files are CODEOWNERS-owned, so guard-wiring parity is a merge-review
    property. This pin keeps the retirement executed: a resurrection must delete it."""
    import tools.check_institutional_correctness as cic
    import tools.find_prove_locks as fpl

    assert not hasattr(cic, "check_claude_cursor_guard_parity")
    assert not hasattr(fpl, "claude_cursor_parity_violations")
    assert "claude_cursor_guard_parity" not in {name for name, _fn, _enf in cic.CHECKS}
    manifest = (REPO / "governance" / "retired_checks.md").read_text(encoding="utf-8")
    assert "claude_cursor_guard_parity" in manifest


def test_find_prove_significance_substance_screams_on_staged_bad_report(
    tmp_path, monkeypatch,
):
    """Full commit path: staged report with bare significance claim must BLOCK."""
    import tools.check_institutional_correctness as C

    reports = tmp_path / "reports"
    reports.mkdir()
    target = reports / "zz_fp_significance_bad.md"
    target.write_text(
        "The strategy Sharpe is 1.4 and statistically significant at p<0.05.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(C, "REPO", tmp_path)

    def fake_git(args: list[str]) -> list[str] | None:
        if args[:3] == ["diff", "--cached", "--name-only"]:
            return ["reports/zz_fp_significance_bad.md"]
        return []

    monkeypatch.setattr(C, "_git_output_lines", fake_git)
    bad = C.check_find_prove_significance_substance()
    assert bad, "staged significance claim without trial ledger was not blocked"
    assert any("n_trials" in v.msg for v in bad)

    target.write_text(
        "Sharpe 1.4; n_trials: 12; multiple_testing_method: dsr; adjusted_p: 0.02.\n",
        encoding="utf-8",
    )
    assert C.check_find_prove_significance_substance() == []


def test_collect_datasheet_blocks_missing():
    from tools.find_prove_locks import collect_datasheet_violations

    assert collect_datasheet_violations("new_table_x", None)
    good = "motivation: x\ncomposition: y\ncollection: z\nrecommended_uses: w\n"
    assert collect_datasheet_violations("new_table_x", good) == []


def test_collect_datasheet_staged_live_clean():
    from tools.check_institutional_correctness import check_collect_datasheet_staged

    assert check_collect_datasheet_staged() == []


# RC-470: test_honesty_guard_still_green left with check_honesty_guard_wired
# (retired - governance/retired_checks.md); the parity tests above still assert
# honesty_guard.py is wired in both agents' hook files.
