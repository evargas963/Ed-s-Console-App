"""Schwab's symbol limits, as its recorded answers state them and as a start reads them.

Real data: Schwab's answers to the first option subscription of one stream connection, and to
the one that followed it within the limits it stated, as production's daemon recorded them on
2026-11-22 (tests/fixtures/real_schwab_symbol_limit_answers_2026_11_22.json): on each option
service a request of 12,478 symbols in six parts, refused past LEVELONE_OPTIONS' 3,000 and
OPTIONS_BOOK's 100. STAND-INS (named): each request's symbol list, which the fixture leaves out
for its size and the limit's reader never reads: as many numbered symbols as it held.

The record is written by the real Recorder (stream_spine.CaptureWriter) and read by the start's
own reader (capture.stored_limits). Schwab's streamer played locally, which every connection
test runs on (tests/schwab_stream_standin.py), is held to the same answers. What a connection
does with a limit, Schwab to the stream's held contracts: tests/test_option_contract_rule_v1.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.market_data.schwab.streaming import capture
from feed.connection import SYMBOL_LIMIT, stated_limit
from stream_spine import CaptureWriter, subscription_msg
from tests.schwab_stream_standin import LocalStreamer, refusal

ANSWERS = json.loads(
    (
        Path(__file__).parent / "fixtures" / "real_schwab_symbol_limit_answers_2026_11_22.json"
    ).read_text(encoding="utf-8")
)["answers"]
L1, BOOK = "LEVELONE_OPTIONS", "OPTIONS_BOOK"
SCHWAB_LIMITS = {L1: 3000, BOOK: 100}


def _record(db: Path, answers: list[dict]) -> None:
    """Write `answers` to the record as the daemon's writer does, each as Schwab sent it."""
    writer = CaptureWriter(db)
    for a in answers:
        writer.insert(
            f"sub.{a['service']}",
            subscription_msg(
                service=a["service"],
                command=a["command"],
                symbols=[str(n) for n in range(a["symbols"])],
                code=a["code"],
                reason=a["reason"],
                ts=a["ts"],
            ),
        )


def test_a_start_reads_each_limit_schwab_last_stated_from_its_recorded_answers(tmp_path):
    """The 26 answers as recorded: 3,000 for LEVELONE_OPTIONS and 100 for OPTIONS_BOOK.

    Each of the 11 refusals of code 19 states its service's limit, and no other answer states
    one: not the code 24 that follows a refused ADD, nor the code 0 that follows a request
    Schwab took part of.
    """
    db = tmp_path / "ed.db"
    _record(db, ANSWERS)
    assert capture.stored_limits(db) == SCHWAB_LIMITS
    stated = [
        (a["code"], a["service"], stated_limit(a["service"], a["code"], a["reason"]))
        for a in ANSWERS
    ]
    assert [code for code, _svc, limit in stated if limit is not None] == [SYMBOL_LIMIT] * 11
    assert {(svc, limit) for _code, svc, limit in stated if limit is not None} == {
        (L1, 3000),
        (BOOK, 100),
    }
    assert sum(1 for a in ANSWERS if a["code"] == SYMBOL_LIMIT) == 11


@pytest.mark.parametrize(
    ("recorded", "limits"),
    [
        ([], {}),  # the record holds no answer
        ([a for a in ANSWERS if a["code"] != SYMBOL_LIMIT], {}),  # no refusal among its answers
        ([a for a in ANSWERS if a["service"] == BOOK], {BOOK: 100}),  # one service's alone
    ],
)
def test_a_service_schwab_has_stated_no_limit_for_has_none(tmp_path, recorded, limits):
    """What the record does not hold is not known, and no number is put in its place.

    A record with no answer, one whose answers hold no refusal, and one that holds
    OPTIONS_BOOK's refusals alone, as after a program that stopped before LEVELONE_OPTIONS'
    were written: that service is asked for everything once more, and Schwab states it again.
    """
    db = tmp_path / "ed.db"
    _record(db, recorded)
    assert capture.stored_limits(db) == limits


def test_a_database_without_the_record_states_no_limit_and_holds_no_watchlist(tmp_path):
    """INDUCED: a database file with no table in it, as a start that ended before its writer wrote.

    The record's tables are not there to read: no limit is stated and the watchlist is empty.
    """
    db = tmp_path / "ed.db"
    db.touch()
    assert capture.stored_limits(db) == {} and capture.stored_watchlist(db) == []


def test_the_newest_statement_is_the_limit_and_a_refusal_that_states_none_leaves_it(tmp_path):
    """Two later refusals on OPTIONS_BOOK, written before the recorded ones.

    INDUCED: every refusal Schwab has sent states the same limit for its service. Here a later
    one states 60, and one later still states none (code 19's text without its number, which
    Schwab has not sent). The newest statement by the answer's time is the service's limit,
    whatever order the rows were written in, and a refusal that states nothing changes nothing.
    """
    last = max(a["ts"] for a in ANSWERS)
    no_number = "You've reached the maximum number of symbols allowed."
    later = [
        {"ts": last + 1, "service": BOOK, "command": "ADD", "symbols": 44, "code": 19}
        | {"reason": refusal(BOOK, 60, 40)},
        {"ts": last + 2, "service": BOOK, "command": "ADD", "symbols": 44, "code": 19}
        | {"reason": no_number},
    ]
    db = tmp_path / "ed.db"
    _record(db, [*later, *ANSWERS])
    assert capture.stored_limits(db) == {L1: 3000, BOOK: 60}
    assert stated_limit(BOOK, 19, no_number) is None


def _requests(answers: list[dict]) -> list[tuple[str, int, list[dict]]]:
    """Return (command, symbols, its answers) of each request the recorded answers were to.

    A request Schwab refused past its limit was answered twice; every other one once.
    """
    out, i = [], 0
    while i < len(answers):
        n = 2 if answers[i]["code"] == SYMBOL_LIMIT else 1
        out.append((answers[i]["command"], answers[i]["symbols"], answers[i : i + n]))
        i += n
    return out


@pytest.mark.parametrize("service", [L1, BOOK])
def test_the_local_streamer_answers_a_request_past_its_limit_as_schwab_did(service):
    """The requests the recorded answers were to, replayed to the stand-in with Schwab's limits.

    The same codes and the same messages, in the same order: a request past the limit is
    answered twice, code 19 with the count past it and then that the command succeeded when part
    of it fit, or failed (code 24) when none did; the request that followed within the limit is
    accepted whole. STAND-IN (named): the symbols, numbered in the order asked; a SUBS begins
    the order again, as the daemon's does.
    """
    recorded = [a for a in ANSWERS if a["service"] == service]
    streamer = LocalStreamer(SCHWAB_LIMITS, data={})
    got, at = [], 0
    try:
        for rid, (command, symbols, _answers) in enumerate(_requests(recorded)):
            at = 0 if command == "SUBS" else at
            keys = ",".join(f"S{n}" for n in range(at, at + symbols))
            at += symbols
            frames = streamer.answer(
                {
                    "service": service,
                    "command": command,
                    "requestid": str(rid),
                    "SchwabClientCorrelId": "replayed",
                    "parameters": {"keys": keys, "fields": "0"},
                }
            )
            got += [
                (f["response"][0]["content"]["code"], f["response"][0]["content"]["msg"])
                for f in frames
            ]
    finally:
        streamer.close()
    assert got == [(a["code"], a["reason"]) for a in recorded]
    assert len(streamer.held[service]) == SCHWAB_LIMITS[service]
