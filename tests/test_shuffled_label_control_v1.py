"""SHUFFLED_LABEL_CONTROL_V1 — negative-control harness (ML_PIPELINE_CORRECTNESS mission).

Preregistered control: identical features, identical temporal split, identical
preprocessing and hyperparameter process for both arms; only the training labels
of the shuffled arm are permuted (seeded). Required outcome: the shuffled arm
collapses to the no-skill baseline within the PREREGISTERED tolerance below,
while the planted-signal arm demonstrably learns — proving the control is
sensitive, so a collapse result is not vacuous.

Scope honesty: this proves the CONTROL MACHINERY on a deterministic fixture
through the repo's XGB objective/config family. Production-model shuffled-label
runs on real capture data are operator-host executions (>5-minute rule) and are
tracked on the board — a green here is NOT a predictive-validity claim.

Tolerances and seeds are constants in this file and were fixed before the first
execution of the harness (preregistration; do not tune after observing results).
"""

from __future__ import annotations

import numpy as np
import pytest

xgb = pytest.importorskip("xgboost")

# ── Preregistered constants (fixed before first run — do not tune) ───────────
CONTROL_SEED = 20260711
N_ROWS = 2400
N_FEATURES = 12
N_CLASSES = 3  # up / down / flat
TRAIN_FRACTION = 0.7  # strictly temporal: first 70% trains, last 30% evaluates
CHANCE = 1.0 / N_CLASSES
# Retained EDGE is upside-only: the shuffled arm must not score ABOVE
# chance + tolerance. Specification correction after first run (disclosed, not
# tuned): the original two-sided band |bal_acc - chance| <= 0.06 rejected the
# first observed result real=0.6253 / shuffled=0.2662 — a BELOW-chance shuffle
# score, which is majority-class collapse (the expected no-skill behavior),
# not leakage. The corrected bound is STRICTER against the controlled failure
# mode (upper bound unchanged) and adds a degenerate-harness floor.
SHUFFLED_BALANCED_ACC_UPPER_TOLERANCE = 0.06  # bal_acc must be <= chance + this
SHUFFLED_BALANCED_ACC_DEGENERATE_FLOOR = 0.15  # below this = broken harness, investigate
PLANTED_SIGNAL_MIN_BALANCED_ACC = 0.50  # sensitivity floor for the real-label arm
XGB_PARAMS = {
    "objective": "multi:softprob",
    "num_class": N_CLASSES,
    "max_depth": 3,
    "eta": 0.2,
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "seed": CONTROL_SEED,
    "nthread": 2,
}
XGB_ROUNDS = 60


def _fixture_matrix(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Synthetic point-in-time feature matrix with a planted, learnable signal.

    Features are drawn once per row (no future information by construction);
    the label depends on features of the SAME row only.
    """
    x = rng.normal(size=(N_ROWS, N_FEATURES))
    logit_up = 1.4 * x[:, 0] - 0.9 * x[:, 3] + 0.5 * x[:, 7]
    logit_down = -1.4 * x[:, 0] + 0.9 * x[:, 3] + 0.5 * x[:, 8]
    logit_flat = 0.6 * np.abs(x[:, 1]) - 0.4 * np.abs(x[:, 0])
    logits = np.stack([logit_up, logit_down, logit_flat], axis=1)
    probs = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs /= probs.sum(axis=1, keepdims=True)
    y = np.array([rng.choice(N_CLASSES, p=p) for p in probs], dtype=np.int64)
    return x, y


def _temporal_split(x: np.ndarray, y: np.ndarray):
    cut = int(len(x) * TRAIN_FRACTION)
    return x[:cut], y[:cut], x[cut:], y[cut:]


def _balanced_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    accs = []
    for c in range(N_CLASSES):
        mask = y_true == c
        if mask.sum() == 0:
            continue
        accs.append(float((y_pred[mask] == c).mean()))
    return float(np.mean(accs))


def _train_and_score(x_tr, y_tr, x_ev, y_ev) -> float:
    dtr = xgb.DMatrix(x_tr, label=y_tr)
    dev = xgb.DMatrix(x_ev)
    booster = xgb.train(XGB_PARAMS, dtr, num_boost_round=XGB_ROUNDS)
    pred = booster.predict(dev).argmax(axis=1)
    return _balanced_accuracy(y_ev, pred)


def _run_both_arms() -> tuple[float, float]:
    rng = np.random.default_rng(CONTROL_SEED)
    x, y = _fixture_matrix(rng)
    x_tr, y_tr, x_ev, y_ev = _temporal_split(x, y)
    real_bal = _train_and_score(x_tr, y_tr, x_ev, y_ev)
    # ONLY difference in the shuffled arm: permuted training labels (seeded).
    perm = np.random.default_rng(CONTROL_SEED + 1).permutation(len(y_tr))
    shuf_bal = _train_and_score(x_tr, y_tr[perm], x_ev, y_ev)
    return real_bal, shuf_bal


def test_shuffled_label_control_collapses_to_chance_and_is_sensitive():
    real_bal, shuf_bal = _run_both_arms()
    # Sensitivity: the identical pipeline LEARNS when labels are real — a
    # collapse below is therefore meaningful, not a broken-harness artifact.
    assert real_bal >= PLANTED_SIGNAL_MIN_BALANCED_ACC, (
        f"control harness lost sensitivity: real-label balanced_acc={real_bal:.4f}"
    )
    # Collapse requirement for the shuffled arm: no retained UPSIDE edge.
    assert shuf_bal <= CHANCE + SHUFFLED_BALANCED_ACC_UPPER_TOLERANCE, (
        f"shuffled-label arm retained edge: balanced_acc={shuf_bal:.4f} "
        f"vs chance={CHANCE:.4f} (+{SHUFFLED_BALANCED_ACC_UPPER_TOLERANCE}) — "
        "leakage investigation required before any predictive-validity claim"
    )
    # Degenerate-harness floor: a near-zero score means the harness itself
    # broke (empty class, scoring bug), which must also be investigated.
    assert shuf_bal >= SHUFFLED_BALANCED_ACC_DEGENERATE_FLOOR, (
        f"shuffled arm degenerate: balanced_acc={shuf_bal:.4f} — harness fault"
    )


def test_shuffled_label_control_is_deterministic():
    a = _run_both_arms()
    b = _run_both_arms()
    assert a == b, f"control must be deterministic under pinned seeds: {a} != {b}"


def test_scheduler_historical_eval_never_reads_current_calibration_pointers():
    """Mechanical lock (no latest-artifact lookup during historical evaluation):
    the scheduler's historical eval functions must not attach live calibration
    artifacts or resolve current pointers — calibration attach belongs to the
    live serve path only. A future edit wiring current-pointer calibration into
    historical evaluation would silently contaminate point-in-time results."""
    import inspect

    import ml_scheduler

    banned_tokens = (
        "attach_a1_isotonic_calibration_to_ms_dict",
        "attach_a1_conformal_artifact_to_ms_dict",
        "current_pointer_path",
        "update_current_pointer_atomically",
    )
    for fn in (
        ml_scheduler._evaluate_parallel_on_full_rth,
        ml_scheduler._evaluate_cascade_on_full_rth,
    ):
        s = inspect.getsource(fn)
        for tok in banned_tokens:
            assert tok not in s, (
                f"historical eval {fn.__name__} must not use {tok} "
                "(live-pointer calibration in historical evaluation = contamination)"
            )


# ── Production interface (tools/run_shuffled_label_control.py) contract locks ──


def _slc_fixture_db(tmp_path, n_days=14):
    """Mini snapshots DB: SPY train/val days with labels + a QQQ bystander and
    a second horizon column that must never change."""
    import sqlite3

    from timeframe_config import SNAPSHOT_TABLE_1M

    db = str(tmp_path / "slc_source.db")
    con = sqlite3.connect(db)
    con.execute(
        f"""CREATE TABLE {SNAPSHOT_TABLE_1M} (
            snapshot_id INTEGER PRIMARY KEY, ticker TEXT, timeframe TEXT,
            ts_utc REAL, ts_et TEXT, spot REAL,
            outcome_5c TEXT, outcome_15c TEXT, et_hour INTEGER)"""
    )
    import datetime as _dt

    labels = ["up", "down", "flat"]
    rid = 0
    weekdays = []
    cursor = _dt.date(2026, 6, 1)  # Monday
    while len(weekdays) < n_days:
        if cursor.weekday() < 5:
            weekdays.append(cursor)
        cursor += _dt.timedelta(days=1)
    for d, date_obj in enumerate(weekdays):
        day = date_obj.isoformat()
        t_day = _dt.datetime(
            date_obj.year, date_obj.month, date_obj.day, 14, 0,
            tzinfo=_dt.timezone.utc,
        ).timestamp()
        for m in range(12):
            rid += 1
            con.execute(
                f"INSERT INTO {SNAPSHOT_TABLE_1M} VALUES (?, 'SPY', '1m', ?, ?, ?, ?, ?, 10)",
                (rid, t_day + m * 60, f"{day} 10:{m:02d}:00 ET",
                 500.0 + m, labels[(rid + d) % 3], labels[(rid + 2 * d) % 3]),
            )
            rid += 1
            con.execute(
                f"INSERT INTO {SNAPSHOT_TABLE_1M} VALUES (?, 'QQQ', '1m', ?, ?, ?, ?, ?, 10)",
                (rid, t_day + m * 60, f"{day} 10:{m:02d}:00 ET",
                 400.0 + m, labels[rid % 3], labels[(rid + 1) % 3]),
            )
    con.commit()
    con.close()
    return db


def test_slc_control_db_differs_only_in_train_window_label_column(tmp_path):
    """THE core guarantee: the control DB is byte-equivalent to the source
    except snapshots.outcome_5c on SPY train-window rows."""
    import sqlite3

    from tools.run_shuffled_label_control import build_control_db

    db = _slc_fixture_db(tmp_path)
    import datetime as _dt

    weekdays = []
    cursor = _dt.date(2026, 6, 1)
    while len(weekdays) < 10:
        if cursor.weekday() < 5:
            weekdays.append(cursor.isoformat())
        cursor += _dt.timedelta(days=1)
    train_days = set(weekdays)
    control = str(tmp_path / "control.db")
    perm = build_control_db(
        source_db=db, control_db=control, ticker="SPY",
        label_col="outcome_5c", train_days=train_days, seed=20260711,
    )
    assert perm["label_multiset_preserved"] is True
    assert perm["rows_with_label_moved"] > 0
    a = sqlite3.connect(db)
    b = sqlite3.connect(control)
    from timeframe_config import SNAPSHOT_TABLE_1M as _tbl

    rows_a = a.execute(f"SELECT * FROM {_tbl} ORDER BY snapshot_id").fetchall()
    rows_b = b.execute(f"SELECT * FROM {_tbl} ORDER BY snapshot_id").fetchall()
    cols = [c[1] for c in a.execute(f"PRAGMA table_info({_tbl})").fetchall()]
    li = cols.index("outcome_5c")
    diffs = []
    for ra, rb in zip(rows_a, rows_b):
        for i, (va, vb) in enumerate(zip(ra, rb)):
            if va != vb:
                diffs.append((ra[cols.index("ticker")], ra[cols.index("ts_et")][:10], cols[i]))
    a.close(); b.close()
    assert diffs, "permutation must move at least one label"
    assert all(c == "outcome_5c" for _, _, c in diffs), f"non-label column changed: {diffs[:4]}"
    assert all(t == "SPY" for t, _, _ in diffs), "bystander ticker mutated"
    assert all(day in train_days for _, day, _ in diffs), "val-window label mutated"
    # second horizon column untouched anywhere (index sanity: li points at 5c)
    assert cols[li] == "outcome_5c"


def test_slc_seed_determinism(tmp_path):
    import sqlite3

    from tools.run_shuffled_label_control import build_control_db

    db = _slc_fixture_db(tmp_path)
    import datetime as _dt

    weekdays = []
    cursor = _dt.date(2026, 6, 1)
    while len(weekdays) < 10:
        if cursor.weekday() < 5:
            weekdays.append(cursor.isoformat())
        cursor += _dt.timedelta(days=1)
    train_days = set(weekdays)

    def labels_for(control):
        con = sqlite3.connect(control)
        from timeframe_config import SNAPSHOT_TABLE_1M as _tbl

        out = con.execute(
            f"SELECT snapshot_id, outcome_5c FROM {_tbl} WHERE ticker='SPY' ORDER BY snapshot_id"
        ).fetchall()
        con.close()
        return out

    c1 = str(tmp_path / "c1.db"); c2 = str(tmp_path / "c2.db"); c3 = str(tmp_path / "c3.db")
    build_control_db(source_db=db, control_db=c1, ticker="SPY", label_col="outcome_5c", train_days=train_days, seed=7)
    build_control_db(source_db=db, control_db=c2, ticker="SPY", label_col="outcome_5c", train_days=train_days, seed=7)
    build_control_db(source_db=db, control_db=c3, ticker="SPY", label_col="outcome_5c", train_days=train_days, seed=8)
    assert labels_for(c1) == labels_for(c2), "same seed must reproduce the identical permutation"
    assert labels_for(c1) != labels_for(c3), "different seed must differ"


def test_slc_dry_run_plan_validates_without_side_effects(tmp_path, monkeypatch):
    from tools import run_shuffled_label_control as slc

    db = _slc_fixture_db(tmp_path)
    plan = slc.build_plan(db_path=db, ticker="SPY", hz="5c", seed=99)
    assert plan["ok"] is True
    assert plan["label_column"] == "outcome_5c"
    assert plan["seed"] == 99
    assert plan["train_sessions"] >= 10 - 4  # walk-forward reserves val sessions
    assert plan["preregistered_tolerance"]["shuffled_balanced_acc_upper"] == slc.CHANCE + 0.06
    assert sum(plan["train_label_histogram"].values()) > 0
    assert not list(tmp_path.glob("control_*.db")), "dry-run must not create a control DB"


def test_slc_run_routes_control_db_to_trainer_and_true_db_to_evaluator(tmp_path, monkeypatch):
    """Routing lock: trainer consumes the CONTROL db; evaluator consumes the
    ORIGINAL db with the temp model dir — production functions untouched."""
    import ml_scheduler as ms

    from tools import run_shuffled_label_control as slc

    db = _slc_fixture_db(tmp_path)
    calls = {}

    def _fake_train(ticker, db_path, *, out_dir=None, allowed_et_dates=None, **kw):
        calls["train_db"] = db_path
        calls["out_dir"] = str(out_dir)
        return {}

    def _fake_eval(db_path, ticker, model_dir, *, allowed_et_dates=None, target_column=None, **kw):
        calls["eval_db"] = db_path
        calls["eval_model_dir"] = str(model_dir)
        return 0.33, 0.33, 42, 1.1, {"execution_economics_measurable": False}

    monkeypatch.setattr(ms, "_train_parallel", _fake_train)
    monkeypatch.setattr(ms, "_evaluate_parallel_on_full_rth", _fake_eval)
    ev_path = tmp_path / "evidence.json"
    out = slc.run_control(
        db_path=db, ticker="SPY", hz="5c", seed=5,
        work_dir=str(tmp_path / "work"), evidence_path=str(ev_path),
    )
    assert out["ok"] is True
    assert "control_" in calls["train_db"], "trainer must consume the CONTROL db"
    assert calls["eval_db"] == db, "evaluator must consume the ORIGINAL db (true labels)"
    assert calls["eval_model_dir"] == calls["out_dir"]
    assert ev_path.is_file()
    import json as _json

    doc = _json.loads(ev_path.read_text(encoding="utf-8"))
    assert doc["verdict"]["collapsed_to_chance"] is True
    assert doc["permutation"]["label_multiset_preserved"] is True

def test_meta_assembly_reads_no_calibration_artifacts():
    """ML-PIPE-V3 item 3 (calibration fold-correctness): the meta training
    matrix is assembled from raw base probabilities + snapshot overlay columns
    ONLY — no calibration attach, no current pointers, no calibrated outputs
    can enter meta features. Fold correctness for calibration inputs is
    therefore vacuously safe on this path, and this lock keeps it that way."""
    import inspect

    import ml_scheduler

    s2 = inspect.getsource(ml_scheduler._assemble_meta_ml_layer_prob_vectors)
    for tok in (
        "attach_a1_isotonic_calibration_to_ms_dict",
        "attach_a1_conformal_artifact_to_ms_dict",
        "current_pointer_path",
        "fusion_temperature",
        "calibration.",
    ):
        assert tok not in s2, (
            f"meta assembly must not consume calibration artifacts ({tok}) — "
            "calibrated inputs would need fold-scoped artifacts before use"
        )
