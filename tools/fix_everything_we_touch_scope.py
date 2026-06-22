"""Pre-commit scope, cache, and profiling for check_fix_everything_we_touch."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / ".cursor" / "cache" / "fix_everything_we_touch_cache.json"
PROFILE_ARTIFACT = REPO_ROOT / "governance" / "artifacts" / "FIX_EVERYTHING_WE_TOUCH_PROFILE.json"

# Staged paths that force expanded governance / repo-wide checks (not cache-only skip).
GOVERNANCE_CRITICAL_PREFIXES: tuple[str, ...] = (
    "governance/",
    "tools/check_",
    "tools/enforce_all_rules.py",
    "tools/audit_",
    "tools/_build_",
    "AGENTS.md",
    "CLAUDE.md",
    "ACTIVE_PROGRAM.md",
    ".cursor/rules/",
    ".github/",
    ".pre-commit-config.yaml",
)

MONEY_PATH_MARKERS: frozenset[str] = frozenset(
    {
        "signals.py",
        "call_engine.py",
        "prediction_engine.py",
        "realized_contract_eval.py",
        "bayesian_fusion.py",
        "mc_fusion_adjustment.py",
        "market_state.py",
        "live_decision_bundle.py",
        "features/signal_layer_v1.py",
        "features/inference_snapshot.py",
        "features/fusion_policy_contract.py",
        "static/index.html",
        "multi_horizon_decision.py",
        "trade_impacting_gate.py",
        "decision_record.py",
    }
)

# Repo-wide check → escalation trigger prefixes (empty = cache-only on fast path).
CHECK_ESCALATION: dict[str, tuple[str, ...]] = {
    "check_agent_preload_contract": (
        "AGENTS.md",
        "CLAUDE.md",
        ".cursor/rules/",
        "tools/check_agent_preload_contract.py",
    ),
    "check_branch_protection_proof": (".github/", "governance/artifacts/BRANCH_PROTECTION"),
    "check_required_status_checks": (".github/", "governance/artifacts/REQUIRED_STATUS"),
    "check_reviewer_evidence_index": (
        "governance/REVIEWER_README.md",
        "governance/artifacts/EVIDENCE_INDEX",
        "governance/artifacts/CURRENT_LIMITATIONS",
        "tools/check_reviewer_evidence_index.py",
        "tools/_build_evidence_index.py",
        "tools/_build_current_limitations.py",
    ),
    "check_governance_critical_files": ("governance/artifacts/GOVERNANCE_CRITICAL",),
    "check_governance_self_protection": ("governance/artifacts/GOVERNANCE_SELF_PROTECTION",),
    "check_no_verify_resistance": ("governance/artifacts/NO_VERIFY",),
    "check_governance_mutation_detection": (
        "tools/governance_mutation_detection.py",
        "governance/GOVERNANCE_MUTATION",
    ),
    "check_env_override_hardening": (
        "tools/check_env_override_hardening.py",
        "governance/artifacts/ENV_OVERRIDE",
    ),
    "check_precommit_performance_contract": (
        "tools/audit_precommit_performance.py",
        "governance/artifacts/PRECOMMIT_PERFORMANCE",
        ".pre-commit-config.yaml",
    ),
    "check_ablation_schwab_universe_contract": (
        "governance/artifacts/feature_ablation_manifest",
        "tools/feature_curation_gate.py",
    ),
    "check_ablation_seven_model_four_horizon_grid": ("tools/feature_curation_gate.py", "governance/artifacts/feature_ablation"),
    "check_ablation_equal_layer_consumers": ("governance/artifacts/feature_ablation",),
    "check_ablation_single_authority": ("governance/artifacts/feature_ablation",),
    "check_ablation_full_stack_non_negotiable": ("governance/artifacts/feature_ablation",),
    "check_no_ablation_gate_bypass_in_money_path": MONEY_PATH_MARKERS,
    "check_zero_bias_ablation_contract": ("governance/artifacts/feature_ablation", "tools/feature_curation_gate.py"),
    "check_graphrag_fidelity_ablation_contract": ("tools/feature_curation_gate.py",),
    "check_ablation_agnostic_ingest_contract": ("tools/feature_curation_gate.py",),
    "check_unified_stack_team_contract": ("governed_stack_contract",),
    "check_live_ablation_experiment_wiring": ("governance/artifacts/feature_ablation",),
    "check_unified_stack_canonical_vocabulary": ("governed_stack_contract",),
    "check_feature_list_no_model_preassignment": ("governance/artifacts/feature_ablation",),
    "check_ablation_manifest_generator_no_model_preassignment": ("tools/build_feature_assignment",),
    "check_full_stack_models_contract": ("governed_stack_contract",),
    "check_fusion_only_card_contract": MONEY_PATH_MARKERS,
    "check_four_horizon_promotion_contract": ("arch_competition/", "models/active"),
    "check_training_anchor_roster_contract": ("ml_scheduler.py", "scheduler_user_tickers.py"),
    "check_encoder_cone_mechanical_lock": (
        "tools/check_encoder_cone_tests.py",
        "lstm_data.py",
        "ml_predict.py",
        "transformer_train.py",
    ),
    "check_governance_archive_batch2_contract": ("governance/archive/", "governance/REPO_CLEANUP"),
    "check_ablation_denominator_vocabulary": ("AGENTS.md", "tools/feature_curation_gate.py"),
    "check_institutional_signoff_contract": ("AGENTS.md", "tools/check_fix_everything_we_touch.py"),
    "check_promoted_agents_rules_mechanically_locked": ("AGENTS.md", "tools/check_fix_everything_we_touch.py"),
    "check_objective_code_audit_documentation": ("AGENTS.md",),
    "check_objective_code_audit_contract": ("AGENTS.md", "tools/enforce_all_rules.py"),
    "check_mandatory_enforcement_registry": ("AGENTS.md",),
    "check_external_rule_tools_wired": (".pre-commit-config.yaml", "tools/enforce_all_rules.py"),
    "check_universal_code_quality_contract": ("tools/check_fix_everything_we_touch.py",),
    "check_meet_or_exceed_cycle_documentation": ("AGENTS.md",),
    "check_definition_of_done_for_fixes_contract": ("AGENTS.md", ".cursor/rules/010-definition-of-done"),
    "check_governance_binding_contract": ("governance/", "AGENTS.md"),
    "check_tier1_engineering_standard": ("AGENTS.md",),
    "check_v3_invariant_mechanical_registry": ("AGENTS.md",),
    "check_institutional_contract": MONEY_PATH_MARKERS,
    "check_mvp_dataframe_ingress": ("features/", "ml_train.py"),
    "check_ablated_training_only": ("tools/train_per_anchor_sequential.ps1",),
}

# Always run on pre-commit even on fast path (lightweight guards).
FAST_PATH_ALWAYS: frozenset[str] = frozenset(
    {
        "check_precommit_performance_contract",
        "check_mandatory_enforcement_registry",
        "check_external_rule_tools_wired",
    }
)

_ARTIFACT_JSON_CACHE: dict[str, Any] = {}


def load_artifact_json(path: Path) -> Any:
    """Load JSON artifact once per process; keyed by resolved path."""
    key = str(path.resolve())
    if key not in _ARTIFACT_JSON_CACHE:
        if not path.is_file():
            _ARTIFACT_JSON_CACHE[key] = None
        else:
            try:
                _ARTIFACT_JSON_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                _ARTIFACT_JSON_CACHE[key] = None
    return _ARTIFACT_JSON_CACHE[key]


def clear_artifact_json_cache() -> None:
    _ARTIFACT_JSON_CACHE.clear()


def _normalize_staged_path(raw: str) -> str:
    return raw.replace("\\", "/").lstrip("./")


def staged_touches_prefix(staged: set[str], prefix: str) -> bool:
    norm = prefix.replace("\\", "/")
    for p in staged:
        sp = _normalize_staged_path(p)
        if sp == norm or sp.startswith(norm):
            return True
    return False


def staged_touches_any(staged: set[str], triggers: tuple[str, ...] | frozenset[str]) -> bool:
    for trig in triggers:
        t = trig.replace("\\", "/")
        if t.endswith("/") or "/" in t:
            if staged_touches_prefix(staged, t):
                return True
        else:
            for p in staged:
                sp = _normalize_staged_path(p)
                if sp == t or sp.endswith("/" + t) or t in sp:
                    return True
    return False


def is_governance_critical_commit(staged: set[str]) -> bool:
    return staged_touches_any(staged, GOVERNANCE_CRITICAL_PREFIXES)


def is_money_path_commit(staged: set[str]) -> bool:
    return staged_touches_any(staged, MONEY_PATH_MARKERS)


def resolve_precommit_check_funcs(
    all_funcs: tuple[str, ...],
    *,
    staged: set[str],
    full_static: bool = False,
) -> tuple[str, ...]:
    """Return repo-wide check func names for this pre-commit invocation."""
    if full_static:
        return all_funcs
    if is_governance_critical_commit(staged):
        return all_funcs
    selected: list[str] = []
    for fn in all_funcs:
        if fn in FAST_PATH_ALWAYS:
            selected.append(fn)
            continue
        triggers = CHECK_ESCALATION.get(fn, ())
        if not triggers:
            continue
        if staged_touches_any(staged, triggers):
            selected.append(fn)
        elif is_money_path_commit(staged) and fn in (
            "check_fusion_only_card_contract",
            "check_institutional_contract",
        ):
            selected.append(fn)
    return tuple(dict.fromkeys(selected))


def _file_content_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _glob_content_hash(pattern: str) -> str:
    h = hashlib.sha256()
    root = REPO_ROOT
    if "**" in pattern:
        paths = sorted(root.glob(pattern))
    else:
        paths = sorted([root / pattern] if (root / pattern).is_file() else [])
    for p in paths:
        if p.is_file():
            h.update(p.as_posix().encode())
            h.update(_file_content_sha256(p).encode())
    return h.hexdigest()


def compute_cache_invalidation_sha256(all_funcs: tuple[str, ...]) -> str:
    """Hash inputs that invalidate cached repo-wide static results."""
    parts: list[str] = []
    for rel in ("AGENTS.md", "CLAUDE.md", "tools/check_fix_everything_we_touch.py"):
        parts.append(_file_content_sha256(REPO_ROOT / rel))
    parts.append(_glob_content_hash("tools/check_*.py"))
    parts.append(_glob_content_hash(".cursor/rules/**"))
    art_dir = REPO_ROOT / "governance" / "artifacts"
    if art_dir.is_dir():
        ah = hashlib.sha256()
        for p in sorted(art_dir.glob("*.json")):
            ah.update(p.name.encode())
            ah.update(_file_content_sha256(p).encode())
        parts.append(ah.hexdigest())
    parts.append("|".join(all_funcs))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


@dataclass
class ProfileRow:
    name: str
    seconds: float
    scope: str
    files_scanned: int = 0
    recommendation: str = ""
    cached: bool = False


@dataclass
class ProfileCollector:
    rows: list[ProfileRow] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter)

    def record(
        self,
        name: str,
        seconds: float,
        *,
        scope: str,
        files_scanned: int = 0,
        recommendation: str = "",
        cached: bool = False,
    ) -> None:
        self.rows.append(
            ProfileRow(
                name=name,
                seconds=round(seconds, 4),
                scope=scope,
                files_scanned=files_scanned,
                recommendation=recommendation,
                cached=cached,
            )
        )

    def to_artifact(self) -> dict:
        total = round(time.perf_counter() - self._t0, 4)
        return {
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "total_seconds": total,
            "subchecks": [
                {
                    "name": r.name,
                    "seconds": r.seconds,
                    "scope": r.scope,
                    "files_scanned": r.files_scanned,
                    "recommendation": r.recommendation,
                    "cached": r.cached,
                }
                for r in self.rows
            ],
        }


def load_disk_cache() -> dict | None:
    if not CACHE_PATH.is_file():
        return None
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_disk_cache(payload: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def cache_covers_all_checks(
    cache: dict | None,
    *,
    invalidation_sha256: str,
    func_names: tuple[str, ...],
) -> bool:
    if not cache or cache.get("invalidation_sha256") != invalidation_sha256:
        return False
    checkers = cache.get("checkers") or {}
    for fn in func_names:
        row = checkers.get(fn)
        if not row or row.get("ok") is not True:
            return False
    return True


def apply_cached_errors(cache: dict, func_names: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    checkers = cache.get("checkers") or {}
    for fn in func_names:
        row = checkers.get(fn)
        if row and row.get("errors"):
            errors.extend(row["errors"])
    return errors


def run_check_funcs(
    func_names: tuple[str, ...],
    globals_map: dict[str, Any],
    *,
    profile: ProfileCollector | None = None,
    scope_label: str = "repo",
    staged: set[str] | None = None,
) -> tuple[list[str], dict[str, dict]]:
    """Run named check funcs; return errors and per-checker results for cache."""
    errors: list[str] = []
    results: dict[str, dict] = {}
    st = staged or set()
    for fn_name in func_names:
        fn = globals_map.get(fn_name)
        t0 = time.perf_counter()
        if fn is None or not callable(fn):
            err = f"repo-wide static audit: missing callable {fn_name}()"
            errors.append(err)
            results[fn_name] = {"ok": False, "errors": [err]}
        else:
            fn_errors = list(fn())
            results[fn_name] = {"ok": not fn_errors, "errors": fn_errors}
            errors.extend(fn_errors)
        elapsed = time.perf_counter() - t0
        if profile is not None:
            profile.record(
                fn_name,
                elapsed,
                scope=scope_label,
                files_scanned=len(st),
                recommendation="",
            )
    return errors, results
