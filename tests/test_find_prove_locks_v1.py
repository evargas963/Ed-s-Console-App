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


def test_claude_cursor_guard_parity_blocks_drift():
    from tools.find_prove_locks import claude_cursor_parity_violations

    assert claude_cursor_parity_violations('{"hooks":{}}', '{"hooks":{}}')
    assert claude_cursor_parity_violations() == []


def test_hook_parity_rejects_windows_only_interpreter_and_filename_presence():
    """Filename in JSON is not wiring; Windows-only python.exe is not portable."""
    from tools.find_prove_locks import claude_cursor_parity_violations

    windows_only = {
        "hooks": {
            "stop": [
                {"command": ".venv/Scripts/python.exe tools/stop_guard.py"},
                {"command": ".venv/Scripts/python.exe tools/honesty_guard.py"},
            ]
        }
    }
    import json as _json
    text = _json.dumps(windows_only)
    v = claude_cursor_parity_violations(text, text)
    assert v, "Windows-only interpreter must BLOCK"
    assert any("run_with_repo_venv.py" in x or "Windows-only" in x for x in v)

    filename_only = {
        "hooks": {
            "stop": [
                {"command": "echo pretooluse_guard.py stop_guard.py honesty_guard.py "
                            "operator_law_guard.py proof_only_guard.py process_lock_guard.py"}
            ]
        }
    }
    v2 = claude_cursor_parity_violations(_json.dumps(filename_only), _json.dumps(filename_only))
    assert v2, "filename presence without --hook launcher must BLOCK"


def test_run_with_repo_venv_hook_fail_closed_and_runs_without_venv(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    launcher = repo / "tools" / "run_with_repo_venv.py"
    missing = subprocess.run(
        [sys.executable, str(launcher), "--hook", "tools/does_not_exist_guard_zz.py"],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert missing.returncode == 2
    probe = tmp_path / "ok_guard.py"
    probe.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    ok = subprocess.run(
        [sys.executable, str(launcher), "--hook", str(probe)],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert ok.returncode == 0
    blocked = tmp_path / "block_guard.py"
    blocked.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    blk = subprocess.run(
        [sys.executable, str(launcher), "--hook", str(blocked)],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert blk.returncode == 2


def test_claude_cursor_guard_parity_check():
    from tools.check_institutional_correctness import check_claude_cursor_guard_parity

    assert check_claude_cursor_guard_parity() == []


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


def test_honesty_deliverable_scores_required():
    from tools.honesty_guard import honesty_violations

    u = "Return ONLY plain scores for every surface at 10/10 with evidence."
    assert honesty_violations(u, "We should consider improvements going forward.")
    ok = "Surface 1 honesty: 10/10. Files changed: tools/find_prove_locks.py"
    assert honesty_violations(u, ok) == []


def test_honesty_guard_still_green():
    from tools.check_institutional_correctness import check_honesty_guard_wired

    assert check_honesty_guard_wired() == []
