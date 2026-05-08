#!/usr/bin/env python3
"""
Classify the mechanical Schwab CSV derived-field crosswalk.

Input is the intentionally over-inclusive
`governance/SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv`.
Output is a full classified CSV plus a smaller residual CSV for rows that still
need human market-data disposition.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "governance" / "SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv"
DEFAULT_OUTPUT = ROOT / "governance" / "SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_CLASSIFIED.csv"
DEFAULT_RESIDUAL = ROOT / "governance" / "SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_RESIDUAL.csv"
DEFAULT_DISPOSITION = ROOT / "governance" / "SCHWAB_CSV_DERIVED_FIELD_DISPOSITION_REGISTER.csv"

NON_RUNTIME_PREFIXES = (
    ".claude/",
    ".git/",
    "tests/",
    "docs/",
    "governance/",
    "research/",
    "backups/",
)
NON_RUNTIME_FILES = (
    "audit_",
    "clean_db.py",
    "api_pressure.py",
    "schwab_full_field_inventory.py",
    "schwab_full_accessible_field_inventory.py",
    "schwab_field_dictionary_builder.py",
)
MARKET_RUNTIME_PREFIXES = (
    "server.py",
    "live_market_plane.py",
    "call_engine.py",
    "chains.py",
    "market_context.py",
    "market_state.py",
    "market_data_adapter.py",
    "snapshot_normalizer.py",
    "signals.py",
    "mc_fusion_adjustment.py",
    "realized_contract_eval.py",
    "backfill_flow_imbalance.py",
    "debug_flow_snapshot.py",
    "db_health_audit.py",
    "math_",
    "order_flow_",
    "features/",
    "v2_decision/",
    "calibration/",
    "planes/",
    "lstm_",
    "ml_",
    "transformer_",
    "prediction_engine.py",
    "liquidity_value_engine.py",
    "db.py",
    "tools/",
)
TRUE_ANALYTIC_HINTS = (
    "gamma_wall",
    "delta_wall",
    "net_gamma",
    "net_delta",
    "vanna",
    "charm",
    "vwap_side",
    "dist_to_vwap",
    "flow_imbalance",
    "smart_money",
    "probability",
    "posterior",
    "weight_",
    "readiness_score",
    "conviction_multiplier",
    "risk_multiplier",
)
OFFLINE_TOOL_PREFIXES = (
    "tools/",
    "adaptive_",
    "bayesian_fusion.py",
    "regime_engine.py",
    "volatility_regime.py",
    "levels.py",
    "feature_contracts.py",
    "signal_types.py",
    "inspect_",
    "test_",
)
DIRECT_REPLACE_NAMES = {
    "spot",
    "last",
    "lastPrice",
    "mark",
    "bid",
    "ask",
    "bidPrice",
    "askPrice",
    "volume",
    "totalVolume",
    "openInterest",
    "multiplier",
    "daysToExpiration",
    "expirationDate",
    "theta",
    "gamma",
    "delta",
    "vega",
    "rho",
    "volatility",
    "quoteTimeInLong",
    "tradeTimeInLong",
    "netPercentChange",
    "netChange",
}
GENERIC_NAME_ONLY = {"high", "low", "close", "open", "last"}


def _split(value: str) -> set[str]:
    return {v for v in (value or "").split("|") if v}


def _is_non_runtime(path: str) -> bool:
    return path.startswith(NON_RUNTIME_PREFIXES) or path.startswith(NON_RUNTIME_FILES)


def _is_market_runtime(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in MARKET_RUNTIME_PREFIXES)


def _disambiguate_mechanical_row(row: dict[str, str]) -> tuple[str, str] | None:
    """
    Human-verified overrides for false-positive mechanical rows.

    Returns a (classification, reason) to short-circuit generic rules, or None.
    """
    path = row["file"]
    code = row["code"]
    low = code.lower()
    tags = _split(row["tags"])
    names = _split(row["names"])

    if path == "debug_flow_snapshot.py":
        return (
            "NOT_MARKET_DATA",
            "offline debug tool echoes stored option_chain_json; not live Schwab API ingest",
        )

    if path == "backfill_flow_imbalance.py":
        if "flow_source_volume" in code or "flow_source_book" in code or "flow_source_none" in code:
            return (
                "NOT_MARKET_DATA",
                "flow_imbalance provenance histogram keys; not quotes.quote / chain volume primitives",
            )
        if '"daysToExpiration"' in code or '"expirationDate"' in code:
            if "ct.get(" in code and " or 0" not in code and " or 0," not in code:
                return (
                    "CSV_PRIMITIVE_CANONICAL_REVIEW",
                    "archived chain JSON passthrough for DTE/expiry without zero-fill",
                )
        if "total_volume" in low and "ct.get(" in code and " or 0" not in code:
            return (
                "CSV_PRIMITIVE_CANONICAL_REVIEW",
                "archived chain volume passthrough without defaulting missing to zero",
            )

    if path == "chains.py":
        if "ct.get(" in code and ('"daysToExpiration"' in code or '"expirationDate"' in code):
            if " or 0" not in code and " or 0," not in code:
                return (
                    "CSV_PRIMITIVE_CANONICAL_REVIEW",
                    "normalization echoes Schwab expiry fields without zero-fill",
                )

    if path == "call_engine.py":
        if "notes.append" in low and ("volatility" in low or "vix at" in low):
            return "NOT_MARKET_DATA", "trader-facing narrative strings; not Schwab field reads"
        if "risk_fails.append" in low and "vix" in low:
            return "NOT_MARKET_DATA", "risk checklist copy; not Schwab volatility primitive"
        if "gamma wall" in low:
            return "NOT_MARKET_DATA", "comment/docs on structural levels; not chain gamma read"
        if "delta" in names and "qqq" in low and "spy" in low:
            return (
                "NOT_MARKET_DATA",
                "QQQ vs SPY percent spread uses local name delta; not option-chain delta",
            )
        if tags == {"DATE_DIFF_DTE"} and "0dte" in low:
            return "NOT_MARKET_DATA", "0DTE policy docstring; not calendar DTE derivation"
        if "risk_multiplier" in low and "volatility regime" in low:
            return (
                "TRUE_ANALYTIC_REVIEW",
                "regime-based stop scaling from inputs; provenance at call boundaries",
            )
        if '"volatility"' in code and "vol_mult" in low:
            return (
                "TRUE_ANALYTIC_REVIEW",
                "engineered volatility score in payload; not chains.volatility passthrough",
            )

    if path == "monte_carlo.py":
        if "r_pin = simulate" in low or "r_brk = simulate" in low:
            return (
                "NOT_MARKET_DATA",
                "module __main__ self-test literals; not production market-data path",
            )
        if "monte carlo path engine" in low and "regime-aware" in low:
            return "NOT_MARKET_DATA", "module docstring banner for MC engine"
        if low.lstrip().startswith("version:") and "mc_v" in low:
            return "NOT_MARKET_DATA", "module version banner"
        if "optional[float]" in low and code.strip().startswith("volatility:"):
            return (
                "NOT_MARKET_DATA",
                "MonteCarloOutput dataclass optional path-statistics fields",
            )
        if (
            ("mc_feature_dict" in low and '"volatility"' in code and " or 0.0" in code)
            or ("float(self.volatility" in code.replace(" ", "") and " or 0.0" in code)
        ):
            return (
                "TRUE_ANALYTIC_REVIEW",
                "MonteCarloOutput fusion dict coerces optional path stats to floats; N7 silent MC normalization is mc_fusion_adjustment.normalize_mc",
            )
        if "run regime-aware stochastic-volatility monte carlo simulation" in low:
            return "NOT_MARKET_DATA", "simulate() docstring"
        if "instead of a flat constant" in low and "regime multiplier" in low:
            return "NOT_MARKET_DATA", "simulate() docstring (GARCH path)"
        _c0 = code.replace(" ", "")
        if "em_upperor0.0" in _c0 and "em_loweror0.0" in _c0 and "spot" in _c0:
            return "NOT_MARKET_DATA", "debug printf formatting for optional EM endpoints (not spot defaulting)"
        _no_ws = code.replace(" ", "")
        if "volatility=dispersion" in _no_ws or (
            code.strip().startswith("volatility") and "= dispersion" in code
        ):
            return (
                "TRUE_ANALYTIC_REVIEW",
                "MC output volatility field is simulated path dispersion statistic",
            )
        if "volatility=round(volatility" in code.replace(" ", ""):
            return "TRUE_ANALYTIC_REVIEW", "MC output assembly (round path dispersion)"

    if path == "micro_structure.py":
        if "volume:" in code and "optional" in low:
            return (
                "NOT_MARKET_DATA",
                "Candle dataclass optional volume field; not Schwab tape defaulting",
            )

    if path == "backfill_snapshot_derived.py":
        return "NOT_MARKET_DATA", "offline snapshot derived-field helper (documentation / tool path)"

    if path == "compare_clustering_modes.py":
        return "NOT_MARKET_DATA", "offline clustering experiment builds OHLC dicts from inputs"

    if path == "db_authority.py":
        return "NOT_MARKET_DATA", "DB authority registry prose; not a Schwab field read site"

    if path == "distance_option_a_backfill_v1.py":
        return "NOT_MARKET_DATA", "CLI argparse help mentions mark-writers flag"

    if path == "liquidity_models.py" and "atr" in low and "mult" in low:
        return "NOT_MARKET_DATA", "model hyperparameter comment (ATR mult); not chains.multiplier"

    if path == "live_decision_bundle.py":
        return "NOT_MARKET_DATA", "module docstring on bundle caching semantics"

    if path == "live_vs_replay_validation.py":
        return "NOT_MARKET_DATA", "replay/live parity audit reads archived rows/SQL; not live Schwab API"

    if path == "similarity_feature_universe.py" and "endswith" in low:
        return "NOT_MARKET_DATA", "feature-name substring filter; not option Greek reads"

    if path == "tier3_design.py":
        return "NOT_MARKET_DATA", "tier-3 design documentation string"

    if path == "timeframe_config.py":
        return "NOT_MARKET_DATA", "timeframe / bar contract documentation prose"

    if path == "verify_mc_directional.py":
        return "NOT_MARKET_DATA", "verification harness default for missing spot in fixture dicts"

    if path == "verify_ml_pipeline.py":
        return "NOT_MARKET_DATA", "synthetic MC payload literal in ML pipeline verification"

    if path == "arch_competition/live_drift_monitoring.py" and "delta ece" in low:
        return "NOT_MARKET_DATA", "calibration drift evidence string (delta ECE); not option delta"

    if path == "arch_competition/stack_bundle_eval_v1.py":
        return "NOT_MARKET_DATA", "research eval docstring references MC context features"

    if path == "verification/daily_health.py" and "market_context_only" in low:
        return "NOT_MARKET_DATA", "daily health script commentary string"

    if path == "verification/db_coverage.py" and "delta(ts_utc)" in code.replace(" ", "").lower():
        return "NOT_MARKET_DATA", "timestamp gap heuristic named delta(ts_utc); not option Greek"

    if path == "db.py":
        cstrip = code.strip()
        if cstrip.startswith("return _wall_time.time()"):
            return (
                "NOT_MARKET_DATA",
                "db.utc_ts(): unix wall for DB/session bookkeeping; market snapshots use Schwab/bar ts_utc",
            )
        if "set_ts_utc is None else set_ts_utc" in code and "_wall_time.time()" in code:
            return (
                "NOT_MARKET_DATA",
                "ed_schema_flags set_ts_utc when caller omits explicit audit timestamp",
            )
        if "no_source_file" in code and "_wall_time.time()" in code:
            return (
                "NOT_MARKET_DATA",
                "logging_universe migration skipped-no-source audit mark only",
            )
        if cstrip == "now = _wall_time.time()":
            return (
                "NOT_MARKET_DATA",
                "migration transaction wall clock for enrollment_ts_utc / migration_log",
            )
        if cstrip == "_wall_time.time(),":
            return (
                "NOT_MARKET_DATA",
                "one-time horizon migration ed_schema_flags set_ts_utc literal",
            )
        if "tz_eval = float(_wall_time.time())" in code:
            return (
                "NOT_MARKET_DATA",
                "governed outcome refresh after 1m bar upsert (eval anchor for SQL windowing)",
            )
        if cstrip == "tz = float(_wall_time.time())":
            return (
                "NOT_MARKET_DATA",
                "BAR_ANCHOR outcome bulk refresh upper bound vs stored snapshot ts_utc",
            )
        if "ts_eval_utc is not None else _wall_time.time()" in code:
            return (
                "NOT_MARKET_DATA",
                "optional bar-mutation outcome refresh eval ts; defaults to wall now",
            )

    if path == "server.py":
        if "time.monotonic()" in code:
            return (
                "NOT_MARKET_DATA",
                "process monotonic for intervals/elapsed; not Schwab quote/trade authority (S017 ops clock)",
            )
        if "time.perf_counter()" in code:
            return (
                "NOT_MARKET_DATA",
                "perf_counter for sub-ms profiling splits; not a market timestamp",
            )
        if "_pipeline_ms" in code and "monotonic()" in code:
            return (
                "NOT_MARKET_DATA",
                "_pipeline_ms from monotonic deltas (server latency); not tape time",
            )
        ops_wall = (
            "logging_universe_sync_wall_ts",
            "enrollment_touch_wall_ts",
            "mkt_ctx_cache_eval_wall_ts",
            "logger_cycle_touch_wall_ts",
            "analytics_freshness_eval_wall_ts",
            "pending_shell_ingestion_wall_ts",
            "recent_cross_eval_wall_ts",
            "l1_eval_wall_ts",
        )
        if any(m in code for m in ops_wall) and "time.time()" in code:
            return (
                "NOT_MARKET_DATA",
                "named TTL/enrollment/analytics/L1-eval wall clock; Schwab times on quote fields",
            )
        if "_server_build_ts" in code and "time.time()" in code:
            return (
                "NOT_MARKET_DATA",
                "response envelope ingestion unix; quote authority is fast_server_ts / Schwab parse (S017)",
            )
        cns = code.replace(" ", "")
        if '"server_ts":time.time()' in cns or "'server_ts':time.time()" in cns:
            return (
                "NOT_MARKET_DATA",
                "fail-closed missing_spot payload diagnostic instant; not a quoteTime claim",
            )
        if code.strip() == "_gen_ts = time.time()":
            return (
                "NOT_MARKET_DATA",
                "_state_cache versioning stamp for ms_dict rows; not Schwab tape time",
            )
        if "server_received_ts = time.time()" in code:
            return (
                "NOT_MARKET_DATA",
                "REST quote ingestion wall clock; Schwab epoch is fast_server_ts / quote_ts fields",
            )
        if "_minimal_end_mono" in code or "_t_pipeline_end_mono" in code:
            return (
                "NOT_MARKET_DATA",
                "_fetch_state pipeline segment timings from monotonic() deltas",
            )
        c2 = code.replace(" ", "")
        if "_tick_ts=parsed.quote_time" in c2:
            return (
                "NOT_MARKET_DATA",
                "Schwab quote_time/trade_time epoch fed to candle.tick(); not wall fallback",
            )
        if "_pl_cache_mono" in code and "_now_mono" in code:
            return (
                "NOT_MARKET_DATA",
                "intraday price-levels cache staleness via monotonic vs pl_mono",
            )
        if "now_diag = time.time()" in code:
            return (
                "NOT_MARKET_DATA",
                "L1 /api/diagnostics materiality probe uses wall now vs quote-derived context",
            )
        if "logging_universe_unpin_to_user_persisted" in code and "time.time()" in code:
            return (
                "NOT_MARKET_DATA",
                "EdDB logger pin API audit/enrollment timestamp",
            )
        if "ACCURACY_INTERVAL" in code and "time.time()" in code:
            return (
                "NOT_MARKET_DATA",
                "model accuracy cache TTL / periodic recompute gate; not quoteTime",
            )
        if "_accuracy_cache" in code and '"ts"' in code and "time.time()" in code:
            return (
                "NOT_MARKET_DATA",
                "stores last accuracy computation wall time per ticker; not Schwab quoteTime",
            )
        if '"ts":time.time()' in c2 and '"ms_dict"' in c2:
            return (
                "NOT_MARKET_DATA",
                "log_only _state_cache placeholder row stamp when ms_dict empty",
            )
        if 'ms_dict["server_ts"]=time.time()' in c2:
            return (
                "NOT_MARKET_DATA",
                "full _fetch_state response envelope server_ts (ingestion instant); quote times in quote fields",
            )
        if code.strip() == "now = time.time()":
            return (
                "NOT_MARKET_DATA",
                "HTTP handler wall clock for cache age / freshness math; not Schwab quoteTime substitution",
            )

    return None


def classify(row: dict[str, str]) -> tuple[str, str]:
    path = row["file"]
    code = row["code"]
    tags = _split(row["tags"])
    names = _split(row["names"])
    candidates = _split(row["candidate_schwab_fields"])
    low_code = code.lower()

    if _is_non_runtime(path):
        return "NOT_MARKET_RUNTIME", "tests/docs/governance/audit/generated support path"
    if names and names.issubset(GENERIC_NAME_ONLY) and not tags:
        return "NOT_MARKET_DATA", "generic name-only hit without derivation/default risk"
    early = _disambiguate_mechanical_row(row)
    if early is not None:
        return early
    if not _is_market_runtime(path):
        if candidates or names:
            return "REVIEW_NONREGISTERED_RUNTIME", "runtime-like path not in market-data allowlist"
        return "NOT_MARKET_DATA", "no market names or Schwab candidates"
    if any(hint in low_code for hint in TRUE_ANALYTIC_HINTS):
        return "TRUE_ANALYTIC_REVIEW", "analytics/model score or strategy transform; verify provenance"
    if candidates and names.intersection(DIRECT_REPLACE_NAMES):
        if tags:
            return "CSV_PRIMITIVE_RISK_REVIEW", "Schwab primitive appears with default/derivation risk"
        return "CSV_PRIMITIVE_CANONICAL_REVIEW", "Schwab primitive referenced; verify canonical normalization"
    if "TIME_NOW_FALLBACK" in tags:
        return "TIME_AUTHORITY_REVIEW", "wall-clock fallback may need Schwab quote/trade timestamp or decision-time split"
    if "BID_ASK_MID" in tags or "ASK_MINUS_BID" in tags:
        return "DERIVED_WITH_PROVENANCE_REVIEW", "bid/ask spread or midpoint derivation needs unit/source contract"
    if tags:
        return "DEFAULT_OR_DERIVATION_REVIEW", "default/derivation in market-data runtime path"
    if candidates:
        return "CSV_FIELD_REFERENCE_REVIEW", "candidate Schwab field reference found"
    return "NOT_MARKET_DATA", "no actionable Schwab-market signal"


def disposition_for(classification: str, row: dict[str, str]) -> tuple[str, str, bool]:
    """Return disposition, rationale, and whether human review is still required."""
    path = row["file"]
    tags = _split(row["tags"])
    names = _split(row["names"])

    if classification in {"NOT_MARKET_RUNTIME", "NOT_MARKET_DATA"}:
        return "NOT_MARKET_DATA", "Excluded from runtime market-data proof surface.", False
    if classification == "CSV_PRIMITIVE_CANONICAL_REVIEW":
        return "CANONICAL_OR_PASS_THROUGH_REVIEWED", "Schwab primitive reference without default/derivation risk.", False
    if classification == "CSV_FIELD_REFERENCE_REVIEW":
        return "REFERENCE_ONLY_REVIEWED", "Candidate field reference only; no risky derivation/default tag.", False
    if classification == "TRUE_ANALYTIC_REVIEW":
        return "KEEP_DERIVED_WITH_PROVENANCE", "True analytic/model/strategy transform; no direct Schwab equivalent.", False
    if classification == "REVIEW_NONREGISTERED_RUNTIME":
        if path.startswith(OFFLINE_TOOL_PREFIXES):
            return "OFFLINE_TOOL_OR_MODEL_REVIEWED", "Offline/tool/model path; keep out of direct Schwab primitive replacement unless promoted.", False
        return "MANUAL_REVIEW_REQUIRED", "Runtime-like path outside allowlist needs human disposition.", True
    if classification == "CSV_PRIMITIVE_RISK_REVIEW":
        if names.intersection(DIRECT_REPLACE_NAMES):
            return "REPLACE_WITH_SCHWAB_OR_GATE", "Schwab primitive appears with default/derivation risk.", True
        return "MANUAL_REVIEW_REQUIRED", "Primitive-risk row needs human disposition.", True
    if classification == "TIME_AUTHORITY_REVIEW":
        if path.startswith("tools/") or path.startswith("db.py"):
            return "KEEP_DERIVED_WITH_PROVENANCE", "Operational/audit wall clock; verify if used as market data timestamp.", True
        return "REPLACE_WITH_SCHWAB_OR_SPLIT_CLOCKS", "Data time should use Schwab quote/trade timestamp; decision time must be labeled.", True
    if classification == "DERIVED_WITH_PROVENANCE_REVIEW":
        return "KEEP_DERIVED_WITH_PROVENANCE", "Derived spread/midpoint requires unit/source provenance.", True
    if classification == "DEFAULT_OR_DERIVATION_REVIEW":
        if tags and not names:
            return "NON_PRIMITIVE_DEFAULT_REVIEWED", "Default/derivation does not reference Schwab primitive name.", False
        return "GATE_FAIL_CLOSED_OR_PROVENANCE", "Market-data default/derivation needs gate or provenance.", True
    return "MANUAL_REVIEW_REQUIRED", "Fallback disposition.", True


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify Schwab CSV crosswalk candidates and emit residuals.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--residual", type=Path, default=DEFAULT_RESIDUAL)
    parser.add_argument("--disposition", type=Path, default=DEFAULT_DISPOSITION)
    args = parser.parse_args()

    rows: list[dict[str, str]] = []
    with args.input.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            classification, reason = classify(row)
            disposition, disposition_reason, manual_review = disposition_for(classification, row)
            row["classification"] = classification
            row["classification_reason"] = reason
            row["disposition"] = disposition
            row["disposition_reason"] = disposition_reason
            row["manual_review_required"] = "yes" if manual_review else "no"
            rows.append(row)

    out_fields = fieldnames + [
        "classification",
        "classification_reason",
        "disposition",
        "disposition_reason",
        "manual_review_required",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(rows)

    residual_classes = {
        "CSV_PRIMITIVE_RISK_REVIEW",
        "TIME_AUTHORITY_REVIEW",
        "DERIVED_WITH_PROVENANCE_REVIEW",
        "DEFAULT_OR_DERIVATION_REVIEW",
        "REVIEW_NONREGISTERED_RUNTIME",
    }
    residual = [r for r in rows if r["classification"] in residual_classes and r["manual_review_required"] == "yes"]
    with args.residual.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(residual)
    with args.disposition.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(r["classification"] for r in rows)
    dispositions = Counter(r["disposition"] for r in rows)
    print(f"input_rows={len(rows)}")
    print(f"classified_output={args.output}")
    print(f"disposition_output={args.disposition}")
    print(f"residual_output={args.residual}")
    for key, value in sorted(counts.items()):
        print(f"{key}={value}")
    for key, value in sorted(dispositions.items()):
        print(f"DISPOSITION_{key}={value}")
    print(f"residual_rows={len(residual)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
