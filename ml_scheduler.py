"""
ml_scheduler.py - Nightly ML Training Scheduler
===============================================
RULE 3: Runs every weekday at 16:15 ET.
For every ticker in EdDB.logging_universe (authoritative enrollment — core + pinned + user_persisted):
  A. Train parallel (XGB, LSTM, Transformer, Meta) → models/parallel/{ticker}/
  B. Train cascade (XGB→LSTM→Transformer) → models/cascade/{ticker}/
  C. Compare both on full RTH
  D. Promote winner to models/active/ or models/active_{hz}/ (governed; all four primaries via --all-horizons)
  E. Write models/arch_state.json + training report

RULE: Do not promote unless provenance validates (timeframe, target, metric).

Cache / reuse (training_cache.py):
  - scheduler_run_manifest.json per candidate dir: skip train+eval when key matches DB fingerprint + versions
  - models/cache/features/{feature_cache_key}/: LSTM npz + parallel Transformer npz (invalidate on data/versions)
"""

from __future__ import annotations

import os
import sys
import json
import logging
import threading
from pathlib import Path

# RC-345/F25: the trainer/scheduler writes artifact filenames and enrollment identity —
# every one delegates to the ONE canonical authority (instrument_identity.ticker_storage_key)
# so the files it WRITES ('$SPX') match what the verifier and predictor LOOK FOR, and match
# the DB storage key. No local .upper() second faucet for artifact/enrollment identity.
from instrument_identity import ticker_storage_key

from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Set
import argparse
import time

APP_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(APP_DIR))

from db import DB_PATH as _DB_PATH_OBJ  # noqa: E402 — after sys.path

DB_PATH = str(_DB_PATH_OBJ)
MODEL_DIR = APP_DIR / "models"
PARALLEL_DIR = MODEL_DIR / "parallel"
CASCADE_DIR = MODEL_DIR / "cascade"
ACTIVE_DIR = MODEL_DIR / "active"
ARCH_STATE_PATH = MODEL_DIR / "arch_state.json"
TRAINING_REPORT_PATH = MODEL_DIR / "training_report.jsonl"
RUN_AT_HOUR = 16
RUN_AT_MINUTE = 15

from time_et import ET

log = logging.getLogger("ml_scheduler")

from ml_horizon import (
    DEFAULT_ML_HORIZON_SLUG,
    normalize_ml_horizon_slug,
    outcome_column,
    target_definition as horizon_target_definition,
)


from ml_scheduler_support import (
    scheduler_arch_state_path,
    scheduler_active_root,
    _now_et,
    _scheduler_auto_promote_to_active,
    _scheduler_skip_parallel_train,
    _append_training_report,
    _apply_pr2_report_fields,
    _resolve_ticker_outcome,
    _is_market_day,
    _wait_until_1615,
)


from ml_scheduler_rth_data import (
    _training_ticker_union,
    _get_tickers_with_rth_data,  # noqa: F401 -- re-export: tests monkeypatch this on the
                                 # ml_scheduler module directly (test_issue22_logging_universe.py)
    _diagnostic_db_tickers_not_enrolled,
    _load_rth_rows_for_ticker,  # noqa: F401 -- re-export: tests monkeypatch this on the
                                # ml_scheduler module directly (test_arch_competition_eval_runner.py)
    _empty_realized_metrics,
    _eval_hist_db_for_labeled_rows,  # noqa: F401 -- re-export: tests monkeypatch this on the
                                     # ml_scheduler module directly (test_arch_competition_eval_runner.py)
)


from ml_scheduler_rth_eval import (
    _evaluate_parallel_on_full_rth,
    _evaluate_cascade_on_full_rth,
)
from ml_scheduler_meta_stack import (
    _meta_ml_layer_triplet,
    _assemble_meta_ml_layer_prob_vectors,
    _write_meta_training_basis_manifest,  # noqa: F401 -- re-export: several tests do
                                          # `from ml_scheduler import _write_meta_training_basis_manifest`
                                          # (test_arch_competition_auto_promote.py, test_manual_governance.py,
                                          # test_ml_feature_provenance.py, test_post_promote_verify_and_rollback.py)
    read_meta_training_basis_manifest,  # noqa: F401 -- re-export: external caller
                                        # arch_competition/promotion_execution.py imports
                                        # `from ml_scheduler import read_meta_training_basis_manifest`
)


from ml_scheduler_parallel_train import (
    _train_parallel_ml_stack_layers_into,
    _train_parallel_meta_oof,  # noqa: F401 -- re-export: tests call this directly via
                               # ml_scheduler._train_parallel_meta_oof (tests/test_oof_stacker.py)
    train_parallel_candidate,  # noqa: F401 -- re-export: external caller train_compare.py
                               # does `from ml_scheduler import train_parallel_candidate`
    _train_parallel,
)


from ml_scheduler_cascade_train import (
    _oof_day_to_fold_map,  # noqa: F401 -- re-export: tests call this directly via
                           # ml_scheduler._oof_day_to_fold_map (tests/test_oof_stacker.py)
    _train_cascade_xgb_lstm_into,  # noqa: F401 -- re-export: tests call this directly via
                                   # ml_scheduler._train_cascade_xgb_lstm_into (tests/test_oof_stacker.py)
    _build_in_sample_cascade_xgb_lstm_tensor,  # noqa: F401 -- re-export: tests do
                                               # `from ml_scheduler import _build_in_sample_cascade_xgb_lstm_tensor`
                                               # (tests/test_ml_feature_schema_parity.py)
    _train_cascade_ml_stack_layers_into,
    _train_cascade_meta_oof,  # noqa: F401 -- re-export: tests call this directly via
                              # ml_scheduler._train_cascade_meta_oof (tests/test_oof_stacker.py)
    _xgb_probs_aligned_to_lstm_dataset,  # noqa: F401 -- re-export: ml_scheduler_parallel_train.py's
                                         # train_parallel_candidate reaches this lazily via
                                         # ml_scheduler._xgb_probs_aligned_to_lstm_dataset
    _train_cascade,
)


def _artifact_paths_relative(out_dir: Path, ticker: str, *, horizon_suffix: str = DEFAULT_ML_HORIZON_SLUG) -> dict[str, str]:
    from training_cache import parallel_artifact_basenames

    rel: dict[str, str] = {}
    for n in parallel_artifact_basenames(ticker, horizon_suffix=horizon_suffix):
        p = out_dir / n
        if p.exists():
            try:
                rel[n] = str(p.relative_to(MODEL_DIR))
            except ValueError:
                rel[n] = str(p.resolve())
    return rel


def aggregate_all_horizons_exit_code(per_horizon_exit_codes) -> int:
    """OR semantics for --all-horizons: any non-zero per-horizon exit fails the whole run."""
    agg = 0
    for code in per_horizon_exit_codes:
        agg |= int(code)
    return agg


def run_once(
    wait: bool = False,
    force_retrain: bool = False,
    bypass_cache: bool = False,
    *,
    allow_non_market_day: bool = False,
    promote_from_manifests_only: bool = False,
    preflip_candidate_root: Path | None = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> dict[str, Any]:
    from training_outcome import TrainingOutcome, compute_run_exit_code, outcome_entry

    run_ticker_outcomes: list[dict[str, Any]] = []
    live_reload_batch: list[dict[str, str]] = []
    hz_sched = normalize_ml_horizon_slug(ml_horizon_slug)
    target_column = outcome_column(hz_sched)
    arch_target_path = scheduler_arch_state_path(hz_sched)
    if wait:
        _wait_until_1615()
    now = _now_et()
    if not allow_non_market_day and not _is_market_day(now):
        log.info(
            "Skipping - not a market day (scheduled mode). "
            "Use --run-now to train on any calendar day when data exists."
        )
        return {"exit_code": 0, "ticker_outcomes": [], "ml_horizon": hz_sched, "skipped": True}

    log.info(
        "ML scheduler run started at %s ET (ml_horizon=%s, label=%s, arch_state=%s)",
        now.strftime("%H:%M"),
        hz_sched,
        target_column,
        arch_target_path.name,
    )

    if not Path(DB_PATH).exists():
        log.warning("DB not found at %s", DB_PATH)
        return {"exit_code": 1, "ticker_outcomes": [], "ml_horizon": hz_sched, "skipped": True}

    _gate_skip = os.environ.get("ED_ML_SCHEDULER_SKIP_PRE_TRAIN_GATE", "").strip().lower()
    if _gate_skip not in ("1", "true", "yes"):
        try:
            from db_health_audit import run_audit
            from audit_model_readiness import evaluate_training_readiness

            _health = run_audit(
                Path(DB_PATH),
                flow_sample=500,
                deep_flow=False,
                flow_tol=0.02,
                strict_flow=False,
            )
            _readiness = evaluate_training_readiness(Path(DB_PATH))
            _gate_reasons: list[str] = []
            if not _health.get("critical_ok"):
                _gate_reasons.append(
                    "db_health_audit critical_ok=false"
                    + (f": {_health.get('fatal')}" if _health.get("fatal") else "")
                )
            if not _readiness.get("training_ok"):
                _gate_reasons.extend(_readiness.get("reasons") or ["audit_model_readiness NO-GO"])
            if _gate_reasons:
                for _gr in _gate_reasons:
                    log.error("pre_train_gate blocked: %s", _gr)
                return {
                    "exit_code": 2,
                    "ticker_outcomes": [],
                    "ml_horizon": hz_sched,
                    "skipped": True,
                    "pre_train_gate_failed": True,
                    "pre_train_gate_reasons": _gate_reasons,
                }
            log.info("pre_train_gate passed (db_health + model readiness GO)")
            from arch_competition.stack_bundle_eval_v1 import ablation_survivors_training_enabled

            if ablation_survivors_training_enabled():
                from tools.feature_curation_gate import run_survivor_retrain_preflight

                from scheduler_user_tickers import TRAINING_ANCHOR_TICKERS

                _core = list(TRAINING_ANCHOR_TICKERS)
                _spf = run_survivor_retrain_preflight(db_path=str(DB_PATH), tickers=_core)
                if not _spf.get("ready"):
                    _gate_reasons = list(_spf.get("issues") or ["survivor_retrain_preflight_failed"])
                    for _gr in _gate_reasons:
                        log.error("survivor_retrain_preflight blocked: %s", _gr)
                    return {
                        "exit_code": 2,
                        "ticker_outcomes": [],
                        "ml_horizon": hz_sched,
                        "skipped": True,
                        "pre_train_gate_failed": True,
                        "pre_train_gate_reasons": _gate_reasons,
                    }
                log.info("survivor_retrain_preflight passed (confirm pass + floors)")
        except Exception as _gate_exc:
            log.error("pre_train_gate error (fail-closed): %s", _gate_exc, exc_info=True)
            return {
                "exit_code": 2,
                "ticker_outcomes": [],
                "ml_horizon": hz_sched,
                "skipped": True,
                "pre_train_gate_failed": True,
                "pre_train_gate_reasons": [str(_gate_exc)],
            }
    else:
        log.warning("pre_train_gate skipped (ED_ML_SCHEDULER_SKIP_PRE_TRAIN_GATE)")

    try:
        from normalized_training_sync import ensure_normalized_training_table

        _ns = ensure_normalized_training_table(DB_PATH, force=False, logger=log)
        if not _ns.get("ok"):
            log.warning("normalized_training_sync failed before training: %s", _ns.get("errors"))
        elif _ns.get("materialized"):
            log.info(
                "snapshots_1m_normalized rematerialized: %s rows",
                (_ns.get("materialize") or {}).get("normalized_rows"),
            )
    except Exception as _e:
        log.warning("normalized_training_sync error (continuing): %s", _e)

    # One sync at scheduler entry; block per-row load_data/extract re-entry for this process
    # (avoids snapshot_id UNIQUE races with the live server's debounced materialize mid-train).
    os.environ["ED_TRAINING_SKIP_INLINE_NORMSYNC"] = "1"

    tickers = _training_ticker_union(DB_PATH, label_column=target_column)
    if not tickers:
        log.warning(
            "No tickers: logging_universe enrollment empty. "
            "Enroll via UI/API (user_persisted/pinned), ensure sync_core rows exist, or run server once; "
            "legacy user_scheduler_tickers.json migrates once. "
            "Training also needs labeled RTH rows per ticker in snapshots_1m_normalized."
        )
        return {"exit_code": 0, "ticker_outcomes": [], "ml_horizon": hz_sched, "skipped": True}
    try:
        db_only = _diagnostic_db_tickers_not_enrolled(DB_PATH, tickers, label_column=target_column)
        if db_only:
            log.info(
                "Diagnostic (not enrolled): %d ticker(s) have labeled RTH rows but are absent from "
                "logging_universe — skipped unless enrolled: %s%s",
                len(db_only),
                db_only[:30],
                "…" if len(db_only) > 30 else "",
            )
    except Exception as e:
        log.debug("db_only ticker diagnostic block failed: %s", e, exc_info=True)

    from scheduler_user_tickers import resolve_ml_training_roster

    _before_roster = len(tickers)
    tickers = resolve_ml_training_roster(tickers, DB_PATH)
    if len(tickers) < _before_roster:
        log.info(
            "ML training roster: %d of %d enrolled tickers scheduled (anchors + guest policy)",
            len(tickers),
            _before_roster,
        )

    _pfx = " (promote-from-manifests-only)" if promote_from_manifests_only else ""
    log.info("Tickers (logging_universe authoritative): %s%s", tickers, _pfx)

    from arch_competition.stack_bundle_eval_v1 import ablation_survivors_training_enabled

    if ablation_survivors_training_enabled():
        from arch_competition.promotion_execution import (
            ensure_survivor_retrain_incumbent_reset_at_run_start,
        )
        from tools.feature_curation_gate import (
            run_survivor_edge_probe,
            run_survivor_stack_refit_backtest,
            run_survivor_validation_run,
        )

        _inc_reset = ensure_survivor_retrain_incumbent_reset_at_run_start(MODEL_DIR, tickers)
        log.info(
            "survivor_retrain incumbent reset for scheduled tickers: reset_count=%s reason=%s",
            _inc_reset.get("reset_count"),
            _inc_reset.get("reason"),
        )
        _backtest = run_survivor_stack_refit_backtest(
            tickers=tickers[:3] or None,
            db_path=str(DB_PATH),
        )
        if not _backtest.get("ready_for_production"):
            log.error(
                "survivor_stack_refit_backtest blocked retrain: issues=%s summary=%s",
                _backtest.get("issues"),
                _backtest.get("summary"),
            )
            return {
                "exit_code": 2,
                "ticker_outcomes": [],
                "ml_horizon": hz_sched,
                "skipped": True,
                "pre_train_gate_failed": True,
                "pre_train_gate_reasons": list(
                    _backtest.get("issues") or ["survivor_stack_refit_backtest_failed"]
                ),
            }
        log.info(
            "survivor_stack_refit_backtest passed: summary=%s",
            _backtest.get("summary"),
        )
        _edge = run_survivor_edge_probe(tickers=tickers[:3] or None)
        if not _edge.get("ready_for_full_retrain"):
            log.error(
                "survivor_edge_probe blocked retrain: issues=%s",
                _edge.get("issues"),
            )
            return {
                "exit_code": 2,
                "ticker_outcomes": [],
                "ml_horizon": hz_sched,
                "skipped": True,
                "pre_train_gate_failed": True,
                "pre_train_gate_reasons": list(_edge.get("issues") or ["survivor_edge_probe_failed"]),
            }
        log.info(
            "survivor_edge_probe passed: edge_cells=%s",
            (_edge.get("summary") or {}).get("edge_cells"),
        )
        _val = run_survivor_validation_run(tickers=tickers[:3] or None, db_path=str(DB_PATH))
        if not _val.get("ready_for_full_retrain"):
            log.error(
                "survivor_validation_run blocked retrain: issues=%s",
                _val.get("issues"),
            )
            return {
                "exit_code": 2,
                "ticker_outcomes": [],
                "ml_horizon": hz_sched,
                "skipped": True,
                "pre_train_gate_failed": True,
                "pre_train_gate_reasons": list(_val.get("issues") or ["survivor_validation_run_failed"]),
            }
        log.info(
            "survivor_validation_run passed: cells=%s",
            len(_val.get("cells") or []),
        )

    # DATA-PIPELINE-INTEGRITY-CHAIN Pass 2 (2026-05-26): MVP coercion preflight
    # gate. Catches the row-0 NaN class of failure in seconds instead of after
    # a multi-hour wall-time run. Pass 1 (fd0accd) fixed the NaN-from-pandas
    # root cause; this gate ensures any FUTURE regression of similar shape is
    # caught early. Tickers that fail are excluded from the run with a
    # preflight_failed outcome (distinct from train_failed); the run aborts
    # only if no tickers survive.
    try:
        from features.training_canonical_input import preflight_tickers_for_training

        _pf = preflight_tickers_for_training(DB_PATH, tickers, sample_rows=100)
        if _pf["tickers_failed"]:
            log.warning(
                "preflight: %d of %d tickers failed MVP coercion in %.2fs — excluded from run",
                len(_pf["tickers_failed"]),
                len(tickers),
                _pf["elapsed_sec"],
            )
            for _failed_ticker, _err in _pf["tickers_failed"].items():
                log.warning("  preflight_failed %s: %s", _failed_ticker, _err)
                run_ticker_outcomes.append(
                    outcome_entry(
                        ticker=_failed_ticker,
                        horizon=hz_sched,
                        outcome=TrainingOutcome.preflight_failed,
                        extra={"error": _err, "stage": "preflight"},
                    )
                )
            tickers = [t for t in tickers if t not in _pf["tickers_failed"]]
            if not tickers:
                log.error(
                    "preflight: ALL selected tickers failed MVP coercion; aborting run "
                    "(elapsed=%.2fs). See OPEN_ITEMS DATA-PIPELINE-INTEGRITY-CHAIN.",
                    _pf["elapsed_sec"],
                )
                try:
                    from training_pipeline_status import record_run_finish

                    record_run_finish(
                        ml_horizon=hz_sched,
                        ticker_outcomes=run_ticker_outcomes,
                        exit_code_hint=1,
                    )
                except Exception as _tps_e2:
                    log.debug("record_run_finish on preflight abort: %s", _tps_e2, exc_info=True)
                return {
                    "exit_code": 1,
                    "ticker_outcomes": run_ticker_outcomes,
                    "ml_horizon": hz_sched,
                    "skipped": False,
                    "preflight_blocked": True,
                }
        else:
            log.info(
                "preflight OK: %d of %d tickers passed MVP coercion in %.2fs",
                len(_pf["tickers_ok"]),
                len(tickers),
                _pf["elapsed_sec"],
            )
        if _pf["tickers_no_data"]:
            log.info(
                "preflight: %d tickers had no normalized rows yet (training will skip them naturally): %s",
                len(_pf["tickers_no_data"]),
                _pf["tickers_no_data"][:30],
            )
    except Exception as _pf_e:
        # Preflight gate must NOT itself block a working training run — fail
        # open with a loud warning. The gate is best-effort prevention; the
        # worst case if it errors is the same 65-min wall-time as today.
        log.warning(
            "preflight gate errored (continuing without it — see DATA-PIPELINE-INTEGRITY-CHAIN): %s",
            _pf_e,
            exc_info=True,
        )
    try:
        from training_pipeline_status import enrollment_category_counts, record_run_start

        _enroll_counts = enrollment_category_counts(DB_PATH)
        log.info("Enrolled universe category counts: %s", _enroll_counts)
        record_run_start(
            ml_horizon=hz_sched,
            target_column=target_column,
            tickers=tickers,
            db_path=DB_PATH,
        )
    except Exception as _tps_e:
        log.debug("training_pipeline_status record_run_start: %s", _tps_e, exc_info=True)

    arch_state = {}
    if arch_target_path.exists():
        try:
            arch_state = json.loads(arch_target_path.read_text())
        except Exception:
            arch_state = {}

    for ticker in tickers:
        try:
            from training_cache import (
                db_training_fingerprint,
                compute_training_code_fingerprint,
                compute_scheduler_cache_key,
                compute_feature_cache_key,
                load_run_manifest,
                save_run_manifest,
                build_manifest,
                full_skip_eligible,
                compute_artifact_sha256_map,
                parallel_artifact_basenames,
                cascade_artifact_basenames,
                archive_candidate_directory_before_train,
            )
            from training_cache_policy import (
                ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
                ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
                MAX_CONSECUTIVE_SCHEDULER_SKIPS,
            )
            from training_provenance import (
                load_provenance,
            )
            from timeframe_config import CANONICAL_TIMEFRAME

            data_fp = db_training_fingerprint(DB_PATH, ticker, label_column=target_column)
            if int(data_fp.get("row_count") or 0) < 1:
                log.info(
                    "%s: skip — no RTH labeled rows for %s in snapshots_1m_normalized (needed for training)",
                    ticker,
                    target_column,
                )
                continue
            code_fp = compute_training_code_fingerprint()

            # Workstream B1 — single authoritative walk-forward split (shared fn).
            # Train on earlier sessions; evaluate (incl. the governed promotion eval) only
            # on the strictly-later held-out tail, so eval rows are provably disjoint from
            # train rows. Thin tickers (< WALK_FORWARD_MIN_TOTAL_SESSIONS) cannot carve a
            # holdout → fall back to full-RTH (in-sample, NOT promotion-clean; A1 floor still
            # gates promotion). NOTE: passing allowed_et_dates overrides the per-stream
            # ROLLING_WINDOW_RTH_SESSIONS_* windows (both default 0 = full history), matching
            # the train_compare reference; revisit if per-stream windowing is enabled.
            from training_cache import walk_forward_session_split, WALK_FORWARD_MIN_TOTAL_SESSIONS

            wf_train_days, wf_val_days = walk_forward_session_split(
                DB_PATH, ticker, label_column=target_column
            )
            if wf_val_days:
                wf_train_dates: Optional[Set[str]] = set(wf_train_days)
                wf_eval_dates: Optional[Set[str]] = set(wf_val_days)
                assert wf_train_dates.isdisjoint(wf_eval_dates), "walk-forward train/eval overlap"
                log.info(
                    "%s: walk-forward split — train %d sessions, eval %d held-out sessions (%s..%s)",
                    ticker, len(wf_train_days), len(wf_val_days), wf_val_days[0], wf_val_days[-1],
                )
            else:
                wf_train_dates = None
                wf_eval_dates = None
                log.warning(
                    "%s: < %d RTH sessions — walk-forward holdout unavailable; training+eval on "
                    "full RTH (in-sample, not promotion-clean)",
                    ticker, WALK_FORWARD_MIN_TOTAL_SESSIONS,
                )
            fk = compute_feature_cache_key(ticker, data_fp, code_fp, target_column=target_column)
            parallel_key = compute_scheduler_cache_key(
                ticker, "parallel", data_fp, code_fp, target_column=target_column,
            )
            cascade_key = compute_scheduler_cache_key(
                ticker, "cascade", data_fp, code_fp, target_column=target_column,
            )
            parallel_out = PARALLEL_DIR / ticker_storage_key(ticker)  # RC-345/F25: one identity
            cascade_out = CASCADE_DIR / ticker_storage_key(ticker)
            if preflip_candidate_root is not None:
                frozen_t = preflip_candidate_root / ticker_storage_key(ticker)
                parallel_out = frozen_t / "parallel"
                cascade_out = frozen_t / "cascade"
            run_ts = _now_et().isoformat()
            utc_now = datetime.now(timezone.utc)
            _gov_manifest: dict[str, Any] | None = None
            _gov_record: dict[str, Any] | None = None
            auto_exec_result: dict[str, Any] = {}
            skip_train = bool(promote_from_manifests_only or preflip_candidate_root is not None)

            if skip_train:
                parallel_man = load_run_manifest(parallel_out)
                cascade_man = load_run_manifest(cascade_out)
                if not parallel_man or not cascade_man:
                    log.warning(
                        "%s: --promote-from-manifests skipped (parallel and/or cascade manifest missing)",
                        ticker,
                    )
                    continue
                pe = parallel_man.get("evaluation") or {}
                ce = cascade_man.get("evaluation") or {}
                if not pe or not ce:
                    log.warning(
                        "%s: --promote-from-manifests skipped (evaluation missing)",
                        ticker,
                    )
                    continue
                mf_hz = normalize_ml_horizon_slug(
                    parallel_man.get("ml_horizon_suffix") or cascade_man.get("ml_horizon_suffix") or hz_sched
                )
                if not (parallel_out / f"xgb_{ticker_storage_key(ticker)}_{mf_hz}.pkl").exists():
                    log.warning(
                        "%s: --promote-from-manifests skipped (parallel xgb missing for horizon %s)",
                        ticker,
                        mf_hz,
                    )
                    continue
                if not (cascade_out / f"xgb_{ticker_storage_key(ticker)}_{mf_hz}.pkl").exists():
                    log.warning(
                        "%s: --promote-from-manifests skipped (cascade xgb missing for horizon %s)",
                        ticker,
                        mf_hz,
                    )
                    continue
                mf_code = parallel_man.get("training_code_fingerprint")
                code_fp = mf_code if isinstance(mf_code, str) and mf_code else compute_training_code_fingerprint()
                mf_df = parallel_man.get("data_fingerprint")
                data_fp = mf_df if isinstance(mf_df, dict) and mf_df else data_fp
                fk_mf = parallel_man.get("feature_cache_key")
                _tc_promo = outcome_column(mf_hz)
                fk = fk_mf if isinstance(fk_mf, str) and fk_mf else compute_feature_cache_key(
                    ticker, data_fp, code_fp, target_column=_tc_promo,
                )
                pk_mf = parallel_man.get("scheduler_cache_key")
                parallel_key = (
                    pk_mf
                    if isinstance(pk_mf, str) and pk_mf
                    else compute_scheduler_cache_key(
                        ticker, "parallel", data_fp, code_fp, target_column=_tc_promo,
                    )
                )
                ck_mf = cascade_man.get("scheduler_cache_key")
                cascade_key = (
                    ck_mf
                    if isinstance(ck_mf, str) and ck_mf
                    else compute_scheduler_cache_key(
                        ticker, "cascade", data_fp, code_fp, target_column=_tc_promo,
                    )
                )
                par_streak_prev = int(parallel_man.get("consecutive_scheduler_skips", 0) or 0)
                cas_streak_prev = int(cascade_man.get("consecutive_scheduler_skips", 0) or 0)
                par_skip_reason = "promote_from_manifests_only"
                cas_skip_reason = "promote_from_manifests_only"
                par_retrain_reason = None
                cas_retrain_reason = None
                par_miss_reason = None
                cas_miss_reason = None
                parallel_skip = True
                cascade_skip = True
                evp = pe
                evc = ce
                parallel_acc = float(evp.get("eval_accuracy", 0.0))
                parallel_bal = float(evp.get("balanced_accuracy", 0.0))
                n_rows = int(evp.get("n_rows", 0))
                parallel_ll = evp.get("eval_log_loss")
                if parallel_ll is not None:
                    parallel_ll = float(parallel_ll)
                _prm = evp.get("realized_contract_metrics")
                parallel_realized_metrics = (
                    dict(_prm) if isinstance(_prm, dict) else _empty_realized_metrics(n_rows)
                )
                cascade_acc = float(evc.get("eval_accuracy", 0.0))
                cascade_bal = float(evc.get("balanced_accuracy", 0.0))
                n_cascade_rows = int(evc.get("n_rows", 0))
                cascade_ll = evc.get("eval_log_loss")
                if cascade_ll is not None:
                    cascade_ll = float(cascade_ll)
                _crm = evc.get("realized_contract_metrics")
                cascade_realized_metrics = (
                    dict(_crm) if isinstance(_crm, dict) else _empty_realized_metrics(n_cascade_rows)
                )
                par_skipped_train = True
                par_skipped_eval = True
                cas_skipped_train = True
                cas_skipped_eval = True
                par_used_fc = bool(parallel_man.get("used_feature_cache", False))
                par_used_ctc = bool(parallel_man.get("used_cascade_tensor_cache", False))
                pm_trained_at = str(parallel_man.get("trained_at", run_ts))
                par_warm_resume = parallel_man.get("warm_resume") or {}
                cas_used_fc = bool(cascade_man.get("used_feature_cache", False))
                cas_used_ctc = bool(cascade_man.get("used_cascade_tensor_cache", False))
                cas_used_bridge = bool(cascade_man.get("used_parallel_cascade_bridge", False))
                cm_trained_at = str(cascade_man.get("trained_at", run_ts))
                cas_warm_resume = cascade_man.get("warm_resume") or {}
                log.info(
                    "%s: skip train (%s)",
                    ticker,
                    "preflip frozen candidates" if preflip_candidate_root else "--promote-from-manifests",
                )
            else:
                parallel_man = load_run_manifest(parallel_out) if not bypass_cache else None
                cascade_man = load_run_manifest(cascade_out) if not bypass_cache else None

                par_streak_prev = int(parallel_man.get("consecutive_scheduler_skips", 0) or 0) if parallel_man else 0
                cas_streak_prev = int(cascade_man.get("consecutive_scheduler_skips", 0) or 0) if cascade_man else 0
                par_inhibit = (
                    not bypass_cache
                    and not force_retrain
                    and MAX_CONSECUTIVE_SCHEDULER_SKIPS > 0
                    and par_streak_prev >= MAX_CONSECUTIVE_SCHEDULER_SKIPS
                )
                cas_inhibit = (
                    not bypass_cache
                    and not force_retrain
                    and MAX_CONSECUTIVE_SCHEDULER_SKIPS > 0
                    and cas_streak_prev >= MAX_CONSECUTIVE_SCHEDULER_SKIPS
                )
                if par_inhibit:
                    log.info(
                        "%s: parallel — consecutive skips %d >= cap %d, forcing train",
                        ticker,
                        par_streak_prev,
                        MAX_CONSECUTIVE_SCHEDULER_SKIPS,
                    )
                if cas_inhibit:
                    log.info(
                        "%s: cascade — consecutive skips %d >= cap %d, forcing train",
                        ticker,
                        cas_streak_prev,
                        MAX_CONSECUTIVE_SCHEDULER_SKIPS,
                    )

                par_elig, par_skip_reason, par_retrain_reason, par_miss_reason = full_skip_eligible(
                    parallel_man,
                    parallel_key,
                    data_fp,
                    code_fp,
                    parallel_out,
                    ticker,
                    "parallel",
                    bypass_cache=bypass_cache,
                    force_retrain=force_retrain,
                    skip_inhibit_reason="max_consecutive_scheduler_skips" if par_inhibit else None,
                    now=utc_now,
                    horizon_suffix=hz_sched,
                )
                parallel_skip = par_elig

                cas_elig, cas_skip_reason, cas_retrain_reason, cas_miss_reason = full_skip_eligible(
                    cascade_man,
                    cascade_key,
                    data_fp,
                    code_fp,
                    cascade_out,
                    ticker,
                    "cascade",
                    bypass_cache=bypass_cache,
                    force_retrain=force_retrain,
                    skip_inhibit_reason="max_consecutive_scheduler_skips" if cas_inhibit else None,
                    now=utc_now,
                    horizon_suffix=hz_sched,
                )
                cascade_skip = cas_elig

            if not skip_train:
                parallel_ll: Optional[float] = None
                parallel_realized_metrics: dict[str, Any] = _empty_realized_metrics(0)
                cascade_ll: Optional[float] = None
                cascade_realized_metrics: dict[str, Any] = _empty_realized_metrics(0)
                n_cascade_rows: int = 0
                cas_used_bridge: bool = False

            if not skip_train and parallel_skip:
                log.info("%s: parallel scheduler cache hit — skip train + eval (key=%s…)", ticker, parallel_key[:12])
                evp = parallel_man.get("evaluation") or {}
                parallel_acc = float(evp.get("eval_accuracy", 0.0))
                parallel_bal = float(evp.get("balanced_accuracy", 0.0))
                n_rows = int(evp.get("n_rows", 0))
                parallel_ll = evp.get("eval_log_loss")
                _prm = evp.get("realized_contract_metrics")
                parallel_realized_metrics = (
                    dict(_prm) if isinstance(_prm, dict) else _empty_realized_metrics(n_rows)
                )
                if parallel_ll is not None:
                    parallel_ll = float(parallel_ll)
                par_skipped_train = True
                par_skipped_eval = True
                par_used_fc = bool(parallel_man.get("used_feature_cache", False))
                par_used_ctc = bool(parallel_man.get("used_cascade_tensor_cache", False))
                pm_trained_at = str(parallel_man.get("trained_at", run_ts))
                par_warm_resume = parallel_man.get("warm_resume") or {}
            elif not skip_train and _scheduler_skip_parallel_train():
                log.info(
                    "%s: parallel train skipped (ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN); eval existing artifacts",
                    ticker,
                )
                parallel_acc, parallel_bal, n_rows, parallel_ll, parallel_realized_metrics = (
                    _evaluate_parallel_on_full_rth(
                        DB_PATH,
                        ticker,
                        parallel_out,
                        allowed_et_dates=wf_eval_dates,
                        target_column=target_column,
                    )
                )
                par_skipped_train = True
                par_skipped_eval = False
                par_used_fc = bool((parallel_man or {}).get("used_feature_cache", False))
                par_used_ctc = bool((parallel_man or {}).get("used_cascade_tensor_cache", False))
                pm_trained_at = str((parallel_man or {}).get("trained_at", run_ts))
                par_warm_resume = (parallel_man or {}).get("warm_resume") or {}
            elif not skip_train:
                log.info("%s: Training parallel...", ticker)
                archive_candidate_directory_before_train(parallel_out, MODEL_DIR, "parallel", ticker)
                par_ret = _train_parallel(
                    ticker,
                    DB_PATH,
                    allowed_et_dates=wf_train_dates,
                    bypass_cache=bypass_cache,
                    data_fp=data_fp,
                    code_fp=code_fp,
                    scheduler_cache_key=parallel_key,
                    feature_cache_key=fk,
                    prior_manifest=parallel_man,
                    ml_horizon_slug=hz_sched,
                )
                parallel_acc, parallel_bal, n_rows, parallel_ll, parallel_realized_metrics = (
                    _evaluate_parallel_on_full_rth(
                        DB_PATH, ticker, parallel_out,
                        allowed_et_dates=wf_eval_dates, target_column=target_column,
                    )
                )
                par_skipped_train = False
                par_skipped_eval = False
                par_used_fc = bool(par_ret.get("used_feature_cache", False))
                par_used_ctc = bool(par_ret.get("used_cascade_tensor_cache", False))
                pm_trained_at = run_ts
                par_warm_resume = par_ret.get("warm_resume") or {}

            if not skip_train and cascade_skip:
                log.info("%s: cascade scheduler cache hit — skip train + eval (key=%s…)", ticker, cascade_key[:12])
                evc = cascade_man.get("evaluation") or {}
                cascade_acc = float(evc.get("eval_accuracy", 0.0))
                cascade_bal = float(evc.get("balanced_accuracy", 0.0))
                n_cascade_rows = int(evc.get("n_rows", 0))
                cascade_ll = evc.get("eval_log_loss")
                _crm = evc.get("realized_contract_metrics")
                cascade_realized_metrics = (
                    dict(_crm) if isinstance(_crm, dict) else _empty_realized_metrics(n_cascade_rows)
                )
                if cascade_ll is not None:
                    cascade_ll = float(cascade_ll)
                cas_skipped_train = True
                cas_skipped_eval = True
                cas_used_fc = bool(cascade_man.get("used_feature_cache", False))
                cas_used_ctc = bool(cascade_man.get("used_cascade_tensor_cache", False))
                cas_used_bridge = bool(cascade_man.get("used_parallel_cascade_bridge", False))
                cm_trained_at = str(cascade_man.get("trained_at", run_ts))
                cas_warm_resume = cascade_man.get("warm_resume") or {}
            elif not skip_train:
                log.info("%s: Training cascade...", ticker)
                archive_candidate_directory_before_train(cascade_out, MODEL_DIR, "cascade", ticker)
                cas_ret = _train_cascade(
                    ticker,
                    DB_PATH,
                    allowed_et_dates=wf_train_dates,
                    bypass_cache=bypass_cache,
                    data_fp=data_fp,
                    code_fp=code_fp,
                    scheduler_cache_key=cascade_key,
                    feature_cache_key=fk,
                    prior_manifest=cascade_man,
                    ml_horizon_slug=hz_sched,
                    parallel_out=parallel_out,
                )
                cascade_acc, cascade_bal, n_cascade_rows, cascade_ll, cascade_realized_metrics = (
                    _evaluate_cascade_on_full_rth(
                        DB_PATH, ticker, cascade_out,
                        allowed_et_dates=wf_eval_dates, target_column=target_column,
                    )
                )
                cas_skipped_train = False
                cas_skipped_eval = False
                cas_used_fc = bool(cas_ret.get("used_feature_cache", False))
                cas_used_ctc = bool(cas_ret.get("used_cascade_tensor_cache", False))
                cas_used_bridge = bool(cas_ret.get("used_parallel_cascade_bridge", False))
                cm_trained_at = run_ts
                cas_warm_resume = cas_ret.get("warm_resume") or {}

            from training_cache import sync_candidate_manifest_lineage_before_governed_eval
            from active_bundle_contract import candidate_bundles_complete
            from training_pipeline_status import get_cache_skip_streak

            artifact_complete, _par_bundle_chk, _cas_bundle_chk = candidate_bundles_complete(
                ticker, hz_sched, parallel_out, cascade_out
            )
            consecutive_cache_skips = get_cache_skip_streak(ticker, hz_sched)
            skip_governed_eval = not artifact_complete

            governed_slice: Optional[dict[str, Any]] = None
            governed_paths: Optional[dict[str, str]] = None

            if skip_governed_eval:
                log.warning(
                    "%s: partial candidate bundle — skip governed eval (parallel_ok=%s cascade_ok=%s)",
                    ticker,
                    _par_bundle_chk.get("compliant"),
                    _cas_bundle_chk.get("compliant"),
                )
                governed_slice = {
                    "schema_version": "1",
                    "error": "partial_candidate_bundle",
                    "failed_closed": True,
                    "issues": {
                        "parallel": _par_bundle_chk.get("issues", []),
                        "cascade": _cas_bundle_chk.get("issues", []),
                    },
                }
            else:
                _lineage_par_eval = {
                    "eval_accuracy": round(parallel_acc, 6),
                    "balanced_accuracy": round(parallel_bal, 6),
                    "n_rows": n_rows,
                    **(
                        {"eval_log_loss": round(parallel_ll, 6)}
                        if parallel_ll is not None
                        else {}
                    ),
                    "realized_contract_metrics": parallel_realized_metrics,
                }
                _lineage_cas_eval = {
                    "eval_accuracy": round(cascade_acc, 6),
                    "balanced_accuracy": round(cascade_bal, 6),
                    "n_rows": n_cascade_rows,
                    **(
                        {"eval_log_loss": round(cascade_ll, 6)}
                        if cascade_ll is not None
                        else {}
                    ),
                    "realized_contract_metrics": cascade_realized_metrics,
                }
                sync_candidate_manifest_lineage_before_governed_eval(
                    parallel_out,
                    ticker=ticker,
                    architecture="parallel",
                    ml_horizon_suffix=hz_sched,
                    scheduler_cache_key=parallel_key,
                    feature_cache_key=fk,
                    data_fp=data_fp,
                    training_code_fingerprint=code_fp,
                    evaluation=_lineage_par_eval,
                    trained_at=pm_trained_at,
                )
                sync_candidate_manifest_lineage_before_governed_eval(
                    cascade_out,
                    ticker=ticker,
                    architecture="cascade",
                    ml_horizon_suffix=hz_sched,
                    scheduler_cache_key=cascade_key,
                    feature_cache_key=fk,
                    data_fp=data_fp,
                    training_code_fingerprint=code_fp,
                    evaluation=_lineage_cas_eval,
                    trained_at=cm_trained_at,
                )

                try:
                    from arch_competition.scheduler_integration import (
                        build_governed_arch_state_slice,
                        run_governed_architecture_competition_pass,
                        scheduler_auto_promote_to_active_enabled,
                    )

                    _gov = run_governed_architecture_competition_pass(
                        model_dir=MODEL_DIR,
                        db_path=DB_PATH,
                        ticker=ticker,
                        parallel_model_dir=parallel_out,
                        cascade_model_dir=cascade_out,
                        ml_horizon_slug=hz_sched,
                        allowed_et_dates=wf_eval_dates,
                    )
                    _man = _gov["evaluation_manifest"]
                    _prec = _gov["promotion_record"]
                    _gov_manifest = _man
                    _gov_record = _prec
                    governed_paths = _gov["paths"]
                    parallel_acc = float(_man["metrics"]["parallel"]["accuracy"])
                    parallel_bal = float(_man["metrics"]["parallel"]["balanced_accuracy"])
                    n_rows = int(_man["metrics"]["parallel"]["n_rows_scored"])
                    _pll = _man["metrics"]["parallel"].get("log_loss")
                    parallel_ll = float(_pll) if _pll is not None else None
                    _prm = _man["metrics"]["parallel"].get("realized_contract_metrics")
                    parallel_realized_metrics = (
                        dict(_prm) if isinstance(_prm, dict) else _empty_realized_metrics(n_rows)
                    )
                    cascade_acc = float(_man["metrics"]["cascade"]["accuracy"])
                    cascade_bal = float(_man["metrics"]["cascade"]["balanced_accuracy"])
                    n_cascade_rows = int(_man["metrics"]["cascade"]["n_rows_scored"])
                    _cll = _man["metrics"]["cascade"].get("log_loss")
                    cascade_ll = float(_cll) if _cll is not None else None
                    _crm = _man["metrics"]["cascade"].get("realized_contract_metrics")
                    cascade_realized_metrics = (
                        dict(_crm) if isinstance(_crm, dict) else _empty_realized_metrics(n_cascade_rows)
                    )
                    governed_slice = build_governed_arch_state_slice(
                        manifest=_man,
                        promotion_record=_prec,
                        paths=_gov["paths"],
                        auto_promote_to_active=scheduler_auto_promote_to_active_enabled(),
                    )
                except Exception as _gov_e:
                    log.exception(
                        "%s: governed architecture competition pass failed: %s",
                        ticker,
                        _gov_e,
                    )
                    governed_slice = {
                        "schema_version": "1",
                        "error": str(_gov_e),
                        "failed_closed": True,
                    }

            try:
                from realized_contract_eval import save_eval_aggregate_merge

                if not parallel_skip:
                    save_eval_aggregate_merge(ticker, "parallel", parallel_realized_metrics, run_ts)
                if not cascade_skip:
                    save_eval_aggregate_merge(ticker, "cascade", cascade_realized_metrics, run_ts)
            except Exception as _sa_e:
                log.warning("realized aggregate save: %s", _sa_e)

            active_root = scheduler_active_root(hz_sched)
            active_dir = active_root / ticker_storage_key(ticker)  # RC-345/F25: one identity
            active_dir.mkdir(parents=True, exist_ok=True)

            parallel_xgb_meta = parallel_out / f"xgb_{ticker_storage_key(ticker)}_{hz_sched}_meta.json"
            cascade_xgb_meta = cascade_out / f"xgb_{ticker_storage_key(ticker)}_{hz_sched}_meta.json"
            parallel_prov = load_provenance(parallel_xgb_meta) if parallel_xgb_meta.exists() else None
            cascade_prov = load_provenance(cascade_xgb_meta) if cascade_xgb_meta.exists() else None

            pprov = parallel_prov or cascade_prov
            report = {
                "ticker": ticker,
                "model_type": "ensemble",
                "training_timeframe": CANONICAL_TIMEFRAME,
                "ml_horizon_suffix": hz_sched,
                "target_column": target_column,
                "target_definition": horizon_target_definition(hz_sched),
                "train_start": pprov.train_start if pprov else "",
                "train_end": pprov.train_end if pprov else "",
                "rows_used": n_rows,
                "eval_accuracy": round(parallel_acc, 4),
                "eval_accuracy_cascade": round(cascade_acc, 4),
                "balanced_accuracy": round(parallel_bal, 4),
                "balanced_accuracy_cascade": round(cascade_bal, 4),
                "eval_log_loss": round(parallel_ll, 6) if parallel_ll is not None else None,
                "eval_log_loss_cascade": round(cascade_ll, 6) if cascade_ll is not None else None,
                "eval_pnl_realized_contract": parallel_realized_metrics.get("eval_pnl_realized_contract"),
                "eval_pnl_realized_contract_cascade": cascade_realized_metrics.get(
                    "eval_pnl_realized_contract"
                ),
                "realized_contract_metrics": parallel_realized_metrics,
                "realized_contract_metrics_cascade": cascade_realized_metrics,
                "realized_parallel_cascade_comparison": None,
                "promoted": False,
                "promotion_reason": "",
                "rejection_reason": "",
                "parallel_cache_skip": parallel_skip,
                "cascade_cache_skip": cascade_skip,
                "bypass_cache": bypass_cache,
                "governed_competition": governed_slice,
                "governed_artifact_paths": governed_paths,
                "auto_promote_to_active": _scheduler_auto_promote_to_active(),
            }
            try:
                from realized_contract_eval import compare_parallel_cascade_trade_logs

                report["realized_parallel_cascade_comparison"] = compare_parallel_cascade_trade_logs()
            except Exception as e:
                log.debug(
                    "compare_parallel_cascade_trade_logs failed: %s",
                    e,
                    exc_info=True,
                )

            # Diagnostic log-loss winner only — production copy uses governed promotion_record (PR4).
            _par_avg = parallel_realized_metrics.get("eval_pnl_realized_contract")
            _cas_avg = cascade_realized_metrics.get("eval_pnl_realized_contract")
            _pnl_tie_parallel = (
                (float("-inf") if _par_avg is None else float(_par_avg))
                >= (float("-inf") if _cas_avg is None else float(_cas_avg))
            )
            if parallel_ll is not None and cascade_ll is not None:
                parallel_wins = parallel_ll < cascade_ll - 1e-9 or (
                    abs(parallel_ll - cascade_ll) <= 1e-9
                    and (
                        parallel_acc > cascade_acc
                        or (
                            parallel_acc == cascade_acc
                            and (
                                parallel_bal > cascade_bal
                                or (parallel_bal == cascade_bal and _pnl_tie_parallel)
                            )
                        )
                    )
                )
            else:
                parallel_wins = parallel_acc > cascade_acc or (
                    parallel_acc == cascade_acc and parallel_bal >= cascade_bal
                )
            report["scheduler_log_loss_winner"] = "parallel" if parallel_wins else "cascade"

            promoted = False
            reason = ""
            auto_active = _scheduler_auto_promote_to_active()
            production_write_held = True
            auto_exec_result: dict[str, Any] = {}

            if (
                isinstance(governed_slice, dict)
                and not governed_slice.get("failed_closed")
                and _gov_manifest is not None
                and _gov_record is not None
            ):
                from arch_competition.promotion_execution import execute_promotion_if_eligible

                auto_exec_result = execute_promotion_if_eligible(
                    MODEL_DIR,
                    ticker,
                    hz_sched,
                    manifest=_gov_manifest,
                    promotion_record=_gov_record,
                    scheduler_run_id=run_ts,
                    db_path=DB_PATH,
                    walk_forward_holdout_available=bool(wf_eval_dates),
                )
                promoted = bool(auto_exec_result.get("executed"))
                production_write_held = not promoted
                if auto_exec_result.get("skipped_reason") == "verify_failed":
                    reason = "verify_failed"
                elif promoted:
                    reason = "governed_auto_promote_ok"
                    if auto_exec_result.get("post_promote_verify_passed") is not False:
                        live_reload_batch.append({"ticker": ticker_storage_key(ticker), "horizon": hz_sched})
                else:
                    reason = str(auto_exec_result.get("skipped_reason") or "promote_skipped")

            report["promoted"] = promoted
            report["promotion_reason"] = "governed_auto_promote" if promoted else reason
            report["rejection_reason"] = reason if not promoted else ""
            report["auto_promote_execution"] = auto_exec_result
            report["production_write_held"] = production_write_held
            report["post_promote_verify_passed"] = auto_exec_result.get("post_promote_verify_passed")
            report["verify_failed_rolled_back"] = auto_exec_result.get("verify_failed_rolled_back")

            if isinstance(governed_slice, dict):
                governed_slice = dict(governed_slice)
                governed_slice["production_write_held"] = production_write_held
                governed_slice["auto_promote_executed"] = promoted
                report["governed_competition"] = governed_slice

            arch_key = ticker_storage_key(ticker)  # RC-345/F25: arch_state writer key == canonical identity (reader in server.py matches)
            prior_arch = arch_state.get(arch_key, {}).get("active_architecture", "none")
            new_arch = prior_arch
            if promoted and auto_exec_result.get("target_architecture"):
                new_arch = auto_exec_result["target_architecture"]
            prov_dict = arch_state.get(arch_key, {}).get("provenance")
            if promoted:
                win_prov = cascade_prov if new_arch == "cascade" else parallel_prov
                if win_prov:
                    prov_dict = win_prov.to_dict()
            arch_state[arch_key] = {
                "active_architecture": new_arch,
                "parallel_acc": round(parallel_acc, 4),
                "cascade_acc": round(cascade_acc, 4),
                "parallel_balanced_acc": round(parallel_bal, 4),
                "cascade_balanced_acc": round(cascade_bal, 4),
                "last_trained_at": _now_et().strftime("%Y-%m-%d %H:%M:%S"),
                "rows_at_training": n_rows,
                "promoted": promoted,
                "promotion_reason": reason if not promoted else "ok",
                "provenance": prov_dict,
            }
            if promoted:
                log.info("%s: governed auto-promote to %s", ticker, new_arch)
            elif auto_active and reason:
                log.info("%s: auto-promote held: %s", ticker, reason)

            if governed_slice is not None:
                arch_state[arch_key]["governed_competition"] = governed_slice

            promotion_decision_record = {
                "scheduler_log_loss_winner": "parallel" if parallel_wins else "cascade",
                "primary_metric": "eval_log_loss",
                "promoted_to_active": promoted,
                "promotion_reason": report["promotion_reason"],
                "rejection_reason": report["rejection_reason"],
                "ml_horizon_suffix": hz_sched,
                "target_column": target_column,
                "governed_promotion_decision": (
                    None
                    if not governed_slice or governed_slice.get("failed_closed")
                    else governed_slice.get("latest_promotion_decision")
                ),
                "governed_evaluation_paths": governed_paths,
                "auto_promote_to_active": auto_active,
            }

            try:
                from eval_metrics_store import save_arch_eval_proof_merge, save_dashboard_eval_metrics

                _prev = {}
                try:
                    from eval_metrics_store import load_dashboard_eval_metrics

                    _prev = load_dashboard_eval_metrics()
                except Exception as e:
                    log.debug("load_dashboard_eval_metrics failed: %s", e, exc_info=True)
                _prev["updated_at"] = run_ts
                _prev["primary_metric"] = "eval_log_loss"
                _prev["realized_contract_pricing"] = (
                    "entry=ask exit=bid; underlying stop/target/time exit per Call plan; "
                    "trade logs: models/realized_contract_trade_log_parallel.csv + _cascade.csv"
                )
                _prev[ticker_storage_key(ticker)] = {  # RC-345/F25: dashboard-metrics key canonical (reader matches)
                    "parallel": {
                        "eval_accuracy": parallel_acc,
                        "balanced_accuracy": parallel_bal,
                        "eval_log_loss": parallel_ll,
                        "eval_pnl_realized_contract": parallel_realized_metrics.get(
                            "eval_pnl_realized_contract"
                        ),
                        "realized_contract_metrics": parallel_realized_metrics,
                        "n_rows": n_rows,
                    },
                    "cascade": {
                        "eval_accuracy": cascade_acc,
                        "balanced_accuracy": cascade_bal,
                        "eval_log_loss": cascade_ll,
                        "eval_pnl_realized_contract": cascade_realized_metrics.get(
                            "eval_pnl_realized_contract"
                        ),
                        "realized_contract_metrics": cascade_realized_metrics,
                        "n_rows": n_cascade_rows,
                    },
                    "scheduler_log_loss_winner": "parallel" if parallel_wins else "cascade",
                }
                save_dashboard_eval_metrics(_prev)
                from realized_contract_eval import (
                    TRADE_LOG_PARALLEL,
                    TRADE_LOG_CASCADE,
                    aggregate_path,
                    compare_parallel_cascade_trade_logs,
                )

                _pw = "parallel" if parallel_wins else "cascade"
                save_arch_eval_proof_merge(
                    ticker,
                    {
                        "updated_at": run_ts,
                        "parallel_eval_log_loss": parallel_ll,
                        "cascade_eval_log_loss": cascade_ll,
                        "parallel_eval_accuracy": parallel_acc,
                        "cascade_eval_accuracy": cascade_acc,
                        "parallel_eval_pnl_realized_contract": parallel_realized_metrics.get(
                            "eval_pnl_realized_contract"
                        ),
                        "cascade_eval_pnl_realized_contract": cascade_realized_metrics.get(
                            "eval_pnl_realized_contract"
                        ),
                        "comparison_winner_by_log_loss": _pw,
                        "final_promoted_winner": (_pw if promoted else None),
                        "promoted_to_active": promoted,
                        "primary_metric": "eval_log_loss",
                        "trade_log_path_parallel": str(TRADE_LOG_PARALLEL.resolve()),
                        "trade_log_path_cascade": str(TRADE_LOG_CASCADE.resolve()),
                        "parallel_cascade_trade_log_comparison": compare_parallel_cascade_trade_logs(),
                        "aggregate_metrics_path": str(aggregate_path().resolve()),
                    },
                )
            except Exception as _em_e:
                log.warning("eval_metrics_store: %s", _em_e)

            par_skip_streak_next = (par_streak_prev + 1) if parallel_skip else 0
            cas_skip_streak_next = (cas_streak_prev + 1) if cascade_skip else 0

            par_sha = compute_artifact_sha256_map(
                parallel_out, parallel_artifact_basenames(ticker, horizon_suffix=hz_sched),
            )
            cas_sha = compute_artifact_sha256_map(
                cascade_out, cascade_artifact_basenames(ticker, horizon_suffix=hz_sched),
            )

            save_run_manifest(
                parallel_out,
                build_manifest(
                    ticker=ticker,
                    architecture="parallel",
                    scheduler_cache_key=parallel_key,
                    feature_cache_key=fk,
                    data_fp=data_fp,
                    trained_at=pm_trained_at,
                    artifact_rel_paths=_artifact_paths_relative(
                        parallel_out, ticker, horizon_suffix=hz_sched,
                    ),
                    artifact_sha256=par_sha,
                    training_code_fingerprint=code_fp,
                    evaluation={
                        "realized_contract_eval_ref": "realized_contract_eval.py",
                        "eval_accuracy": round(parallel_acc, 6),
                        "balanced_accuracy": round(parallel_bal, 6),
                        "n_rows": n_rows,
                        **(
                            {"eval_log_loss": round(parallel_ll, 6)}
                            if parallel_ll is not None
                            else {}
                        ),
                        "realized_contract_metrics": parallel_realized_metrics,
                    },
                    promotion_decision=promotion_decision_record,
                    skipped_train=par_skipped_train,
                    skipped_eval=par_skipped_eval,
                    used_feature_cache=par_used_fc,
                    used_cascade_tensor_cache=par_used_ctc,
                    rolling_window_days_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
                    rolling_window_days_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
                    rolling_rth_sessions_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
                    rolling_rth_sessions_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
                    consecutive_scheduler_skips=par_skip_streak_next,
                    skip_reason=par_skip_reason if parallel_skip else None,
                    retrain_reason=(None if parallel_skip else (par_retrain_reason or "trained_fresh")),
                    cache_miss_reason=(None if parallel_skip else par_miss_reason),
                    warm_resume=par_warm_resume,
                    ml_horizon_suffix=hz_sched,
                ),
            )
            save_run_manifest(
                cascade_out,
                build_manifest(
                    ticker=ticker,
                    architecture="cascade",
                    scheduler_cache_key=cascade_key,
                    feature_cache_key=fk,
                    data_fp=data_fp,
                    trained_at=cm_trained_at,
                    artifact_rel_paths=_artifact_paths_relative(
                        cascade_out, ticker, horizon_suffix=hz_sched,
                    ),
                    artifact_sha256=cas_sha,
                    training_code_fingerprint=code_fp,
                    evaluation={
                        "realized_contract_eval_ref": "realized_contract_eval.py",
                        "eval_accuracy": round(cascade_acc, 6),
                        "balanced_accuracy": round(cascade_bal, 6),
                        "n_rows": n_cascade_rows,
                        **(
                            {"eval_log_loss": round(cascade_ll, 6)}
                            if cascade_ll is not None
                            else {}
                        ),
                        "realized_contract_metrics": cascade_realized_metrics,
                    },
                    promotion_decision=promotion_decision_record,
                    skipped_train=cas_skipped_train,
                    skipped_eval=cas_skipped_eval,
                    used_feature_cache=cas_used_fc,
                    used_cascade_tensor_cache=cas_used_ctc,
                    used_parallel_cascade_bridge=cas_used_bridge,
                    rolling_window_days_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
                    rolling_window_days_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
                    rolling_rth_sessions_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
                    rolling_rth_sessions_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
                    consecutive_scheduler_skips=cas_skip_streak_next,
                    skip_reason=cas_skip_reason if cascade_skip else None,
                    retrain_reason=(None if cascade_skip else (cas_retrain_reason or "trained_fresh")),
                    cache_miss_reason=(None if cascade_skip else cas_miss_reason),
                    warm_resume=cas_warm_resume,
                    ml_horizon_suffix=hz_sched,
                ),
            )

            outcome_val, consecutive_cache_skips = _resolve_ticker_outcome(
                ticker=ticker,
                horizon=hz_sched,
                skip_governed_eval=skip_governed_eval,
                governed_slice=governed_slice,
                parallel_skip=parallel_skip,
                cascade_skip=cascade_skip,
                promoted=promoted,
                consecutive_cache_skips=consecutive_cache_skips,
                auto_exec_result=auto_exec_result,
            )
            would_promote = bool(
                isinstance(governed_slice, dict)
                and governed_slice.get("would_promote_challenger")
                and not governed_slice.get("failed_closed")
            )
            _apply_pr2_report_fields(
                report,
                outcome=outcome_val,
                horizon=hz_sched,
                artifact_complete=artifact_complete,
                consecutive_cache_skips=consecutive_cache_skips,
                governed_slice=governed_slice,
            )
            run_ticker_outcomes.append(
                outcome_entry(
                    ticker=ticker,
                    horizon=hz_sched,
                    outcome=TrainingOutcome(outcome_val),
                    extra={"would_promote": would_promote} if would_promote else None,
                )
            )

            _append_training_report(report)

        except Exception as e:
            log.exception("%s: failed: %s", ticker, e)
            run_ticker_outcomes.append(
                outcome_entry(
                    ticker=ticker,
                    horizon=hz_sched,
                    outcome=TrainingOutcome.train_failed,
                    extra={"error": str(e)},
                )
            )

    try:
        from training_cache import cleanup_feature_cache_directories, prune_model_archives

        _n_removed = cleanup_feature_cache_directories()
        if _n_removed:
            log.info("Feature cache cleanup removed %d director(ies)", _n_removed)
        _np = prune_model_archives(MODEL_DIR)
        if _np:
            log.info("Model archive prune removed %d snapshot(s)", _np)
    except Exception as ex:
        log.warning("Feature cache / archive cleanup skipped: %s", ex)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    arch_target_path.write_text(json.dumps(arch_state, indent=2), encoding="utf-8", newline="\n")
    log.info("%s updated", arch_target_path.name)
    log.info("Training report appended to %s", TRAINING_REPORT_PATH)

    exit_code = compute_run_exit_code(run_ticker_outcomes)
    try:
        from training_pipeline_status import record_run_finish

        # P1-1: ticker_outcomes populated with per-(ticker, horizon) TrainingOutcome values.
        record_run_finish(
            ml_horizon=hz_sched,
            ticker_outcomes=run_ticker_outcomes,
            exit_code_hint=exit_code,
        )
    except Exception as _tps_fin:
        log.debug("training_pipeline_status record_run_finish: %s", _tps_fin, exc_info=True)

    # Active artifact verification — flag non-compliant
    try:
        from verify_active_models import check_artifact_compliance, _get_active_tickers
        for tkr in _get_active_tickers():
            r = check_artifact_compliance(tkr)
            if not r["compliant"]:
                log.warning("NON-COMPLIANT active %s: %s — retrain required", tkr, r["issues"])
    except Exception as e:
        log.warning("Verification skipped: %s", e)

    live_reload_report: dict[str, Any] | None = None
    if live_reload_batch:
        try:
            from arch_competition.live_model_reload import build_live_reload_report

            live_reload_report = build_live_reload_report(reloads=live_reload_batch)
            log.info("live_reload batch: %s", live_reload_report)
        except Exception as _lr_e:
            log.warning("live_reload batch failed: %s", _lr_e, exc_info=True)

    return {
        "exit_code": exit_code,
        "ticker_outcomes": run_ticker_outcomes,
        "ml_horizon": hz_sched,
        "skipped": False,
        "live_reload": live_reload_report,
    }


_bg_scheduler_lock = threading.Lock()
_bg_scheduler_thread: Optional[threading.Thread] = None
_bg_scheduler_started = False


def _next_scheduled_run_et(now: datetime) -> datetime:
    """Earliest RUN_AT_HOUR:RUN_AT_MINUTE ET on a market day strictly after ``now``."""
    from datetime import time as dtime

    for i in range(0, 28):
        day = now.date() + timedelta(days=i)
        cand = datetime.combine(day, dtime(RUN_AT_HOUR, RUN_AT_MINUTE)).replace(tzinfo=ET)
        if cand <= now:
            continue
        if _is_market_day(cand):
            return cand
    return now + timedelta(days=1)


def start_background_scheduler() -> None:
    """
    Start a daemon thread that sleeps until the next market-day 16:15 ET, then calls ``run_once``
    (scheduled mode: no --run-now). Safe to call once per process; duplicates are ignored.

    Default (ED_ML_SCHEDULER_ALL_HORIZONS=1): trains/promotes all four primary horizons per night.
    Set ED_ML_SCHEDULER_ALL_HORIZONS=0 to run only ED_ML_SCHEDULER_HORIZON (legacy single-horizon).
    """
    global _bg_scheduler_thread, _bg_scheduler_started
    with _bg_scheduler_lock:
        if _bg_scheduler_started:
            log.warning("start_background_scheduler: already started; ignoring duplicate")
            return
        _bg_scheduler_started = True

    from arch_competition.scheduler_auto_promote_policy import scheduler_nightly_all_horizons_enabled

    single_hz = os.environ.get("ED_ML_SCHEDULER_HORIZON", DEFAULT_ML_HORIZON_SLUG)

    def _run_scheduled_nightly() -> None:
        if scheduler_nightly_all_horizons_enabled():
            from ml_horizon import ALL_GOVERNED_HORIZONS

            agg_exit = 0
            for _hz in ALL_GOVERNED_HORIZONS:
                log.info("ML scheduler background: starting horizon %s", _hz)
                summary = run_once(
                    wait=False,
                    force_retrain=False,
                    bypass_cache=False,
                    allow_non_market_day=False,
                    promote_from_manifests_only=False,
                    ml_horizon_slug=str(_hz),
                )
                code = int(summary.get("exit_code", 0))
                agg_exit |= code
                log.info(
                    "ML scheduler background: finished horizon %s (exit=%s)",
                    _hz,
                    code,
                )
            if agg_exit:
                log.warning(
                    "ML scheduler background: one or more horizons failed (agg_exit=%s)",
                    agg_exit,
                )
        else:
            run_once(
                wait=False,
                force_retrain=False,
                bypass_cache=False,
                allow_non_market_day=False,
                promote_from_manifests_only=False,
                ml_horizon_slug=str(single_hz),
            )

    def _loop() -> None:
        while True:
            try:
                now = _now_et()
                nxt = _next_scheduled_run_et(now)
                delay = max(1.0, (nxt - now).total_seconds())
                log.info(
                    "ML scheduler background: next run at %s ET (in %.0f s)",
                    nxt.strftime("%Y-%m-%d %H:%M"),
                    delay,
                )
                time.sleep(delay)
                _run_scheduled_nightly()
            except Exception as e:
                log.exception("ML scheduler background loop error: %s", e)
                time.sleep(300.0)

    _bg_scheduler_thread = threading.Thread(
        target=_loop,
        name="ml_scheduler_nightly",
        daemon=True,
    )
    _bg_scheduler_thread.start()
    if scheduler_nightly_all_horizons_enabled():
        log.info(
            "ML background scheduler thread started (nightly market-day %02d:%02d ET; all horizons)",
            RUN_AT_HOUR,
            RUN_AT_MINUTE,
        )
    else:
        log.info(
            "ML background scheduler thread started (nightly market-day %02d:%02d ET; horizon=%s)",
            RUN_AT_HOUR,
            RUN_AT_MINUTE,
            single_hz,
        )


# deprecated aliases — unified-stack vocabulary migration
_meta_base_triplet = _meta_ml_layer_triplet
_assemble_meta_base_prob_vectors = _assemble_meta_ml_layer_prob_vectors
_train_parallel_base_models_into = _train_parallel_ml_stack_layers_into
_train_cascade_base_models_into = _train_cascade_ml_stack_layers_into


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", action="store_true")
    ap.add_argument(
        "--run-now",
        action="store_true",
        help="Do not wait until 16:15 ET; allow training on weekends/holidays (still needs DB rows).",
    )
    ap.add_argument("--force-retrain", action="store_true",
                    help="Ignore scheduler cache-skip / inhibitor and force a fresh train+eval this run "
                         "(training_cache skip bypass). Does NOT override the promotion score/row gate.")
    ap.add_argument("--bypass-cache", action="store_true",
                    help="Ignore scheduler + feature tensor cache (full retrain + re-eval)")
    ap.add_argument(
        "--promote-from-manifests",
        action="store_true",
        help="Issue 11: skip training; re-run promotion from existing parallel/ cascade artifacts + manifests (implies --run-now).",
    )
    ap.add_argument(
        "--horizon",
        type=str,
        default=os.environ.get("ED_ML_SCHEDULER_HORIZON", DEFAULT_ML_HORIZON_SLUG),
        help="ML horizon slug for this scheduler run (1c, 5c, 15c, 60c). Non-1c promotes to models/active_{slug}/.",
    )
    ap.add_argument(
        "--all-horizons",
        action="store_true",
        help=(
            "Sequentially invoke run_once for every primary decision horizon (1c, 5c, 15c, 60c) "
            "in one CLI call. Each horizon runs train/eval/governed competition; when "
            "ED_SCHEDULER_AUTO_PROMOTE=1 (default), execute_promotion_if_eligible copies the "
            "seven-file bundle into models/active/ or models/active_{hz}/. Overrides --horizon."
        ),
    )
    ap.add_argument(
        "--preflip-candidate-root",
        type=str,
        default=None,
        help="PR4: skip train; use frozen candidate tree at PATH/{TICKER}/parallel|cascade for governed eval + auto-promote replay.",
    )
    args = ap.parse_args()
    _preflip_root = Path(args.preflip_candidate_root).resolve() if args.preflip_candidate_root else None
    run_now = bool(args.run_now or args.promote_from_manifests)
    if args.all_horizons:
        from ml_horizon import ALL_GOVERNED_HORIZONS

        agg_exit = 0
        for _hz in ALL_GOVERNED_HORIZONS:
            log.info("ml_scheduler --all-horizons: starting horizon %s", _hz)
            summary = run_once(
                wait=False if run_now else args.wait,
                force_retrain=args.force_retrain,
                bypass_cache=args.bypass_cache,
                allow_non_market_day=run_now,
                promote_from_manifests_only=bool(args.promote_from_manifests),
                preflip_candidate_root=_preflip_root,
                ml_horizon_slug=str(_hz),
            )
            agg_exit = aggregate_all_horizons_exit_code((agg_exit, summary.get("exit_code", 0)))
            log.info("ml_scheduler --all-horizons: finished horizon %s (exit=%s)", _hz, summary.get("exit_code"))
        sys.exit(agg_exit)
    summary = run_once(
        wait=False if run_now else args.wait,
        force_retrain=args.force_retrain,
        bypass_cache=args.bypass_cache,
        allow_non_market_day=run_now,
        promote_from_manifests_only=bool(args.promote_from_manifests),
        preflip_candidate_root=_preflip_root,
        ml_horizon_slug=str(args.horizon),
    )
    sys.exit(int(summary.get("exit_code", 0)))
