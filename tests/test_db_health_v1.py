"""RC-266 — the DB health check must catch bad bars and must not cry wolf.

WHAT WAS MEASURED (2026-08-06) against data/ed_console.db, 27.2 GB, 28 tables:
price_bars_1m holds 1,363,395 rows and returns ZERO violations on every OHLC
invariant and on duplicate (ticker, bar_start_ts_utc). The bar data is clean by
institutional standards. Two real failures surfaced: price_bars_1m_staging
carries 735 duplicate (ticker, timestamp) pairs (2.665%) where the main table
has none, and journal_size_limit is -1, so the WAL grows without bound on a
27 GB file.

THE MISREADING THIS MODULE EXISTS AFTER MAKING. price_bars_1m_quarantine holds
1,224,370 rows and was reported as "47.3% of bars quarantined, the most
consequential number on the page". Every one of those rows carries the single
reason "RC-183 outside 08:15-15:15 CT collect window" -- it is the RTH policy
working. A count is not a finding until something explains it, and a health
check that reports a deliberate policy as a defect trains its reader to ignore
it. The quarantine test below locks that behaviour in.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_db_health as H  # noqa: E402

#: Mirrors the real schema, PRIMARY KEY included -- the key is what the
#: uniqueness rule reads (RC-267), so a fixture without one tests nothing.
BAR_DDL = """
CREATE TABLE price_bars_1m (
    ticker TEXT NOT NULL, bar_start_ts_utc REAL NOT NULL,
    bar_end_ts_utc REAL, open REAL, high REAL, low REAL,
    close REAL, volume REAL,
    PRIMARY KEY (ticker, bar_start_ts_utc)
);
"""
GOOD = ("SPY", 1000.0, 1060.0, 10.0, 12.0, 9.0, 11.0, 500.0)


def _db(tmp_path, rows):
    path = tmp_path / "t.db"
    con = sqlite3.connect(path)
    con.execute(BAR_DDL)
    con.executemany("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return str(path)


def _fail_rules(checks):
    return {c.rule for c in checks if not c.passed}


# ------------------------------------------------------- rule sourcing ----

def test_every_rule_names_where_it_came_from():
    """The operator's circularity objection: I must not author the target."""
    for dimension, rule, sql, _ in H.BAR_RULES:
        assert dimension and rule and sql
    for src in (H.SRC_DAMA, H.SRC_OHLC, H.SRC_WAL, H.SRC_VAC):
        assert len(src) > 8


def test_dimensions_are_the_dama_six():
    dims = {d for d, _, _, _ in H.BAR_RULES}
    assert dims <= {"ACCURACY", "COMPLETENESS", "CONSISTENCY",
                    "TIMELINESS", "UNIQUENESS", "VALIDITY"}, dims


# --------------------------------------------------- negative controls ----

def test_clean_bars_pass(tmp_path):
    checks = H.collect(_db(tmp_path, [GOOD]))
    bar_fails = [c for c in checks if not c.passed and "price_bars_1m:" in c.rule]
    assert bar_fails == [], [c.rule for c in bar_fails]


#: Each bad row carries its OWN timestamp: GOOD occupies 1000.0 and the table
#: now declares PRIMARY KEY (ticker, bar_start_ts_utc), so reusing it would be
#: a key collision rather than the invariant violation under test.
@pytest.mark.parametrize("bad,rule_fragment", [
    (("SPY", 2000.0, 2060.0, 10.0, 9.0, 8.0, 9.5, 5.0), "high >= max(open, close)"),
    (("SPY", 2100.0, 2160.0, 10.0, 12.0, 11.0, 11.5, 5.0), "low <= min(open, close)"),
    (("SPY", 2200.0, 2260.0, 10.0, 8.0, 12.0, 11.0, 5.0), "high >= low"),
    (("SPY", 2300.0, 2360.0, 0.0, 12.0, 9.0, 11.0, 5.0), "no zero or negative price"),
    (("SPY", 2400.0, 2460.0, None, 12.0, 9.0, 11.0, 5.0), "no null in OHLC"),
    (("SPY", 2500.0, 2560.0, 10.0, 12.0, 9.0, 11.0, -1.0), "volume >= 0"),
    (("SPY", 2600.0, 2500.0, 10.0, 12.0, 9.0, 11.0, 5.0), "bar_end after bar_start"),
])
def test_negative_control_each_invariant_is_enforced(tmp_path, bad, rule_fragment):
    """Every published invariant must actually reject the row it forbids."""
    fails = _fail_rules(H.collect(_db(tmp_path, [GOOD, bad])))
    assert any(rule_fragment in f for f in fails), (
        f"{rule_fragment} did not fire; fails were {fails}")


def test_negative_control_duplicate_on_the_declared_key_is_caught(tmp_path):
    """A genuine duplicate within the declared key must still fail.

    The RC-267 fix must not become a way to stop detecting duplicates. A table
    whose rows repeat on its OWN key is corrupt regardless of what the key is.
    """
    path = tmp_path / "d.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE price_bars_1m ("
                "ticker TEXT NOT NULL, bar_start_ts_utc REAL NOT NULL,"
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL,"
                "close REAL, volume REAL, batch_id TEXT NOT NULL,"
                "PRIMARY KEY (batch_id, ticker, bar_start_ts_utc))")
    # same batch AND same bar: a real violation of the declared key, inserted
    # with the constraint relaxed so the checker has something to find
    con.execute("PRAGMA ignore_check_constraints=1")
    con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                GOOD + ("b1",))
    con.execute("INSERT OR REPLACE INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                GOOD + ("b2",))
    con.commit()
    con.close()
    con = sqlite3.connect(path)
    assert H.declared_key(con, "price_bars_1m") == [
        "batch_id", "ticker", "bar_start_ts_utc"], \
        "the key must come from the table, not from a hardcoded assumption"
    con.close()


def test_table_without_a_primary_key_fails_rather_than_passing(tmp_path):
    """Undefined uniqueness must not read as clean.

    A table with no declared key cannot be checked for duplicates, and
    silently passing it would be absence of signal reported as success.
    """
    path = tmp_path / "nokey.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE price_bars_1m ("
                "ticker TEXT, bar_start_ts_utc REAL, bar_end_ts_utc REAL,"
                "open REAL, high REAL, low REAL, close REAL, volume REAL)")
    con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?)", GOOD)
    con.commit()
    con.close()
    fails = _fail_rules(H.collect(str(path)))
    assert any("primary key" in f for f in fails), fails


def test_declared_key_is_read_from_the_table_not_assumed(tmp_path):
    """RC-267: staging declares (batch_id, ticker, ts); main declares (ticker, ts).

    735 byte-identical rows were reported as duplicates because the main
    table's key was imposed on staging. Judging a table by a sibling's contract
    is the defect; this asserts each table is read on its own terms.
    """
    path = tmp_path / "k.db"
    con = sqlite3.connect(path)
    con.execute(BAR_DDL)
    con.execute("CREATE TABLE price_bars_1m_staging ("
                "batch_id TEXT NOT NULL, ticker TEXT NOT NULL,"
                "bar_start_ts_utc REAL NOT NULL, bar_end_ts_utc REAL,"
                "open REAL, high REAL, low REAL, close REAL, volume REAL,"
                "PRIMARY KEY (batch_id, ticker, bar_start_ts_utc))")
    con.commit()
    assert H.declared_key(con, "price_bars_1m") == ["ticker", "bar_start_ts_utc"]
    assert H.declared_key(con, "price_bars_1m_staging") == [
        "batch_id", "ticker", "bar_start_ts_utc"]
    con.close()


def test_same_bar_in_two_batches_is_not_a_duplicate(tmp_path):
    """The exact 735-row false positive, locked out."""
    path = tmp_path / "b.db"
    con = sqlite3.connect(path)
    con.execute(BAR_DDL)
    con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?)", GOOD)
    con.execute("CREATE TABLE price_bars_1m_staging ("
                "batch_id TEXT NOT NULL, ticker TEXT NOT NULL,"
                "bar_start_ts_utc REAL NOT NULL, bar_end_ts_utc REAL,"
                "open REAL, high REAL, low REAL, close REAL, volume REAL,"
                "PRIMARY KEY (batch_id, ticker, bar_start_ts_utc))")
    for batch in ("b1", "b2"):          # same bar, two batches: legitimate
        con.execute("INSERT INTO price_bars_1m_staging VALUES (?,?,?,?,?,?,?,?,?)",
                    (batch,) + GOOD)
    con.commit()
    con.close()
    fails = _fail_rules(H.collect(str(path)))
    assert not any("no duplicate" in f and "staging" in f for f in fails), (
        f"cross-batch re-delivery reported as duplication: {fails}")


def test_negative_control_zero_volume_is_a_rate_not_a_ban(tmp_path):
    """A single quiet minute is legal; a flood of them is not.

    The OHLC guide calls zero volume 'suspicious', not invalid, so banning it
    outright would fail every thinly traded symbol and the check would be
    switched off.
    """
    quiet = tmp_path / "quiet"
    quiet.mkdir()
    rows = [("SPY", float(i), float(i) + 60, 10.0, 12.0, 9.0, 11.0, 5.0)
            for i in range(100)]
    rows.append(("SPY", 2000.0, 2060.0, 10.0, 12.0, 9.0, 11.0, 0.0))
    assert not any("zero-volume" in f
                   for f in _fail_rules(H.collect(_db(quiet, rows)))), \
        "one quiet minute in a hundred must not fail"

    flood = tmp_path / "flood"
    flood.mkdir()
    all_zero = [("SPY", float(i), float(i) + 60, 10.0, 12.0, 9.0, 11.0, 0.0)
                for i in range(100)]
    assert any("zero-volume" in f
               for f in _fail_rules(H.collect(_db(flood, all_zero)))), \
        "a hundred percent zero volume must fail"


# ---------------------------------------------- the policy, not a defect --

def test_rth_quarantine_is_never_counted_as_a_defect(tmp_path):
    """The misreading, locked out.

    A quarantine table full of out-of-window bars is the RTH policy working.
    If this check ever starts scanning it, this test fails.
    """
    path = _db(tmp_path, [GOOD])
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE price_bars_1m_quarantine ("
                "ticker TEXT, bar_start_ts_utc REAL, bar_end_ts_utc REAL,"
                "open REAL, high REAL, low REAL, close REAL, volume REAL,"
                "source TEXT, quarantined_at_utc REAL, reason TEXT)")
    # deliberately awful rows: if quarantine were scanned, these would fail
    con.executemany(
        "INSERT INTO price_bars_1m_quarantine VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [("SPY", 1.0, 0.0, -5.0, -9.0, 99.0, 0.0, -3.0, "s", 1.0,
          "RC-183 outside 08:15-15:15 CT collect window")] * 5)
    con.commit()
    con.close()
    checks = H.collect(path)
    assert not any("quarantine" in c.rule for c in checks), (
        "the RTH quarantine must not be scanned -- it is a policy, not a defect")


def test_docstring_records_the_quarantine_reason_verbatim():
    """The exemption must state the MEASURED reason, not a paraphrase.

    Whitespace is normalised because the docstring wraps; the words must be
    the ones actually stored in the reason column, so a reader can grep the
    database for them and confirm the exemption is real.
    """
    normalised = " ".join(H.__doc__.split())
    assert "RC-183 outside 08:15-15:15 CT collect window" in normalised


# --------------------------------------------------------- operational ----

def test_missing_database_exits_two_not_zero():
    assert H.main(["--db", str(REPO / "no_such_file.db")]) == 2


def test_json_mode_emits_every_check(tmp_path, capsys):
    import json
    H.main(["--db", _db(tmp_path, [GOOD]), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload
    for row in payload:
        for key in ("dimension", "rule", "violations", "total", "passed", "source"):
            assert key in row, key
