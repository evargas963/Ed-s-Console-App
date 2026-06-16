"""One-shot builder for governance_coverage_matrix.json — run when matrix rows change."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "governance" / "artifacts" / "governance_coverage_matrix.json"


def _row(
    id: str,
    domain: str,
    title: str,
    status: str,
    owner: str,
    mechanism: str,
    location: str,
    failure: str,
    bypass: str,
    audit: str,
    checker: str | None,
    test: str | None,
    severity: int = 2,
) -> dict:
    return {
        "id": id,
        "domain": domain,
        "title": title,
        "status": status,
        "owner": owner,
        "enforcement_mechanism": mechanism,
        "enforcement_location": location,
        "failure_mode": failure,
        "bypass_path": bypass,
        "audit_evidence": audit,
        "checker": checker,
        "test": test,
        "severity": severity,
    }


def build() -> dict:
    rows: list[dict] = []

    t1 = [
        ("T1-01", "Correctness over convenience"),
        ("T1-02", "Explicitness over implicitness"),
        ("T1-03", "Architecture intentional"),
        ("T1-04", "Maintainability first-class"),
        ("T1-05", "Reproducibility mandatory"),
        ("T1-06", "Deterministic behavior preferred"),
        ("T1-07", "Testability required"),
        ("T1-08", "Observability designed in"),
        ("T1-09", "Security by design"),
        ("T1-10", "Documentation is product"),
        ("T1-11", "Simplicity over cleverness"),
        ("T1-12", "Minimize cognitive load"),
        ("T1-13", "Strong contracts preferred"),
        ("T1-14", "Single source of truth"),
        ("T1-15", "Dependency discipline"),
        ("T1-16", "Failures intentional — no silent failure"),
        ("T1-17", "Production is the standard"),
        ("T1-18", "Auditability must exist"),
        ("T1-19", "Version everything"),
        ("T1-20", "Decisions require justification"),
        ("T1-21", "No tribal knowledge"),
        ("T1-22", "Continuous improvement"),
        ("T1-23", "Professional skepticism"),
        ("T1-24", "Engineering excellence standard"),
    ]
    for tid, title in t1:
        st = "PARTIALLY_ENFORCED" if tid in ("T1-07", "T1-11", "T1-16", "T1-17") else "DOCUMENTED_ONLY"
        chk: str | None = None
        tst: str | None = None
        if tid == "T1-11":
            chk = "check_universal_code_quality_contract"
            tst = "tests/test_check_fix_everything_we_touch.py::test_universal_code_quality_contract"
        elif tid == "T1-16":
            chk = "check_fusion_only_card_contract"
            tst = "tests/test_ml_predict_fail_closed.py"
        elif tid == "T1-07":
            tst = "tests/test_governance_consolidation.py (closure requires tests)"
        rows.append(
            _row(
                tid,
                "engineering",
                title,
                st,
                "agents",
                "pre-commit static locks (partial)" if st == "PARTIALLY_ENFORCED" else "agent discipline only",
                "tools/check_fix_everything_we_touch.py"
                if st == "PARTIALLY_ENFORCED"
                else "AGENTS.md",
                "Pre-commit fails where checker wired" if st == "PARTIALLY_ENFORCED" else "No commit block",
                "Un-wired principles; agent prose compliance",
                "Pre-commit exit 1" if st == "PARTIALLY_ENFORCED" else "None",
                chk,
                tst,
            )
        )

    v3 = [
        ("I-01", "No silent substitution / undeclared degradation", 1),
        ("I-02", "Single promotion authority", 1),
        ("I-03", "Causal information ordering", 2),
        ("I-04", "Single clock policy", 2),
        ("I-05", "Train-serve feature identity", 1),
        ("I-06", "Artifact hash immutability", 2),
        ("I-07", "No orphan paths", 1),
        ("I-08", "Output schema validity", 2),
        ("I-09", "Secrets exclusion", 2),
        ("I-10", "Reproducible training identity", 2),
        ("I-11", "Evaluation integrity", 2),
        ("I-12", "Pre-declared OOS discipline", 2),
        ("I-13", "Risk limits supersede model", 2),
        ("I-14", "Attributable change", 2),
        ("I-15", "Tuple health before trade impact", 1),
        ("I-16", "Decision explainability", 2),
        ("I-17", "Deterministic inference", 1),
        ("I-18", "Capacity bounded", 2),
        ("I-19", "Clock synchronization health", 1),
        ("I-20", "Dependency pinning in serving path", 1),
    ]
    v3_map = {
        "I-01": ("PARTIALLY_ENFORCED", "check_fusion_only_card_contract", "tests/test_prediction_engine_chunk1_fail_closed.py"),
        "I-02": ("PARTIALLY_ENFORCED", None, "tests/test_arch_competition_auto_promote.py"),
        "I-05": ("PARTIALLY_ENFORCED", "check_encoder_cone_mechanical_lock", "tests/test_ml_feature_schema_parity.py"),
        "I-11": ("PARTIALLY_ENFORCED", None, "tests/test_arch_competition_eval_runner.py"),
        "I-14": ("PARTIALLY_ENFORCED", None, "tests/test_batch2_analytics_bg_fail_counter.py"),
        "I-15": ("PARTIALLY_ENFORCED", "check_institutional_contract", "tools/live_diag_compare.py"),
        "I-07": ("PARTIALLY_ENFORCED", "check_storage_writer_has_consumer", "tests/test_check_fix_everything_we_touch.py"),
        "I-17": ("PARTIALLY_ENFORCED", None, "tests/test_ml_predict_fail_closed.py"),
        "I-19": ("PARTIALLY_ENFORCED", "check_institutional_contract", "tests/test_batch2_analytics_bg_fail_counter.py"),
        "I-20": ("PARTIALLY_ENFORCED", None, "requirements.txt — partial pin audit only"),
    }
    for iid, title, sev in v3:
        st, chk, tst = v3_map.get(iid, ("DOCUMENTED_ONLY", None, None))
        rows.append(
            _row(
                iid,
                "v3_core",
                title,
                st,
                "v3-spec",
                "pre-commit checker" if chk else "V3 spec vault; partial runtime code",
                "tools/check_fix_everything_we_touch.py" if chk else "governance/INSTITUTIONAL_STANDARD_V3.md",
                "Pre-commit fails" if chk else "No automatic block",
                "Single engineer; unwired paths",
                tst or "None",
                chk,
                tst,
                sev,
            )
        )

    platform = [
        ("I-21", "Data lineage integrity", 1),
        ("I-22", "Configuration governance", 1),
        ("I-23", "Incident accountability", 2),
        ("I-24", "Four-eyes review", 1),
        ("I-25", "Release governance", 1),
        ("I-26", "Disaster recovery objectives", 1),
        ("I-27", "Model risk retirement", 2),
        ("I-28", "Market data integrity", 1),
        ("I-29", "Risk governance", 1),
        ("I-30", "Override accountability", 1),
        ("I-31", "Decision reconstructability", 1),
    ]
    p_partial = {
        "I-28": (
            "PARTIALLY_ENFORCED",
            None,
            "server.py staleness flags; verification/daily_health.py",
            "tests/test_batch2_analytics_bg_fail_counter.py",
            "runtime/UI stale markers; daily health FAIL — no trade-path block",
        ),
        "I-27": (
            "PARTIALLY_ENFORCED",
            None,
            "arch_competition/live_drift_monitoring.py; operational_policy.py",
            "tests/test_arch_competition_auto_promote.py",
            "alerts and promotion_frozen — no retirement workflow gate",
        ),
    }
    for iid, title, sev in platform:
        if iid in p_partial:
            st, chk, loc, tst, fail = p_partial[iid]
            mech = "runtime surveillance + structural audit"
        else:
            st, chk, loc, tst, fail, mech = (
                "NOT_IMPLEMENTED",
                None,
                "none",
                None,
                "No block",
                "none",
            )
        rows.append(
            _row(
                iid,
                "platform",
                title,
                st,
                "platform-tier1",
                mech,
                loc,
                fail,
                "Single actor; no workflow gate",
                "Partial logs" if st == "PARTIALLY_ENFORCED" else "None",
                chk,
                tst,
                sev,
            )
        )

    product = [
        ("PL-FUSION-CARDS", "Fusion-only horizon cards", "ENFORCED", "check_fusion_only_card_contract", "tests/test_check_fix_everything_we_touch.py::test_fusion_only_card_contract"),
        ("PL-FULL-STACK", "Seven-model full stack", "ENFORCED", "check_full_stack_models_contract", "tests/test_ml_feature_schema_parity.py::test_full_stack_models_contract"),
        ("PL-ZERO-BIAS", "ZERO-BIAS ablation placement", "ENFORCED", "check_zero_bias_ablation_contract", "tests/test_check_fix_everything_we_touch.py::test_zero_bias_ablation_contract"),
        ("PL-ABLATION-GRID", "7x4 ablation grid", "ENFORCED", "check_ablation_seven_model_four_horizon_grid", "tests/test_check_fix_everything_we_touch.py::test_ablation_grid_requires_all_seven_models_and_four_horizons"),
        ("PL-PROMOTION", "Single promotion authority", "PARTIALLY_ENFORCED", None, "tests/test_arch_competition_auto_promote.py"),
        ("PL-TRAINING-ROSTER", "Training anchor roster", "ENFORCED", "check_training_anchor_roster_contract", "tests/test_scheduler_user_tickers_return_type.py"),
        ("PL-SCHWAB-CSV", "Schwab CSV-first new sites", "PARTIALLY_ENFORCED", "external:tools/check_schwab_csv_first.py", "tests/test_check_schwab_csv_first.py"),
        ("PL-UPFRONT-GATE", "Tier 0 upfront mechanical gate", "ENFORCED", "check_upfront_mechanical_gate_stamp", "tests/test_governance_consolidation.py::test_upfront_mechanical_gate_stamp"),
        ("PL-SIGNOFF", "Institutional sign-off ladder", "ENFORCED", "check_institutional_signoff_contract", "tests/test_governance_consolidation.py::test_institutional_signoff_contract"),
        ("PL-NO-DEFERRAL", "No deferral without REAL-GATE", "ENFORCED", "external:tools/check_no_deferral_language.py", "tests/test_check_no_deferral_language.py"),
        ("PL-STORAGE-CONSUMER", "Storage needs consumer", "ENFORCED", "check_storage_writer_has_consumer", "tests/test_check_fix_everything_we_touch.py"),
        ("PL-REGISTRY", "Mandatory enforcement registry", "ENFORCED", "check_mandatory_enforcement_registry", "tests/test_check_fix_everything_we_touch.py::test_mandatory_enforcement_registry_passes_on_current_repo"),
    ]
    for pid, title, st, chk, tst in product:
        rows.append(
            _row(
                pid,
                "product_law",
                title,
                st,
                "product",
                "pre-commit mechanical lock",
                "tools/check_fix_everything_we_touch.py",
                "git commit rejected (exit 1)",
                "git commit --no-verify (operator only)",
                "pre-commit stdout + exit code",
                chk,
                tst,
                1,
            )
        )

    return {
        "schema_version": 1,
        "artifact": "governance/artifacts/governance_coverage_matrix.json",
        "classification_vocabulary": [
            "ENFORCED",
            "PARTIALLY_ENFORCED",
            "DOCUMENTED_ONLY",
            "NOT_IMPLEMENTED",
        ],
        "burden_of_proof_fields": [
            "enforcement_mechanism",
            "enforcement_location",
            "failure_mode",
            "bypass_path",
            "audit_evidence",
            "checker",
            "test",
        ],
        "enforced_definition": (
            "ENFORCED only when violation triggers failed commit, CI, runtime block, "
            "workflow gate, or immutable audit — not documentation or tests alone."
        ),
        "rows": rows,
    }


def main() -> int:
    doc = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    from collections import Counter

    c = Counter(r["status"] for r in doc["rows"])
    print(f"wrote {OUT} rows={len(doc['rows'])} status={dict(c)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
