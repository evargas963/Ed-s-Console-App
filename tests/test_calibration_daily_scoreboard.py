"""Daily signal scoreboard: per-horizon fusion prediction vs attached outcome labels."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


from calibration.schema import ensure_calibration_schema

ET = ZoneInfo("America/New_York")
ET_DATE = "2026-06-09"


def _mh_bundle(direction_by_hz: dict[str, str], top_prob: float = 0.55) -> str:
    by_hz = {
        hz: {
            "horizon_slug": hz,
            "horizon_fusion_available": True,
            "dominant_direction": d,
            "top_probability": top_prob,
        }
        for hz, d in direction_by_hz.items()
    }
    return json.dumps(
        {"stack_probs_bundle": {"multi_horizon_ml_fusion_bundle": {"by_horizon": by_hz}}}
    )


def _mh_json(final_bias: str, primary_horizon: str, final_confidence: float = 0.61) -> str:
    return json.dumps(
        {
            "final_bias": final_bias,
            "final_confidence": final_confidence,
            "primary_horizon": primary_horizon,
            "final_tradeable": final_bias in ("LONG", "SHORT"),
        }
    )


def _insert_decision(
    conn: sqlite3.Connection,
    ticker: str,
    ts_utc: float,
    model_outputs_json: str,
    outcomes: dict[str, str | None],
    multi_horizon_json: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, model_outputs_json,
            multi_horizon_json,
            outcome_1c, outcome_5c, outcome_15c, outcome_60c, calibration_trust
        ) VALUES (?, ?, '1m', ?, ?, ?, ?, ?, ?, 'trusted')
        """,
        (
            ts_utc,
            ticker,
            model_outputs_json,
            multi_horizon_json,
            outcomes.get("1c"),
            outcomes.get("5c"),
            outcomes.get("15c"),
            outcomes.get("60c"),
        ),
    )


def _fixture_db(tmp_path: Path) -> Path:
    db = tmp_path / "calib.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    ensure_calibration_schema(conn)
    ts0 = datetime(2026, 6, 9, 10, 0, tzinfo=ET).timestamp()

    # SPY row 1: 1c hit (up/up), 5c miss (up/down), 15c flat-pred hit, 60c outcome unattached.
    # ALL card: LONG scored at primary 5c (outcome down) -> directional miss.
    _insert_decision(
        conn,
        "SPY",
        ts0,
        _mh_bundle({"1c": "up", "5c": "up", "15c": "flat", "60c": "up"}),
        {"1c": "up", "5c": "down", "15c": "flat", "60c": None},
        multi_horizon_json=_mh_json("LONG", "5c"),
    )
    # SPY row 2: directional hit on 5c. ALL card: SHORT at primary 5c (down) -> hit.
    _insert_decision(
        conn,
        "SPY",
        ts0 + 60,
        _mh_bundle({"1c": "down", "5c": "down"}),
        {"1c": "flat", "5c": "down"},
        multi_horizon_json=_mh_json("SHORT", "5c"),
    )
    # SPY row 3: WAIT decision -> ALL card scores as flat vs 15c outcome flat (non-directional hit).
    _insert_decision(
        conn,
        "SPY",
        ts0 + 90,
        _mh_bundle({}),
        {"15c": "flat"},
        multi_horizon_json=_mh_json("WAIT", "15c"),
    )
    # QQQ row on another ET date: must be excluded.
    other_day = datetime(2026, 6, 8, 10, 0, tzinfo=ET).timestamp()
    _insert_decision(conn, "QQQ", other_day, _mh_bundle({"1c": "up"}), {"1c": "up"})
    # After-hours row on the date (20:00 ET): no snapshot/outcome bar exists — must be excluded.
    after_hours = datetime(2026, 6, 9, 20, 0, tzinfo=ET).timestamp()
    _insert_decision(conn, "SPY", after_hours, _mh_bundle({"1c": "up"}), {"1c": "up"})
    # Untrusted row on the date: must be excluded.
    conn.execute(
        """
        INSERT INTO calibration_decision_log (
            decision_ts_utc, ticker, canonical_timeframe, model_outputs_json,
            outcome_1c, calibration_trust
        ) VALUES (?, 'SPY', '1m', ?, 'up', 'legacy')
        """,
        (ts0 + 120, _mh_bundle({"1c": "up"})),
    )
    conn.commit()
    conn.close()
    return db












# ── Rolling skill weights for ALL-card pooling (operator 2026-06-11) ─────────


def _insert_skill_rows(conn: sqlite3.Connection, n: int, ts0: float) -> None:
    """n trusted rows, outcomes attached: 1c predicts truth at p=0.6 (skilled),
    5c/15c/60c uniform 1/3 (zero skill vs ln(3) baseline)."""
    for i in range(n):
        truth = "up" if i % 2 == 0 else "down"
        by_hz = {}
        for hz in ("1c", "5c", "15c", "60c"):
            if hz == "1c":
                probs = {"prob_up": 0.2, "prob_down": 0.2, "prob_flat": 0.2}
                probs[f"prob_{truth}"] = 0.6
            else:
                probs = {"prob_up": 1 / 3, "prob_down": 1 / 3, "prob_flat": 1 / 3}
            by_hz[hz] = {
                "horizon_slug": hz,
                "horizon_fusion_available": True,
                "dominant_direction": truth,
                "top_probability": max(probs.values()),
                **probs,
            }
        mo = json.dumps(
            {"stack_probs_bundle": {"multi_horizon_ml_fusion_bundle": {"by_horizon": by_hz}}}
        )
        conn.execute(
            """
            INSERT INTO calibration_decision_log (
                decision_ts_utc, ticker, canonical_timeframe, model_outputs_json,
                outcome_1c, outcome_5c, outcome_15c, outcome_60c,
                outcomes_attached_ts_utc, calibration_trust
            ) VALUES (?, 'SPY', '1m', ?, ?, ?, ?, ?, ?, 'trusted')
            """,
            (ts0 + i * 60.0, mo, truth, truth, truth, truth, ts0 + i * 60.0 + 900.0),
        )






# ── SCOREBOARD_ACTIONABILITY_JOIN_V1 (Phase 1 — report-only) ─────────────────



def _act_row(ticker: str, ts: float, expiry: str = "2026-06-09") -> dict:
    return {
        "ticker": ticker,
        "decision_ts_utc": ts,
        "expiry": expiry,
        "session_label": "RTH",
        "decision_source": "test",
    }




















def test_live_skill_weight_path_untouched_by_actionability():
    """AST lock: rolling_horizon_log_loss and horizon_skill_weights reference no
    actionability code — the live weighting path is provably unchanged."""
    import ast

    src = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned = {
        "classify_actionability_rows", "build_actionability_report",
        "read_freshness_budget_sec", "load_harness_annotations",
        "ACTIONABILITY_STATES",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "rolling_horizon_log_loss", "horizon_skill_weights",
        ):
            names = {s.id for s in ast.walk(node) if isinstance(s, ast.Name)}
            assert not (names & banned), f"{node.name} touches actionability: {names & banned}"




# ── DAILY_SCOREBOARD_DENOMINATOR_FIRST_V1 (operator-approved 2026-07-09) ──────


def _add_universe(db: Path, tickers: dict[str, str]) -> None:
    """tickers: {ticker: category}. Creates a minimal logging_universe table."""
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS logging_universe (ticker TEXT PRIMARY KEY, category TEXT)"
    )
    for t, cat in tickers.items():
        conn.execute("INSERT OR REPLACE INTO logging_universe VALUES (?, ?)", (t, cat))
    conn.commit()
    conn.close()


def _add_snapshots(db: Path, tickers: list[str], ts_utc: float) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS snapshots (ticker TEXT, ts_utc REAL)"
    )
    for t in tickers:
        conn.execute("INSERT INTO snapshots VALUES (?, ?)", (t, ts_utc))
    conn.commit()
    conn.close()


def _denominator_fixture(tmp_path: Path) -> Path:
    """Base fixture + roster of 4: SPY (rows), ZLOG (snapshots only, no calib rows),
    ZOFF (no producer contact at all), ZGUEST (guest-style with rows)."""
    db = _fixture_db(tmp_path)
    _add_universe(db, {"SPY": "core", "ZLOG": "panel_auto", "ZOFF": "panel_auto", "ZGUEST": "user_persisted"})
    ts0 = datetime(2026, 6, 9, 10, 0, tzinfo=ET).timestamp()
    _add_snapshots(db, ["SPY", "ZLOG", "ZGUEST"], ts0)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    # guest ticker with a scored row (required test 10)
    _insert_decision(
        conn, "ZGUEST", ts0 + 30,
        _mh_bundle({"1c": "up"}), {"1c": "up"},
    )
    conn.commit()
    conn.close()
    return db


















def test_denominator_no_ticker_literals_in_grid_code():
    """Required 11: no ticker literals drive grid/reason/rollup behavior."""
    import ast as _ast

    src_text = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    tree = _ast.parse(src_text)
    for fname in (
        "_eligible_roster", "_production_tallies", "_cell_not_scored_reason",
        "_build_eligible_grid", "_equal_weight_rollup", "_coverage_diagnostics",
        "_quality_circle_summary",
    ):
        fn = next(n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef) and n.name == fname)
        doc = fn.body[0].value if isinstance(fn.body[0], _ast.Expr) else None
        for node in _ast.walk(fn):
            if node is doc:
                continue  # prose docstring, not behavior
            if isinstance(node, _ast.Constant) and isinstance(node.value, str):
                assert not (node.value.isalpha() and node.value.isupper() and len(node.value) <= 5), (
                    f"ticker-literal-shaped constant {node.value!r} in {fname}"
                )




def test_denominator_grid_built_before_scoring_source_lock():
    """Required local proof: the eligible grid/tallies are constructed BEFORE the
    scoring pass inside build_daily_scoreboard."""
    src_text = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    body = src_text[src_text.index("def build_daily_scoreboard(") :]
    i_roster = body.index("_eligible_roster(conn)")
    i_tallies = body.index("_production_tallies(conn")
    i_scoring = body.index("_per_horizon_prediction_rows(conn")
    assert i_roster < i_scoring and i_tallies < i_scoring












# ── Quality-circle contract (operator 2026-07-09, item 8) ────────────────────






















# ── SCOREBOARD_TARGET_TRUTH_V1 (v4) — abstention, baselines, warnings ─────────



def _v4_row(pred: str, truth: str | None, hz: str = "1c", ts: float = 1000.0, **kw) -> dict:
    return {
        "ticker": "ZZZ", "decision_ts_utc": ts, "horizon": hz, "pred": pred,
        "truth": truth, "top_probability": 0.5,
        "join_cohort": kw.get("join_cohort", "exact_timestamp"),
        "bundle_identity_proven": kw.get("bundle_identity_proven", True),
    }












def test_all_card_row_reads_only_persisted_row_fields():
    """Required 7 (AST lock): _all_card_row consumes ONLY the database row — no
    import/config fallback can substitute current configuration for history."""
    import ast

    src = Path(__file__).resolve().parent.parent.joinpath(
        "calibration", "daily_scoreboard.py"
    ).read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_all_card_row"
    )
    names = {x.id for x in ast.walk(fn) if isinstance(x, ast.Name)}
    allowed = {"row", "mh", "pred", "primary_hz", "json", "isinstance", "dict", "str",
               "float", "Optional", "_FINAL_BIAS_TO_LABEL", "HORIZON_SLUGS", "ALL_CARD_SLUG",
               "TypeError", "ValueError", "Any", "sqlite3",
               # RC-REHAB-3: multi_horizon_json may be gzip-compressed; decode_json_blob
               # (json_blob_codec) still reads it from the row's own persisted field only
               # -- no config/roster substitution, the lock this test enforces.
               "_mhj", "decode_json_blob", "OSError"}
    assert names <= allowed, f"unexpected names in _all_card_row: {names - allowed}"
    # The load-bearing lock: no config/roster/horizon-selection machinery inside.
    banned = {"PRIMARY_DECISION_HORIZONS", "load_movement_thresholds_by_horizon_v1",
              "_eligible_roster", "os", "importlib"}
    assert not (names & banned)






















def test_invalid_threshold_classification_is_flat_and_disclosed():
    """Historical behavior preserved and DISCLOSED: classify_direction_pts turns a
    missing/non-positive threshold into 'flat'. The forward fail-closed change to
    the truth writer (no-label instead of flat) belongs to the target-redesign
    mission; until then the risk flag is the governed disclosure."""
    from math_probabilities import classify_direction_pts

    assert classify_direction_pts(5.0, None) == "flat"
    assert classify_direction_pts(5.0, 0.0) == "flat"
    assert classify_direction_pts(5.0, -1.0) == "flat"
    assert classify_direction_pts(5.0, 1.0) == "up"






# ── DEFECT-1: operator semantic safety (independent requirements) ─────────────
# These tests assert the REQUIRED CONCEPTS as independent strings — they do NOT
# import the production display-contract constants and echo them back.

import re as _re  # noqa: E402


def _plain_text(html: str) -> str:
    """CSS/markup-independent extraction: what a screen reader / copy-paste sees."""
    return _re.sub(r"<[^>]+>", " ", html)














# ── V2 (Cursor findings): eligible grid, governed unit, low-coverage safety ───










def test_lane_a_mutation_manifest_purity():
    """Package truth: the Lane-A manifest contains ONLY lane-A mutations with the
    required evidence fields; Lane-B mutations live in the quarantined artifact
    marked excluded from the Lane-A package."""
    root = Path(__file__).resolve().parent.parent
    m = json.loads((root / "reports/scoreboard_forensic/mutation_evidence_manifest.json").read_text(encoding="utf-8"))
    assert m["lane"] == "A"
    assert all(r["lane"] == "A" for r in m["mutations"])
    assert not any(r["id"] in ("M2", "M3") for r in m["mutations"])
    for r in m["mutations"]:
        for field in ("preimage_sha256", "unified_diff", "iteration_history"):
            assert field in r, f"{r['id']} missing {field}"
        # schema v5: per-run evidence blocks with matched canonical signatures.
        for run_key in ("run1", "run2"):
            run = r[run_key]
            for field in ("signature_digest", "structured_failures",
                          "restoration_hashes_match_preimages", "raw_evidence_files"):
                assert field in run, f"{r['id']}.{run_key} missing {field}"
        assert r["signature_match"] is True, f"{r['id']} signatures differ between runs"
    assert m["summary"]["statement"].startswith("LANE_A_MUTATIONS_DETECTED = ")
    assert m["summary"]["signature_matches"] == "27/27"
    for run_key in ("run1", "run2"):
        assert "lane-A composition" in m["restoration"][run_key]["suite_footprint"]
    # The Lane-B artifact is EXCLUDED from the Lane-A patch; when present in a
    # combined worktree it must be explicitly quarantined.
    lane_b = root / "reports/scoreboard_forensic/mutation_evidence_lane_b_uncommitted.json"
    if lane_b.is_file():
        b = json.loads(lane_b.read_text(encoding="utf-8"))
        assert b["lane"] == "B" and "QUARANTINED" in b["composition"]
        assert {r["id"] for r in b["mutations"]} == {"M2", "M3"}


def test_forensic_packet_lane_purity():
    """Package truth: the forensic packet machine-readably excludes Lane-B design
    from the Lane-A patch and never claims identity-first implementation for Lane A."""
    root = Path(__file__).resolve().parent.parent
    d = json.loads((root / "reports/scoreboard_forensic/july13_2026_target_truth_forensic.json").read_text(encoding="utf-8"))
    tags = d["lane_decomposition"]["section_tags"]
    assert tags["join_identity_forensic"]["included_in_lane_a_patch"] is False
    assert tags["join_identity_forensic"]["not_commit_evidence_for_lane_a"] is True
    fw = d["join_identity_forensic"]["verdicts"]["FORWARD_IDENTITY_FIRST_DESIGN"]
    assert fw.startswith("LANE_B_UNCOMMITTED_DESIGN")
    assert "LOCALLY_IMPLEMENTED" not in fw
    dumped = json.dumps(d)
    assert "correction_landed" not in dumped


def test_board_row_lane_language_purity():
    """Package truth: the board row states the Lane-A patch ships HEAD backfill
    behavior and carries no identity-first-implemented claim for Lane A."""
    board = Path(__file__).resolve().parent.parent.joinpath("OPEN_ITEMS.md").read_text(encoding="utf-8")
    row = next(l for l in board.splitlines() if "SCOREBOARD-TARGET-TRUTH " in l)
    assert "HEAD backfill behavior only" in row
    assert "FORWARD_IDENTITY_FIRST_DESIGN = LOCALLY_IMPLEMENTED" not in row
    assert "LOCALLY_PROVEN_PENDING_PR" not in row
    assert "NOT in the Lane-A patch" in row
    assert "LANE B COMMIT_READY = NO" in row














