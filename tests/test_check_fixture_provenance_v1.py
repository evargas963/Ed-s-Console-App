"""tools/check_fixture_provenance.py: a staged fixture is refused unless its provenance block names
the record it came from and its rows equal that record re-queried read-only. The record here is
SPY's and TSLA's captured books and option chains, and SPY's and $SPX's recorded level crosses,
written through the daemon's and the console's own writers into this test's databases."""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import fields
from datetime import datetime
from pathlib import Path

import pytest

REPO =Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import check_fixture_provenance as cfp  # noqa: E402
from app.market_data.schwab.streaming.capture import SERVICE_TOPIC  # noqa: E402
from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture  # noqa: E402
from db import EdDB, LevelCrossEvent  # noqa: E402
from stream_spine import CaptureWriter, book_msg  # noqa: E402
from time_et import ET  # noqa: E402

FX = REPO / "tests" / "fixtures"
NAME = "tests/fixtures/real_spy_tsla_books_record.json"
BOOKS_QUERY = ("SELECT ts_recv, symbol, service, src, schwab_ts, native_json FROM stream_book_raw "
               "WHERE symbol=? AND ts_recv>=? AND ts_recv<? ORDER BY ts_recv")
CROSS_COLUMNS = [f.name for f in fields(LevelCrossEvent)]


def _captured_books() -> list[tuple[str, float, str, dict]]:
    """(symbol, ts_recv, service, Schwab's item) of every captured SPY and TSLA book message."""
    spy = json.loads((FX / "real_spy_nyse_nasdaq_books.json").read_text(encoding="utf-8"))["books"]
    tsla = json.loads((FX / "real_tsla_book_rows.json").read_text(encoding="utf-8"))["rows"]
    return ([("SPY", b["ts_recv"], service, b["content"]) for service, b in spy.items()]
            + [("TSLA", ts, service, item) for ts, service, item in tsla])


def _record_books(data: Path) -> dict:
    """The captured books through the daemon's writer into `data`/stream_capture.db; the fixture of them."""
    writer = CaptureWriter(data / "stream_capture.db")
    rows = []
    with sqlite3.connect(str(writer.db_path)) as con:
        for symbol, ts, service, item in _captured_books():
            kind, src = SERVICE_TOPIC[service]
            writer.insert(f"{kind}.{symbol}", book_msg(symbol=symbol, service=service, content=item, src=src,
                                                       ts_recv=ts), conn=con)
            rows.append({"ts_recv": ts, "symbol": symbol, "service": service, "src": src, "schwab_ts": None,
                         "native": item})
    rows.sort(key=lambda r: (r["symbol"], r["ts_recv"]))
    return {"provenance": {
        "sent_by": "Schwab streamer NYSE_BOOK and NASDAQ_BOOK", "recorded_by": "capture daemon (its one writer)",
        "database": "data/stream_capture.db, opened read-only", "table": "stream_book_raw",
        "symbols": ["SPY", "TSLA"], "ts_recv_from_et": "2026-09-25T00:00", "ts_recv_to_et": "2026-09-26T00:00",
        "captured_utc": "2026-10-04T00:00:00+00:00", "query": BOOKS_QUERY}, "rows": rows}


def _dbs(data: Path) -> dict[str, Path]:
    return {"stream_capture.db": data / "stream_capture.db", "ed_console.db": data / "ed_console.db"}


def _staged(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True, capture_output=True)
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", *files], cwd=root, check=True, capture_output=True)
    return root


def test_a_fixture_that_is_the_daemons_record_passes(tmp_path):
    fixture = _record_books(tmp_path / "data")
    assert len(fixture["rows"]) == 152
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == []


def test_an_edited_row_is_refused(tmp_path):
    fixture = _record_books(tmp_path / "data")
    tsla = [r for r in fixture["rows"] if r["symbol"] == "TSLA"]
    tsla[3]["native"] = copy.deepcopy(tsla[4]["native"])
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"{NAME}: row 5 differs from the record in native"]


def test_a_dropped_row_is_refused(tmp_path):
    fixture = _record_books(tmp_path / "data")
    fixture["rows"].remove(next(r for r in fixture["rows"] if r["symbol"] == "TSLA"))
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [f"{NAME}: 151 rows, the record has 152"]


def test_rows_of_a_symbol_the_block_does_not_name_are_refused(tmp_path):
    fixture = _record_books(tmp_path / "data")
    fixture["provenance"]["symbols"] = ["TSLA"]
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [f"{NAME}: 152 rows, the record has 150"]


def test_fixtures_without_a_provenance_block_are_refused(tmp_path):
    names = ["real_spy_0dte_chain.json", "real_tsla_complete_chain_strike_range_all.json"]
    root = _staged(tmp_path, {f"tests/fixtures/{n}": (FX / n).read_text(encoding="utf-8") for n in names})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"tests/fixtures/{n}: no top-level provenance block: a fixture without one cannot be checked against the "
        "record it came from" for n in names]


def test_schwabs_option_chain_as_the_daemons_chain_sweep_recorded_it_is_checked_decoded(tmp_path):
    """The daemon's ChainSweep records Schwab's option chain in ed_console.db, its chain stored
    compressed: the fixture's chain equals it decoded, and an edited contract is refused."""
    db = tmp_path / "data" / "ed_console.db"
    db.parent.mkdir(parents=True)
    rows = []
    for name in ("real_spy_0dte_chain.json", "real_tsla_complete_chain_strike_range_all.json"):
        sent = json.loads((FX / name).read_text(encoding="utf-8"))
        expiry = sent["chain"][0]["expirationDate"][:10]
        ts = datetime.fromisoformat(expiry).replace(hour=10, tzinfo=ET).timestamp()
        persist_complete_chain_capture(db, ticker=sent["ticker"], expiry=expiry, contracts=sent["chain"], spot=None,
                                       completeness_basis=CAPTURE_BASIS, ts_utc=ts)
        rows.append({"ticker": sent["ticker"], "expiry": expiry, "ts_utc": ts, "chain": sent["chain"]})
    fixture = {"provenance": {
        "sent_by": "Schwab REST option chain", "recorded_by": "capture daemon ChainSweep",
        "database": "data/ed_console.db, opened read-only", "table": "complete_chain_captures",
        "symbols": ["SPY", "TSLA"], "sweep_from_et": "2026-08-01T00:00", "sweep_to_et": "2026-10-01T00:00",
        "captured_utc": "2026-10-04T00:00:00+00:00",
        "query": "SELECT ticker, expiry, ts_utc, chain_json FROM complete_chain_captures WHERE ticker=? AND "
                 "ts_utc>=? AND ts_utc<? ORDER BY expiry"},
        "rows": rows}
    edited = copy.deepcopy(fixture)
    edited["rows"][1]["chain"][0] = edited["rows"][1]["chain"][1]
    root = _staged(tmp_path, {"tests/fixtures/a.json": json.dumps(fixture), "tests/fixtures/b.json": json.dumps(edited)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        "tests/fixtures/b.json: row 1 differs from the record in chain"]


def _record_crosses(data: Path) -> dict:
    """SPY's and $SPX's recorded level crosses through the console's writer into `data`/ed_console.db;
    the fixture of them."""
    con = EdDB(data / "ed_console.db", allow_noncanonical=True)
    rows = []
    for name in ("real_spy_level_crosses.json", "real_spx_level_crosses_2026_09_25_28.json"):
        for r in json.loads((FX / name).read_text(encoding="utf-8"))["rows"]:
            con.log_level_cross(LevelCrossEvent(**{c: r[c] for c in CROSS_COLUMNS}))
            rows.append({c: r[c] for c in CROSS_COLUMNS})
    rows.sort(key=lambda r: (r["ticker"], r["ts_utc"]))
    return {"provenance": {
        "computed_by": "Ed Console", "database": "data/ed_console.db, opened read-only", "table": "level_crosses",
        "symbols": ["$SPX", "SPY"], "ts_from_et": "2026-09-01T00:00", "ts_to_et": "2026-10-01T00:00",
        "captured_utc": "2026-10-04T00:00:00+00:00",
        "query": f"SELECT {', '.join(CROSS_COLUMNS)} FROM level_crosses WHERE ticker=? AND ts_utc>=? AND ts_utc<? "
                 "ORDER BY ts_utc"}, "rows": rows}


def test_a_query_that_computes_a_value_the_record_does_not_hold_is_refused(tmp_path):
    """Every row's level_value moved +5.0, and the query computing the same +5.0: the rows equal
    what the query returns, but the record holds no such value."""
    fixture = _record_crosses(tmp_path / "data")
    for r in fixture["rows"]:
        r["level_value"] += 5.0
    fixture["provenance"]["query"] = fixture["provenance"]["query"].replace(
        "level_value,", "level_value + 5.0 AS level_value,")
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"{NAME}: provenance.query selects level_value + 5.0 AS level_value, which is not a column of level_crosses"]


@pytest.mark.parametrize("literal, value", [("585", 585), ("0x249", 585), ("1e3", 1000.0), ("NULL", None),
                                            ("TRUE", 1)])
def test_a_literal_in_the_select_list_is_refused(tmp_path, literal, value):
    """A literal returns the same value in every row, a value no column of the record holds."""
    fixture = _record_crosses(tmp_path / "data")
    fixture["provenance"]["query"] = fixture["provenance"]["query"].replace("SELECT ", f"SELECT {literal}, ", 1)
    fixture["rows"] = [{literal: value, **r} for r in fixture["rows"]]
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"{NAME}: provenance.query selects {literal}, which is not a column of level_crosses"]


def test_only_the_blocks_one_range_pair_may_hold_a_number(tmp_path):
    fixture = _record_crosses(tmp_path / "data")
    fixture["provenance"]["expected_pin_to_et"] = 585.0
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"{NAME}: provenance expected_pin_to_et hold numbers outside the checked rows"]


def test_a_number_as_a_key_is_refused(tmp_path):
    top = _record_crosses(tmp_path / "data")
    top["expected"] = {"585.0": True}
    block = copy.deepcopy(top)
    del block["expected"]
    block["provenance"]["expected"] = {"585.0": True}
    root = _staged(tmp_path, {"tests/fixtures/a.json": json.dumps(top), "tests/fixtures/b.json": json.dumps(block)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        "tests/fixtures/a.json: top-level expected hold numbers outside the checked rows",
        "tests/fixtures/b.json: provenance expected hold numbers outside the checked rows"]


@pytest.mark.parametrize("note", ["pin 585", "$585", "585.0 USD", "0x249"])
def test_a_number_inside_free_text_is_refused_and_a_date_or_time_is_not(tmp_path, note):
    fixture = _record_crosses(tmp_path / "data")
    fixture["provenance"]["note"] = "captured 2026-10-04 at 09:30:00 ET"
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == []
    fixture["provenance"]["note"] = note
    root = _staged(tmp_path / "again", {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"{NAME}: provenance note hold numbers outside the checked rows"]


def test_a_renamed_and_edited_fixture_is_checked(tmp_path):
    """`git mv` then an edit: git stages it as a rename (R), and the edited row is refused."""
    fixture = _record_crosses(tmp_path / "data")
    old, new = "tests/fixtures/crosses.json", "tests/fixtures/crosses_renamed.json"
    root = _staged(tmp_path, {old: json.dumps(fixture, indent=1)})
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"], cwd=root,
                   check=True, capture_output=True)
    subprocess.run(["git", "mv", old, new], cwd=root, check=True, capture_output=True)
    fixture["rows"][0]["level_name"] += " "
    (root / new).write_text(json.dumps(fixture, indent=1), encoding="utf-8")
    subprocess.run(["git", "add", new], cwd=root, check=True, capture_output=True)
    status = subprocess.run(["git", "diff", "--cached", "--name-status"], cwd=root, check=True,
                            capture_output=True, text=True).stdout
    assert status.startswith("R"), status
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [f"{new}: row 0 differs from the record in level_name"]


def test_a_query_of_a_table_valued_function_is_refused(tmp_path):
    """`json_each` returns whatever JSON the query hands it: invented rows equal what it returns,
    but no table of the record holds them."""
    fixture = _record_crosses(tmp_path / "data")
    fixture["provenance"].update(symbols=["$SPX"], query="SELECT value FROM json_each WHERE "
                                 "json='[590.5,591.25]' AND (type=? OR key>=? OR key<?)")
    fixture["rows"] = [{"value": 590.5}, {"value": 591.25}]
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"{NAME}: provenance.query reads json_each, which is not a table of ed_console.db"]


def test_a_number_in_the_provenance_block_is_refused(tmp_path):
    fixture = _record_crosses(tmp_path / "data")
    fixture["provenance"]["expected_pin"] = 585.0
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"{NAME}: provenance expected_pin hold numbers outside the checked rows"]


def test_a_number_written_as_text_outside_the_rows_is_refused(tmp_path):
    fixture = _record_crosses(tmp_path / "data")
    fixture["expected"] = {"pin": "585.00", "ticker": "SPY"}
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"{NAME}: top-level expected hold numbers outside the checked rows"]


def test_console_computed_crosses_are_checked_against_the_consoles_table(tmp_path):
    fixture = _record_crosses(tmp_path / "data")
    rows = fixture["rows"]
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == []
    rows[0]["level_name"] = rows[1]["level_name"] + " "
    root = _staged(tmp_path / "again", {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [f"{NAME}: row 0 differs from the record in level_name"]


def test_without_the_record_the_fixture_is_refused_never_passed(tmp_path):
    fixture = _record_books(tmp_path / "data")
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    missing = tmp_path / "nowhere"
    assert cfp.violations(root, _dbs(missing)) == [
        f"{NAME}: cannot verify: the record {missing / 'stream_capture.db'} is not here"]


def test_the_hook_reads_the_runtime_record(tmp_path):
    """The hook as the commit runs it: the databases are runtime_layout's (ED_RUNTIME_ROOT here)."""
    fixture = _record_books(tmp_path / "runtime" / "data")
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    run = [sys.executable, str(REPO / "tools" / "check_fixture_provenance.py")]
    env = {**os.environ, "ED_RUNTIME_ROOT": str(tmp_path / "runtime")}
    ok = subprocess.run(run, cwd=root, env=env, capture_output=True, text=True)
    assert (ok.returncode, ok.stdout) == (0, "")
    env["ED_RUNTIME_ROOT"] = str(tmp_path / "empty")
    refused = subprocess.run(run, cwd=root, env=env, capture_output=True, text=True)
    assert refused.returncode == 1 and "cannot verify" in refused.stdout
