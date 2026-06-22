"""
CAPS — Comprehensive Anti-Pattern Sweep.

Enumerates silent-default-substitution shapes on Schwab-leaf-derived paths.
Output: file:line:variant_id:expression (tab-separated on CLI).

Used by tests/test_anti_pattern_family_repo_wide.py and governance register maintenance.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIR_PARTS = frozenset(
    {
        ".git",
        ".claude",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
        "backups",
        "governance",
        "schwab_field_inventory",
    }
)

# Production scan excludes tooling and test harnesses (allowlisted via register prefix rows).
SCAN_SKIP_PREFIXES = (
    "tools/",
    "tests/",
)

DEFAULT_VALUE_RE = re.compile(
    r"""
    \b0\.0\b|\b0\b|\b1\.0\b|\b1\b|\b100\.0\b|\b100\b|\b6\.5\b|
    ["']above["']|["']unknown["']|["']neutral["']|["']flat["']|
    \bFalse\b|\bTrue\b
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class VariantSpec:
    variant_id: str
    regex: re.Pattern[str]
    description: str


VARIANTS: tuple[VariantSpec, ...] = (
    VariantSpec(
        "GET_WITH_DEFAULT",
        re.compile(r"""\.get\(\s*['"][^'"]+['"]\s*,\s*(?!None\b)([^)]+)\)"""),
        "dict.get(key, default) where default is not None",
    ),
    VariantSpec(
        "GET_OR_DEFAULT",
        re.compile(r"""\.get\(\s*['"][^'"]+['"]\s*\)\s+or\s+"""),
        "dict.get(key) or default (default must be in silent-default value family)",
    ),
    VariantSpec(
        "GET_NONE_OR_DEFAULT",
        re.compile(r"""\.get\(\s*['"][^'"]+['"]\s*,\s*None\s*\)\s+or\s+"""),
        "dict.get(key, None) or default",
    ),
    VariantSpec(
        "CAST_OR_DEFAULT",
        re.compile(r"""(?:int|float)\(.+?\s+or\s+0(?:\.0)?\)"""),
        "int(x or default) / float(x or default)",
    ),
    VariantSpec(
        "IF_NOT_NONE_ELSE",
        re.compile(r"""\bif\s+[^\n:]+?\s+is\s+not\s+None\s+else\s+"""),
        "x if x is not None else default",
    ),
    VariantSpec(
        "IF_TRUTHY_ELSE",
        re.compile(
            r"""(?<!['"])\bif\s+([a-zA-Z_][\w.]*)\s+else\s+(?!None\b)"""
        ),
        "x if x else default (truthy branch)",
    ),
    VariantSpec(
        "GETATTR_DEFAULT",
        re.compile(
            r"""getattr\(\s*[^,]+,\s*['"][^'"]+['"]\s*,\s*(?!None\b)"""
        ),
        "getattr(obj, field, default) where default is not None",
    ),
    VariantSpec(
        "SETDEFAULT",
        re.compile(r"""\.setdefault\(\s*['"][^'"]+['"]\s*,"""),
        "dict.setdefault(key, default)",
    ),
    VariantSpec(
        "NEXT_DEFAULT",
        re.compile(r"""next\(\s*[^,]+,\s*"""),
        "next(iter, default)",
    ),
    VariantSpec(
        "EXCEPT_RETURN_DEFAULT",
        re.compile(r"""except\s*[^:]*:\s*(?:return\s+)?(?:0\.0|0|None|False|True)\b"""),
        "try/except return default",
    ),
)


def _line_is_explicit_none_branch(line: str, variant_id: str) -> bool:
    """`x if x is not None else 0.0` is explicit missingness, not silent .get default."""
    if variant_id == "IF_NOT_NONE_ELSE" and "is not None else" in line:
        return bool(re.search(r"else\s+0(?:\.0)?\b", line))
    return False


def _line_is_doc_or_comment(line: str) -> bool:
    s = line.strip()
    if s.startswith("#"):
        return True
    if '"""' in line or "'''" in line:
        if any(
            tok in line
            for tok in (
                "silent default",
                "pattern family",
                "without ``",
                "CAPS",
                "anti-pattern",
            )
        ):
            return True
    return False


def iter_py_files(*, production_only: bool) -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        if set(path.parts) & SKIP_DIR_PARTS:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if production_only and any(rel.startswith(p) for p in SCAN_SKIP_PREFIXES):
            continue
        out.append(path)
    return out


def scan_file(path: Path) -> list[tuple[int, str, str, str]]:
    rel = path.relative_to(ROOT).as_posix()
    hits: list[tuple[int, str, str, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        if _line_is_doc_or_comment(line):
            continue
        for spec in VARIANTS:
            m = spec.regex.search(line)
            if not m:
                continue
            if spec.variant_id == "GET_OR_DEFAULT":
                tail = line[m.start() :]
                if not DEFAULT_VALUE_RE.search(tail):
                    continue
            if _line_is_explicit_none_branch(line, spec.variant_id):
                continue
            if spec.variant_id in ("IF_TRUTHY_ELSE", "IF_NOT_NONE_ELSE"):
                if not DEFAULT_VALUE_RE.search(line):
                    continue
            hits.append((lineno, rel, spec.variant_id, line.strip()))
            break
    return hits


def scan_all(*, production_only: bool = False) -> list[tuple[int, str, str, str]]:
    all_hits: list[tuple[int, str, str, str]] = []
    for path in sorted(iter_py_files(production_only=production_only)):
        all_hits.extend(scan_file(path))
    return all_hits


def format_hit(lineno: int, rel: str, variant_id: str, expr: str) -> str:
    expr_one = expr.replace("\t", " ").replace("\n", " ")[:200]
    expr_one = expr_one.encode("ascii", "replace").decode("ascii")
    return f"{rel}:{lineno}:{variant_id}:{expr_one}"


def parse_hit_line(line: str) -> tuple[str, int, str, str]:
    parts = line.strip().split(":", 3)
    if len(parts) != 4:
        raise ValueError(f"bad hit line: {line!r}")
    rel, lineno_s, variant_id, expr = parts
    return rel, int(lineno_s), variant_id, expr


def hit_is_allowlisted(
    rel: str,
    lineno: int,
    variant_id: str,
    *,
    prefix_rules: tuple[tuple[str, str], ...],
    line_rules: tuple[tuple[str, int | str, str, str], ...],
) -> bool:
    for prefix, _reason in prefix_rules:
        if rel == prefix or rel.startswith(prefix):
            return True
    for file, line, variant, _reason in line_rules:
        if rel != file:
            continue
        if line != "*" and int(line) != lineno:
            continue
        if variant != "*" and variant != variant_id:
            continue
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CAPS anti-pattern family sweep")
    parser.add_argument(
        "--production-only",
        action="store_true",
        help="Exclude tests/ and tools/",
    )
    parser.add_argument(
        "--variant",
        action="append",
        help="Filter to variant_id (repeatable)",
    )
    parser.add_argument(
        "--emit-register-tsv",
        action="store_true",
        help="Emit CAPS allowlist TSV rows to stdout (for register maintenance)",
    )
    args = parser.parse_args(argv)

    allowed_variants = set(args.variant) if args.variant else None
    hits = scan_all(production_only=args.production_only)
    for lineno, rel, vid, expr in hits:
        if allowed_variants and vid not in allowed_variants:
            continue
        if args.emit_register_tsv:
            print(f"{rel}\t{lineno}\t{vid}\tauto-classified pending")
        else:
            print(format_hit(lineno, rel, vid, expr))
    return 0


# Prefix allowlist: path prefix → justification (all variants, all lines).
CAPS_PREFIX_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("tests/", "test fixtures and gate documentation"),
    ("tools/", "scanner/CLI tooling not production data path"),
    ("calibration/", "calibration audit SQL aggregates and phase cleanup counters"),
    ("verification/", "verification harness diagnostics"),
    ("arch_competition/", "offline arch competition harness"),
    ("adaptive_shadow_v2_calibration.py", "shadow calibration ranking aggregates"),
    ("adaptive_similarity_engine.py", "adaptive similarity pool diagnostics"),
    ("replay_bundle_coverage.py", "replay bundle join row-count audit"),
    ("bar_rehydration_issue19_v1.py", "rehydration repair counters"),
    ("db_health_audit.py", "DB health audit counters"),
    ("similarity_audit.py", "similarity trace diagnostics"),
    ("similarity_feature_search.py", "shadow feature-search counters"),
    ("similarity_feature_universe.py", "feature universe report counters"),
    ("training_cache.py", "training manifest fingerprint counters"),
    ("training_provenance.py", "training manifest rows_used counter"),
    ("ml_scheduler.py", "scheduler manifest skip/row counters"),
    ("patch_active_artifact_provenance.py", "artifact patch counters"),
    ("planes/", "L1/runtime plane timestamps and version counters"),
    ("lifecycle_rule_core.py", "session minutes-since-open derived input"),
    ("setup_readiness.py", "readiness display probability coercion"),
    ("call_engine.py", "rules-engine display percent coercion"),
    ("ml_train.py", "training window max_ts comparison guard"),
    ("realized_contract_eval.py", "contract eval PnL + SQL pool counts"),
    ("liquidity_value_engine.py", "internal bar _ts sort keys"),
    ("order_flow_engine.py", "Schwab print time_millis sort/cutoff"),
    ("snapshot_normalizer.py", "materialize row-count audit"),
    ("market_state.py", "wall-score audit diff derived metrics"),
    ("db.py", "SQL COUNT aggregate int coercion"),
    ("server.py", "L1/SSE instrumentation timestamps and volume deltas"),
    ("monte_carlo.py", "MC output dict serialization of derived sim metrics"),
    ("live_vs_replay_validation.py", "replay validation row counts"),
    ("live_market_plane.py", "streaming plane timestamps and carry-forward guards"),
    ("bayesian_fusion.py", "fusion stack model-output defaults when sub-model unavailable"),
    ("features/signal_layer_v1.py", "derived signal layer counters"),
    ("features/fusion_policy_contract.py", "fusion policy prob normalization"),
    ("api_pressure.py", "HTTP client status_code getattr default"),
    ("tier3_design.py", "design-only similarity documentation"),
    ("distance_option_a_backfill_v1.py", "distance backfill counters"),
    ("inspect_trading_data.py", "inspection script"),
    ("feature_contracts.py", "legacy contract test helpers"),
    ("signals.py", "signal orchestration derived defaults (non-Schwab-leaf paths)"),
    ("prediction_engine.py", "prediction orchestration derived defaults and empirical pools"),
    ("multi_horizon_decision.py", "horizon decision orchestration derived defaults"),
    ("ml_predict.py", "inference orchestration derived defaults"),
    ("live_pipeline_diag.py", "live pipeline diagnostic counters"),
    ("lstm_model.py", "LSTM model wrapper derived defaults"),
    ("lstm_data.py", "training dataset builder — non-leaf time/session fields"),
    ("transformer_model.py", "transformer wrapper derived defaults"),
    ("transformer_train.py", "transformer training script counters"),
    ("train_all.py", "training driver counters"),
    ("train_compare.py", "training comparison script"),
    ("verify_ml_pipeline.py", "ML pipeline verification counters"),
    ("levels.py", "legacy levels helper derived defaults"),
    ("news_sentiment.py", "news API optional field coercion"),
    ("mc_fusion_adjustment.py", "MC fusion adjustment derived metrics"),
    ("micro_structure.py", "microstructure derived metrics"),
    ("movement_target_threshold.py", "movement target threshold derived metrics"),
    ("order_flow_live_state.py", "order-flow live state derived metrics"),
    ("order_flow_streaming.py", "order-flow streaming diagnostics"),
    ("institutional_behavior.py", "institutional behavior derived metrics"),
    ("polling_adapter.py", "polling adapter timestamps"),
    ("governed_stack_contract.py", "stack contract validation defaults"),
    ("math_volatility.py", "volatility derived metrics"),
    ("multi_horizon_ml_bundle.py", "ML bundle orchestration defaults"),
    ("training_cache_policy.py", "training cache policy counters"),
    ("similarity_feature_survivorship.py", "similarity survivorship audit"),
    ("similarity_feature_universe.py", "similarity universe audit"),
    ("research/", "research pilot scripts"),
    ("schwab_full_field_inventory.py", "field inventory scanner"),
    ("v2_decision/", "v2 decision adapter derived defaults"),
    ("audit_", "audit script counters and diagnostics"),
    ("backfill_", "backfill script counters"),
    ("compare_clustering_modes.py", "clustering comparison CLI"),
    ("debug_", "debug utilities"),
    ("crash_trace.py", "crash trace env flag"),
    ("db_authority.py", "DB authority env flags"),
    ("db_safety.py", "sqlite3 constant getattr defaults"),
    ("feature_contract_validation.py", "feature contract validation CLI"),
    ("feature_presence_contract.py", "feature presence validation CLI"),
    ("rules_engine.py", "rules engine display coercion"),
    ("market_context.py", "Schwab quote envelope nesting (quote/extended/regular dict shells)"),
    ("features/inference_snapshot.py", "SignalInput getattr with None default — fail-closed read"),
    ("features/monte_carlo_stack_input.py", "MC stack input derived defaults"),
    ("features/live_feature_adapter.py", "live feature adapter optional reads"),
    ("features/db_feature_adapter.py", "DB feature adapter optional reads"),
    ("features/regime_mvp_context.py", "regime MVP context derived defaults"),
    ("features/replay_signal_input_v1.py", "replay signal input derived defaults"),
    ("features/training_canonical_input.py", "training canonical merge path"),
    ("features/xgb_model_input.py", "XGB tabular envelope path"),
    ("features/shared_sequence_context.py", "shared sequence context derived defaults"),
    ("math_exposure_core.py", "explicit None branches on bucket aggregates"),
    ("math_probabilities.py", "probability derived metrics"),
    ("features/parallel_stack_schema.py", "parallel stack prob triplet defaults when probs dict partial"),
    ("features/fusion_model_input.py", "explicit unknown semantics for missing zone/vwap (Day 3)"),
    ("live_decision_bundle.py", "env config thresholds not Schwab leaves"),
    ("ml_data_common.py", "pandas merge empty-frame guards"),
    ("normalized_training_sync.py", "training sync env/debounce config"),
    ("ops_runner.py", "ops runner env flags"),
    ("pin_neutral_outcome_repair_v1.py", "outcome repair CLI"),
    ("print_liquidity_value_snapshot.py", "CLI display script"),
    ("regime_engine.py", "regime engine micro attribute read"),
    ("schwab_field_dictionary_builder.py", "field dictionary builder tooling"),
    ("math_levels.py", "structural window index default (non-price)"),
    ("market_data_adapter.py", "Schwab timestamp key alias (datetime vs timestamp) not numeric default"),
    ("smoke_predict_active.py", "smoke test CLI"),
    ("ticker_readiness_lookup.py", "readiness lookup API envelope"),
    ("verify_snapshot_pipeline.py", "snapshot pipeline verification counters"),
    ("xgboost_model.py", "XGB model prob triplet defaults when partial dict"),
)

# Line-level exceptions (file, line or *, variant or *, justification).
CAPS_LINE_ALLOWLIST: tuple[tuple[str, int | str, str, str], ...] = (
    ("calibration/v2_advisory_backfill.py", "*", "SETDEFAULT", "reconstructed Tier C ms dict setdefault for optional blocks"),
    ("fusion_contract.py", "*", "GETATTR_DEFAULT", "duck-typing on fusion + CanonicalForecast objects (FusionOutput.available, CanonicalForecast.provenance); not a silent-default fabrication"),
    ("numeric_contract.py", "*", "GETATTR_DEFAULT", "duck-typing on base-model output objects (prob_up/prob_down/prob_flat, dominant_class/dominant_dir); not a silent-default fabrication"),
    # ANTI_PATTERN_CAPS_VIOLATIONS bucket — exact line+variant exemptions for reviewed
    # non-market-leaf hits (no whole-file prefix; any future hit on another line/variant
    # in these files is still caught). Reasons state the reviewed category.
    ("decision_record.py", 305, "IF_TRUTHY_ELSE", "explicit fail-closed no-payload result"),
    ("decision_record.py", 375, "IF_TRUTHY_ELSE", "explicit fail-closed no-payload result"),
    ("money_path_ticker_tiers.py", 66, "GET_WITH_DEFAULT", "env config only"),
    ("override_registry.py", 85, "IF_TRUTHY_ELSE", "SQL COUNT(*) aggregate coercion"),
    ("release_object.py", 35, "GET_WITH_DEFAULT", "env config only"),
    ("release_object.py", 106, "GET_WITH_DEFAULT", "env config only"),
    ("release_object.py", 107, "GET_WITH_DEFAULT", "env config only"),
    ("scheduler_user_tickers.py", 60, "GET_WITH_DEFAULT", "env config only"),
    ("schwab_client.py", 51, "GETATTR_DEFAULT", "constant base URL only"),
    ("schwab_client.py", 293, "GET_WITH_DEFAULT", "OAuth/config timeout only"),
    ("schwab_client.py", 371, "GET_OR_DEFAULT", "parse_qs indexing idiom only"),
    ("schwab_client.py", 372, "GET_OR_DEFAULT", "parse_qs indexing idiom only"),
    ("schwab_client.py", 403, "GET_WITH_DEFAULT", "OAuth/config timeout only"),
    ("timing_probe2.py", 23, "GET_WITH_DEFAULT", "diagnostic probe display fallback"),
    ("trade_impacting_gate.py", 218, "GET_WITH_DEFAULT", "env config only"),
)


def caps_hit_allowed(rel: str, lineno: int, variant_id: str) -> bool:
    if hit_is_allowlisted(
        rel,
        lineno,
        variant_id,
        prefix_rules=CAPS_PREFIX_ALLOWLIST,
        line_rules=CAPS_LINE_ALLOWLIST,
    ):
        return True
    return False


def caps_register_markdown() -> str:
    """Markdown table for governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md."""
    rows = [
        "## CAPS allowlist (silent-default substitution family)",
        "",
        "<!-- CAPS_ALLOWLIST_START -->",
        "| file | line | variant | justification |",
        "|---|---:|---|---|",
    ]
    for prefix, justification in CAPS_PREFIX_ALLOWLIST:
        rows.append(f"| `{prefix}` | * | * | {justification} |")
    for file, line, variant, justification in CAPS_LINE_ALLOWLIST:
        rows.append(f"| `{file}` | {line} | {variant} | {justification} |")
    rows.extend(["<!-- CAPS_ALLOWLIST_END -->", ""])
    return "\n".join(rows)


def find_unallowlisted_hits(*, production_only: bool = True) -> list[str]:
    out: list[str] = []
    for lineno, rel, vid, expr in scan_all(production_only=production_only):
        if caps_hit_allowed(rel, lineno, vid):
            continue
        out.append(format_hit(lineno, rel, vid, expr))
    return out


if __name__ == "__main__":
    sys.exit(main())
