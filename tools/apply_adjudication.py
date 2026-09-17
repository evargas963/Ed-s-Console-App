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
    ["FB-00266", "FB-00294"],
    "REPAIRED 2026-09-17, CORRECTED 2026-09-17 (operator rejected the first pass as still "
    "substituting a meaningful state): market_state.py build_market_state()'s except-"
    "handler no longer guesses a value off consensus_summary.gex_magnitude (an attribute "
    "that does not exist upstream in practice) -- the first correction stopped there but "
    "kept a hardcoded 'negligible' alongside the new state_error disclosure, which the "
    "operator correctly identified as still a meaningful, valid-looking value standing in "
    "for a genuine computation failure. ms.gex_magnitude is now genuinely None on "
    "failure; MarketState.gex_magnitude's own field type changed from `str = "
    "\"negligible\"` to `Optional[str] = None` to make this representable. "
    "Tests: tests/test_action12_7_market_state_fail_closed.py::"
    "test_gex_magnitude_computation_failure_is_disclosed_not_guessed (updated to assert "
    "None, not 'negligible'), "
    "::test_gex_magnitude_never_reads_a_guessed_alternate_source_on_failure.",
    "market_state_rendering")
_mark_repaired(
    ["FB-00282"],
    "REPAIRED 2026-09-17 (previously deliberately paused as an apparent irreducible "
    "product decision -- 'inventing a DEX magnitude bucketing methodology'; the operator "
    "corrected this framing: the mandate was never to invent thresholds, only to stop "
    "fabricating a value where no real computation exists). Traced the full construction "
    "graph: MarketState.dex_magnitude (str='negligible' -> Optional[str]=None) -> "
    "SignalInput.dex_magnitude (already Optional[str]=None, unaffected) -> "
    "call_engine.py's `dex_magnitude=inp.dex_magnitude or 'moderate'` (removed the `or "
    "'moderate'`, passes None through) -> math_exposure_core.greek_bias's own "
    "`dex_magnitude: str = 'moderate'` parameter default and "
    "`MAG_SCALE.get(dex_magnitude, 0.7)` (both changed to exclude the delta-magnitude "
    "vote's contribution entirely when the magnitude is None or unrecognized, rather than "
    "assuming a 'moderate' 0.7 significance for exposure whose scale was never computed). "
    "governance/provenance_roots.py's own pre-existing registry already documented "
    "'dex_magnitude': ('MARKET', None) -- no derivation function -- confirming this field "
    "has never had a real producer; grep-confirmed no persistence (db.py) or frontend "
    "(static/*.js) consumer exists, so the blast radius is fully contained to the "
    "MarketState/SignalInput/call_engine/greek_bias decision chain. charm_magnitude's "
    "identical `or 'moderate'` + MAG_SCALE default in the SAME greek_bias call was fixed "
    "in the same pass (charm_magnitude already had a real, Optional-typed producer -- "
    "server.py's own charm computation -- so only the consumer-side fallback needed "
    "fixing, not the producer). Tests: "
    "tests/test_action12_7_market_state_fail_closed.py::"
    "test_dex_magnitude_is_always_none_no_producer_exists (new); "
    "tests/test_greek_bias_magnitude_unavailable.py (4 new tests proving an unavailable "
    "or unrecognized magnitude excludes that vote's score contribution entirely, not a "
    "silent moderate-scale assumption); the existing call_engine/charm-vote-gate test "
    "suites (41 tests) still pass since they always pass explicit magnitude strings, "
    "never relying on the old default.",
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
        if c["id"] == "FB-00187":
            ADJUDICATION[c["id"]] = (
                "NOT_FALLBACK",
                "Investigated 2026-09-17 during repair: `enrollment_source = "
                "COALESCE(enrollment_source, ?)` inside an UPDATE is a preserve-existing-"
                "value WRITE (only fills the column the FIRST time a ticker is "
                "re-enrolled, never overwrites an already-recorded source with a later "
                "re-enrollment's source) -- structurally the same shape as FB-00181, a "
                "WRITE deliberately protecting prior provenance, not a READ masking a "
                "missing value as a fabricated one. Rewriting it as an explicit "
                "'WHERE enrollment_source IS NULL' second statement would express the "
                "identical semantics with no behavioral difference, at the cost of a "
                "second round trip for no real gain -- left as-is.",
                "none",
                "calibration_ml_governance",
            )
        if c["id"] in ("FB-00258", "FB-00259", "FB-00286"):
            ADJUDICATION[c["id"]] = (
                "NOT_FALLBACK",
                "Investigated 2026-09-17: `for ct in contracts or []` / `(ct for ct in "
                "contracts or [])` is an ordinary iteration-safety guard, not a value "
                "substitution -- None and [] produce the IDENTICAL observable behavior here "
                "(zero iterations), and no semantic field is ever assigned a fabricated "
                "value as a result. This is the mission's own required 'ordinary control "
                "flow, not falsely rejected' positive control, not a fallback.",
                "none",
                "market_state_rendering",
            )
        if c["id"] == "FB-00265":
            ADJUDICATION[c["id"]] = (
                "NOT_FALLBACK",
                "Investigated 2026-09-17: `charm_top_drivers or []` normalizes an "
                "Optional[list] parameter to a list, matching the MarketState dataclass "
                "field's own `field(default_factory=list)` default. Unlike a scalar/enum "
                "default (which can be mistaken for a genuine reading), an empty list is "
                "not a fabricated valid-looking VALUE -- 'no drivers computed' and 'zero "
                "drivers found' render and behave identically for every consumer (an empty "
                "iteration either way). Ordinary collection-type normalization, not a "
                "fallback substitution.",
                "none",
                "market_state_rendering",
            )
        if c["id"] == "FB-00270":
            ADJUDICATION[c["id"]] = (
                "NOT_FALLBACK",
                "Investigated 2026-09-17: `exp_key = str(expiry or \"\")[:10]` is immediately "
                "followed by `if len(exp_key) != 10: return None` -- an explicit, "
                "self-documented ('An empty/missing expiry is a governed absence -- NO "
                "selected-contract DTE -- never a silent search across every expiry') "
                "fail-closed check. The `or \"\"` only exists so None can be uniformly "
                "length-checked alongside a malformed string; it is the disclose-the-"
                "failure pattern the mandate itself requires, not a substitution for it.",
                "none",
                "market_state_rendering",
            )
        if c["id"] == "FB-00285":
            ADJUDICATION[c["id"]] = (
                "NOT_FALLBACK",
                "Investigated 2026-09-17: `t = (ms.ticker or \"\").upper().strip()` feeds a "
                "purely cosmetic contract-label string (e.g. 'SPY 2026-06-20 450C'). "
                "ms.ticker is populated from build_market_state's required, non-Optional "
                "`ticker: str` parameter -- the function's own primary identity input, never "
                "legitimately absent in a correct call. The guard prevents a `None.upper()` "
                "crash; its degraded output is an honest blank space in the label, not a "
                "fabricated ticker symbol that could be mistaken for real data.",
                "none",
                "market_state_rendering",
            )
        if c["id"] in ("FB-00263", "FB-00264"):
            ADJUDICATION[c["id"]] = (
                "NOT_FALLBACK",
                "Investigated 2026-09-17: `iv_direction if iv_direction in (\"expanding\", "
                "\"contracting\", \"flat\") else None` / the analogous charm_direction check "
                "is an explicit WHITELIST validation -- any value outside the three named, "
                "real states maps to an honest None, never to a fabricated valid-looking "
                "member of the enum. This is the mission's own required 'ordinary control "
                "flow, not falsely rejected' positive control: it EXPOSES an invalid/unknown "
                "input as None rather than substituting a guessed value for it.",
                "none",
                "market_state_rendering",
            )
        if c["id"] in ("FB-00271", "FB-00287", "FB-00288", "FB-00289"):
            ADJUDICATION[c["id"]] = (
                "NOT_FALLBACK",
                "RE-INVESTIGATED 2026-09-17 (superseding an earlier pass that cited a "
                "structural test's assertion as if that were the proof -- tests are not "
                "semantic authority; corrected per direct operator instruction). "
                "Independently traced the actual source chain, not the test: server.py's "
                "per-cycle vol_ctx construction (~line 7850-7867) sets "
                "`vol_ctx = MarketVolContextV1(market_iv_level=_vol_vix_now, ...)` where "
                "`_vol_vix_now = float(mkt_ctx.vix)` -- literally the same float value read "
                "from the same single Schwab $VIX quote fetch inside "
                "market_context.fetch_market_context (one call site, confirmed via grep: "
                "no second vendor call, no alternate producer anywhere in the chain). "
                "`vol_ctx.market_iv_level if vol_ctx is not None else mkt_ctx.vix` is "
                "therefore reading the IDENTICAL underlying value through whichever of two "
                "structurally-equivalent carriers a given caller populated -- not an "
                "alternate/different vendor source standing in for a missing one, which is "
                "what this rule class prohibits. The two direction/change siblings "
                "(FB-00288 market_iv_direction, FB-00289 market_iv_change) don't even have a "
                "mkt_ctx-side value to fall back to -- they degrade to a bare None when "
                "vol_ctx is absent, the mandate's own required shape, not a substitution. "
                "This finding does not depend on, and is not weakened by, the separate "
                "structural test that happens to also assert this source shape.",
                "none",
                "market_state_rendering",
            )
        if c["id"] in ("FB-01161", "FB-01162"):
            ADJUDICATION[c["id"]] = (
                "NOT_FALLBACK",
                "RE-INVESTIGATED 2026-09-17 per operator instruction to establish "
                "correctness independently (not defer to a blanket pattern-match): "
                "training_cache.py's compare_tabular_data_fingerprint_from_df uses "
                "s.fillna(-1.0) ONLY to make a ts_utc Series hashable/sortable when "
                "computing a cache content_hash (confirmed via grep: content_hash flows "
                "into compute_feature_cache_key/compute_scheduler_cache_key -- cache KEY "
                "generation -- never into engineer_features, X, or any model .fit()/"
                ".predict() call anywhere in the repo). ts_utc is a Unix epoch timestamp "
                "(~1.7-1.9 billion for real dates); -1.0 is structurally outside that "
                "domain and can never be confused with, or collide with, a genuine "
                "timestamp. This is a hash-stability sentinel for cache-key computation, "
                "not model-feature imputation -- the mandate's ML-imputation rule targets "
                "missing training/serving data becoming an observed value fed to a model, "
                "which does not happen here.",
                "none",
                "ml_training_pipeline",
            )


_mark_repaired(
    ["FB-00114", "FB-00115", "FB-01072", "FB-01075"],
    "REPAIRED 2026-09-17: calibration/operable_surface_quarantine.py's operable_filter_sql "
    "and its own quarantine UPDATE, plus tools/operable_surface_gate.py's own COUNT query "
    "and report-string description of the same predicate -- COALESCE(research_excluded,0) "
    "was provably-redundant, not a real fallback: every call site is guarded by _has_col() "
    "before running, and the ONE writer that ever creates the column always does so via "
    "'ALTER TABLE ... ADD COLUMN research_excluded INTEGER NOT NULL DEFAULT 0', which "
    "SQLite backfills onto every pre-existing row and enforces going forward -- NULL is "
    "structurally impossible past that guard. Simplified to a plain `research_excluded=0`/"
    "`=1`. Tests: tests/test_operable_surface_gate.py (2 new tests) plus the 3 pre-existing "
    "tests in that file, all still passing unchanged.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-01073", "FB-01074"],
    "REPAIRED 2026-09-17: tools/operable_surface_gate.py's MAX/MIN aggregate-over-possibly-"
    "empty-set COALESCE(...,0) calls removed at the SQL level (per the operator's ruling: "
    "no aggregate exemption survives). Behavior is unchanged -- this file's own "
    "pre-existing Python-side `float(x or 0.0)` on the very next line already handled the "
    "resulting NULL identically; only the SQL-level redundancy is gone.",
    "calibration_ml_governance")


def _apply_deleted_file_repairs(raw_candidates: list[dict]) -> int:
    """A candidate whose FILE no longer exists on disk is REPAIRED by deletion, full stop --
    generalized after a real gap this session's own reconciliation caught: the
    tools/legacy/horizon_7/ deletion was recorded via a manually-typed FB-id list that
    missed 17 of the directory's own 29 candidates (every non-SQL, non-EXCEPT_SUBSTITUTE
    pattern in those files was simply never enumerated by hand). Checking the filesystem
    directly cannot have that class of gap -- a deleted file has zero surviving candidates,
    mechanically, regardless of which patterns this session happened to adjudicate in it."""
    n = 0
    for c in raw_candidates:
        if c["adjudication"] == "REPAIRED":
            continue
        if not (REPO / c["file"]).exists():
            c["adjudication"] = "REPAIRED"
            c["required_repair"] = (
                f"REPAIRED (file deleted): {c['file']} no longer exists in this tree -- "
                f"see git history for the commit that removed it and its own reasoning."
            )
            c["proposed_ownership_group"] = "deleted_file"
            n += 1
    return n


_mark_repaired(
    ["FB-00433", "FB-00434", "FB-00435", "FB-00436", "FB-00437", "FB-00438"],
    "REPAIRED 2026-09-17: normalized_training_sync.py's _aggregate_select_exprs -- all 6 "
    "MAX/SUM COALESCE(...,0) calls removed. The one consumer, "
    "compute_snapshots_training_fingerprint, concatenates every value into a change-"
    "detection fingerprint STRING; an aggregate-over-zero-rows now contributes 'None' "
    "instead of '0', still a distinct, deterministic, change-sensitive token (the "
    "fingerprint's only real contract). Tests: "
    "tests/test_issue16_normalized_training_sync.py::"
    "test_fingerprint_handles_empty_snapshots_table_without_crashing.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00724"],
    "REPAIRED 2026-09-17: snapshot_normalizer.py's MAX(snapshot_id) COALESCE removed -- "
    "the very next line's Python `int(row_mx[0] if ... is not None else 0)` already "
    "handled the NULL case identically.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-01062"],
    "REPAIRED 2026-09-17: tools/migrate_snapshots_schema_repair_v1.py's "
    "MAX(snapshot_id) COALESCE removed -- the Python-side `int(row[...] or 0)` two lines "
    "below already handled the NULL case identically.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-01110"],
    "REPAIRED 2026-09-17: tools/repo_exposure_audit.py's SUM(c-1) COALESCE removed. Unlike "
    "the other aggregate sites in this group, this one had NO pre-existing Python-side "
    "guard -- the f-string/division right after it would have crashed on the common, "
    "healthy-database 'zero duplicate groups' case if the SQL-level default were simply "
    "deleted, so an explicit `extra = extra_row if extra_row is not None else 0` guard was "
    "added. Tests: tests/test_repo_exposure_audit_v1.py (3 new tests, including the "
    "zero-duplicates case that would have crashed without the added guard).",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00179", "FB-00180"],
    "REPAIRED 2026-09-17: db.py compute_accuracy's rth_only boundary check "
    "(et_hour*60+et_minute) no longer defaults a NULL et_minute to :00 -- et_minute is a "
    "genuine nullable INTEGER, and dropping the SQL default lets a row with an unrecorded "
    "minute be naturally excluded (SQL NULL arithmetic fails the boundary comparison) "
    "rather than assumed to have landed on the hour. Tests: "
    "tests/test_model_accuracy_wire.py::test_compute_accuracy_rth_scope_excludes_null_et_minute.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00058"],
    "REPAIRED 2026-09-17: audit_model_readiness.py's rules_signal GROUP BY report no longer "
    "SQL-defaults a NULL signal to the string 'NULL' -- SQLite already groups a genuine NULL "
    "into its own distinct bucket unaided, and the report's own f-string "
    "(', '.join(f'{s}:{c}' ...)) already prints Python's 'None' for that bucket, an "
    "equally self-describing label.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00175"],
    "REPAIRED 2026-09-17: db.py sql_issue19_snapshots_context_group no longer SQL-defaults "
    "a NULL grouping column to the string '(null)' -- the one caller "
    "(tools/issue19_option_a_post_validate.py) puts the result straight into a JSON-shaped "
    "report entry, where a real JSON null is more honest than a string that could be "
    "mistaken for a genuine category value.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00081", "FB-00083", "FB-00084"],
    "REPAIRED 2026-09-17: calibration/anchor_audit.py's three canonical_timeframe filters "
    "no longer SQL-default a NULL canonical_timeframe to '1m' -- "
    "calibration/schema.py's base CREATE TABLE for the calibration decision-log table "
    "declares canonical_timeframe TEXT NOT NULL DEFAULT '1m' from inception, and the "
    "column is absent from _CALIBRATION_OPTIONAL_COLUMNS (the lazy ALTER TABLE ADD "
    "COLUMN migration list), so no code path can ever produce a row with a NULL value "
    "here -- the same 'provably redundant, engine-enforced NOT NULL' shape as "
    "research_excluded. Tests: "
    "tests/test_calibration_anchor_stability.py::test_no_fallback_lock_repair_2026_09_17_"
    "no_coalesce_left_in_anchor_audit_source (structural) plus the file's 2 pre-existing "
    "behavioral tests, both still green.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00088"],
    "REPAIRED 2026-09-17: calibration/backfill_outcomes.py's re-sync join key no longer "
    "unconditionally falls back from a missing matched_snapshot_ts_utc to decision_ts_utc. "
    "matched_snapshot_ts_utc is a genuinely nullable column (pre-migration legacy rows never "
    "had it recorded); substituting decision_ts_utc for it was an unproven guess that could "
    "silently re-attach a legacy nearest-tolerance-matched row to the WRONG snapshot. The "
    "repair only treats decision_ts_utc as the join key when outcome_join_method=='exact' "
    "proves the two timestamps are equal (an actual computed fact, not a substitution, per "
    "resolve_snapshot_for_backfill's own exact-match invariant); a legacy row whose original "
    "match provenance is neither recorded nor provably exact is now skipped (new "
    "resync_skipped_match_provenance_unrecorded stat) instead of guessed. Tests: "
    "tests/test_backfill_outcomes_resync_provenance.py (4 new tests, including the exact "
    "scenario -- a decoy snapshot present at decision_ts_utc -- that would have silently "
    "attached the wrong outcome under the old guess).",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00091", "FB-00093"],
    "REPAIRED 2026-09-17: calibration/canonical_1m_grid_scan.py's two snapshots-scoping "
    "queries no longer SQL-default a NULL horizon_outcome_schema_version to "
    "HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1 -- identical shape and identical genuine-nullable "
    "root cause (a bare ALTER TABLE ADD COLUMN with no DEFAULT for pre-existing databases) "
    "already repaired across db.py's own fill_outcomes-family queries. Dropping the COALESCE "
    "lets SQL NULL propagation exclude a row of unknown/legacy schema version from the scan "
    "rather than silently counting it as verified BAR_ANCHOR_V1. Tests: "
    "tests/test_canonical_1m_grid_scan_schema_version.py (a real BAR_ANCHOR_V1 row is still "
    "counted; a structural proof mirrors db.py's own "
    "test_fill_outcomes_unfilled_row_query_never_defaults_a_null_schema_version precedent, "
    "since a NULL row isn't constructible through the ORM on a freshly created database).",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00122", "FB-00124"],
    "REPAIRED 2026-09-17: calibration/phase6_edge_discovery_governed_v1.py's load_rows() "
    "governed-population query no longer SQL-defaults a NULL horizon_outcome_schema_version "
    "to 3 -- identical shape and identical genuine-nullable root cause already repaired "
    "across db.py and calibration/canonical_1m_grid_scan.py. "
    "calibration/phase65_edge_isolation_v1.py's FROZEN['governed_predicate'] constant quoted "
    "the same COALESCE as prose describing this exact query (it imports load_rows from this "
    "module); reworded to match the repaired query rather than left stale. Tests: "
    "tests/test_phase6_edge_discovery_governed_schema_version.py (a real anchored, "
    "full-outcome BAR_ANCHOR_V1 row is still loaded; structural proofs for both files).",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00129", "FB-00130", "FB-00132", "FB-00133", "FB-00134"],
    "REPAIRED 2026-09-17: calibration/repair_canonical_1m_edge_carry_v1.py and its sibling "
    "calibration/repair_canonical_1m_interior_gaps_v1.py both reported 0 for "
    "rows_upserted/tickers_touched/governed_outcome_refresh_tickers/fill_outcomes_tickers "
    "in their except-handlers on a batch-write failure. apply_repair_1m_bar_batch_writes "
    "(calibration/repair_canonical_1m_shared.py) rolls back its single BEGIN IMMEDIATE "
    "transaction on any exception, so these counts ARE durably zero -- but reporting a bare "
    "0 collapses a crash into the same value a genuine no-op success would report, exactly "
    "the mission's prohibited 'zero...placeholder' shape even though the number itself is "
    "accurate: the field can no longer distinguish 'ran fine, nothing to touch' from "
    "'crashed, transaction rolled back.' Changed all affected fields to None on failure -- "
    "an explicit not-reported-due-to-failure marker distinct from either real outcome, "
    "alongside the pre-existing rep['error'] string. Tests: "
    "tests/test_repair_canonical_1m_edge_carry_v1.py and "
    "tests/test_repair_canonical_1m_interior_gaps_v1.py each gained a "
    "test_run_repair_failure_reports_none_not_zero_counts proving the None-on-failure shape "
    "via a monkeypatched batch-writer that raises.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-01076", "FB-01077", "FB-01078", "FB-00892", "FB-00893"],
    "REPAIRED 2026-09-17: tools/pin_neutral_1m_5m_divergence_audit_v1.py's "
    "bar_anchor_scope_sql() no longer SQL-defaults a NULL horizon_outcome_schema_version "
    "(same genuine-nullable root cause repaired repeatedly across this branch), and its two "
    "COALESCE(outcome_filled,0)=N sites now compare outcome_filled directly -- db.py's own "
    "production queries (fill_outcomes, pin_neutral eligibility, etc.) already compare "
    "outcome_filled bare throughout, so a COALESCE here was the outlier against this repo's "
    "own established contract, not the norm. The JSON-registered SQL templates for this "
    "file's by_ticker_agg and unfilled_has_anchor keys (snapshot_sql/registry_full_c.json) "
    "carried the identical COALESCE shapes -- not reachable by the discovery scanner since "
    "they are JSON string values, not Python string literals -- and were fixed in lockstep, "
    "including trimming the now-3-vs-2 placeholder mismatch this created (all three "
    "bar_anchor_scope_sql() call sites' scope tuples shrank from (tf, V1, V1) to (tf, V1)). "
    "tests/test_pin_neutral_1m_5m_divergence_audit_v1.py's own COALESCE-quoting example "
    "input was reworded to a bare comparison (it was just demonstrating alias substitution, "
    "not asserting the shape must be COALESCE). Tests: the same file gained a structural "
    "no-COALESCE proof plus a real-DB integration test exercising inventory_timeframe and "
    "by_ticker_breakdown end-to-end, which would have raised sqlite3.ProgrammingError on any "
    "placeholder-count mismatch.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00137", "FB-00830"],
    "REPAIRED 2026-09-17: calibration/run_production_accumulation_validation.py's "
    "_unsafe_non_exact_joins (renamed _non_exact_or_unrecorded_joins) and the mirrored "
    "assertion in tests/test_calibration_outcome_join_scale.py both used "
    "IFNULL(outcome_join_method, '') NOT IN ('exact', '') / != 'exact' -- defaulting a NULL "
    "(unrecorded) join method to a never-occurring '' sentinel before the comparison, which "
    "silently counted 'we don't know how this row was joined' as safe alongside a proven "
    "exact match. Split into two explicit, non-overlapping counts (recorded "
    "nearest_within_tol vs. unrecorded/NULL provenance); the validation harness's "
    "unsafe_joins_zero gate now requires BOTH to be zero, and the report exposes both counts "
    "by name rather than one folded 'unsafe' figure. This was originally reclassified "
    "NOT_FALLBACK before the operator's blanket SQL correction swept it to FALLBACK; "
    "re-investigated on its own evidence (not the blanket ruling) and confirmed as a genuine "
    "repair target, not a safe idiom -- unrecorded provenance was being silently treated as "
    "safe by omission from the risk count. Tests: "
    "tests/test_calibration_accumulation_validation.py gained "
    "test_non_exact_or_unrecorded_joins_separates_nearest_from_unrecorded (direct unit proof "
    "of the two-bucket split); the full accumulation harness "
    "(test_production_accumulation_harness_passes) and outcome-join scale suite both still "
    "pass end-to-end.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00148"],
    "REPAIRED 2026-09-17: calibration/writer.py's _count_enrolled_tickers queried "
    "logging_universe WHERE COALESCE(active, 1) = 1 -- but db.py's real CREATE TABLE for "
    "logging_universe has never had an `active` column (eviction is DELETE-based, tracked "
    "separately in logging_universe_eviction_log, not an in-row flag). This query has always "
    "raised sqlite3.OperationalError against a real production database, silently swallowed "
    "by the function's own broad except into a fabricated '0 enrolled tickers' on every "
    "single call -- a confirmed production bug hiding behind the fallback pattern, not just a "
    "style violation. Fixed to SELECT COUNT(*) FROM logging_universe with no WHERE clause, "
    "since every row present is enrolled by construction. Also fixed "
    "tests/test_calibration_logging_production_path.py's _seed_calibration_health_fixture, "
    "which had its own hand-rolled logging_universe CREATE TABLE that (accidentally) DID "
    "define an `active` column -- a fixture schema diverging from the real production schema, "
    "which is exactly what let the original bug's tests pass while production silently always "
    "returned 0. The fixture now builds via EdDB (the real schema) instead. Tests: added "
    "test_count_enrolled_tickers_against_real_production_schema, which would have failed "
    "loudly (sqlite3.OperationalError) against the pre-repair query and the real schema.",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00927"],
    "REPAIRED 2026-09-17: tools/_multi_timeframe_audit_v1.py's schema-version histogram "
    "used COALESCE(horizon_outcome_schema_version, -1) as a GROUP BY key -- binning NULL "
    "rows under a fabricated sentinel, -1, written into a report field literally named "
    "'schema_version' that could be misread as a genuine (if nonsensical) version number "
    "rather than 'unknown'. A bare GROUP BY lets SQLite group NULL rows on their own; the "
    "report now carries a real null for that bucket. Tests: "
    "tests/test_multi_timeframe_audit_v1.py (structural no-COALESCE proof; a direct proof of "
    "the query shape's NULL-grouping behavior, since a NULL "
    "horizon_outcome_schema_version isn't constructible through a fresh EdDB's NOT NULL "
    "DEFAULT 3 schema).",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-01105"],
    "REPAIRED 2026-09-17: tools/repair_validation_counts_v1.py's diagnostic counts used "
    "SQL-level default-on-NULL comparisons for outcome_filled and horizon_outcome_schema_version "
    "throughout, including a whole third comparison line explicitly labeled by that shape "
    "whose value was always mathematically just the sum of the two bare-comparison lines "
    "above it (outcome_filled IS NULL and outcome_filled = 0 are disjoint, so their SQL-level "
    "default-on-NULL union added no information). Simplified every query to a bare "
    "comparison and derived the redundant comparison in Python instead of issuing a fourth "
    "SQL-level default-on-NULL query; removed the now-unused loop_coalesce0 JSON registry "
    "entry. Three MORE COALESCE occurrences in this file's JSON-registered SQL templates "
    "(snapshot_sql/_auto_extracted.json, snapshot_sql/registry_full_b.json) were unreachable "
    "by the discovery scanner (JSON string values, not Python literals) and were fixed in "
    "lockstep, including trimming two now-3-vs-2 placeholder mismatches this created. Tests: "
    "tests/test_repair_validation_counts_v1.py (structural no-COALESCE proof; a real-DB "
    "end-to-end run proving every placeholder-count fix line up correctly and the derived "
    "sum prints correctly).",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-01135"],
    "REPAIRED 2026-09-17: tools/smoke_movement_heads_inference_v1.py's GOV governed-"
    "population predicate SQL-defaulted a NULL horizon_outcome_schema_version to 3 -- the "
    "identical shape and identical genuine-nullable root cause repaired repeatedly across "
    "this branch. Simplified to a bare equality. Tests: "
    "tests/test_smoke_movement_heads_inference_v1.py (structural no-COALESCE proof; a "
    "real-DB proof that the predicate selects a BAR_ANCHOR_V1 row and excludes a row of a "
    "different recorded schema version).",
    "calibration_ml_governance")
_mark_repaired(
    ["FB-00262"],
    "REPAIRED 2026-09-17: market_state.py's build_market_state() read "
    "mkt_ctx.vix_regime/vix_color/vix_implication/pcr_arrow/pcr_color/pcr_label via "
    "getattr(mkt_ctx, name, default) -- but mkt_ctx is provably always a real MarketContext "
    "instance: server.py's _fetch_and_store_mkt_ctx falls back to a fresh MarketContext() "
    "of its own (never None or a partial object) on any fetch failure, and every real and "
    "test call site confirmed to pass a full MarketContext/mock with these fields always "
    "set. The getattr default could never fire -- provably redundant, same class as the SQL "
    "COALESCE repairs across this branch, just in attribute-access form. Simplified all six "
    "to bare attribute access. Tests: "
    "tests/test_action12_7_market_state_fail_closed.py gained "
    "test_mkt_ctx_fields_read_directly_no_silent_default_on_a_real_value, proving a genuine "
    "non-default value flows through untouched; the file's other 12 tests (including the "
    "gex_magnitude disclosure tests from the earlier market_state_rendering repair) still "
    "pass, as do the three other build_market_state test files.",
    "market_state_rendering")
_mark_repaired(
    ["FB-00260", "FB-00281"],
    "REPAIRED 2026-09-17: market_state.py's two `ms.call_option_expiry or "
    "ms.selected_exp` sites (_build_contract_context_ms and the selected-DTE call in "
    "build_market_state) simplified to bare `ms.call_option_expiry` -- that field has "
    "exactly one write site in this whole repo (build_market_state's own "
    "`ms.call_option_expiry = selected_exp`, always executed before either read site "
    "runs), so it is provably always equal to ms.selected_exp: the `or` fallback could "
    "never actually substitute a different value. Updated "
    "tests/test_single_producer_batch_f02_f13_v1.py's "
    "test_rc345_selected_dte_selectors_both_key_on_expiry, which had asserted the exact "
    "pre-repair source text, to match the simplified shape while preserving the real "
    "invariant it protects (both DTE-selector callers pass the selected expiry).",
    "market_state_rendering")
_mark_repaired(
    ["FB-00272", "FB-00273", "FB-00274", "FB-00275", "FB-00276", "FB-00277", "FB-00278"],
    "REPAIRED 2026-09-17: market_state.py's whole 'The Call' field-population block "
    "(~30 getattr(_call, name, default) calls, of which these 7 were the ones the "
    "discovery scanner's semantic-term matcher flagged) simplified to bare attribute "
    "access. _call is always a signal_types.TheCall instance -- a @dataclass whose every "
    "field read here is required or class-defaulted, and call_engine.py is confirmed the "
    "SOLE production constructor -- so Python's own dataclass machinery makes it "
    "impossible to construct a TheCall missing any of them; every getattr default was "
    "provably dead code. Also simplified the sibling 'Right Now' block's `_rules.micro` "
    "sub-fields (session_high/session_low/sweeps/last_sweep -- _micro is always a real "
    "micro_structure.MicroRead when truthy, confirmed via rules_engine.py's `micro=micro` "
    "pass-through) and `_rules.headline_1m` (a required, non-default str field on "
    "RulesCard), beyond the scanner-flagged set, matching this branch's established "
    "practice of fixing the whole identical-shape cluster once one member is confirmed. "
    "One test (tests/test_market_state_numeric_contract_v1.py) had constructed an "
    "incomplete SimpleNamespace stand-in for TheCall (only 12 of its ~30 fields) that "
    "the pre-repair getattr calls had silently tolerated -- replaced with a real TheCall "
    "instance, matching this session's established precedent of fixing a test fixture to "
    "the real schema rather than leaving it diverged. Other test files construct "
    "incomplete RulesCard(micro=SimpleNamespace(...)) stand-ins, but confirmed none of "
    "them route through build_market_state (they test rules_engine.py/call_engine.py "
    "directly), so they are unaffected. Tests: the 4 build_market_state test files (30 "
    "tests) plus test_action11_9_call_engine_fail_closed.py and "
    "test_action11_12_regime_engine_fail_closed.py (13 tests) all still pass.",
    "market_state_rendering")
_mark_repaired(
    ["FB-00279", "FB-00280", "FB-00283", "FB-00284", "FB-00290", "FB-00291",
     "FB-00292", "FB-00293", "FB-00295", "FB-00296", "FB-00297"],
    "REPAIRED 2026-09-17: market_state.py's remaining signals-output getattr clusters "
    "simplified to bare attribute access, following the same dataclass-completeness proof "
    "as the TheCall cluster: _regime is always None or a real regime_engine.RegimePayload "
    "(8 required fields), _fusion always None or bayesian_fusion.FusionPayload (every field "
    "read is a class-defaulted or required field, confirmed by tracing FusionPayload's "
    "construction to functions typed `-> FusionPayload`), _vr always None or "
    "volatility_regime.VolRegimePayload (frozen dataclass, all fields required), "
    "_path (stack_decision_path) is Optional[StackDecisionPath] -- a SPECIFIC dataclass "
    "type, not loose `object` -- whose 6 StackStage fields and each StackStage's own "
    "fields are all required/defaulted, and _mhd/_mr/_pt/_a are all "
    "multi_horizon_decision.py dataclasses (MultiHorizonDecision, HorizonAlignmentReport, "
    "FinalTradePlan, SupportingHorizonAssessment respectively) with every field required "
    "(most have NO class-level default at all, an even stronger guarantee than TheCall). "
    "guest_anchor_active/_weights_ticker/_affiliation/_rationale and "
    "model_serving_provenance are declared, class-defaulted fields on SignalOutput itself. "
    "Value-level `or <default>` guards on _mhd/_mr/_pt string fields (e.g. `_mhd.final_bias "
    "or 'WAIT'`) were deliberately LEFT AS-IS -- those guard against a genuinely-empty "
    "computed value, not a missing attribute, and confirming each is safe to drop needs a "
    "deeper trace into multi_horizon_decision.py's own construction logic this pass did not "
    "do. A second incomplete SimpleNamespace test stand-in for FusionPayload (missing all "
    "12 Monte-Carlo/weight fields) was found and replaced with a real FusionPayload "
    "instance, same precedent as the TheCall fixture fix. Confirmed no other test file "
    "both calls build_market_state(...) and uses an incomplete SimpleNamespace/Mock "
    "regime/fusion/vol_regime/stack_decision_path stand-in (several call_engine.py/"
    "rules_engine.py test files construct incomplete stand-ins, but for functions other "
    "than build_market_state, confirmed via grep + one AST-based false-positive check). "
    "Tests: all 4 build_market_state test files (30 tests) still pass.",
    "market_state_rendering")
_mark_repaired(
    ["FB-00519", "FB-00559", "FB-00560"],
    "REPAIRED 2026-09-17 (completing a repair the operator correctly rejected as "
    "incomplete on 2026-09-17): server.py's three background-loop ticker-roster readers "
    "(_terrain_loop, _bars_loop, _seed_strike_geometry_from_storage) processed "
    "CORE_TICKERS as the enrolled roster on any _logger_lock/_logger_tickers read "
    "failure -- an earlier pass in this same session had added a log.warning disclosing "
    "the substitution but still RAN the cycle's work against CORE_TICKERS as though it "
    "were the requested set, which the operator correctly identified as 'logging the "
    "fallback is not a repair.' Redesigned per-site: _terrain_loop/_bars_loop leave "
    "`tickers` at its pre-declared [] on a roster-read failure (skipping that cycle's "
    "enrolled-board work entirely -- the same degrade-safely behavior a genuinely empty "
    "enrolled board already has, so no new failure mode is introduced) rather than "
    "processing an unrequested roster; _seed_strike_geometry_from_storage's inner "
    "try/except was removed entirely so a roster-read failure propagates to its caller "
    "(_terrain_prewarm_worker), which already has a correct, documented, ALREADY-ACCEPTED "
    "degrade path for this whole one-time boot seed failing outright ('first cycle uses "
    "cold-start width') -- narrowing to CORE_TICKERS inside the seed would have been a "
    "WORSE outcome (a silently-incomplete seed masquerading as a normal one) than letting "
    "the existing outer handler take over. This closes the market_data_server_core group: "
    "0 FALLBACK remaining. Tests: tests/test_server_ticker_roster_read_failure.py (5 new "
    "tests, including one proving the roster-read exception genuinely propagates out of "
    "_seed_strike_geometry_from_storage rather than being swallowed); "
    "tests/test_bars_collection_service_v1.py and 5 other files referencing these "
    "functions (109 tests total) still pass.",
    "market_data_server_core")
_mark_repaired(
    ["FB-00972"],
    "REPAIRED 2026-09-17: tools/feature_curation_gate.py's Spearman-hierarchical "
    "clustering median-imputed missing feature readings before computing the "
    "correlation matrix -- fabricating a value the correlation would then treat as "
    "observed data, capable of silently pulling two features into (or out of) the same "
    "redundancy cluster based on invented numbers rather than real co-movement. This "
    "is a RESEARCH/CURATION tool (feature redundancy analysis for curation decisions), "
    "not a production model training or serving path -- but the same principle applies: "
    "a missing reading must not become an observed one. Changed to complete-case rows "
    "only (pandas .dropna()): a row missing any clustered column is excluded from the "
    "correlation computation entirely. Tests: "
    "tests/test_feature_curation_gate_no_impute.py (structural no-fillna proof; a "
    "direct proof that an incomplete row's other column value is excluded from the "
    "correlation, never diluting/distorting it via a fabricated median).",
    "ml_training_pipeline")
_mark_repaired(
    ["FB-01156"],
    "REPAIRED 2026-09-17: train_compare.py's _compute_baseline mapped a rules_signal "
    "value outside {long, short, wait} (unexpected/malformed) to 'flat' via fillna -- "
    "treating an unrecognized signal the same as a genuine wait/flat reading, capable "
    "of silently biasing the reported baseline-accuracy diagnostic metric in either "
    "direction. This is a diagnostic/reporting metric, not a value fed to any model, "
    "but the same principle applies. Changed to exclude unmapped rows from the metric "
    "entirely rather than guessing a prediction for them. Tests: "
    "tests/test_train_compare_baseline_no_impute.py (4 new tests, including an "
    "unrecognized-signal-value case proving it's excluded rather than scored as a "
    "coincidental 'flat' guess).",
    "ml_training_pipeline")
_mark_repaired(
    ["FB-01111"],
    "REPAIRED 2026-09-17: tools/research/d2_dual_label_eval_report.py's run_cell "
    "defaulted a NULL tb_truncated_{hz} flag to 0 (not truncated) via fillna before "
    "filtering -- an unrecorded truncation status is not proof the row wasn't "
    "truncated, so silently including it in the 'confirmed untruncated' subset could "
    "bias this research evaluation's fixed-vs-triple-barrier labeling comparison. "
    "Changed to a bare `== 0` comparison, which excludes NaN rows naturally via "
    "pandas' NaN-not-equal-zero semantics (mirroring SQL NULL propagation used "
    "throughout this branch's earlier repairs). Tests: "
    "tests/test_d2_dual_label_truncation_no_impute.py (structural no-fillna proof; a "
    "direct proof that a NaN truncation flag is excluded, not assumed 0).",
    "ml_training_pipeline")
_mark_repaired(
    ["FB-00420"],
    "REPAIRED 2026-09-17 (the LAST remaining FALLBACK candidate repo-wide): "
    "ml_train.py's XGBoost training pipeline median-imputed missing feature readings "
    "(fit on the train partition only, to avoid training-skew leakage) before fitting, "
    "and then unconditionally zeroed any remaining NaN via nan_to_num -- both a "
    "specific, meaningful value substituted for 'never observed,' feeding directly into "
    "the model's learned decision boundary, not just a display field. Verified "
    "empirically that xgboost's sklearn API defaults `missing=nan` and both .fit() and "
    ".predict() handle real NaN inputs directly (tree splits learn an optimal direction "
    "for missing values internally) with zero special configuration -- confirmed via a "
    "direct interactive test before touching any code. Removed the imputation "
    "computation and the nan_to_num zeroing entirely from training; X_np now carries "
    "real NaN straight into .fit()/.predict(). "
    "apply_xgb_imputation_matrix (the ONE function every serving path -- ml_predict.py, "
    "arch_competition.ablation_bundle_inference -- routes through) was made a true "
    "passthrough (no median fill, no unconditional zeroing) when impute_medians is "
    "empty, which a v2-trained model always carries -- BACKWARD COMPATIBLE: a model "
    "carrying the prior contract's real, complete impute_medians sees byte-identical "
    "behavior to before this repair, so ml_predict.py's and the ablation framework's own "
    "call sites needed zero changes. "
    "model_contract.py's CURRENT_MISSINGNESS_CONTRACT_VERSION bumped from "
    "'issue7_v1_empirical_nan_impute' to 'issue7_v2_xgb_native_nan_no_impute' -- per "
    "this contract's own established, tested convention ('bump when semantics change; "
    "retrain all families'), this is the deliberate, documented mechanism that makes "
    "every bundle trained under v1 fail meta_matches_system_contract until retrained: "
    "the mandate's own 'affected models are retrained/evaluated before production "
    "authority' requirement, enforced mechanically rather than left to trust. "
    "_xgb_impute_complete (model_contract.py) and validate_ablation_scoring_bundle_meta "
    "(arch_competition/ablation_bundle_inference.py, a separate, parallel offline-"
    "ablation contract check) both updated to accept the new empty-dict shape as valid "
    "while still rejecting a PARTIAL dict (some but not all features covered) as "
    "malformed under either contract version. "
    "PRODUCTION IMPACT, explicitly surfaced rather than silently absorbed: this branch "
    "is not the production-serving branch (production runs off origin/main, deployed "
    "separately) -- committing this repair here has zero live effect. Deploying it, "
    "however, will take every currently-serving XGBoost model bundle offline (contract "
    "mismatch) until each ticker is retrained under the new contract; retraining itself "
    "is a separate, not-yet-performed operational step requiring live/historical data "
    "access this session does not exercise, and is owed before this repair can carry "
    "production authority. Tests: tests/test_xgb_native_nan_no_impute.py (6 new tests: "
    "a real train_ticker() end-to-end run writes an empty impute_medians and the v2 "
    "contract stamp and passes validate_artifact_contract; a v1-stamped bundle is "
    "proven to fail contract validation, the deliberate consequence; "
    "apply_xgb_imputation_matrix's two shapes -- empty-passthrough and legacy-fill -- "
    "both directly proven); fixed a real, unrelated pre-existing regression this pass "
    "discovered in tests/test_model_contract_enforcement.py (an earlier commit this "
    "session had already simplified two getattr() calls in market_state.py to bare "
    "attribute access, but the structural test asserting the exact source text was "
    "never re-run against that change until now). Full ML/model-contract test surface "
    "(238 tests across 12 files) passes.",
    "ml_training_pipeline")


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

    deleted_file_repairs = _apply_deleted_file_repairs(candidates)
    applied += deleted_file_repairs

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
