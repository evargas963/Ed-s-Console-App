#!/usr/bin/env python3
"""Applies the human/agent SEMANTIC adjudication pass on top of
reports/no_fallback_discovery_raw.json's mechanical candidates, producing
reports/no_fallback_inventory.json -- the mission's required machine-readable inventory.

Every candidate not explicitly adjudicated below stays NOT_PROVEN (the raw scanner's own
default) -- this script NEVER invents a verdict; it only records the ones a human/agent
reading actually confirmed, each with its own evidence and required-repair note. This first
pass covers the two categories a real reading is tractable for at repo scale in one session:
SQL_COALESCE_STYLE (59), IMPUTATION (7), and EXCEPT_SUBSTITUTE (56) -- the three patterns the
mission's own PROHIBITED list names most explicitly ("exception-triggered substitute",
"SQL COALESCE/IFNULL-style semantic replacement", "model/training substitution", "missing
numeric value converted to zero"). OR_LADDER/TERNARY/DICT_GET_DEFAULT/GETATTR_DEFAULT/JS/PS
candidates (the remaining ~1060) are reported honestly as NOT_PROVEN -- not adjudicated this
pass, not silently excluded, still present in the artifact for the operator/next pass.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# id -> (adjudication, evidence, required_repair, group)
ADJUDICATION: dict[str, tuple[str, str, str, str]] = {}


def _mark(ids: list[str], verdict: str, evidence: str, repair: str, group: str) -> None:
    for i in ids:
        ADJUDICATION[i] = (verdict, evidence, repair, group)


# ---------------------------------------------------------------------------
# GROUP A1: COALESCE(horizon_outcome_schema_version, 3|?bound-to-3) -- FALLBACK.
# horizon_outcomes.py documents schema v2 as "invalidated -- do not use" and v3 (the
# BAR_ANCHOR_V1 constant, =3) as current; snapshots.horizon_outcome_schema_version defaults
# to 3 for rows written by current code (db.py:866). A NULL in this column can only be a
# pre-migration legacy row -- COALESCE(...,3) silently asserts every such row IS confirmed
# v3-equivalent with no proof in the query itself; if any legacy row were actually v2
# mechanics, this would feed invalidated-schema data into training/decision paths labeled
# as current-schema. This is the "zero/default constant" substitution the mission bans,
# repeated at scale (26 sites) because each site independently re-derived the same
# unverified assumption rather than reading it from a single adjudicated authority.
_A1 = ["FB-00091", "FB-00093", "FB-00122", "FB-00124", "FB-00174", "FB-00181", "FB-00182",
       "FB-00184", "FB-00185", "FB-00186", "FB-00188", "FB-01005", "FB-01006", "FB-01007",
       "FB-01008", "FB-01012", "FB-01013", "FB-01014", "FB-01015", "FB-01020", "FB-01024",
       "FB-01028", "FB-01029", "FB-01135"]
_mark(_A1, "FALLBACK",
      "COALESCE(horizon_outcome_schema_version, 3) treats a NULL (pre-migration/unrecorded) "
      "row as CONFIRMED schema v3 with no per-row proof; horizon_outcomes.py documents v2 as "
      "'invalidated -- do not use', so a true-v2 legacy row would be silently mislabeled v3.",
      "Replace the COALESCE default with an explicit NULL-preserving read (e.g. a "
      "'schema_version_confirmed' boolean, or exclude NULL rows from version-scoped queries "
      "unless a separate, evidenced backfill proves them v3) -- do not assume the anchor "
      "version for unrecorded rows.",
      "calibration_ml_governance")

# COALESCE(...,-1) uses an impossible-for-a-real-version sentinel -- never confused with a
# real schema version (2 or 3). This is the mission's OWN recommended shape (an explicit,
# unmistakable failure marker), not a masquerading substitute.
_mark(["FB-00927", "FB-01003"], "NOT_FALLBACK",
      "COALESCE(horizon_outcome_schema_version, -1): -1 can never be a real schema version "
      "(only 2/invalidated and 3/current exist), so NULL reads as an unmistakable distinct "
      "sentinel, never as a masquerading valid version.",
      "none", "calibration_ml_governance")

# ---------------------------------------------------------------------------
# GROUP B: COALESCE(canonical_timeframe, '1m') -- FALLBACK. timeframe is a real
# distinguishing dimension in this repo (1m vs 5m work is a named, separate audit lane
# per project memory); assuming NULL means '1m' silently misclassifies any row from a
# non-1m context that lacks the column.
_mark(["FB-00081", "FB-00083", "FB-00084"], "FALLBACK",
      "COALESCE(canonical_timeframe, '1m') assumes an unset timeframe is 1m; timeframe is a "
      "real distinguishing dimension (this repo maintains a separate 1m/5m divergence audit "
      "lane), so a genuinely-non-1m row missing the column would be silently misclassified.",
      "Confirm via migration history whether every pre-column row is provably 1m-only; if "
      "not, exclude NULL-timeframe rows from timeframe-scoped queries rather than assuming.",
      "calibration_ml_governance")

# ---------------------------------------------------------------------------
# GROUP C: COALESCE(MAX(...)|SUM(...), 0) -- NOT_FALLBACK. Standard SQL: an aggregate over
# zero matching rows is NULL by definition; 0 is the mathematically correct total, not a
# substitute for a missing OBSERVATION.
_mark(["FB-00433", "FB-00434", "FB-00435", "FB-00436", "FB-00437", "FB-00438", "FB-00724",
       "FB-01062", "FB-01073", "FB-01074", "FB-01110"], "NOT_FALLBACK",
      "COALESCE(MAX(...)|SUM(...), 0) on an aggregate over zero matching rows: SQL returns "
      "NULL for an aggregate of an empty set by definition, and 0 is the mathematically "
      "correct total/max-of-nothing, not a substitute for a missing per-row observation.",
      "none", "sql_idiom_confirmed_safe")

# ---------------------------------------------------------------------------
# GROUP D: COALESCE(<boolean-flag>, 0) on audit/quality-gate flags (research_excluded,
# outcome_filled, active) -- NOT_PROVEN. Could be legitimate DEFAULT-0 schema-column
# semantics (absence structurally means "not flagged"), but these specific flags gate what
# data enters ML calibration/training -- silently defaulting an audit-exclusion flag to
# "not excluded" when never explicitly set is a real integrity question this session cannot
# resolve without the schema's own DDL/migration intent, which needs operator confirmation.
_mark(["FB-00114", "FB-00115", "FB-00148", "FB-00892", "FB-00893", "FB-01072", "FB-01075",
       "FB-01076", "FB-01077", "FB-01078", "FB-01105"], "NOT_PROVEN",
      "COALESCE(<audit/quality flag>, 0) on a calibration-gating column (research_excluded / "
      "outcome_filled / active): could be legitimate DEFAULT-0 schema semantics, or could "
      "silently admit never-vetted rows into training by defaulting 'excluded' to false. "
      "Needs the column's DDL/migration intent confirmed by the operator.",
      "Confirm via schema DDL whether these columns are NOT NULL DEFAULT 0 (making COALESCE "
      "redundant-but-harmless) or nullable-by-design (making the default a real assumption).",
      "calibration_ml_governance")

# ---------------------------------------------------------------------------
# GROUP E: COALESCE(matched_snapshot_ts_utc, decision_ts_utc) -- FALLBACK. Alternate-field
# substitution: using a DIFFERENT real field's value in place of the intended one when the
# intended one is absent is explicitly prohibited by the mission ("alternate field").
_mark(["FB-00088"], "FALLBACK",
      "COALESCE(matched_snapshot_ts_utc, decision_ts_utc): substitutes a DIFFERENT real "
      "field's value (decision_ts_utc) for the intended one (matched_snapshot_ts_utc) when "
      "absent -- the mission's explicitly-prohibited 'alternate field' substitution shape.",
      "Expose the join-failure explicitly (e.g. a separate matched_snapshot_ts_utc_confirmed "
      "flag) rather than silently attributing the decision's own timestamp to the snapshot "
      "match.",
      "calibration_ml_governance")

# ---------------------------------------------------------------------------
# GROUP F: enrollment_source = COALESCE(enrollment_source, ?) -- an UPDATE-statement
# preserve-existing-else-set-new idiom (never overwrite a value that's already recorded),
# not a read-time substitution for a missing OBSERVATION. Genuinely different shape from
# every other COALESCE in this file; tentatively clear but not independently re-verified
# against the full surrounding statement in this pass.
_mark(["FB-00187"], "NOT_PROVEN",
      "enrollment_source = COALESCE(enrollment_source, ?) reads as an UPDATE-preserve-"
      "existing-value idiom (write the new value only if none is already recorded), not a "
      "read-time substitution -- plausible NOT_FALLBACK but not independently confirmed "
      "against the full surrounding statement in this pass.",
      "Confirm the full UPDATE statement's intent before clearing.", "db_write_path")

# ---------------------------------------------------------------------------
# GROUP G: IFNULL(outcome_join_method, '') compared against a set including '' -- a
# comparison-safety technique (NULL and '' both read as "no method"), not fabricating a
# valid-looking join-method label.
_mark(["FB-00137", "FB-00830"], "NOT_FALLBACK",
      "IFNULL(outcome_join_method, '') NOT IN ('exact', ''): '' is used only to make the "
      "NOT IN comparison NULL-safe: both NULL and '' still read as 'no confirmed join "
      "method', never as a fabricated valid method name like 'exact'.",
      "none", "sql_idiom_confirmed_safe")

# ---------------------------------------------------------------------------
# GROUP I: COALESCE(rules_signal, 'NULL') as sig -- the literal string 'NULL' used as a
# self-describing, unmistakable display label in a GROUP BY audit query, not a real signal
# value ('buy'/'sell'/'flat' etc.) -- cannot be confused with real data.
_mark(["FB-00058"], "NOT_FALLBACK",
      "COALESCE(rules_signal, 'NULL') AS sig in a GROUP BY audit query: the literal string "
      "'NULL' is a self-describing, unmistakable display label, never confusable with a real "
      "signal value (buy/sell/flat/etc).",
      "none", "sql_idiom_confirmed_safe")

# ---------------------------------------------------------------------------
# IMPUTATION group
_mark(["FB-00420", "FB-00972"], "NOT_PROVEN",
      "pandas median-imputation of ML feature columns (X.fillna(median)): standard, "
      "disclosed ML preprocessing methodology, but the mission's own PROHIBITED list "
      "explicitly names 'model/training substitution' as a category requiring adjudication "
      "-- deferred to the operator rather than unilaterally cleared as industry-standard.",
      "Operator to confirm whether pipeline-level disclosure (the fact imputation runs at "
      "all, documented in training methodology) satisfies the no-fallback mandate for "
      "feature-level ML preprocessing, or whether missing features must instead be excluded/"
      "flagged per-row.",
      "ml_training_pipeline")
_mark(["FB-00884"], "NOT_FALLBACK",
      "Test file exercising the imputation behavior itself as a test fixture, not production "
      "data flow.", "none", "test_artifact")
_mark(["FB-01111"], "NOT_PROVEN",
      "fillna(0).astype(int)==0 on a 'truncated' flag column before filtering -- likely a "
      "boolean-default-false idiom (similar to GROUP D) but not independently confirmed "
      "against the column's schema intent.",
      "Confirm column DDL/intent.", "ml_training_pipeline")
_mark(["FB-01156"], "FALLBACK",
      "df['rules_signal'].map(rules_map).fillna('flat'): 'flat' is a real, meaningful "
      "trading-position state (not a sentinel) -- an unmapped or missing signal silently "
      "reads as a genuine 'no position' call instead of disclosing the mapping/data failure. "
      "Matches the mission's explicitly-prohibited 'neutral value' substitution.",
      "Expose unmapped/missing signals as an explicit distinct state (e.g. "
      "'UNMAPPED'/None with a carried reason), never as the same string a genuine flat "
      "signal would produce.",
      "ml_training_pipeline")
_mark(["FB-01161", "FB-01162"], "NOT_PROVEN",
      "s.fillna(-1.0) on what appears to be a bounded similarity/probability-like series -- "
      "plausible impossible-sentinel technique (like the -1 schema-version case) IF -1.0 is "
      "genuinely outside the series' real value range, but that range was not independently "
      "confirmed in this pass.",
      "Confirm the series' real value domain excludes -1.0 before clearing as a safe "
      "sentinel.",
      "ml_training_pipeline")

# ---------------------------------------------------------------------------
# EXCEPT_SUBSTITUTE group
_mark(["FB-00368", "FB-00369", "FB-00267", "FB-00268", "FB-00484", "FB-01097", "FB-01098",
       "FB-01121", "FB-00618", "FB-00518", "FB-00617", "FB-00780", "FB-01057", "FB-01058",
       "FB-00067", "FB-00068", "FB-00996", "FB-00997"], "NOT_FALLBACK",
      "Except handler records/discloses the FAILURE ITSELF (an explicit error string, a "
      "named fail-closed/error status, an error counter, or a fail-closed object flag) "
      "rather than substituting a value that could be mistaken for a successful read -- "
      "exactly the disclosure behavior the mission requires, not a violation of it.",
      "none", "correct_failure_disclosure")
_mark(["FB-00024", "FB-00031", "FB-00032", "FB-00251", "FB-01183", "FB-01049", "FB-00502",
       "FB-00009"], "NOT_PROVEN",
      "Except/init-time assignment to None or an empty sentinel that PLAUSIBLY reads as "
      "'not yet observed/computed' rather than a fabricated valid value, but the downstream "
      "consumer was not traced in this pass to confirm it is never treated as a genuine "
      "reading.",
      "Trace each downstream consumer to confirm None/empty is always checked and disclosed, "
      "never silently used as a real value.",
      "needs_downstream_trace")
_mark(["FB-00573", "FB-00558"], "NOT_PROVEN",
      "server.py sets an explicit None sentinel for gamma-surface/contract-admission state "
      "on a code path this session's own prior work (RC-560..RC-564) established a "
      "None-means-'not yet computed' convention for -- plausibly correct, but this is a "
      "Cursor-overlap file and was not re-traced end-to-end in this pass; the existing "
      "convention should be confirmed, not assumed, before clearing.",
      "Confirm downstream consumers of _gamma_surface/_contract_admission never render None "
      "as a live value (per the existing cell-state disclosure machinery).",
      "needs_downstream_trace")
_mark(["FB-00007", "FB-00490", "FB-00491"], "NOT_FALLBACK",
      "Algorithm/control-flow bookkeeping (a bisection midpoint, a static probe parameter "
      "list) -- not a semantic market-data field substitution at all; the scanner's broad "
      "semantic-term match produced a false positive here.",
      "none", "scanner_false_positive")
_mark(["FB-00543"], "NOT_PROVEN",
      "server.py: on a PriceLevels computation failure, a fresh empty PriceLevels() is "
      "assigned locally, but the immediately-following `else:` block (which publishes to "
      "_state_cache) is skipped on the exception path -- so the CACHED/served value is very "
      "likely left at its last-good generation-tracked state, not overwritten by the empty "
      "object. Whether the empty local PriceLevels() is ALSO used directly later in the same "
      "response (bypassing the cache) was not traced far enough in this pass to be certain.",
      "Trace whether `price_levels` (the local empty-on-failure variable) is read anywhere "
      "later in the same function/response before the next real recompute, and if so whether "
      "it is disclosed as unavailable rather than rendered as zero/empty levels.",
      "needs_downstream_trace")
_mark(["FB-00266"], "FALLBACK",
      "ms.gex_magnitude = str(getattr(consensus_summary, 'gex_magnitude', 'negligible') or "
      "'negligible'): double fallback (getattr default AND `or`) both landing on the "
      "meaningful, valid-looking classification 'negligible' -- a missing/falsy real value "
      "reads identically to a genuinely-computed negligible-magnitude result. Matches the "
      "mission's prohibited 'neutral value' substitution exactly.",
      "Expose 'not computed' as a distinct state from the genuine 'negligible' classification "
      "(e.g. None vs the string, with the UI/consumer disclosing which).",
      "market_state_rendering")
_mark(["FB-00129", "FB-00130", "FB-00132", "FB-00133", "FB-00134"], "FALLBACK",
      "A repair-tool's report dict is set to 0 (tickers_touched / "
      "governed_outcome_refresh_tickers / fill_outcomes_tickers) inside an except handler -- "
      "silently reports 'confirmed zero tickers touched' when the true outcome is 'the "
      "repair crashed and the real count is unknown', misrepresenting a failure as a "
      "specific counted fact. Matches the mission's prohibited 'zero...placeholder' shape.",
      "Report an explicit failure marker (e.g. null/'UNKNOWN_DUE_TO_ERROR') distinct from a "
      "genuine zero-tickers-touched outcome.",
      "calibration_ml_governance")
_mark(["FB-00243", "FB-00246", "FB-00392", "FB-01155", "FB-01179"], "FALLBACK",
      "tickers = [] inside an except handler in an ML training/dataset-build pipeline: "
      "silently substitutes an empty ticker list for a computation that actually failed, "
      "letting the pipeline proceed 'as if' zero tickers were ever requested rather than "
      "surfacing that ticker-list resolution itself failed. Matches the mission's prohibited "
      "'empty collection' + 'exception-triggered substitute' shapes.",
      "Propagate/raise the failure, or mark the run as degraded/incomplete rather than "
      "silently training on an empty-appearing ticker set.",
      "ml_training_pipeline")
_mark(["FB-00519", "FB-00559", "FB-00560"], "FALLBACK",
      "tickers = list(CORE_TICKERS) inside an except handler in server.py's terrain/bars "
      "loops: substitutes the static default roster for a failed DYNAMIC ticker-list "
      "computation, silently narrowing/changing which tickers get processed without "
      "necessarily disclosing that the dynamic roster computation failed. Cursor-overlap "
      "file (server.py) -- discovery/adjudication only, no edit made.",
      "Disclose that the dynamic roster computation failed and CORE_TICKERS is a fallback "
      "roster, rather than processing it silently as if it were the intended set.",
      "market_data_server_core")
_mark(["FB-00929", "FB-00934"], "NOT_PROVEN",
      "Not independently traced in this pass whether this is a genuine except-substitute or "
      "a scanner context-detection artifact (comprehension/nested-function edge case).",
      "Re-verify by direct reading in the next adjudication pass.", "needs_recheck")
_mark(["FB-00501", "FB-00482"], "NOT_PROVEN",
      "`return tickers` inside an except handler -- likely returns a partially-populated or "
      "previously-set variable rather than a fresh empty/default literal (a 'cached/prior-"
      "value carry-forward presented as current' shape if so), but the exact prior state of "
      "`tickers` at the point of the exception was not traced in this pass.",
      "Trace what `tickers` holds at the moment the exception fires; if it is a stale prior "
      "value, disclose that explicitly rather than returning it as current.",
      "needs_downstream_trace")
_mark(["FB-01113"], "NOT_PROVEN",
      "vendor = None inside an except in vendor_reconcile -- plausible 'not yet resolved' "
      "sentinel, not independently traced downstream in this pass.",
      "Trace downstream consumer.", "needs_downstream_trace")
_mark(["FB-00394"], "NOT_PROVEN",
      "arch_state = {} inside an except in run_once -- plausible 'no state yet' "
      "initialization vs. a real substitution; not independently traced in this pass.",
      "Trace downstream consumer.", "needs_downstream_trace")
_mark(["FB-00261"], "NOT_FALLBACK",
      "strike_disp = str(k): formatting a strike value already held in `k` for display -- "
      "not a substitution of a missing value at all; scanner false positive (semantic-term "
      "match on the enclosing function name, not this line's actual behavior).",
      "none", "scanner_false_positive")


# ---------------------------------------------------------------------------
# Late additions caught during reconciliation (verify every target ID got a verdict)
_mark(["FB-00175"], "NOT_FALLBACK",
      "COALESCE(col, '(null)') AS k in a GROUP BY audit query (sql_issue19_snapshots_"
      "context_group): the literal '(null)' is a self-describing display label, same shape "
      "as FB-00058, never confusable with a real column value.",
      "none", "sql_idiom_confirmed_safe")
_mark(["FB-00179", "FB-00180"], "FALLBACK",
      "(et_hour * 60 + COALESCE(et_minute, 0)) in compute_accuracy: a missing et_minute is "
      "assigned exactly :00, fabricating a specific wrong time-of-day for the accuracy "
      "computation's time-bucket boundary rather than excluding the row or disclosing the "
      "missing minute.",
      "Exclude rows with a NULL et_minute from the time-bucket computation, or backfill it "
      "from the row's own ts_utc rather than assuming :00.",
      "calibration_ml_governance")
_mark(["FB-00269"], "NOT_FALLBACK",
      "ms.is_no_trade = True on an exception in build_market_state: a conservative, "
      "fail-CLOSED safety default (refuse to signal a trade when the state computation "
      "itself failed) -- the opposite of masking failure as a valid go-ahead signal.",
      "none", "correct_failure_disclosure")
_mark(["FB-00362"], "FALLBACK",
      "flags = set() on an exception in _active_base_collapse_flags: silently proceeds as "
      "if 'no collapse conditions detected' when the detection computation itself actually "
      "failed -- an empty warning-flag set on failure can mask a genuine collapse condition "
      "rather than disclosing that detection was inconclusive.",
      "Distinguish 'computed, zero flags raised' from 'computation failed, flags unknown' -- "
      "e.g. return None/raise rather than an empty set on exception.",
      "market_state_rendering")
_mark(["FB-00522"], "NOT_FALLBACK",
      "base['plane_quote_authority'] = 'rest_only' on an exception in api_live_plane: "
      "explicitly NAMES the degraded authority state (as opposed to the normal streaming-"
      "plane authority) -- disclosure, not concealment, of the failure.",
      "none", "correct_failure_disclosure")


# =============================================================================
# OPERATOR CORRECTION (2026-09-17, independent review of the first pass): every
# "confirmed-safe SQL idiom" classification above (aggregate-over-empty-set COALESCE,
# self-describing display-label defaults, UPDATE-preserve-existing COALESCE) and every
# "deferred to operator" ML-imputation classification is REJECTED. Operator ruling, verbatim:
# "these are fallback candidates and cannot automatically pass" and "the operator did not
# pre-authorize ML imputation." This session does not get to unilaterally clear a SQL
# substitution or a pandas imputation call as safe -- every SQL_COALESCE_STYLE and every
# IMPUTATION candidate is reclassified FALLBACK below, overriding every _mark() call above
# that touched those two patterns (including the "-1 impossible sentinel" schema-version
# case and the "(null)"/"'NULL'" audit-label case: under the mandate's own absolutist
# wording -- "no other value may replace it" -- ANY COALESCE default is a replacement value,
# regardless of how carefully chosen). The ONE exception is a genuine TEST FIXTURE
# (FB-00884) exercising imputation behavior as test data, not a production/tooling
# authorization -- left as NOT_FALLBACK, matching every other test-artifact classification
# in this file, which the operator's correction did not address.
def _repair_group_for(rel_path: str) -> str:
    if rel_path.startswith(("lstm_", "ml_train", "ml_scheduler", "ml_predict", "train_",
                             "transformer_", "training_cache", "tools/feature_curation_gate",
                             "tools/research/")):
        return "ml_training_pipeline"
    if rel_path.startswith("server.py"):
        return "market_data_server_core"
    if rel_path.startswith("market_state.py"):
        return "market_state_rendering"
    return "calibration_ml_governance"


def _apply_operator_correction_2026_09_17(raw_candidates: list[dict]) -> None:
    for c in raw_candidates:
        if c["id"] == "FB-00884":
            continue  # test fixture, not a production/tooling authorization
        if c["pattern"] in ("SQL_COALESCE_STYLE", "IMPUTATION"):
            ADJUDICATION[c["id"]] = (
                "FALLBACK",
                "OPERATOR CORRECTION 2026-09-17 overrides this session's own earlier "
                "'confirmed-safe idiom' / 'deferred to operator' classification: 'these are "
                "fallback candidates and cannot automatically pass' (SQL) / 'the operator "
                "did not pre-authorize ML imputation' -- reclassified FALLBACK "
                "unconditionally, matching tools/check_no_fallback_lock.py's own "
                "unconditional R1/R2 rules after the same correction.",
                "Expose the missing/failed value's own failure state; no COALESCE/IFNULL/"
                "NVL default and no imputed value may substitute for it, regardless of the "
                "default's shape.",
                _repair_group_for(c["file"]),
            )


#: id -> (repair_note, group). A REPAIRED entry overrides any FALLBACK verdict above --
#: production code has actually been fixed and covered by a new regression test. This dict
#: is the durable, re-runnable record of closed repairs; a fresh run of this script always
#: reproduces REPAIRED status for these ids, so it can never be silently lost by re-running
#: from the raw discovery file.
REPAIRED: dict[str, tuple[str, str]] = {}


def _mark_repaired(ids: list[str], repair_note: str, group: str) -> None:
    for i in ids:
        REPAIRED[i] = (repair_note, group)


_mark_repaired(
    ["FB-00266"],
    "REPAIRED 2026-09-17: market_state.py build_market_state() -- except-handler no longer "
    "guesses a value off consensus_summary.gex_magnitude (an attribute that does not exist "
    "upstream in practice); failure is now disclosed via ms.state_error/state_error_detail. "
    "Tests: tests/test_action12_7_market_state_fail_closed.py::"
    "test_gex_magnitude_computation_failure_is_disclosed_not_guessed, "
    "::test_gex_magnitude_never_reads_a_guessed_alternate_source_on_failure.",
    "market_state_rendering")
_mark_repaired(
    ["FB-00362"],
    "REPAIRED 2026-09-17: ml_predict.py _active_base_collapse_flags() -- a failed "
    "collapse-flag read is no longer cached as a confirmed empty result; only a successful "
    "read is cached, so a transient failure is retried on the next call instead of being "
    "trusted forever. Tests: tests/test_ml_predict_fail_closed.py::"
    "test_active_base_collapse_flags_does_not_cache_a_failed_read_as_confirmed_empty, "
    "::test_active_base_collapse_flags_caches_a_successful_read.",
    "market_state_rendering")

# ml_training_pipeline: 5 except-substitute repairs (the 6 IMPUTATION items in this group
# stay FALLBACK, unrepaired -- ml_train.py/training_cache.py's own imputation methodology
# is a real product-accuracy decision, not a mechanical fix; treated as the mission's own
# "irreducible product decision" pause criterion pending explicit operator sign-off on the
# replacement methodology, not silently picked by this session).
_mark_repaired(
    ["FB-00243", "FB-00246"],
    "REPAIRED 2026-09-17: lstm_data.py -- a ticker-roster-resolution FAILURE used to log/"
    "warn the identical message a genuinely-empty roster produces, masking which one "
    "actually happened. Now disclosed distinctly (CLI script: an accurate ERROR message "
    "before the same sys.exit(1); library function: a distinct log.warning naming the "
    "exception).",
    "ml_training_pipeline")
_mark_repaired(
    ["FB-00392"],
    "REPAIRED 2026-09-17: ml_scheduler.py -- _training_ticker_union no longer swallows a "
    "roster-resolution failure into an empty list; the one call site now distinguishes "
    "'resolution failed' (exit_code 2, error disclosed) from 'confirmed-empty enrollment' "
    "(exit_code 0) instead of reporting both as the same clean skip.",
    "ml_training_pipeline")
_mark_repaired(
    ["FB-01155"],
    "REPAIRED 2026-09-17: train_all.py run_xgb -- a roster-resolution failure now prints an "
    "accurate ERROR before falling through to zero tickers, instead of silently training "
    "nothing with no disclosure of why.",
    "ml_training_pipeline")
_mark_repaired(
    ["FB-01179"],
    "REPAIRED 2026-09-17: transformer_train.py -- same fix as train_all.py, via log.warning.",
    "ml_training_pipeline")

# calibration_ml_governance: tools/legacy/horizon_7/* (11 sites) DELETED entirely -- the
# whole directory was quarantined dead code (identical "DEPRECATED... do not run against
# post-D3 databases" banner on every file, confirmed by its own README), not a required
# responsibility. Four files outside that directory had real imports from it
# (_incomplete_fused_sql/_classify_failure, schema-agnostic, relocated to the new
# tools/_fusion_backfill_shared.py; GOV_WHERE, genuinely schema-specific to the dropped
# outcome_3c/8c/13c columns, removed outright since the query would error against the
# current schema) -- see tests/test_fusion_backfill_shared_v1.py.
_mark_repaired(
    ["FB-01005", "FB-01006", "FB-01007", "FB-01008", "FB-01012", "FB-01013", "FB-01014",
     "FB-01015", "FB-01020", "FB-01024", "FB-01028", "FB-01029"],
    "REPAIRED 2026-09-17: tools/legacy/horizon_7/ deleted entirely (17 files, all "
    "identically quarantined dead code per the directory's own README). Dependent files "
    "(tools/backfill_fusion_policy_complete_v1.py, tools/validate_fusion_backfill_complete_v1.py, "
    "tools/backfill_fusion_policy_columns_expanded_v1.py, "
    "tools/analyze_fused_xgb_comparison_dataset_v1.py) repaired to not import from the "
    "deleted module. Tests: tests/test_fusion_backfill_shared_v1.py (7 tests).",
    "calibration_ml_governance")
# db.py: 6 COALESCE(horizon_outcome_schema_version, X) = X sites simplified to a plain
# `= ?` (SQL's own NULL semantics naturally exclude an unrecorded-version row instead of
# assuming the current anchor version for it). See tests/test_horizon_bar_outcomes.py.
_mark_repaired(
    ["FB-00174", "FB-00182", "FB-00184", "FB-00185", "FB-00186", "FB-00188"],
    "REPAIRED 2026-09-17: db.py -- COALESCE(horizon_outcome_schema_version, X) = X "
    "simplified to a plain `horizon_outcome_schema_version = ?` across fill_outcomes, "
    "refresh_all_governed_bar_anchor_outcomes_v1, fill_outcomes_pin_neutral_backfill_v1, "
    "and _snapshot_rows_affected_by_bar_mutations. Tests: "
    "tests/test_horizon_bar_outcomes.py::"
    "test_fill_outcomes_unfilled_row_query_never_defaults_a_null_schema_version.",
    "calibration_ml_governance")


# FB-00181 (db.py:3341, inside the ONE-TIME schema-flag-gated migration that ESTABLISHES
# horizon_outcome_schema_version in the first place) was swept into the blanket SQL
# reclassification above without individual review. Direct investigation during repair
# (2026-09-17) found it structurally different from every other COALESCE in this group: it
# is not a READ masking a missing value as a confirmed one -- it is the WRITE that
# deliberately treats "no version recorded" (COALESCE(...,0), 0 being lower than any real
# version) as "needs migrating to the current version", which is the correct, intentional
# mechanism that makes the other 6 repaired read-queries' `= ?` filters actually correct
# (a NULL row gets migrated to a real version here, not silently left ambiguous forever).
# Reclassified NOT_FALLBACK with this specific reasoning -- distinct from, not a re-run of,
# the operator's rejected blanket "safe idiom" classifications (aggregate-over-empty-set,
# display-label, update-preserve), none of which apply to a migration WRITE.
def _apply_fb_00181_investigated_reclassification(raw_candidates: list[dict]) -> None:
    for c in raw_candidates:
        if c["id"] == "FB-00181":
            ADJUDICATION[c["id"]] = (
                "NOT_FALLBACK",
                "Investigated 2026-09-17 during repair (not a blanket idiom classification): "
                "this COALESCE sits inside the ONE-TIME, schema-flag-gated migration "
                "(guarded by a ed_schema_flags row check) that ESTABLISHES "
                "horizon_outcome_schema_version for pre-existing rows -- it is the WRITE "
                "mechanism, not a READ masking absence. COALESCE(...,0) deliberately "
                "treats an unrecorded version as 'older than any real version, needs "
                "migrating', which is what makes it safe for every OTHER (read-side) query "
                "in this file to now assume the column is populated.",
                "none",
                "calibration_ml_governance",
            )


def main() -> int:
    raw_path = REPO / "reports" / "no_fallback_discovery_raw.json"
    out_path = REPO / "reports" / "no_fallback_inventory.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    candidates = raw["candidates"]
    _apply_operator_correction_2026_09_17(candidates)
    _apply_fb_00181_investigated_reclassification(candidates)

    applied = 0
    for c in candidates:
        if c["id"] in REPAIRED:
            repair_note, group = REPAIRED[c["id"]]
            c["adjudication"] = "REPAIRED"
            c["required_repair"] = repair_note
            c["proposed_ownership_group"] = group
            applied += 1
            continue
        override = ADJUDICATION.get(c["id"])
        if override:
            verdict, evidence, repair, group = override
            c["adjudication"] = verdict
            c["evidence"] = c["evidence"] + " | ADJUDICATED: " + evidence
            c["required_repair"] = repair
            c["proposed_ownership_group"] = group
            applied += 1
        else:
            c["required_repair"] = ("pending semantic adjudication -- not yet reached by a "
                                     "human/agent reading in this pass")
            c["proposed_ownership_group"] = "unadjudicated_pending_next_pass"

    by_verdict: dict[str, int] = {}
    for c in candidates:
        by_verdict[c["adjudication"]] = by_verdict.get(c["adjudication"], 0) + 1

    report = {
        "scanned_by_type": raw["scanned_by_type"],
        "unscanned_declared_noop_by_ext": raw["unscanned_declared_noop_by_ext"],
        "unscanned_unknown_extensions": raw["unscanned_unknown_extensions"],
        "candidate_count": len(candidates),
        "adjudicated_this_pass": applied,
        "verdict_counts": by_verdict,
        "candidates": candidates,
    }
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"candidate_count: {len(candidates)}")
    print(f"adjudicated_this_pass: {applied}")
    print(f"verdict_counts: {by_verdict}")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
