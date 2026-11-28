"""The daemon's Schwab sign-in, whose one record is the token file.

A sign-in saved there is taken without a restart (while Schwab refuses the old one, at the next
request; while signed in, when the next refresh is due); once Schwab refuses the sign-in, nothing
more is sent to Schwab until a new one is saved.

Through the real schwab-py client (schwab_client.client_from_token_file_atomic) against the local
stand-in for Schwab's host (tests/schwab_rest_standin.py: its real data and stand-ins are named
there, Schwab's refusal REFUSED among them), and the daemon's real chain sweep (ChainSweep.work) on
a fixed clock: 2026-10-07 20:00 ET, after that day's option close, a day Schwab's /markets answer
was captured for. STAND-INS (named): the token files; the host a test's client delivers to (the
stand-in's), named in that test.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import pytest

import live_market_plane as lmp
import time_et
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.capture import CaptureWriter
from feed import chain_sweep as cch
from feed import schwab_client as sc
from push import verdict as push_verdict
from stream_spine import HealthRegistry, MessageBus
from tests.feed_live_helper import daemon_status, mark_feed_down
from tests.schwab_rest_standin import EXPIRATIONS, TOKEN, LocalSchwab
from tests.shared_helpers import until
from time_et import ET

_AFTER_THE_CLOSE = datetime(2026, 10, 7, 20, 0, tzinfo=ET).timestamp()


def _posts(schwab: LocalSchwab) -> int:
    return sum(1 for r in schwab.requests if r[0] == TOKEN)


def _asked(schwab: LocalSchwab) -> list:
    """Each data request that reached Schwab: (path, the token it carried)."""
    return [(r[0], r[5]) for r in schwab.requests if r[0] != TOKEN]


def _every_request(client) -> list:
    """Each kind of request the daemon sends Schwab, as it sends it.

    The stream's login first asks for the user's preferences (schwab-py StreamClient.login).
    """
    return [
        lambda: client.get_user_preferences(),
        lambda: client.get_option_expiration_chain("SPY"),
        lambda: sc.safe_get_chain(client, "SPY", strike_range="ALL"),
        lambda: sc.safe_get_quotes(client, ["SPY"]),
        lambda: client.get_price_history_every_minute("SPY"),
        lambda: client.get_market_hours([client.MarketHours.Market.EQUITY]),
    ]


def _saved_whole(tmp_path, held: str):
    """Save `held` as the token file whole, as every writer saves; return the file's path."""
    token = tmp_path / "schwab_token.json"
    bad = tmp_path / "not_a_sign_in.json"
    bad.write_text(held)
    bad.replace(token)
    return token


def _new_sign_in(token_path, access: str) -> int:
    """Save a new sign-in to the token file; return its creation time.

    It is saved by the writer of every sign-in python reauth_schwab.py saves
    (sc.write_token_file_atomically).
    """
    created = int(time_et.now()) + 1
    sc.write_token_file_atomically(
        str(token_path),
        {
            "creation_timestamp": created,
            "token": {
                "access_token": access,
                "refresh_token": "r2",
                "token_type": "Bearer",
                "expires_in": 1800,
                "expires_at": int(time_et.now() + 3600),
            },
        },
    )
    return created


class _Turns(threading.Event):
    """The sweep's stop event, set after `n` of the sweep's idle waits.

    Each wait returns at once (the sweep's second between looks, not waited out).
    """

    def __init__(self, n: int):
        super().__init__()
        self.left = n

    def wait(self, _timeout=None):
        self.left -= 1
        if self.left <= 0:
            self.set()
        return self.is_set()


def _sweep(tmp_path):
    sqlite3.connect(tmp_path / "ed_console.db").close()
    return cch.ChainSweep(
        tmp_path / "ed_console.db",
        ["SPY"],
        lambda _topic, _msg: None,
        clock=lambda: _AFTER_THE_CLOSE,
        failures=CaptureWriter(tmp_path / "stream_capture.db"),
        streamed=lambda _symbol: None,
    )


def _work(sweep, schwab_client, turns: int) -> bool:
    """Run the sweep's thread, stopped after `turns` idle looks.

    Returns whether it ended within 20 s by that stop (not by an exception ending the thread).
    """
    stop = _Turns(turns)
    worker = threading.Thread(target=sweep.work, args=(schwab_client, stop), daemon=True)
    worker.start()
    worker.join(20)
    return stop.is_set() and not worker.is_alive()


def test_a_token_schwab_calls_invalid_is_refreshed_once_whatever_its_expiry_says(tmp_path):
    """Measured 2026-11-05 07:07 to 07:32 CT: a token Schwab answered 401 invalid_token.

    The token's expires_at said 30 more minutes, and Schwab answered every request 401
    invalid_token. Schwab's answer decides: the token is refreshed once, the refused request is
    answered with the new one, and the next request carries it.
    """
    schwab = LocalSchwab()
    schwab.expired = {"a"}
    try:
        client = schwab.client(tmp_path)  # its expires_at an hour away
        first = client.get_option_expiration_chain("SPY")
        second = client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert (first.status_code, second.status_code) == (200, 200)
    assert _posts(schwab) == 1
    assert _asked(schwab) == [
        (EXPIRATIONS, "Bearer a"),
        (EXPIRATIONS, "Bearer new-access"),
        (EXPIRATIONS, "Bearer new-access"),
    ]


def test_once_schwab_refuses_the_sign_in_no_request_of_any_kind_reaches_schwab(tmp_path):
    """The token in its refresh window and Schwab refusing it.

    The first request's refresh is refused (SignInRefusedError), and every kind of request the
    daemon sends after it, the stream's login among them, raises the same, sending nothing: one
    POST in all, no data request. Each refusal raised is its own, carrying only its own
    request's frames (one held and raised again would grow its traceback by every request's
    frames, for as long as Schwab refuses).
    """
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        raised = []
        for request in _every_request(client) * 3:
            with pytest.raises(sc.SignInRefusedError, match="Refresh token is invalid") as r:
                request()
            raised.append(r.value)
        refusal = client.session.refusal()
        assert "Refresh token is invalid" in refusal and refusal.endswith("python reauth_schwab.py")
    finally:
        schwab.close()
    assert (_posts(schwab), _asked(schwab)) == (1, [])
    depth = [len(traceback.extract_tb(e.__traceback__)) for e in raised]
    assert len({id(e) for e in raised}) == len(raised) and depth[6:12] == depth[12:] == depth[:6]


def test_a_new_sign_in_saved_after_the_refusal_is_taken_without_a_restart(tmp_path):
    """After the refusal, a new sign-in saved to the token file.

    The next request carries its token, and the client's token and creation time (the
    streamer's login reads them) are its.
    """
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        with pytest.raises(sc.SignInRefusedError):
            client.get_option_expiration_chain("SPY")
        created = _new_sign_in(tmp_path / "schwab_token.json", "fresh")
        resp = client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert resp.status_code == 200 and _asked(schwab) == [(EXPIRATIONS, "Bearer fresh")]
    assert client.token_metadata.token["access_token"] == "fresh"
    assert client.token_metadata.creation_timestamp == created


def test_a_new_sign_in_saved_while_signed_in_is_taken_when_the_refresh_is_due(tmp_path):
    """A sign-in saved while the daemon still holds the old one.

    While the old token is not yet due for its refresh, requests carry it; once it is due, the
    new sign-in is taken in place of the refresh: no token request, the request carries the new
    token, the token file still holds it.
    """
    schwab = LocalSchwab()
    try:
        client = schwab.client(tmp_path)  # the old sign-in, an hour from expiry
        token = tmp_path / "schwab_token.json"
        created = _new_sign_in(token, "fresh")
        client.get_option_expiration_chain("SPY")
        client.session.token["expires_at"] = (
            int(time_et.now()) + 100
        )  # the old token now in its refresh window
        resp = client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert resp.status_code == 200 and _posts(schwab) == 0
    assert _asked(schwab) == [(EXPIRATIONS, "Bearer a"), (EXPIRATIONS, "Bearer fresh")]
    saved = json.loads(token.read_text())
    assert saved["token"]["access_token"] == "fresh" and saved["creation_timestamp"] == created


#: another process saving a sign-in (as python reauth_schwab.py saves one, holding the token file's
#: lock): it says "held", holds the lock a moment, sees whether anything wrote the file meanwhile,
#: then saves the sign-in
_SAVER = """
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from feed import schwab_client as sc
path, payload = sys.argv[2], json.loads(sys.argv[3])
with sc.token_file_lock(path):
    seen = os.stat(path)
    print("held", flush=True)
    time.sleep(0.3)
    now = os.stat(path)
    sc.write_token_file_atomically(path, payload)
sys.exit(3 if (now.st_mtime_ns, now.st_ino) != (seen.st_mtime_ns, seen.st_ino) else 0)
"""
_FRESH = {
    "creation_timestamp": int(time_et.now()) + 1,
    "token": {
        "access_token": "fresh",
        "refresh_token": "r2",
        "token_type": "Bearer",
        "expires_in": 1800,
        "expires_at": int(time_et.now() + 3600),
    },
}


def _saving(token) -> subprocess.Popen:
    """Start the other process, holding the token file's lock once this returns.

    It is saving a sign-in newer than the one the file holds.
    """
    newer = {
        **_FRESH,
        "creation_timestamp": json.loads(token.read_text())["creation_timestamp"] + 1,
    }
    saver = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _SAVER,
            str(Path(__file__).resolve().parent.parent),
            str(token),
            json.dumps(newer),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert saver.stdout.readline().strip() == "held"
    return saver


def test_a_refresh_due_while_a_sign_in_is_being_saved_takes_it_and_never_writes_over_it(tmp_path):
    """A refresh due while another process is saving a sign-in (holding the token file's lock).

    Nothing writes the file while it is held, and the session takes the saved sign-in instead of
    refreshing the old one: no token request, the request carries the new sign-in's token.
    """
    schwab = LocalSchwab()
    token = tmp_path / "schwab_token.json"
    try:
        client = schwab.client(tmp_path, 100)  # the old sign-in, in its refresh window
        with _saving(token) as saver:  # leaving it closes the saver's pipe
            client.get_option_expiration_chain("SPY")
            assert saver.wait(30) == 0, (
                "the token file was written while a sign-in being saved held it"
            )
    finally:
        schwab.close()
    assert json.loads(token.read_text())["token"]["access_token"] == "fresh"
    assert (_posts(schwab), _asked(schwab)) == (0, [(EXPIRATIONS, "Bearer fresh")])


def test_a_client_built_while_a_sign_in_is_being_saved_holds_that_sign_in(tmp_path):
    """The daemon's client built while another process is saving a sign-in.

    The other process holds the token file's lock. The client is built from the saved sign-in,
    never from the one it replaces, and its first request carries it.
    """
    schwab = LocalSchwab()
    token = tmp_path / "schwab_token.json"
    try:
        schwab.client(tmp_path)  # the old sign-in, saved before
        with _saving(token) as saver:  # leaving it closes the saver's pipe
            client = schwab.delivering_here(sc.client_from_token_file_atomic(str(token), "k", "s"))
            held = client.token_metadata.token["access_token"]
            assert saver.wait(30) == 0
        client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert held == "fresh"
    assert _asked(schwab) == [(EXPIRATIONS, "Bearer fresh")]


def test_a_sign_in_in_progress_removes_the_token_file_and_nothing_breaks(tmp_path):
    """Python reauth_schwab.py removes the token file before it saves the new sign-in.

    While it is not there the session holds no sign-in and raises nothing else; once saved, it
    is taken.
    """
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        token = tmp_path / "schwab_token.json"
        with pytest.raises(sc.SignInRefusedError):
            client.get_option_expiration_chain("SPY")
        token.unlink()
        assert client.session.refusal() is not None
        with pytest.raises(sc.SignInRefusedError):
            client.get_option_expiration_chain("SPY")
        _new_sign_in(token, "fresh")
        assert client.session.refusal() is None
    finally:
        schwab.close()
    assert _posts(schwab) == 1


def test_schwabs_edge_page_at_the_token_endpoint_is_not_a_refusal(tmp_path):
    """Schwab's edge answering the refresh with its 403 page.

    The request fails and the next one asks again; only Schwab's answer refusing the sign-in
    stops the requests.
    """
    schwab = LocalSchwab()
    schwab.token = "edge"
    try:
        client = schwab.client(tmp_path, 100)
        for _ in range(2):
            with pytest.raises(Exception) as raised:
                client.get_option_expiration_chain("SPY")
            assert not isinstance(raised.value, sc.SignInRefusedError)
        assert client.session.refusal() is None
    finally:
        schwab.close()
    assert _posts(schwab) == 2


def test_a_token_endpoint_that_cannot_be_reached_is_not_a_refusal(tmp_path):
    """Schwab's host not answering at all (a network failure: its port closed).

    The request fails, the session still holds its sign-in, and the next request tries again.
    """
    schwab = LocalSchwab()
    client = schwab.client(tmp_path, 100)
    schwab.close()
    schwab.server.server_close()
    for _ in range(2):
        with pytest.raises(Exception) as raised:
            client.get_option_expiration_chain("SPY")
        assert not isinstance(raised.value, sc.SignInRefusedError)
    assert client.session.refusal() is None


def test_a_refresh_whose_connection_ends_with_no_answer_is_sent_once_and_is_not_a_refusal(
    tmp_path, caplog
):
    """INDUCED: the token endpoint's connection ends before any answer.

    As Schwab's end reset two connections on 2026-11-18 and 2026-11-20. The refresh is a POST,
    which a client does not repeat on its own (RFC 9110 §9.2.2), made inside the GET whose token
    was due: it is raised, sent once, and the GET, never sent, is not sent again or named as the
    request with no answer. The session still holds its sign-in, and the next request refreshes
    and is answered.
    """
    schwab = LocalSchwab()
    schwab.token = "drops"
    try:
        client = schwab.client(tmp_path, 100)
        with (
            caplog.at_level(logging.WARNING, logger=sc.log.name),
            pytest.raises(sc.NO_ANSWER) as raised,
        ):
            client.get_option_expiration_chain("SPY")
        assert raised.value.request.url.path == TOKEN
        assert (_posts(schwab), _asked(schwab), client.session.refusal()) == (1, [], None)
        assert [r.getMessage() for r in caplog.records if "no answer" in r.getMessage()] == []
        schwab.token = "refreshes"
        assert client.get_option_expiration_chain("SPY").status_code == 200
    finally:
        schwab.close()
    assert _posts(schwab) == 2


def test_the_builder_builds_on_a_usable_sign_in_and_names_one_that_cannot_be_refreshed(tmp_path):
    """The daemon's builder (build_client_from_token) on a sign-in saved as reauth saves it.

    It builds a client on the daemon's one session; on a sign-in with no refresh token it builds
    none, and says what to run.
    """
    token = tmp_path / "schwab_token.json"
    _new_sign_in(token, "a")
    built = sc.build_client_from_token(str(token), "LiveLookingKey", "LiveLookingSecret")
    assert built.client is not None
    built.client.session.close()
    assert (built.ok, built.message) == (True, "Client loaded from token file.")
    assert isinstance(built.client.session, sc.OneRefreshSession)
    sent = {k: v for k, v in _FRESH["token"].items() if k != "refresh_token"}
    _saved_whole(tmp_path, json.dumps({**_FRESH, "token": sent}))
    refused = sc.build_client_from_token(str(token), "LiveLookingKey", "LiveLookingSecret")
    assert (refused.ok, refused.client) == (False, None)
    assert refused.message == (
        f"Schwab token is NOT refreshable (refresh_token missing or empty) at {str(token)!r}. "
        "Remediation: python reauth_schwab.py --manual"
    )


@pytest.mark.parametrize("scope", ["api", ["api", "read"], None])
def test_the_token_files_scope_is_shown_as_sent(tmp_path, scope):
    """The scope reauth_schwab.py prints is the token's as saved; none when none was sent."""
    sent = {**_FRESH["token"], **({} if scope is None else {"scope": scope})}
    token = _saved_whole(tmp_path, json.dumps({**_FRESH, "token": sent}))
    assert sc.inspect_token_file(str(token)).scope_value == scope


def test_the_chain_sweep_asks_nothing_while_signed_out_and_goes_on_after_a_new_sign_in(
    tmp_path, caplog
):
    """The daemon's chain sweep over SPY while Schwab refuses the sign-in.

    Its first round meets the refusal (one POST), then it only looks, 50 times, sending nothing
    and logging nothing more (a round per look would log every request's failure); a new
    sign-in saved, it asks Schwab.
    """
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING):
            assert _work(sweep, lambda: client, 50), (
                "the sweep never stopped to look: it kept asking"
            )
        first_round = len(caplog.records)
        assert (_posts(schwab), _asked(schwab)) == (1, [])
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            assert _work(sweep, lambda: client, 50)
        assert (_posts(schwab), _asked(schwab)) == (1, []) and not caplog.records and first_round
        _new_sign_in(tmp_path / "schwab_token.json", "fresh")
        assert _work(sweep, lambda: client, 1)
    finally:
        schwab.close()
    asked = _asked(schwab)
    assert asked and all(auth == "Bearer fresh" for _path, auth in asked)


def test_the_header_says_schwab_refused_the_sign_in_and_what_to_run(tmp_path):
    """The daemon's status carries its Schwab sign-in for the header (capture.sign_in_line).

    While Schwab refuses it, its word is REFUSED and its line says what to run, with Schwab's
    own reason in full; once a new sign-in is saved and taken, both say accepted. Without a
    chain sweep the daemon has asked nothing, and the header shows '-'.
    """
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        sweep = _sweep(tmp_path)
        assert _work(sweep, lambda: client, 3)
        daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])
        assert daemon.status(1.0)["sign_in"] is None
        daemon.chains = sweep
        refused = daemon.status(1.0)["sign_in"]
        _new_sign_in(tmp_path / "schwab_token.json", "fresh")
        assert _work(sweep, lambda: client, 1)
        accepted = daemon.status(2.0)["sign_in"]
    finally:
        schwab.close()
    assert refused["line"] == "REFUSED: run python reauth_schwab.py" and refused["cls"] == "neg"
    assert refused["word"] == "REFUSED"
    assert "Refresh token is invalid" in refused["why"]
    assert accepted == {
        "word": "accepted",
        "line": "accepted",
        "why": "Schwab accepts the daemon's sign-in",
        "cls": "",
    }


#: the daemon's waiting when Schwab refused its sign-in, as production logged it at 2026-11-19
#: 13:00:13 CT, seven days after the sign-in was saved
REFUSED_2026_11_19 = (
    'Schwab refused the sign-in (unsupported_token_type: 400 Bad Request: "{"error_description":'
    '"Refresh token is invalid, expired or revoked","error":"invalid_grant"}"); nothing is sent '
    "to Schwab until a new sign-in is saved: python reauth_schwab.py"
)
#: the header's sign-in lines the browser test draws
E2E_SIGN_IN = Path(__file__).parent / "e2e" / "fixtures" / "sign_in_lines.json"


def test_the_browser_tests_sign_in_lines_are_the_daemons_own():
    assert json.loads(E2E_SIGN_IN.read_text(encoding="utf-8")) == {
        "refused": capture.sign_in_line(REFUSED_2026_11_19),
        "accepted": capture.sign_in_line(None),
    }


def _verdict(daemon, computed: float | None, at: datetime) -> tuple:
    """Return the console's verdict on SPY's levels computed at `computed`, judged at `at`.

    Judged with the daemon's status stamped then taken in by the plane: (levels_state,
    levels_stale_reason).
    """
    now = at.timestamp()
    lmp.record_feed_heartbeat(daemon.status(now))
    try:
        verdict = push_verdict.terrain_staleness(computed, "SPY", now=now)
    finally:
        lmp.record_feed_heartbeat(daemon_status(0.0, schwab_socket_open=True))
        mark_feed_down()
    return verdict["levels_state"], verdict["levels_stale_reason"]


def test_a_refused_sign_in_is_why_the_screen_says_the_levels_are_not_live(tmp_path):
    """Schwab refusing the sign-in (REFUSED): the daemon's chain sweep asks for nothing.

    The sweep keeps why, and the daemon's status carries it. The console's verdict on SPY's
    levels names the refusal and what to run: past due during 2026-10-07's session, after its
    option close before the close values were fetched, never computed, and on 2026-09-20, a date
    Schwab's /markets answer is not held for. A new sign-in saved, the sweep's why is gone.
    """
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        sweep = _sweep(tmp_path)
        assert _work(sweep, lambda: client, 3)
        refused = sweep.waiting
        daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])
        daemon.chains = sweep
        noon, evening = (
            datetime(2026, 10, 7, 12, 0, tzinfo=ET),
            datetime(2026, 10, 7, 20, 0, tzinfo=ET),
        )
        past_due = _verdict(daemon, noon.timestamp() - 3600, noon)
        closed = _verdict(daemon, datetime(2026, 10, 7, 15, 0, tzinfo=ET).timestamp(), evening)
        none_yet = _verdict(daemon, None, noon)
        unknown = _verdict(
            daemon,
            datetime(2026, 9, 20, 10, 0, tzinfo=ET).timestamp(),
            datetime(2026, 9, 20, 11, 0, tzinfo=ET),
        )
        _new_sign_in(tmp_path / "schwab_token.json", "fresh")
        assert _work(sweep, lambda: client, 1)
    finally:
        schwab.close()
    why = f" — no chain is fetched: {refused}"
    assert "Refresh token is invalid" in refused and refused.endswith("python reauth_schwab.py")
    assert past_due == ("STALE", "levels are 3600s old" + why)
    assert closed == (
        "STALE",
        "this ticker's options are closed and its levels were not current at the close" + why,
    )
    assert none_yet == ("STALE", "no terrain snapshot has been computed yet" + why)
    assert unknown == ("NOT LIVE", "the market session is unknown" + why)
    assert sweep.waiting is None


#: another process holding the token file's lock (as a save would) for 25 s: "held" once it does
_HOLDER = """
import sys, time
sys.path.insert(0, sys.argv[1])
from feed import schwab_client as sc
with sc.token_file_lock(sys.argv[2]):
    print("held", flush=True)
    time.sleep(25)
"""


def test_a_build_that_fails_is_logged_once_by_the_sweep_with_its_cause(tmp_path, caplog):
    """A usable sign-in whose file another process holds locked past the builder's wait.

    The wait is schwab_client.TOKEN_LOCK_WAIT_SEC. The real builder, through the daemon's real
    client holder (capture.OneSchwabClient), fails inside the build. The sweep's one warning
    carries the traceback with the lock's own TimeoutError as its cause, and a second ask adds
    no warning.
    """
    token = tmp_path / "schwab_token.json"
    _new_sign_in(token, "a")
    schwab_client = capture.OneSchwabClient(
        lambda: sc.build_client_from_token(str(token), "LiveLookingKey", "LiveLookingSecret")
    )
    with subprocess.Popen(  # leaving it waits for the holder and closes its pipe
        [sys.executable, "-c", _HOLDER, str(Path(__file__).resolve().parent.parent), str(token)],
        stdout=subprocess.PIPE,
        text=True,
    ) as holder:
        try:
            assert holder.stdout.readline().strip() == "held"
            sweep = _sweep(tmp_path)
            with caplog.at_level(logging.WARNING, logger=cch.log.name):
                sweep.waits(schwab_client)
                sweep.waits(schwab_client)
        finally:
            holder.kill()
    warned = [r for r in caplog.records if r.getMessage().startswith("chain sweep waits")]
    assert len(warned) == 1, [r.getMessage() for r in warned]
    error = warned[0].exc_info[1] if warned[0].exc_info else None
    assert isinstance(error, ConnectionError), warned[0].exc_info
    assert isinstance(error.__cause__, TimeoutError), error.__cause__


def test_the_chain_sweep_waits_for_a_client_it_cannot_build_and_goes_on_once_built(
    tmp_path, caplog
):
    """The daemon's client holder (capture.OneSchwabClient, the real one), client unbuildable.

    While its client cannot be built: the real builder's answer for a token file that is not there
    (schwab_client.build_client_from_token), which the holder raises as ConnectionError and
    builds again on the next ask. The sweep keeps looking, logs it once and asks Schwab for
    nothing; once the token file is saved and the client built, it asks. STAND-IN (named): the
    built client is the real builder of the client (client_from_token_file_atomic), delivering to
    the stand-in, which build_client_from_token's client does not.
    """
    schwab = LocalSchwab()
    token = tmp_path / "schwab_token.json"

    def build():
        if not token.exists():
            return sc.build_client_from_token(str(token), "LiveLookingKey", "LiveLookingSecret")
        return sc.SchwabClientState(
            ok=True,
            message="",
            client=schwab.delivering_here(sc.client_from_token_file_atomic(str(token), "k", "s")),
        )

    schwab_client = capture.OneSchwabClient(build)
    try:
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING):
            assert _work(sweep, schwab_client, 20), "the sweep ended or never looked again"
        waits = [r.getMessage() for r in caplog.records]
        assert len(waits) == 1 and waits[0].startswith(
            "chain sweep waits for the daemon's Schwab client: no Schwab client ("
        )
        assert schwab.requests == []
        assert sweep.waiting.startswith(
            "the daemon holds no Schwab sign-in to ask with (no Schwab client ("
        )
        assert sweep.waiting.endswith("python reauth_schwab.py")
        _new_sign_in(token, "fresh")
        assert _work(sweep, schwab_client, 1)
    finally:
        schwab.close()
    assert _asked(schwab) and sweep.waiting is None


#: another process with the token file open, as a reader without its lock has it (the console's
#: token status): "held" once it is open, closed when the test sends a line
_READER = """
import sys
with open(sys.argv[1], "rb"):
    print("held", flush=True)
    sys.stdin.readline()
"""


def test_a_sign_in_saved_while_another_process_reads_the_old_one_lands_whole(tmp_path, caplog):
    """A new sign-in saved while another process has the token file open.

    On Windows, as production runs, the file cannot be replaced while it is open (a sharing
    violation): the same write is tried again, each time logged, and lands once the reader
    closes it; where the system lets an open file be replaced it lands at once. The file then
    holds the new sign-in, whole, and the reader read the old one whole.
    """
    token = tmp_path / "schwab_token.json"
    _new_sign_in(token, "old")
    saving = threading.Thread(target=_new_sign_in, args=(token, "new"))

    def blocked() -> bool:
        return any(r.getMessage().startswith("token replace blocked") for r in caplog.records)

    with subprocess.Popen(
        [sys.executable, "-c", _READER, str(token)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as reader:
        assert reader.stdout.readline().strip() == "held"
        with caplog.at_level(logging.WARNING, logger=sc.log.name):
            saving.start()
            asyncio.run(until(lambda: blocked() or not saving.is_alive(), 10))
            reader.communicate("\n")
            saving.join(10)
    assert not saving.is_alive()
    assert json.loads(token.read_text(encoding="utf-8"))["token"]["access_token"] == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["schwab_token.json"], "no temp file left"


def test_a_token_file_that_is_not_utf8_text_is_reported_unreadable(tmp_path):
    """A token file saved as UTF-16 (as Windows PowerShell 5.1's Out-File saves text).

    The daemon's builder reads it as a token file that is not valid, a client it cannot build
    (the sweep waits for one: the test above), never an error that ends the sweep's thread.
    """
    token = tmp_path / "schwab_token.json"
    token.write_bytes(json.dumps(_FRESH).encode("utf-16"))
    got = sc.inspect_token_file(str(token))
    assert (
        got.file_exists
        and not got.json_valid
        and got.message.startswith("Invalid JSON in token file")
    )


@pytest.mark.parametrize(
    "held",
    [
        "{not a sign-in",
        "[]",
        '{"token": "x", "creation_timestamp": 1}',
        '{"token": {}, "creation_timestamp": 1}',
    ],
    ids=["not JSON", "JSON, not a sign-in", "a token that is not one", "an empty token"],
)
def test_a_token_file_that_cannot_be_read_is_logged_once_and_the_sweep_goes_on(
    tmp_path, caplog, held
):
    """Schwab having refused the sign-in, the token file then holding what is not a sign-in.

    The chain sweep keeps looking (each look reads the file for a new sign-in), it is logged
    once, and the sign-in saved after it is taken.
    """
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        with pytest.raises(sc.SignInRefusedError):
            client.get_option_expiration_chain("SPY")
        token = _saved_whole(tmp_path, held)
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING, logger=sc.log.name):
            assert _work(sweep, lambda: client, 20), "the sweep's thread ended"
            assert _work(sweep, lambda: client, 20)
        assert len([r for r in caplog.records if "holds no sign-in" in r.getMessage()]) == 1
        _new_sign_in(token, "fresh")
        client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert _asked(schwab) == [(EXPIRATIONS, "Bearer fresh")]


def test_a_sign_in_a_client_cannot_use_is_not_taken(tmp_path, caplog):
    """A token file with an access and a refresh token but no expiry is not a usable sign-in.

    It is not a sign-in the builder can use. The sweep logs it once, does not take it, and takes
    the sign-in saved after.
    """
    held = '{"token": {"access_token": "a", "refresh_token": "r"}, "creation_timestamp": 1}'
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        with pytest.raises(sc.SignInRefusedError):
            client.get_option_expiration_chain("SPY")
        token = _saved_whole(tmp_path, held)
        assert "expires_at" in sc.sign_in_problem(sc.inspect_token_file(str(token)), str(token))
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING, logger=sc.log.name):
            assert _work(sweep, lambda: client, 20), "the sweep's thread ended"
            assert _work(sweep, lambda: client, 20)
        assert len([r for r in caplog.records if "holds no sign-in" in r.getMessage()]) == 1
        with pytest.raises(sc.SignInRefusedError):
            client.get_option_expiration_chain("SPY")
        _new_sign_in(token, "fresh")
        client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert _asked(schwab) == [(EXPIRATIONS, "Bearer fresh")]
