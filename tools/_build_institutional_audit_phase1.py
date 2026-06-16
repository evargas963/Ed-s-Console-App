"""Build Institutional Audit Phase 1 artifacts — reality-validated, not matrix-inherited.

Run: python tools/_build_institutional_audit_phase1.py

Outputs:
  governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json
  governance/artifacts/GOVERNANCE_ATTACK_TREE.json
  governance/artifacts/RUNTIME_ENFORCEMENT_MATRIX.json
  governance/GOVERNANCE_SELF_PROTECTION_AUDIT.md
  governance/COVERAGE_JUSTIFICATION.md

Then run Phase 2: python tools/_build_institutional_audit_phase2.py
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ART = REPO / "governance" / "artifacts"
TODAY = date.today().isoformat()

# Maturity: L1 Documented | L2 Checked | L3 Enforced (commit block) | L4 Tamper-resistant | L5 Institutionally governed
# coverage_percent: estimated % of full invariant surface the wired checker+tests actually cover.


def _bypass(
    vector: str,
    difficulty: str,
    audit_event: bool,
    classification: str,
) -> dict:
    return {
        "vector": vector,
        "difficulty": difficulty,
        "audit_event_generated": audit_event,
        "classification": classification,
    }


def _surface(build: bool, deploy: bool, runtime: bool, postmortem: bool) -> dict:
    return {
        "build_time": build,
        "deploy_time": deploy,
        "runtime": runtime,
        "postmortem": postmortem,
    }


def _row(
    control_id: str,
    title: str,
    matrix_claimed_status: str,
    validated_maturity: str,
    matrix_accurate: bool,
    coverage_percent: int,
    checker: str | None,
    checker_location: str | None,
    test: str | None,
    bypass_test: str | None,
    enforcement_path: list[str],
    bypass_path: list[str],
    bypass_vectors: list[dict],
    audit_artifact: str | None,
    enforcement_surface: dict,
    adversarial_tests: list[str],
    uncovered: list[str],
    evidence: list[str],
    severity_rationale: str,
) -> dict:
    return {
        "control_id": control_id,
        "title": title,
        "matrix_claimed_status": matrix_claimed_status,
        "validated_maturity": validated_maturity,
        "matrix_status_accurate": matrix_accurate,
        "coverage_percent": coverage_percent,
        "checker_name": checker,
        "checker_location": checker_location,
        "test_name": test,
        "bypass_detection_test": bypass_test,
        "enforcement_code_paths": enforcement_path,
        "bypass_code_paths": bypass_path,
        "bypass_vectors": bypass_vectors,
        "audit_artifact": audit_artifact,
        "enforcement_surface": enforcement_surface,
        "adversarial_test_suite": adversarial_tests,
        "uncovered_invariant_portions": uncovered,
        "last_validation_date": TODAY,
        "validation_method": "Read end-to-end + test inventory + checker source review (Institutional Audit Phase 1)",
        "evidence": evidence,
        "severity_rationale": severity_rationale,
    }


def build_validation_register() -> dict:
    common_bypass_no_verify = _bypass(
        "git commit --no-verify",
        "trivial",
        False,
        "tolerated_dev_unacceptable_institutional",
    )
    common_bypass_env = _bypass(
        "ED_* environment variable change + server restart",
        "easy",
        False,
        "intentional_dev_unacceptable_without_config_manifest",
    )

    rows: list[dict] = []

    # ── Platform Severity-1 ─────────────────────────────────────────────
    rows.append(
        _row(
            "I-31",
            "Decision reconstructability",
            "NOT_IMPLEMENTED",
            "L0",
            True,
            0,
            None,
            None,
            None,
            None,
            [],
            [
                "live_decision_bundle.py:stamp_decision_bundle — in-process counter only",
                "calibration/writer.py:append_calibration_decision — env-gated ED_CALIBRATION_LOG",
            ],
            [
                common_bypass_env,
                _bypass("server restart clears decision_generation_id", "trivial", False, "unacceptable"),
                _bypass("no single-query retrieval API", "n/a", False, "unacceptable"),
            ],
            None,
            _surface(False, False, False, False),
            [],
            [
                "immutable Decision ID",
                "one-query third-party reconstruction <60s",
                "artifact hash linkage",
                "override state in bundle",
            ],
            [
                "live_decision_bundle.py:54-87 — monotonic int, not persisted",
                "calibration/schema.py:21-84 — richest store; keyed (ticker, decision_ts_utc)",
                "No GET /api/decision/{id} retrieval path",
            ],
            "Foundational auditability prerequisite — all other Sev-1 controls depend on reconstructable decisions.",
        )
    )
    rows.append(
        _row(
            "I-28",
            "Market data integrity",
            "PARTIALLY_ENFORCED",
            "L2",
            False,
            18,
            None,
            None,
            "tests/test_batch2_analytics_bg_fail_counter.py (staleness contract only)",
            None,
            [
                "features/canonical_contract.py — price.spot > 0 at MVP boundary",
                "features/monte_carlo_stack_input.py:47-55 — MC blocked if spot missing/<=0",
                "verification/daily_health.py — STALE_BAR_DATA_SEC structural report",
            ],
            [
                "Wrong-but-valid prices (SPY 0.01, 50000) pass float>0 validation",
                "No trade-path circuit breaker in signals.py/compute_signals",
            ],
            [
                common_bypass_env,
                _bypass("skip daily_health run", "easy", False, "tolerated"),
                _bypass("inject plausible wrong spot via Schwab wire", "medium", False, "unacceptable"),
            ],
            "verification/daily_health.py JSON report (manual)",
            _surface(True, False, True, False),
            [],
            [
                "wrong data / outlier quarantine",
                "cross-source disagreement",
                "corporate actions",
                "feed degradation circuit breaker",
                "duplicate tick detection at ingest",
                "future timestamp rejection on trade path",
            ],
            [
                "features/canonical_contract.py:198-201 — invalid is spot<=0 only",
                "verification/daily_health.py:9-11 — staleness not wrongness",
                "No adversarial price injection tests in tests/",
            ],
            "Bad market data can corrupt live decisions — direct trade-impact path.",
        )
    )
    rows.append(
        _row(
            "I-29",
            "Risk governance",
            "NOT_IMPLEMENTED",
            "L1",
            True,
            5,
            None,
            None,
            None,
            None,
            [
                "call_engine.py:1363-1400 — _validate_trade Layer 3 risk gates (code branch)",
            ],
            [
                "call_engine.py:1269+ — models/fusion run before risk validation",
                "signals.py — no immutable risk policy object",
            ],
            [
                _bypass("skip _validate_trade path on alternate routes", "unknown", False, "unacceptable"),
                common_bypass_env,
            ],
            None,
            _surface(False, False, True, False),
            [],
            [
                "signed risk policy objects",
                "proof model cannot override risk on all trade-impacting routes",
                "risk policy versioning",
            ],
            [
                "governance/V3_CONFORMANCE_AUDIT.md — I-13 DOES_NOT_CONFORM_NEW_GAP",
                "call_engine.py:1405-1409 — trade_valid requires risk_valid but not proven universal",
            ],
            "Risk must supersede model — institutional ordering requirement.",
        )
    )
    rows.append(
        _row(
            "I-24",
            "Four-eyes review",
            "NOT_IMPLEMENTED",
            "L0",
            True,
            0,
            None,
            None,
            None,
            None,
            [],
            [".github/CODEOWNERS — review request only if branch protection enabled"],
            [
                _bypass("single actor commit + merge", "trivial", False, "unacceptable"),
                common_bypass_no_verify,
            ],
            None,
            _surface(False, False, False, False),
            [],
            ["required independent approver on promotion/risk/schema/override changes"],
            [".github/CODEOWNERS:36-41 — AGENTS/governance owned but protection not in-repo"],
            "Material control changes require independent review.",
        )
    )
    rows.append(
        _row(
            "I-25",
            "Release governance",
            "NOT_IMPLEMENTED",
            "L0",
            True,
            0,
            None,
            None,
            None,
            None,
            ["GET /api/build git_sha — runtime tip indicator only"],
            ["undefined release artifact — commit != release"],
            [_bypass("deploy unlabeled git tip", "easy", False, "unacceptable")],
            None,
            _surface(True, False, True, False),
            [],
            ["versioned release manifest", "artifact hash bundle", "approval record", "rollback pointer"],
            ["PROMOTION_POLICY.md:1-4 marked historical not authoritative"],
            "Controlled change identity — precedes DR.",
        )
    )
    rows.append(
        _row(
            "I-22",
            "Configuration governance",
            "NOT_IMPLEMENTED",
            "L1",
            True,
            8,
            None,
            None,
            "tests/test_governance_consolidation.py::test_config_py_has_no_hardcoded_api_secrets",
            None,
            ["docs/host/ENVIRONMENT_VARIABLES.md — documentation only"],
            ["any ED_* change at runtime without commit"],
            [common_bypass_env],
            None,
            _surface(False, False, True, False),
            [],
            ["config manifest pinned to release", "drift detection", "immutable config audit"],
            ["docs/host/ENVIRONMENT_VARIABLES.md — 39+ ED_* vars, no manifest lock"],
            "Shadow release channel via environment.",
        )
    )
    rows.append(
        _row(
            "I-30",
            "Override accountability",
            "NOT_IMPLEMENTED",
            "L1",
            True,
            10,
            None,
            None,
            None,
            None,
            ["signals.py:184-185 — _pred_override_allowed env gate"],
            [
                "server.py POST /api/prediction/override when ED_CONSOLE_ALLOW_PRED_OVERRIDE=1",
                "governance/TRADE_IMPACTING_ROUTE_INVENTORY.md:R-017",
            ],
            [
                common_bypass_env,
                _bypass("override in memory without append-only audit", "easy", False, "unacceptable"),
            ],
            None,
            _surface(False, False, True, False),
            [],
            ["append-only override event linked to Decision ID"],
            ["signals.py:184-185", "docs/host/ENVIRONMENT_VARIABLES.md:31"],
            "Human override must be reconstructable.",
        )
    )
    rows.append(
        _row(
            "I-21",
            "Data lineage integrity",
            "NOT_IMPLEMENTED",
            "L1",
            True,
            12,
            None,
            None,
            "tests/test_arch_competition_eval_runner.py (eval row alignment partial)",
            None,
            ["arch_competition/lineage.py — partial eval alignment"],
            ["no end-to-end lineage ID on production decision"],
            [common_bypass_no_verify],
            None,
            _surface(True, False, False, False),
            [],
            ["immutable lineage graph", "feature contract version on every decision"],
            ["Depends on I-31 — no decision key to attach lineage"],
            "Cannot audit without lineage chain.",
        )
    )
    rows.append(
        _row(
            "I-26",
            "Disaster recovery objectives",
            "NOT_IMPLEMENTED",
            "L0",
            True,
            0,
            None,
            None,
            None,
            None,
            [],
            [],
            [_bypass("no RTO/RPO defined", "n/a", False, "unacceptable")],
            None,
            _surface(False, False, False, False),
            [],
            ["RTO/RPO on release artifact", "game-day proof"],
            ["No DR objective doc with measurable targets in enforcement path"],
            "Requires I-25 release definition first.",
        )
    )

    # ── V3 core Severity-1 ──────────────────────────────────────────────
    rows.append(
        _row(
            "I-01",
            "No silent substitution / undeclared degradation",
            "PARTIALLY_ENFORCED",
            "L3",
            False,
            35,
            "check_fusion_only_card_contract",
            "tools/check_fix_everything_we_touch.py:2638",
            "tests/test_check_fix_everything_we_touch.py::test_fusion_only_card_contract_passes_on_current_repo",
            None,
            [
                "tools/check_fix_everything_we_touch.py:2638 — marker/banned-pattern scan",
                "prediction_engine.py — runtime withhold paths",
                "bayesian_fusion.py — default blend 0.0",
            ],
            ["git commit --no-verify", "runtime ED_* blend env if reintroduced"],
            [common_bypass_no_verify],
            "pre-commit stdout",
            _surface(True, False, True, False),
            [
                "tests/test_prediction_engine_chunk1_fail_closed.py::test_overlay_withholds_product_triplets_when_fusion_missing",
            ],
            [
                "all silent-default patterns repo-wide",
                "all degradation paths outside fusion cards",
                "runtime env override of blend weights",
            ],
            [
                "Checker verifies string markers exist — not behavioral proof on live server",
                "Meta-test only asserts checker==[] on current repo",
            ],
            "Silent degradation on live cards corrupts operator decisions.",
        )
    )
    rows.append(
        _row(
            "I-02",
            "Single promotion authority",
            "PARTIALLY_ENFORCED",
            "L3",
            True,
            55,
            None,
            "arch_competition/promotion_execution.py",
            "tests/test_arch_competition_auto_promote.py",
            None,
            [
                "arch_competition/promotion_execution.py::execute_promotion_if_eligible",
                "arch_competition/promotion_execution.py::assert_active_writes_use_governed_executor",
            ],
            [
                "manual copy into models/active/",
                "ED_DISABLE_AUTO_PROMOTE=1",
            ],
            [
                common_bypass_no_verify,
                _bypass("manual filesystem copy to models/active/", "easy", False, "unacceptable"),
                _bypass("ED_DISABLE_AUTO_PROMOTE=1", "easy", False, "intentional"),
            ],
            "models/training_report.jsonl",
            _surface(True, True, True, False),
            [
                "tests/test_arch_competition_auto_promote.py::test_reconcile_write_outside_governed_scope_raises",
            ],
            ["manual promotion without executor", "four-eyes on promotion"],
            ["tests/test_arch_competition_auto_promote.py — strong unit tests; no bypass detection test"],
            "Wrong model in production is high blast-radius.",
        )
    )
    rows.append(
        _row(
            "I-05",
            "Train-serve feature identity",
            "PARTIALLY_ENFORCED",
            "L2",
            True,
            40,
            "check_encoder_cone_mechanical_lock",
            "tools/check_fix_everything_we_touch.py:3237",
            "tests/test_ml_feature_schema_parity.py",
            None,
            [
                "tools/check_encoder_cone_tests.py — encoder cone pytest on staged paths",
                "feature_contracts.py registries",
            ],
            ["train with different feature set than serve if artifacts manually swapped"],
            [common_bypass_no_verify],
            "encoder cone pytest output",
            _surface(True, False, True, False),
            ["tests/test_ml_feature_schema_parity.py — schema parity"],
            ["live artifact swap without re-train", "wire row drift at runtime"],
            ["check_encoder_cone_mechanical_lock checks tool exists + AGENTS markers"],
            "Feature skew breaks model validity silently.",
        )
    )
    rows.append(
        _row(
            "I-07",
            "No orphan paths",
            "PARTIALLY_ENFORCED",
            "L3",
            True,
            45,
            "check_storage_writer_has_consumer",
            "tools/check_fix_everything_we_touch.py",
            "tests/test_check_fix_everything_we_touch.py",
            None,
            [
                "tools/check_fix_everything_we_touch.py — INSERT without consumer blocks commit",
                "tools/audit_persistence_consumers.py — persistence map",
            ],
            ["writer added outside db.py pattern", "REAL-GATE tracked dormancy"],
            [common_bypass_no_verify],
            "governance/artifacts/persistence_consumer_map.json",
            _surface(True, False, False, False),
            [],
            ["orphan API endpoints", "orphan model paths", "orphan env flags"],
            ["Lock is pre-commit on db.py INSERT pattern only"],
            "Dormant persistence misleads operators.",
        )
    )
    rows.append(
        _row(
            "I-15",
            "Tuple health before trade impact",
            "PARTIALLY_ENFORCED",
            "L2",
            True,
            30,
            "check_institutional_contract",
            "tools/check_fix_everything_we_touch.py",
            "tests/test_issue18_ui_contract.py; tools/live_diag_compare.py",
            None,
            [
                "tools/check_institutional_contract — UI/API contract markers",
                "tools/live_diag_compare.py — manual runtime compare",
            ],
            ["deploy without running live_diag", "stale server process"],
            [common_bypass_no_verify, _bypass("skip live_diag before claims", "easy", False, "tolerated")],
            "live_diag_compare output (manual)",
            _surface(True, False, True, False),
            ["tests/test_issue18_ui_contract.py"],
            ["continuous runtime tuple health monitor", "automatic block on divergence"],
            ["Checker is static marker scan; live_diag is manual operator tool"],
            "UI/API divergence misleads trading decisions.",
        )
    )
    rows.append(
        _row(
            "I-17",
            "Deterministic inference",
            "PARTIALLY_ENFORCED",
            "L2",
            True,
            25,
            None,
            None,
            "tests/test_ml_predict_fail_closed.py",
            None,
            ["ml_predict.py fail-closed triplet helpers"],
            ["nondeterministic GPU/threading at runtime not gated"],
            [common_bypass_no_verify],
            None,
            _surface(True, False, True, False),
            ["tests/test_ml_predict_fail_closed.py"],
            ["full-stack deterministic replay proof", "MC stochastic seed governance"],
            [],
            "Nondeterministic live output breaks audit replay.",
        )
    )
    rows.append(
        _row(
            "I-19",
            "Clock synchronization health",
            "PARTIALLY_ENFORCED",
            "L2",
            True,
            20,
            "check_institutional_contract",
            "tools/check_fix_everything_we_touch.py",
            "tests/test_batch2_analytics_bg_fail_counter.py",
            None,
            ["time_et.py — ET clock policy", "tests for analytics stale semantics"],
            ["host clock drift at runtime"],
            [common_bypass_no_verify],
            None,
            _surface(True, False, True, False),
            [],
            ["NTP health gate", "future timestamp rejection on trade path"],
            [],
            "Clock skew breaks causal ordering.",
        )
    )
    rows.append(
        _row(
            "I-20",
            "Dependency pinning in serving path",
            "PARTIALLY_ENFORCED",
            "L1",
            True,
            15,
            None,
            None,
            None,
            None,
            ["requirements.txt"],
            ["pip install unpinned package on host"],
            [_bypass("host venv drift", "easy", False, "unacceptable")],
            None,
            _surface(True, True, True, False),
            [],
            ["lockfile hash in release manifest", "serving path import audit"],
            [],
            "Dependency drift changes inference behavior.",
        )
    )

    # ── Product law Severity-1 (matrix ENFORCED → validated L3) ───────────
    pl_specs = [
        (
            "PL-FUSION-CARDS",
            "Fusion-only horizon cards",
            "check_fusion_only_card_contract",
            "tools/check_fix_everything_we_touch.py:2638",
            "tests/test_check_fix_everything_we_touch.py::test_fusion_only_card_contract_passes_on_current_repo",
            28,
            ["Marker scan only — see I-01"],
        ),
        (
            "PL-FULL-STACK",
            "Seven-model full stack",
            "check_full_stack_models_contract",
            "tools/check_fix_everything_we_touch.py",
            "tests/test_ml_feature_schema_parity.py::test_full_stack_models_contract",
            35,
            ["Checks vocabulary/markers — not runtime 7-layer availability"],
        ),
        (
            "PL-ZERO-BIAS",
            "ZERO-BIAS ablation placement",
            "check_zero_bias_ablation_contract",
            "tools/check_fix_everything_we_touch.py",
            "tests/test_check_fix_everything_we_touch.py::test_zero_bias_ablation_contract",
            50,
            ["Strong static bias detector; runtime ablation env can bypass spirit"],
        ),
        (
            "PL-ABLATION-GRID",
            "7x4 ablation grid",
            "check_ablation_seven_model_four_horizon_grid",
            "tools/check_fix_everything_we_touch.py",
            "tests/test_check_fix_everything_we_touch.py::test_ablation_grid_requires_all_seven_models_and_four_horizons",
            45,
            ["Grid contract in code/docs; scored run coverage separate"],
        ),
        (
            "PL-PROMOTION",
            "Single promotion authority",
            None,
            "arch_competition/promotion_execution.py",
            "tests/test_arch_competition_auto_promote.py",
            55,
            ["Same as I-02"],
        ),
        (
            "PL-TRAINING-ROSTER",
            "Training anchor roster",
            "check_training_anchor_roster_contract",
            "tools/check_fix_everything_we_touch.py",
            "tests/test_scheduler_user_tickers_return_type.py",
            60,
            ["ED_ML_SCHEDULER_TRAINING_EXPAND=1 bypasses anchor-only default"],
        ),
        (
            "PL-SCHWAB-CSV",
            "Schwab CSV-first new sites",
            "external:tools/check_schwab_csv_first.py",
            "tools/check_schwab_csv_first.py",
            "tests/test_check_schwab_csv_first.py",
            40,
            ["CI diff-emission on PR; local --no-verify bypass"],
        ),
        (
            "PL-UPFRONT-GATE",
            "Tier 0 upfront mechanical gate",
            "check_upfront_mechanical_gate_stamp",
            "tools/check_fix_everything_we_touch.py:3408",
            "tests/test_governance_consolidation.py::test_upfront_mechanical_gate_stamp",
            55,
            ["Stamp skipped via --no-verify; tests stamp mechanics not full static run"],
        ),
        (
            "PL-SIGNOFF",
            "Institutional sign-off ladder",
            "check_institutional_signoff_contract",
            "tools/check_fix_everything_we_touch.py:3497",
            "tests/test_governance_consolidation.py::test_institutional_signoff_contract",
            40,
            ["Prose/docs wiring check; chat not scanned"],
        ),
        (
            "PL-NO-DEFERRAL",
            "No deferral without REAL-GATE",
            "external:tools/check_no_deferral_language.py",
            "tools/check_no_deferral_language.py",
            "tests/test_check_no_deferral_language.py",
            50,
            ["Regex surface scan; omission not caught"],
        ),
        (
            "PL-STORAGE-CONSUMER",
            "Storage needs consumer",
            "check_storage_writer_has_consumer",
            "tools/check_fix_everything_we_touch.py",
            "tests/test_check_fix_everything_we_touch.py",
            55,
            ["Same as I-07"],
        ),
        (
            "PL-REGISTRY",
            "Mandatory enforcement registry",
            "check_mandatory_enforcement_registry",
            "tools/check_fix_everything_we_touch.py",
            "tests/test_check_fix_everything_we_touch.py::test_mandatory_enforcement_registry_passes_on_current_repo",
            35,
            ["Registry checks lock existence — not lock correctness vs invariant"],
        ),
    ]
    for pid, title, chk, loc, tst, cov, notes in pl_specs:
        rows.append(
            _row(
                pid,
                title,
                "ENFORCED",
                "L3",
                False,
                cov,
                chk,
                loc,
                tst,
                None,
                [f"{loc} — pre-commit static lock"],
                ["git commit --no-verify", "runtime bypass outside checker scope"],
                [common_bypass_no_verify],
                "pre-commit stdout + CI hardening.yml",
                _surface(True, False, False, False),
                [],
                ["runtime enforcement", "bypass detection tests", "tamper-resistant governance"],
                notes,
                "Product law — high impact if violated in production.",
            )
        )

    inaccurate = sum(1 for r in rows if not r["matrix_status_accurate"])
    overstated = sum(
        1
        for r in rows
        if r["matrix_claimed_status"] == "ENFORCED" and r["validated_maturity"] != "L4"
    )
    return {
        "schema_version": 1,
        "artifact": "governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json",
        "supersedes_matrix_maturity_claims": True,
        "methodology": (
            "Institutional Audit Phase 1 — matrix is inventory input; validated_maturity and "
            "coverage_percent come from code-path review, checker source analysis, and test inventory. "
            "Meta-tests that only assert checker==[] on current repo do NOT raise maturity above L3."
        ),
        "maturity_vocabulary": {
            "L0": "Not built",
            "L1": "Documented / named gap",
            "L2": "Checker or test exists; partial coverage; bypass trivial",
            "L3": "Commit/CI blocked on happy path",
            "L4": "Bypass requires privileged action + audit event",
            "L5": "Workflow approval + immutable audit + reconstructable",
        },
        "validation_summary": {
            "severity_1_controls": len(rows),
            "matrix_status_inaccurate_count": inaccurate,
            "matrix_enforced_overstated_count": overstated,
            "controls_at_L3_or_below": sum(1 for r in rows if r["validated_maturity"] in ("L0", "L1", "L2", "L3")),
            "controls_with_adversarial_tests": sum(1 for r in rows if r["adversarial_test_suite"]),
            "controls_with_bypass_detection_test": sum(
                1 for r in rows if r["bypass_detection_test"]
            ),
            "median_coverage_percent": sorted(r["coverage_percent"] for r in rows)[len(rows) // 2],
        },
        "rows": rows,
    }


def build_attack_tree(register: dict) -> dict:
    nodes = []
    for r in register["rows"]:
        cid = r["control_id"]
        nodes.append(
            {
                "control_id": cid,
                "violation_goal": f"Violate {cid} ({r['title']}) without detection",
                "attack_paths": [
                    {
                        "path_id": f"{cid}-AP-{i+1}",
                        "steps": [bv["vector"]],
                        "difficulty": bv["difficulty"],
                        "classification": bv["classification"],
                    }
                    for i, bv in enumerate(r["bypass_vectors"])
                ],
                "detection_method": (
                    "pre-commit/CI static lock"
                    if r["enforcement_surface"]["build_time"]
                    else "none automated"
                ),
                "block_method": (
                    "git commit rejected"
                    if r["validated_maturity"] == "L3"
                    else "not blocked"
                ),
                "audit_evidence": r["audit_artifact"] or "none",
                "validated_maturity": r["validated_maturity"],
            }
        )
    return {
        "schema_version": 1,
        "artifact": "governance/artifacts/GOVERNANCE_ATTACK_TREE.json",
        "generated_from": "SEVERITY_1_CONTROL_VALIDATION_REGISTER.json",
        "last_validation_date": TODAY,
        "nodes": nodes,
    }


def build_runtime_matrix(register: dict) -> dict:
    rows = []
    for r in register["rows"]:
        s = r["enforcement_surface"]
        rows.append(
            {
                "control_id": r["control_id"],
                "title": r["title"],
                "validated_maturity": r["validated_maturity"],
                "coverage_percent": r["coverage_percent"],
                "build_time_enforcement": s["build_time"],
                "deploy_time_enforcement": s["deploy_time"],
                "runtime_enforcement": s["runtime"],
                "postmortem_enforcement": s["postmortem"],
                "production_drift_risk": (
                    "high"
                    if not s["runtime"] and r["control_id"].startswith(("I-28", "I-29", "I-31", "PL-FUSION"))
                    else "medium"
                    if not s["runtime"]
                    else "low"
                ),
            }
        )
    build_only = sum(1 for r in rows if r["build_time_enforcement"] and not r["runtime_enforcement"])
    return {
        "schema_version": 1,
        "artifact": "governance/artifacts/RUNTIME_ENFORCEMENT_MATRIX.json",
        "last_validation_date": TODAY,
        "summary": {
            "severity_1_controls": len(rows),
            "build_time_only_count": build_only,
            "runtime_enforced_count": sum(1 for r in rows if r["runtime_enforcement"]),
            "postmortem_enforced_count": sum(1 for r in rows if r["postmortem_enforcement"]),
        },
        "rows": rows,
    }


def build_self_protection_md() -> str:
    return f"""# Governance Self-Protection Audit

**Classification:** Institutional Audit Phase 1 | **Date:** {TODAY}  
**Method:** Read `.github/CODEOWNERS`, `.pre-commit-config.yaml`, `.github/workflows/hardening.yml`, `tools/check_governance_coverage_matrix.py`, git mechanics — not matrix inheritance.

## Executive verdict

Governance is **not self-protecting at institutional grade**. CODEOWNERS assigns review ownership, but **in-repo evidence does not prove branch protection, required reviews, or signed commits**. Weakening governance is **detectable only via git history** (post-hoc), not blocked at privilege boundary.

## Who can modify governance?

| Surface | CODEOWNERS | Proven block in repo? | Audit event? |
|---------|------------|----------------------|--------------|
| `AGENTS.md` | @evargas963 | No — file in repo | Git commit only |
| `governance/artifacts/*.json` | @evargas963 (via `/governance/`) | No | Git commit only |
| `tools/check_fix_everything_we_touch.py` | Not listed individually | No | Git commit only |
| `.pre-commit-config.yaml` | @evargas963 | No — can commit with `--no-verify` | None |
| `.github/workflows/*` | @evargas963 | No — merge without PR if allowed | CI log if PR used |
| `governance_coverage_matrix.json` | @evargas963 | `check_governance_coverage_matrix()` validates schema only | None |

## Who can disable governance?

| Action | Detection | Block | Audit |
|--------|-----------|-------|-------|
| `git commit --no-verify` | None at commit time | None | None |
| Remove hook from `.pre-commit-config.yaml` | Next CI run on PR | Only if PR + required check | Git diff |
| Lower matrix maturity in JSON | Checker allows if schema valid | None if L4+ not required yet | Git diff |
| Delete checker function | Other static locks may fail | `--no-verify` bypasses | Git diff |
| Set `ED_*` to change runtime law | None | None | None |
| Disable branch protection (GitHub settings) | Not in repo | N/A | GitHub audit log (if enabled) |

## Who can bypass governance?

See `governance/artifacts/GOVERNANCE_ATTACK_TREE.json`. Universal bypass: **`--no-verify`** (trivial, no audit event).

## What evidence is generated?

| Event | Evidence today | Institutional grade? |
|-------|----------------|---------------------|
| Pre-commit fail | stderr to developer | No persistence |
| CI fail | GitHub Actions log | PR-only |
| Promotion | `models/training_report.jsonl` | Partial |
| Override | None append-only | No |
| Governance change | Git commit | Mutable, rewriteable |

## Required upgrades (Phase 0 governance-of-governance)

1. GitHub branch protection: required reviews + required checks (`hardening.yml`, `pytest.yml`) — **verify on host**
2. CODEOWNERS must cover `tools/check_fix_everything_we_touch.py` explicitly
3. Matrix v2: forbid maturity > L2 without `bypass_detection_test` reference
4. Immutable governance event log (or signed tags on governance releases)
5. CI job that diffs governance files without corresponding validation register update → fail

**Git history alone is not institutional protection.**
"""


def build_coverage_md(register: dict) -> str:
    lines = [
        "# Coverage Justification — Severity-1 Controls",
        "",
        "> **Classification:** Operational Ledger | **Scope:** Validated maturity and coverage % per Severity-1 control.",
        "",
        f"**Date:** {TODAY} | **Source:** Institutional Audit Phase 1 validation register",
        "",
        "No control may claim maturity above what evidence justifies. Matrix `ENFORCED` labels are **overstated** where noted.",
        "",
        "| Control | Matrix claim | Validated | Coverage % | Why not higher |",
        "|---------|--------------|-----------|------------|----------------|",
    ]
    for r in sorted(register["rows"], key=lambda x: x["control_id"]):
        why = r["uncovered_invariant_portions"][0] if r["uncovered_invariant_portions"] else "—"
        if len(why) > 60:
            why = why[:57] + "..."
        lines.append(
            f"| {r['control_id']} | {r['matrix_claimed_status']} | {r['validated_maturity']} | "
            f"{r['coverage_percent']} | {why} |"
        )
    lines.extend(
        [
            "",
            "## Checker honesty (critical finding)",
            "",
            "Many checkers are **presence/marker scans**, not behavioral proofs:",
            "",
            "- `check_fusion_only_card_contract` — verifies strings exist in source files (`tools/check_fix_everything_we_touch.py:2638`)",
            "- `test_fusion_only_card_contract_passes_on_current_repo` — asserts checker returns `[]` on current repo only",
            "- **No test proves `--no-verify` is detected or blocked**",
            "",
            "## Adversarial testing gap",
            "",
            f"Controls with dedicated adversarial tests: **{register['validation_summary']['controls_with_adversarial_tests']}** / {register['validation_summary']['severity_1_controls']}",
            "",
            "Missing suites (Priority 0):",
            "- I-28: inject SPY 0.01 / 50000 / negative / duplicate ticks → expect quarantine + audit",
            "- I-31: delete feature/promotion records → expect loud reconstruction failure",
            "- I-24: single-actor promotion change → expect hard failure",
            "- Governance: commit governance weaken with `--no-verify` → expect block (currently none)",
            "",
            "## Severity classification (audit Phase 5)",
            "",
            "**Severity-1 (trade/audit foundational):** I-31, I-28, I-29, I-30, I-24, I-25, I-02, PL-PROMOTION, I-01/PL-FUSION-CARDS",
            "",
            "**Severity-2:** I-05, I-07, I-11, I-15, I-17, code quality, documentation",
            "",
            "**Severity-3:** Developer experience, DX tooling",
            "",
            "Matrix currently marks 31 rows severity-1 — several (I-20 dependency pins) are **Severity-2** in practice.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    reg = build_validation_register()
    atk = build_attack_tree(reg)
    rt = build_runtime_matrix(reg)

    (ART / "SEVERITY_1_CONTROL_VALIDATION_REGISTER.json").write_text(
        json.dumps(reg, indent=2) + "\n", encoding="utf-8"
    )
    (ART / "GOVERNANCE_ATTACK_TREE.json").write_text(
        json.dumps(atk, indent=2) + "\n", encoding="utf-8"
    )
    (ART / "RUNTIME_ENFORCEMENT_MATRIX.json").write_text(
        json.dumps(rt, indent=2) + "\n", encoding="utf-8"
    )
    (REPO / "governance" / "GOVERNANCE_SELF_PROTECTION_AUDIT.md").write_text(
        build_self_protection_md(), encoding="utf-8"
    )
    (REPO / "governance" / "COVERAGE_JUSTIFICATION.md").write_text(
        build_coverage_md(reg), encoding="utf-8"
    )

    s = reg["validation_summary"]
    print(
        f"wrote Phase 1 artifacts: severity_1={s['severity_1_controls']} "
        f"matrix_inaccurate={s['matrix_status_inaccurate_count']} "
        f"enforced_overstated={s['matrix_enforced_overstated_count']} "
        f"adversarial={s['controls_with_adversarial_tests']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
