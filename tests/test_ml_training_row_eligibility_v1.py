"""ML TRAINING DATA — quote-only capture rows are not training examples (2026-08-26).

WHAT WAS FOUND, and how. While retraining for RC-436, QQQ 1c came back with a SIXTEEN-feature
model where the same ticker previously had 84: the NaN filter had dropped 74 of 90 features.

The cause was not the RC-436 feature retirement. base_money_path_capture writes, by its own
docstring, "Quote-only inserts tagged logger_source=base_money_path - no full _fetch_state
stack" — roughly 49 of 441 columns, carrying quotes/candles/outcomes and no engineered features.
ml_train.load_data had no filter, so those rows were being trained on.

MEASURED on the production database, post-June RTH rows:
    SPY  24,516 rows, 52.1% from base_money_path, 100% of those feature-NULL
    QQQ  20,040 rows, 72.8%
    IWM  20,010 rows, 73.9%
    NVDA  2,073 rows,  0.0%   (receives no base_money_path rows)
    AAPL  1,666 rows,  0.0%
The damage lands precisely on the three anchor tickers that carry the only promoted models. The
incumbent artifacts never exposed it because they were trained on a window ending 2026-05-28,
before this capture began diluting the table.

WHY EXCLUSION IS THE RIGHT FIX rather than making the capture write features: the capture is
wanted — it is a deliberate equal-rate money-path latency probe. Its rows are simply not
feature-complete snapshots, so they are not training examples.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from base_money_path_capture import LOGGER_SOURCE_BASE_MONEY_PATH  # noqa: E402


def _make_db(path: Path) -> None:
    """A minimal snapshots_1m_normalized carrying both row KINDS, shaped like production."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE snapshots_1m_normalized (
            ticker TEXT, timeframe TEXT, ts_utc REAL, ts_et TEXT,
            logger_source TEXT, outcome_1c TEXT,
            net_gamma REAL, net_delta REAL, iv_level REAL, atr REAL,
            zone TEXT, spot REAL
        )""")
    rows = []
    base = 1787_000_000.0
    for i in range(40):
        # Feature-COMPLETE rows, as the full snapshot path writes them.
        rows.append(("SPY", "1m", base + i * 60, "2026-08-26 10:%02d:00 ET" % (i % 60),
                     "background_logger", "up", 1.5e9, 2.2e8, 0.19, 1.4, "pin_bull", 767.0))
    for i in range(60):
        # Quote-ONLY capture rows: every engineered feature NULL, exactly as measured.
        rows.append(("SPY", "1m", base + 5000 + i * 60, "2026-08-26 11:%02d:00 ET" % (i % 60),
                     LOGGER_SOURCE_BASE_MONEY_PATH, "up", None, None, None, None, None, 767.0))
    conn.executemany("INSERT INTO snapshots_1m_normalized VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_quote_only_capture_rows_are_excluded_from_training(tmp_path):
    """The exclusion must be expressed in the QUERY, so diluted rows never reach the frame."""
    db = tmp_path / "t.db"
    _make_db(db)
    conn = sqlite3.connect(str(db))
    total = conn.execute(
        "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE outcome_1c IS NOT NULL").fetchone()[0]
    eligible = conn.execute(
        "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE outcome_1c IS NOT NULL "
        "AND (logger_source IS NULL OR logger_source != ?)",
        (LOGGER_SOURCE_BASE_MONEY_PATH,)).fetchone()[0]
    null_after = conn.execute(
        "SELECT SUM(net_gamma IS NULL) FROM snapshots_1m_normalized WHERE outcome_1c IS NOT NULL "
        "AND (logger_source IS NULL OR logger_source != ?)",
        (LOGGER_SOURCE_BASE_MONEY_PATH,)).fetchone()[0]
    conn.close()

    assert total == 100
    assert eligible == 40, "quote-only rows were not excluded"
    assert (null_after or 0) == 0, (
        "feature-NULL rows survived the eligibility filter — the NaN filter would then drop "
        "real features and produce a degenerate model, which is exactly the QQQ 16-feature case")


def test_load_data_query_carries_the_exclusion(tmp_path):
    """Pin it in load_data itself, not only in a hand-written query.

    Asserted structurally: load_data must bind the capture source as a PARAMETER. A test that
    only re-derived the SQL by hand would keep passing if the filter were removed from the
    module, which is the failure mode this is guarding.
    """
    import inspect

    import ml_train

    src = inspect.getsource(ml_train.load_data)
    assert "LOGGER_SOURCE_BASE_MONEY_PATH" in src, (
        "load_data no longer excludes quote-only capture rows — SPY/QQQ/IWM training sets go "
        "back to being 52-74% feature-empty")
    assert "logger_source" in src
    # The name must be IMPORTED from the writer, never re-spelled as a literal here.
    assert '"base_money_path"' not in src and "'base_money_path'" not in src, (
        "the capture source is spelled as a literal in load_data — it must come from "
        "base_money_path_capture so the writer identity has one definition")


def test_the_sequence_path_carries_the_same_exclusion():
    """BOTH training readers must exclude, not just the tabular one.

    lstm_data.extract_rth_snapshots builds its OWN query and does not go through
    ml_train.load_data, so fixing only load_data would leave LSTM and Transformer training on
    the diluted table. It matters more there, not less: a sequence is a WINDOW, and
    encode_tabular fills absent numerics with 0.0 for tensor stability, so feature-null rows do
    not shrink the sample - they fill the window with zeros the model reads as real
    observations of zero.
    """
    import inspect

    import lstm_data

    src = inspect.getsource(lstm_data.extract_rth_snapshots)
    assert "LOGGER_SOURCE_BASE_MONEY_PATH" in src, (
        "the sequence dataset reader no longer excludes quote-only capture rows — LSTM and "
        "Transformer would train on windows that are mostly encoded zeros")
    assert '"base_money_path"' not in src and "'base_money_path'" not in src, (
        "the capture source is spelled as a literal in lstm_data — import it from "
        "base_money_path_capture so the writer identity has one definition")


def test_the_excluded_source_is_the_one_the_writer_declares():
    """If the writer renames its tag, this fails instead of silently training on junk again."""
    assert LOGGER_SOURCE_BASE_MONEY_PATH == "base_money_path"
    import base_money_path_capture

    doc = (base_money_path_capture.__doc__ or "").lower()
    assert "quote-only" in doc, (
        "base_money_path no longer documents itself as quote-only; if it now writes full "
        "features, the training exclusion should be revisited rather than left in place")
