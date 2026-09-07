"""Build Institutional Audit Phase 2 — proof artifacts (not inventory).

Reads the tracked SEVERITY_1_CONTROL_VALIDATION_REGISTER.json. The Phase-1 builder
was retired under the ED CONSOLE SLIMMING directive; the register is a tracked artifact.

Outputs:
  reports/artifacts/UNIVERSAL_BYPASS_REGISTER.json
  reports/artifacts/DECISION_PATH_REGISTRY.json
  reports/artifacts/RUNTIME_MUTATION_REGISTER.json
  reports/artifacts/RELEASE_OBJECT_SCHEMA.json
  reports/artifacts/BLIND_RECONSTRUCTION_TEST_RESULT.json
  reports/artifacts/GOVERNANCE_ADVERSARIAL_TEST_SPEC.json
  reports/artifacts/MATURITY_PROMOTION_RULES.json
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ART = REPO / "reports" / "artifacts"
TODAY = date.today().isoformat()

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ── helpers ─────────────────────────────────────────────────────────────


def _load_phase1_register() -> dict:
    path = ART / "SEVERITY_1_CONTROL_VALIDATION_REGISTER.json"
    if not path.is_file():
        raise SystemExit(
            "missing SEVERITY_1_CONTROL_VALIDATION_REGISTER.json (tracked artifact; the "
            "_build_institutional_audit_phase1 builder was retired under ED CONSOLE SLIMMING)"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _bp(
    path: str,
    classification: str,
    audit_type: str,
    detection: str,
    time_to_detect: str,
    location: str = "",
) -> dict:
    return {
        "path": path,
        "classification": classification,
        "audit_type": audit_type,
        "detection": detection,
        "time_to_detect_estimate": time_to_detect,
        "location": location,
    }


def _ep(name: str, location: str, surface: str) -> dict:
    return {"name": name, "location": location, "surface": surface}


# ── A. Universal Bypass Register ────────────────────────────────────────


def _i28_bypass_register() -> dict:
    return {
        "control_id": "I-28",
        "title": "Market data integrity",
        "lowest_defensible_maturity": "L2",
        "enforcement_points": [
            _ep("spot non-positive reject", "features/canonical_contract.py", "runtime"),
            _ep("daily health staleness/structure", "verification/daily_health.py", "postmortem"),
            _ep("finite numeric contract", "numeric_contract.py", "runtime"),
            _ep("Schwab adapter normalization", "market_data_adapter / live_market_plane", "runtime"),
        ],
        "bypass_paths": [
            _bp(
                "wrong but finite price (e.g. SPY 0.01 or 50000)",
                "unacceptable",
                "none",
                "none",
                "unknown — no wrongness quarantine",
                "features/canonical_contract.py — rejects spot <= 0 only",
            ),
            _bp(
                "malformed option chain with finite placeholders",
                "unacceptable",
                "none",
                "delayed",
                "hours — operator visual only",
                "call_engine.py — may degrade to R-005 synthetic path",
            ),
            _bp(
                "stale quote under TTL threshold",
                "tolerated",
                "none",
                "delayed",
                "seconds–minutes via analytics_stale UI",
                "server.py cache + ED_VIEWER_STATE_CACHE_TTL_SEC",
            ),
            _bp(
                "manual DB write to snapshots_1m_normalized",
                "unacceptable",
                "mutable",
                "none",
                "unknown — no DB immutability gate",
                "sqlite direct write",
            ),
            _bp(
                "runtime ED_* quote/refresh threshold override",
                "intentional",
                "none",
                "none",
                "immediate effect, no audit",
                "docs/host/ENVIRONMENT_VARIABLES.md",
            ),
            _bp(
                "disabled or skipped daily_health job",
                "unacceptable",
                "none",
                "none",
                "until manual run",
                "verification/daily_health.py — not wired as runtime block",
            ),
            _bp(
                "git commit --no-verify (staleness checker edits)",
                "tolerated",
                "none",
                "none",
                "never if not committed",
                "pre-commit bypass",
            ),
            _bp(
                "R-005 no_valid_expiry synthetic bundle without live quotes",
                "intentional",
                "mutable",
                "immediate",
                "immediate — state_error flag only",
                "server.py ~L2844 no_valid_expiry",
            ),
        ],
        "adversarial_tests_required": [
            "inject SPY=0.01 → quarantine + audit + block",
            "inject SPY=50000 → quarantine + audit + block",
            "stale quote under threshold → explicit stale surface",
            "duplicate/conflicting quote ticks → quarantine",
        ],
        "adversarial_tests_implemented": [],
    }


def _expand_bypass_from_register(reg_row: dict) -> dict:
    """Derive structured bypass register row from Phase 1 validation row."""
    cid = reg_row["control_id"]
    vectors = reg_row.get("bypass_vectors") or []
    bypass_paths = []
    for v in vectors:
        audit = "none"
        if reg_row.get("audit_artifact"):
            audit = "mutable"
        bypass_paths.append(
            _bp(
                v.get("vector", "unknown"),
                v.get("classification", "unacceptable"),
                audit,
                "none" if not v.get("audit_event_generated") else "mutable",
                "unknown",
            )
        )
    for bp in reg_row.get("bypass_code_paths") or []:
        if not any(bp in p["path"] for p in bypass_paths):
            bypass_paths.append(_bp(bp, "unacceptable", "none", "none", "unknown"))

    enforcement_points = [
        _ep("code path", loc, "runtime" if reg_row.get("enforcement_surface", {}).get("runtime") else "build")
        for loc in (reg_row.get("enforcement_code_paths") or [])[:6]
    ]
    if reg_row.get("checker_location"):
        enforcement_points.insert(
            0,
            _ep(reg_row.get("checker_name") or "checker", reg_row["checker_location"], "build"),
        )

    return {
        "control_id": cid,
        "title": reg_row.get("title", cid),
        "lowest_defensible_maturity": reg_row.get("validated_maturity", "L1"),
        "matrix_claimed_status": reg_row.get("matrix_claimed_status"),
        "coverage_percent": reg_row.get("coverage_percent", 0),
        "enforcement_points": enforcement_points,
        "bypass_paths": bypass_paths,
        "adversarial_tests_required": reg_row.get("adversarial_test_suite") or [],
        "adversarial_tests_implemented": reg_row.get("adversarial_test_suite") or [],
        "bypass_detection_test": reg_row.get("bypass_detection_test"),
    }


def build_universal_bypass_register(reg: dict) -> dict:
    rows_by_id = {r["control_id"]: r for r in reg["rows"]}
    entries: list[dict] = []
    # I-28 gets expanded exemplar (operator-requested shape)
    entries.append(_i28_bypass_register())
    for cid, row in sorted(rows_by_id.items()):
        if cid == "I-28":
            continue
        entry = _expand_bypass_from_register(row)
        if cid == "I-31":
            entry["bypass_paths"].extend(
                [
                    _bp(
                        "no GET /api/decision/{id} retrieval",
                        "unacceptable",
                        "none",
                        "none",
                        "immediate — query fails",
                    ),
                    _bp(
                        "decision_generation_id in-process only; lost on restart",
                        "unacceptable",
                        "none",
                        "none",
                        "immediate after restart",
                        "live_decision_bundle.py:stamp_decision_bundle",
                    ),
                    _bp(
                        "calibration_decision_log keyed by (ticker, ts) not Decision ID",
                        "unacceptable",
                        "mutable",
                        "delayed",
                        "manual SQL only",
                        "calibration/schema.py",
                    ),
                ]
            )
        if cid == "I-29":
            entry["bypass_paths"].extend(
                [
                    _bp(
                        "R-005 synthetic wait/flat bypasses compute_call and _validate_trade",
                        "unacceptable",
                        "none",
                        "immediate",
                        "immediate",
                        "server.py no_valid_expiry",
                    ),
                    _bp(
                        "models/fusion run before risk validation inside compute_call",
                        "unacceptable",
                        "none",
                        "none",
                        "never — ordering gap",
                        "call_engine.py:1269+ before _validate_trade",
                    ),
                ]
            )
        entries.append(entry)

    no_bypass_test = sum(1 for e in entries if not e.get("bypass_detection_test"))
    return {
        "schema_version": 1,
        "artifact": "reports/artifacts/UNIVERSAL_BYPASS_REGISTER.json",
        "generated": TODAY,
        "methodology": (
            "Per Severity-1 control: all enforcement points, all bypass paths, "
            "classification (intentional|tolerated|unacceptable), audit type, detection, time-to-detect. "
            "I-28 expanded as reference shape. Matrix maturity claims are NOT proof."
        ),
        "summary": {
            "severity_1_controls": len(entries),
            "controls_without_bypass_detection_test": no_bypass_test,
            "institutional_enforcement_proven": False,
            "strongest_supported_claim": (
                "Product-law controls are largely L3 (developer-path). "
                "Platform controls L0-L2. No control demonstrates L5."
            ),
        },
        "entries": entries,
    }


# ── B. Decision Path Registry ───────────────────────────────────────────


def _route(
    route_id: str,
    route: str,
    lineage: list[str],
    market_data: str,
    risk: str,
    override_reg: str,
    decision_id: str,
    audit: str,
    trade_impacting: bool,
    gaps: list[str],
) -> dict:
    mandatory_ok = (
        market_data not in ("none", "partial", "bypass")
        and risk not in ("none", "partial", "bypass")
        and decision_id not in ("none", "partial", "ephemeral")
    )
    return {
        "route_id": route_id,
        "route": route,
        "lineage": lineage,
        "market_data_validation": market_data,
        "risk_validation": risk,
        "override_registry": override_reg,
        "decision_id": decision_id,
        "audit": audit,
        "trade_impacting": trade_impacting,
        "passes_mandatory_controls": mandatory_ok and not gaps,
        "gaps": gaps,
    }


def build_decision_path_registry() -> dict:
    routes = [
        _route(
            "R-001",
            "market_state.py → build_market_state",
            ["server._fetch_state", "signals._compute_signals_impl", "call_engine.compute_call"],
            "partial — canonical_contract spot<=0 only",
            "yes — call_engine._validate_trade",
            "none",
            "ephemeral — stamp_decision_bundle in ms_dict",
            "mutable — snapshot if logger path",
            True,
            [],
        ),
        _route(
            "R-004",
            "GET /api/state / analytics refresh → _fetch_state",
            ["server._fetch_state", "R-001 chain"],
            "partial",
            "yes",
            "none",
            "ephemeral",
            "mutable — cache + optional calibration",
            True,
            [],
        ),
        _route(
            "R-005",
            "server._fetch_state no_valid_expiry synthetic",
            ["server._fetch_state — hard-coded dict"],
            "bypass — no live quote validation",
            "bypass — compute_call not invoked",
            "none",
            "none",
            "none",
            True,
            [
                "I-29 risk supremacy bypass",
                "I-28 market data bypass",
                "I-31 no decision_generation_id",
            ],
        ),
        _route(
            "R-010",
            "GET /api/state serves Tier C cache",
            ["last R-004/R-006 compute"],
            "partial — stale body allowed",
            "partial — last good compute",
            "none",
            "stale — prior generation",
            "none",
            True,
            ["stale market/risk state served without re-validation"],
        ),
        _route(
            "R-011",
            "GET /api/debug/prediction",
            ["sync _fetch_state"],
            "partial",
            "yes",
            "none",
            "ephemeral",
            "none",
            True,
            ["ungated in prod — debug surface"],
        ),
        _route(
            "R-012",
            "GET /api/live/state Tier A",
            ["live_market_plane — no build_market_state"],
            "partial — quote only",
            "none",
            "none",
            "none",
            "none",
            False,
            [],
        ),
        _route(
            "R-017",
            "POST /api/prediction/override",
            ["memory flag → next R-004"],
            "n/a",
            "partial — affects next compute_call",
            "none — no append-only registry",
            "none",
            "none",
            True,
            ["I-30 override without TTL or immutable audit"],
        ),
        _route(
            "R-027",
            "governance/ops promote + jobs",
            ["manual_control / ops runner"],
            "n/a",
            "n/a",
            "partial — env gates only",
            "none",
            "partial — training_report.jsonl",
            False,
            ["future R-004 impact — no release object"],
        ),
        _route(
            "R-034",
            "ml_scheduler / training promotion",
            ["execute_promotion_if_eligible or manual copy"],
            "n/a",
            "n/a",
            "partial — governed executor if used",
            "none",
            "mutable — jsonl",
            False,
            ["manual models/active/ copy bypasses executor"],
        ),
        _route(
            "R-031",
            "verify_model_outputs CLI",
            ["server._fetch_state"],
            "partial",
            "yes",
            "none",
            "ephemeral",
            "none",
            True,
            [],
        ),
        _route(
            "R-033",
            "calibration/*.py stack",
            ["compute_signals direct"],
            "partial",
            "yes",
            "none",
            "none",
            "mutable — calibration log if ED_CALIBRATION_LOG=1",
            True,
            ["not production HTTP — trust boundary"],
        ),
    ]

    bypass_routes = [r["route_id"] for r in routes if r["gaps"]]
    ti_routes = [r for r in routes if r["trade_impacting"]]

    return {
        "schema_version": 1,
        "artifact": "reports/artifacts/DECISION_PATH_REGISTRY.json",
        "generated": TODAY,
        "source_inventory": "docs/TRADE_IMPACTING_ROUTE_INVENTORY.md",
        "route_universality": {
            "proven": False,
            "mandatory_controls": [
                "market_data_validation",
                "risk_validation",
                "override_registry",
                "decision_id",
                "audit",
            ],
            "trade_impacting_routes": len(ti_routes),
            "routes_with_gaps": bypass_routes,
            "conclusion": (
                "Risk supremacy and market-data gates are NOT universal. "
                "R-005 bypasses compute_call/_validate_trade. R-010 serves stale decisions. "
                "R-017 mutates next decision without immutable override registry."
            ),
        },
        "routes": routes,
        "proof_gaps": [
            "No formal proof that all future server routes call build_market_state",
            "No continuous monitor that cache age exceeds market-data freshness SLO",
            "No single Decision ID on all trade-impacting outputs",
        ],
    }


# ── C. Runtime Mutation Register ────────────────────────────────────────


def _parse_ed_env_vars() -> list[str]:
    text = (REPO / "docs/host/ENVIRONMENT_VARIABLES.md").read_text(encoding="utf-8")
    return sorted(set(re.findall(r"ED_[A-Z0-9_]+", text)))


def build_runtime_mutation_register() -> dict:
    ed_vars = _parse_ed_env_vars()
    mutations: list[dict] = []

    def _mut(
        mechanism: str,
        can_change_behavior: bool,
        can_change_decisions: bool,
        without_deployment: bool,
        audit: str,
        classification: str,
        location: str = "",
    ) -> None:
        mutations.append(
            {
                "mechanism": mechanism,
                "can_change_behavior": can_change_behavior,
                "can_change_decisions": can_change_decisions,
                "without_deployment": without_deployment,
                "audit_type": audit,
                "classification": classification,
                "location": location,
            }
        )

    for var in ed_vars:
        decisions = var in {
            "ED_CONSOLE_ALLOW_PRED_OVERRIDE",
            "ED_MH_EMPIRICAL_SUPPORT",
            "ED_SIGNAL_LAYER_FUSION_BLEND",
            "ED_XGB_STRICT_ACTIVE_ONLY",
            "ED_CALIBRATION_LOG",
            "ED_SCHEDULER_AUTO_PROMOTE",
            "ED_DISABLE_AUTO_PROMOTE",
            "ED_ALLOW_ACTIVE_SYNC",
        }
        _mut(
            var,
            True,
            decisions,
            True,
            "none",
            "intentional_dev_unacceptable_institutional",
            "docs/host/ENVIRONMENT_VARIABLES.md",
        )

    static_mutations = [
        ("manual copy to models/active/", True, True, True, "none", "unacceptable", "filesystem"),
        ("sqlite write snapshots_1m_normalized", True, True, True, "mutable", "unacceptable", "data/ed_console.db"),
        ("POST /api/prediction/override", True, True, True, "none", "unacceptable", "server.py"),
        ("governance.json manifest edits", True, False, True, "mutable", "tolerated", "reports/artifacts/"),
        ("feature_curation_overrides.json", True, True, True, "mutable", "unacceptable", "reports/artifacts/"),
        ("ED_DISABLE_AUTO_PROMOTE=1", True, True, True, "none", "intentional", "runtime env"),
        ("scheduler flags / ml_scheduler CLI", True, True, True, "partial", "tolerated", "ml_scheduler.py"),
        ("POST /api/ops/run* when ED_OPS_RUNNER=1", True, True, True, "partial", "tolerated", "server.py"),
        ("governance UI actions ED_GOVERNANCE_UI_ACTIONS", True, False, True, "none", "tolerated", "server.py"),
        (".env file edit + restart", True, True, True, "none", "unacceptable", "repo root .env"),
    ]
    for row in static_mutations:
        _mut(*row)

    decision_mutators = [m for m in mutations if m["can_change_decisions"]]
    no_audit = [m for m in mutations if m["audit_type"] == "none"]

    return {
        "schema_version": 1,
        "artifact": "reports/artifacts/RUNTIME_MUTATION_REGISTER.json",
        "generated": TODAY,
        "summary": {
            "total_mechanisms": len(mutations),
            "ed_env_var_count": len(ed_vars),
            "can_change_decisions_count": len(decision_mutators),
            "without_deployment_count": sum(1 for m in mutations if m["without_deployment"]),
            "no_audit_count": len(no_audit),
            "institutional_runtime_governance": False,
        },
        "mutations": mutations,
    }


# ── E. Release Object ───────────────────────────────────────────────────


def build_release_object_schema() -> dict:
    schema = {
        "release_id": "string — immutable identifier",
        "git_sha": "string — full commit SHA",
        "model_hashes": "array — per ticker×horizon bundle content hashes",
        "config_hash": "string — hash of pinned env manifest + governance artifact pins",
        "approval_record": "string — four-eyes approval reference",
        "artifact_manifest": "string — path or hash of full artifact listing",
        "rollback_target": "string — prior release_id",
        "created_at_utc": "string — ISO8601",
    }
    return {
        "schema_version": 1,
        "artifact": "reports/artifacts/RELEASE_OBJECT_SCHEMA.json",
        "generated": TODAY,
        "release_object_schema": schema,
        "example": {
            "release_id": "rel-2026-06-11T12:00:00Z-abc123",
            "git_sha": "3f977b048782f33f6fe4969071d85e480f4d5896",
            "model_hashes": ["sha256:…/models/active/SPY/xgb_SPY_1c.pkl"],
            "config_hash": "sha256:…",
            "approval_record": "github-pr-1234-approved-by-…",
            "artifact_manifest": "reports/artifacts/release_manifest_rel-….json",
            "rollback_target": "rel-2026-06-10T…",
            "created_at_utc": "2026-06-11T12:00:00Z",
        },
        "current_state": {
            "release_object_defined_in_code": False,
            "production_decisions_reference_release": False,
            "nearest_partial": "GET /api/build git_sha + calibration build_generation column",
            "i26_dr_blocked_until_release_object": True,
            "evidence": [
                "PROMOTION_POLICY.md marked historical",
                "calibration_decision_log.build_generation is partial — not full release manifest",
                "live_decision_bundle does not stamp release_id",
            ],
        },
        "proof_required": "Every production decision row must carry release_id resolvable to this schema",
    }


# ── F. Blind Reconstruction Test ────────────────────────────────────────


def run_blind_reconstruction_test() -> dict:
    db_path = REPO / "data" / "ed_console.db"
    if not db_path.is_file():
        return {
            "schema_version": 2,
            "artifact": "reports/artifacts/BLIND_RECONSTRUCTION_TEST_RESULT.json",
            "generated": TODAY,
            "verdict": "SKIP",
            "reason": "data/ed_console.db not present",
            "i31_effective_maturity": "L0",
        }

    from decision_record import (
        ensure_production_decision_schema,
        get_production_decision_by_id,
        reconstruction_complete,
    )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        ensure_production_decision_schema(conn)
        row = conn.execute(
            "SELECT decision_id FROM production_decision_records ORDER BY decision_ts_utc DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return {
            "schema_version": 2,
            "artifact": "reports/artifacts/BLIND_RECONSTRUCTION_TEST_RESULT.json",
            "generated": TODAY,
            "procedure": (
                "Select latest production_decision_records.decision_id. Auditor receives ONLY that id. "
                "Single query via get_production_decision_by_id."
            ),
            "verdict": "FAIL",
            "reason": "no production_decision_records rows — emit at least one production decision",
            "i31_effective_maturity": "L1",
            "expected_outcome": "PASS after production decisions persist with full reconstruction payload",
        }

    decision_id = row["decision_id"]
    t0 = time.perf_counter()
    payload = get_production_decision_by_id(decision_id, db_path)
    elapsed = time.perf_counter() - t0

    if payload is None:
        return {
            "schema_version": 2,
            "artifact": "reports/artifacts/BLIND_RECONSTRUCTION_TEST_RESULT.json",
            "generated": TODAY,
            "sample_decision_id": decision_id,
            "verdict": "FAIL",
            "reason": "decision_id not retrievable",
            "i31_effective_maturity": "L1",
        }

    ok, missing = reconstruction_complete(payload)
    passed = ok and elapsed <= 60.0

    return {
        "schema_version": 2,
        "artifact": "reports/artifacts/BLIND_RECONSTRUCTION_TEST_RESULT.json",
        "generated": TODAY,
        "procedure": (
            "Select latest production_decision_records.decision_id. Auditor receives ONLY that id. "
            "Single query via get_production_decision_by_id."
        ),
        "sample_decision_id": decision_id,
        "elapsed_sec": round(elapsed, 4),
        "target_sla_sec": 60,
        "third_party_single_query": True,
        "missing_fields": missing,
        "verdict": "PASS" if passed else "FAIL",
        "i31_effective_maturity": "L3" if passed else "L1",
        "note": "Code path proven in tests/decision_reconstruction/; production DB row required for PASS here",
    }


# ── G. Adversarial Test Spec ─────────────────────────────────────────────


def build_adversarial_test_spec(reg: dict) -> dict:
    suites = [
        {
            "suite_id": "GOV-FOUR-EYES",
            "control_ids": ["I-24"],
            "scenario": "same actor authors and approves governance weakening",
            "expected": "hard fail",
            "implemented_test": None,
            "status": "NOT_IMPLEMENTED",
        },
        {
            "suite_id": "MKT-BAD-PRICE",
            "control_ids": ["I-28"],
            "scenario": "inject SPY=0.01, SPY=50000, stale quote, clock skew, duplicate quote",
            "expected": "quarantine + audit event + decision blocked",
            "implemented_test": None,
            "status": "NOT_IMPLEMENTED",
        },
        {
            "suite_id": "PROMO-MANUAL-COPY",
            "control_ids": ["I-02", "PL-PROMOTION"],
            "scenario": "manual copy into models/active/ without execute_promotion_if_eligible",
            "expected": "detection + audit + block at inference",
            "implemented_test": "tests/test_arch_competition_auto_promote.py (unit — not bypass detection)",
            "status": "PARTIAL",
        },
        {
            "suite_id": "OVERRIDE-NO-TTL",
            "control_ids": ["I-30"],
            "scenario": "override without TTL and without append-only registry",
            "expected": "fail closed",
            "implemented_test": None,
            "status": "NOT_IMPLEMENTED",
        },
        {
            "suite_id": "COMMIT-NO-VERIFY",
            "control_ids": ["PL-*"],
            "scenario": "git commit --no-verify with governance weakening",
            "expected": "block or immutable audit event",
            "implemented_test": None,
            "status": "NOT_IMPLEMENTED",
        },
        {
            "suite_id": "RECON-BLIND",
            "control_ids": ["I-31"],
            "scenario": "blind reconstruction from Decision ID only",
            "expected": "full bundle in <60s single query",
            "implemented_test": "tests/decision_reconstruction/test_immutable_decision_id.py",
            "status": "PARTIAL",
        },
        {
            "suite_id": "ROUTE-R005-BYPASS",
            "control_ids": ["I-29", "I-28"],
            "scenario": "no_valid_expiry path serves synthetic call without _validate_trade",
            "expected": "block or explicit non-tradeable surface",
            "implemented_test": None,
            "status": "NOT_IMPLEMENTED",
        },
    ]
    implemented = sum(1 for s in suites if s["status"] in ("PARTIAL", "PASS", "FAILING"))
    return {
        "schema_version": 1,
        "artifact": "reports/artifacts/GOVERNANCE_ADVERSARIAL_TEST_SPEC.json",
        "generated": TODAY,
        "methodology": "Governance is proven by adversarial tests, not checker existence.",
        "summary": {
            "suites_defined": len(suites),
            "suites_with_bypass_detection": 0,
            "suites_partial_or_better": implemented,
            "institutional_grade": False,
        },
        "suites": suites,
        "phase1_cross_check": {
            "controls_with_bypass_detection_test": reg["validation_summary"]["controls_with_bypass_detection_test"],
        },
    }


# ── H. Maturity Promotion Rules ─────────────────────────────────────────


def build_maturity_promotion_rules() -> dict:
    return {
        "schema_version": 1,
        "artifact": "reports/artifacts/MATURITY_PROMOTION_RULES.json",
        "generated": TODAY,
        "binding_rule": (
            "No control may move upward in maturity based on implementation work alone. "
            "Promotion evidence must exist. Burden of proof is on enforcement, not documentation."
        ),
        "maturity_vocabulary": {
            "L0": "Not built",
            "L1": "Documented / named gap",
            "L2": "Checker or test exists; partial coverage; bypass trivial",
            "L3": "Commit/CI blocked on happy path",
            "L4": "Bypass requires privileged action + audit event",
            "L5": "Workflow approval + immutable audit + reconstructable",
        },
        "promotion_requirements": {
            "L1_to_L2": ["named enforcement location in code or CI"],
            "L2_to_L3": ["pre-commit or CI block on happy path", "paired test (may be meta-test)"],
            "L3_to_L4": [
                "universal_bypass_register entry complete",
                "runtime enforcement or immutable audit event on bypass attempt",
                "adversarial test spec entry with failing or passing harness",
                "bypass_detection_test reference",
            ],
            "L4_to_L5": [
                "independent approval workflow (four-eyes)",
                "immutable audit trail",
                "blind reconstruction test PASS",
                "operational exercise record",
            ],
        },
        "forbidden": [
            "Promote because checker exists",
            "Promote because test asserts checker==[] on current repo",
            "Promote matrix status to ENFORCED without bypass inventory",
            "Promote I-26 DR while release object undefined",
        ],
        "authoritative_maturity_source": "SEVERITY_1_CONTROL_VALIDATION_REGISTER.json — supersedes governance_coverage_matrix.json",
    }


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    reg = _load_phase1_register()

    bypass = build_universal_bypass_register(reg)
    routes = build_decision_path_registry()
    runtime = build_runtime_mutation_register()
    release = build_release_object_schema()
    blind = run_blind_reconstruction_test()
    adversarial = build_adversarial_test_spec(reg)
    promotion = build_maturity_promotion_rules()

    writes = {
        "UNIVERSAL_BYPASS_REGISTER.json": bypass,
        "DECISION_PATH_REGISTRY.json": routes,
        "RUNTIME_MUTATION_REGISTER.json": runtime,
        "RELEASE_OBJECT_SCHEMA.json": release,
        "BLIND_RECONSTRUCTION_TEST_RESULT.json": blind,
        "GOVERNANCE_ADVERSARIAL_TEST_SPEC.json": adversarial,
        "MATURITY_PROMOTION_RULES.json": promotion,
    }
    for name, doc in writes.items():
        (ART / name).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


    print(
        f"wrote Phase 2 artifacts: bypass={bypass['summary']['severity_1_controls']} "
        f"route_universality={routes['route_universality']['proven']} "
        f"runtime_mutators={runtime['summary']['total_mechanisms']} "
        f"blind_reconstruction={blind.get('verdict')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
