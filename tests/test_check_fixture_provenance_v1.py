"""tools/check_fixture_provenance.py (FIXTURE-PROVENANCE): a staged fixture is refused unless its
provenance block names the record it came from and its rows equal that record re-queried read-only.
The record here is SPY's and TSLA's captured books (and SPY's and $SPX's recorded level crosses)
written through the daemon's own writer (and the console's own), into this test's databases."""
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

REPO = Path(__file__).resolve().parent.parent
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
        f"{NAME}: TSLA: row 3 differs from the record in native"]


def test_a_dropped_row_is_refused(tmp_path):
    fixture = _record_books(tmp_path / "data")
    fixture["rows"].remove(next(r for r in fixture["rows"] if r["symbol"] == "TSLA"))
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [f"{NAME}: TSLA: 149 rows, the record has 150"]


def test_rows_of_a_symbol_the_block_does_not_name_are_refused(tmp_path):
    fixture = _record_books(tmp_path / "data")
    fixture["provenance"]["symbols"] = ["TSLA"]
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"{NAME}: rows of SPY, which provenance.symbols does not list"]


def test_fixtures_without_a_provenance_block_are_refused(tmp_path):
    names = ["real_spy_0dte_chain.json", "real_tsla_complete_chain_strike_range_all.json"]
    root = _staged(tmp_path, {f"tests/fixtures/{n}": (FX / n).read_text(encoding="utf-8") for n in names})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        f"tests/fixtures/{n}: no top-level provenance block: a fixture without one cannot be checked against the "
        "record it came from" for n in names]


def test_schwab_data_must_be_the_daemons_record_and_computed_data_must_not_be(tmp_path):
    fixture = _record_books(tmp_path / "data")
    console = copy.deepcopy(fixture)
    console["provenance"].update(database="data/ed_console.db", table="level_crosses")
    computed = copy.deepcopy(fixture)
    computed["provenance"]["computed_by"] = computed["provenance"].pop("sent_by")
    root = _staged(tmp_path, {"tests/fixtures/a.json": json.dumps(console), "tests/fixtures/b.json": json.dumps(computed)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        "tests/fixtures/a.json: sent_by names ed_console.db level_crosses, which is not the capture daemon's record "
        "of what Schwab sent (ed_console.db complete_chain_captures, stream_capture.db stream_bars_raw, "
        "stream_capture.db stream_book_raw, stream_capture.db stream_news_raw, stream_capture.db "
        "stream_options_quotes_raw, stream_capture.db stream_quotes_raw)",
        "tests/fixtures/b.json: computed_by names stream_book_raw, which is the daemon's record of what Schwab sent"]


def test_schwabs_option_chain_as_the_daemons_chain_sweep_recorded_it_is_schwab_data(tmp_path):
    """The daemon's ChainSweep records Schwab's option chain in ed_console.db, its chain stored
    compressed: a fixture of it is checked as what Schwab sent, and is refused as computed."""
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
    computed = copy.deepcopy(fixture)
    computed["provenance"]["computed_by"] = computed["provenance"].pop("sent_by")
    root = _staged(tmp_path, {"tests/fixtures/a.json": json.dumps(fixture), "tests/fixtures/b.json": json.dumps(computed)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [
        "tests/fixtures/b.json: computed_by names complete_chain_captures, which is the daemon's record of what "
        "Schwab sent"]


def test_console_computed_crosses_are_checked_against_the_consoles_table(tmp_path):
    con = EdDB(tmp_path / "data" / "ed_console.db", allow_noncanonical=True)
    rows = []
    for name in ("real_spy_level_crosses.json", "real_spx_level_crosses_2026_09_25_28.json"):
        for r in json.loads((FX / name).read_text(encoding="utf-8"))["rows"]:
            con.log_level_cross(LevelCrossEvent(**{c: r[c] for c in CROSS_COLUMNS}))
            rows.append({c: r[c] for c in CROSS_COLUMNS})
    rows.sort(key=lambda r: (r["ticker"], r["ts_utc"]))
    fixture = {"provenance": {
        "computed_by": "Ed Console", "database": "data/ed_console.db, opened read-only", "table": "level_crosses",
        "symbols": ["$SPX", "SPY"], "ts_from_et": "2026-09-01T00:00", "ts_to_et": "2026-10-01T00:00",
        "captured_utc": "2026-10-04T00:00:00+00:00",
        "query": f"SELECT {', '.join(CROSS_COLUMNS)} FROM level_crosses WHERE ticker=? AND ts_utc>=? AND ts_utc<? "
                 "ORDER BY ts_utc"}, "rows": rows}
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == []
    rows[0]["level_name"] = rows[1]["level_name"] + " "
    root = _staged(tmp_path / "again", {NAME: json.dumps(fixture)})
    assert cfp.violations(root, _dbs(tmp_path / "data")) == [f"{NAME}: $SPX: row 0 differs from the record in level_name"]


def test_without_the_record_the_fixture_is_refused_never_passed(tmp_path):
    fixture = _record_books(tmp_path / "data")
    root = _staged(tmp_path, {NAME: json.dumps(fixture)})
    missing = tmp_path / "nowhere"
    assert cfp.violations(root, _dbs(missing)) == [
        f"{NAME}: cannot verify: the record {missing / 'stream_capture.db'} is not here (refused, never passed "
        "unverified)"]


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
