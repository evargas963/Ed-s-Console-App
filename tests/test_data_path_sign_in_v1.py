"""The daemon's Schwab sign-in, whose one record is the token file: a sign-in saved there is taken
without a restart (while Schwab refuses the old one, at the next request; while signed in, when
the next refresh is due); once Schwab refuses the sign-in, nothing more is sent to Schwab until a
new one is saved.

Through the real schwab-py client (schwab_client.client_from_token_file_atomic) against the local
stand-in for Schwab's host (tests/schwab_rest_standin.py: its real data and stand-ins are named
there, Schwab's refusal REFUSED among them), and the daemon's real chain sweep (ChainSweep.work) on
a fixed clock: 2026-10-07 20:00 ET, after that day's option close, a day Schwab's /markets answer
was captured for. STAND-INS (named): the token files; the transport the client a test builds is
given (to the stand-in's host), named in that test.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import pytest

import schwab_client as sc
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.capture import CaptureWriter
from calibration import complete_chain_capture as cch
from tests.schwab_rest_standin import EXPIRATIONS, TOKEN, LocalSchwab, _ToLocal
from time_et import ET

_AFTER_THE_CLOSE = datetime(2026, 10, 7, 20, 0, tzinfo=ET).timestamp()


def _posts(schwab: LocalSchwab) -> int:
    return sum(1 for r in schwab.requests if r[0] == TOKEN)


def _asked(schwab: LocalSchwab) -> list:
    """Each data request that reached Schwab: (path, the token it carried)."""
    return [(r[0], r[5]) for r in schwab.requests if r[0] != TOKEN]


def _every_request(client) -> list:
    """Each kind of request the daemon sends Schwab, as it sends it: the stream's login first
    asks for the user's preferences (schwab-py StreamClient.login)."""
    return [lambda: client.get_user_preferences(),
            lambda: client.get_option_expiration_chain("SPY"),
            lambda: sc.safe_get_chain(client, "SPY", strike_range="ALL"),
            lambda: sc.safe_get_quotes(client, ["SPY"]),
            lambda: client.get_price_history_every_minute("SPY"),
            lambda: client.get_market_hours([client.MarketHours.Market.EQUITY])]


def _new_sign_in(token_path, access: str) -> int:
    """A new sign-in saved to the token file by the writer of every sign-in python
    reauth_schwab.py saves (sc.write_token_file_atomically): its creation time."""
    created = int(time.time()) + 1
    sc.write_token_file_atomically(str(token_path), {"creation_timestamp": created, "token": {
        "access_token": access, "refresh_token": "r2", "token_type": "Bearer", "expires_in": 1800,
        "expires_at": int(time.time() + 3600)}})
    return created


class _Turns(threading.Event):
    """The sweep's stop event, set after `n` of the sweep's idle waits; each wait returns at once
    (the sweep's second between looks, not waited out)."""

    def __init__(self, n: int):
        super().__init__()
        self.left = n

    def wait(self, timeout=None):
        self.left -= 1
        if self.left <= 0:
            self.set()
        return self.is_set()


def _sweep(tmp_path):
    sqlite3.connect(tmp_path / "ed_console.db").close()
    return cch.ChainSweep(tmp_path / "ed_console.db", ["SPY"], lambda topic, msg: None,
                          clock=lambda: _AFTER_THE_CLOSE,
                          failures=CaptureWriter(tmp_path / "stream_capture.db"), streamed=lambda symbol: None)


def _work(sweep, schwab_client, turns: int) -> bool:
    """The sweep's thread, stopped after `turns` idle looks; whether it ended within 20 s by that
    stop (not by an exception ending the thread)."""
    stop = _Turns(turns)
    worker = threading.Thread(target=sweep.work, args=(schwab_client, stop), daemon=True)
    worker.start()
    worker.join(20)
    return stop.is_set() and not worker.is_alive()


def test_once_schwab_refuses_the_sign_in_no_request_of_any_kind_reaches_schwab(tmp_path):
    """The token in its refresh window and Schwab refusing it: the first request's refresh is
    refused (SignInRefused), and every kind of request the daemon sends after it, the stream's
    login among them, raises the same, sending nothing: one POST in all, no data request. Each
    refusal raised is its own, carrying only its own request's frames (one held and raised again
    would grow its traceback by every request's frames, for as long as Schwab refuses)."""
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        raised = []
        for request in _every_request(client) * 3:
            with pytest.raises(sc.SignInRefused, match="Refresh token is invalid") as r:
                request()
            raised.append(r.value)
        assert not client.session.signed_in()
    finally:
        schwab.close()
    assert (_posts(schwab), _asked(schwab)) == (1, [])
    depth = [len(traceback.extract_tb(e.__traceback__)) for e in raised]
    assert len({id(e) for e in raised}) == len(raised) and depth[6:12] == depth[12:] == depth[:6]


def test_a_new_sign_in_saved_after_the_refusal_is_taken_without_a_restart(tmp_path):
    """After the refusal, a new sign-in saved to the token file: the next request carries its
    token, and the client's token and creation time (the streamer's login reads them) are its."""
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        with pytest.raises(sc.SignInRefused):
            client.get_option_expiration_chain("SPY")
        created = _new_sign_in(tmp_path / "schwab_token.json", "fresh")
        resp = client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert resp.status_code == 200 and _asked(schwab) == [(EXPIRATIONS, "Bearer fresh")]
    assert client.token_metadata.token["access_token"] == "fresh"
    assert client.token_metadata.creation_timestamp == created


def test_a_new_sign_in_saved_while_signed_in_is_taken_when_the_refresh_is_due(tmp_path):
    """A sign-in saved while the daemon still holds the old one: while the old token is not yet due
    for its refresh, requests carry it; once it is due, the new sign-in is taken in place of the
    refresh: no token request, the request carries the new token, the token file still holds it."""
    schwab = LocalSchwab()
    try:
        client = schwab.client(tmp_path)                   # the old sign-in, an hour from expiry
        token = tmp_path / "schwab_token.json"
        created = _new_sign_in(token, "fresh")
        client.get_option_expiration_chain("SPY")
        client.session.token["expires_at"] = int(time.time()) + 100   # the old token now in its refresh window
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
import schwab_client as sc
path, payload = sys.argv[2], json.loads(sys.argv[3])
with sc.token_file_lock(path):
    seen = os.stat(path)
    print("held", flush=True)
    time.sleep(0.3)
    now = os.stat(path)
    sc.write_token_file_atomically(path, payload)
sys.exit(3 if (now.st_mtime_ns, now.st_ino) != (seen.st_mtime_ns, seen.st_ino) else 0)
"""
_FRESH = {"creation_timestamp": int(time.time()) + 1, "token": {
    "access_token": "fresh", "refresh_token": "r2", "token_type": "Bearer", "expires_in": 1800,
    "expires_at": int(time.time() + 3600)}}


def _saving(token) -> subprocess.Popen:
    """The other process, holding the token file's lock once this returns, saving a sign-in newer
    than the one the file holds."""
    newer = {**_FRESH, "creation_timestamp": json.loads(token.read_text())["creation_timestamp"] + 1}
    saver = subprocess.Popen([sys.executable, "-c", _SAVER, str(Path(__file__).resolve().parent.parent),
                              str(token), json.dumps(newer)], stdout=subprocess.PIPE, text=True)
    assert saver.stdout.readline().strip() == "held"
    return saver


def test_a_refresh_due_while_a_sign_in_is_being_saved_takes_it_and_never_writes_over_it(tmp_path):
    """A refresh due while another process is saving a sign-in (holding the token file's lock):
    nothing writes the file while it is held, and the session takes the saved sign-in instead of
    refreshing the old one: no token request, the request carries the new sign-in's token."""
    schwab = LocalSchwab()
    token = tmp_path / "schwab_token.json"
    try:
        client = schwab.client(tmp_path, 100)              # the old sign-in, in its refresh window
        saver = _saving(token)
        client.get_option_expiration_chain("SPY")
        assert saver.wait(30) == 0, "the token file was written while a sign-in being saved held it"
    finally:
        schwab.close()
    assert json.loads(token.read_text())["token"]["access_token"] == "fresh"
    assert (_posts(schwab), _asked(schwab)) == (0, [(EXPIRATIONS, "Bearer fresh")])


def test_a_client_built_while_a_sign_in_is_being_saved_holds_that_sign_in(tmp_path):
    """The daemon's client built while another process is saving a sign-in (holding the token
    file's lock): the client is built from the saved sign-in, never from the one it replaces, and
    its first request carries it."""
    schwab = LocalSchwab()
    token = tmp_path / "schwab_token.json"
    try:
        schwab.client(tmp_path)                            # the old sign-in, saved before
        saver = _saving(token)
        client = sc.client_from_token_file_atomic(str(token), "k", "s",
                                                  transport=_ToLocal(schwab.server.server_address[1]))
        held = client.token_metadata.token["access_token"]
        assert saver.wait(30) == 0
        client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert held == "fresh"
    assert _asked(schwab) == [(EXPIRATIONS, "Bearer fresh")]


def test_a_sign_in_in_progress_removes_the_token_file_and_nothing_breaks(tmp_path):
    """python reauth_schwab.py removes the token file before it saves the new sign-in: while it
    is not there the session holds no sign-in and raises nothing else; once saved, it is taken."""
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        token = tmp_path / "schwab_token.json"
        with pytest.raises(sc.SignInRefused):
            client.get_option_expiration_chain("SPY")
        token.unlink()
        assert not client.session.signed_in()
        with pytest.raises(sc.SignInRefused):
            client.get_option_expiration_chain("SPY")
        _new_sign_in(token, "fresh")
        assert client.session.signed_in()
    finally:
        schwab.close()
    assert _posts(schwab) == 1


def test_schwabs_edge_page_at_the_token_endpoint_is_not_a_refusal(tmp_path):
    """Schwab's edge answering the refresh with its 403 page: the request fails and the next one
    asks again; only Schwab's answer refusing the sign-in stops the requests."""
    schwab = LocalSchwab()
    schwab.token = "edge"
    try:
        client = schwab.client(tmp_path, 100)
        for _ in range(2):
            with pytest.raises(Exception) as raised:
                client.get_option_expiration_chain("SPY")
            assert not isinstance(raised.value, sc.SignInRefused)
        assert client.session.signed_in()
    finally:
        schwab.close()
    assert _posts(schwab) == 2


def test_a_token_endpoint_that_cannot_be_reached_is_not_a_refusal(tmp_path):
    """Schwab's host not answering at all (a network failure: its port closed): the request fails,
    the session still holds its sign-in, and the next request tries again."""
    schwab = LocalSchwab()
    client = schwab.client(tmp_path, 100)
    schwab.close()
    schwab.server.server_close()
    for _ in range(2):
        with pytest.raises(Exception) as raised:
            client.get_option_expiration_chain("SPY")
        assert not isinstance(raised.value, sc.SignInRefused)
    assert client.session.signed_in()


def test_the_chain_sweep_asks_nothing_while_signed_out_and_goes_on_after_a_new_sign_in(tmp_path, caplog):
    """The daemon's chain sweep over SPY while Schwab refuses the sign-in: its first round meets
    the refusal (one POST), then it only looks, 50 times, sending nothing and logging nothing more
    (a round per look would log every request's failure); a new sign-in saved, it asks Schwab."""
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING):
            assert _work(sweep, lambda: client, 50), "the sweep never stopped to look: it kept asking"
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


def test_the_chain_sweep_waits_for_a_client_it_cannot_build_and_goes_on_once_built(tmp_path, caplog):
    """The daemon's client holder (capture.one_schwab_client, the real one) while its client
    cannot be built: the real builder's answer for a token file that is not there
    (schwab_client.build_client_from_token), which the holder raises as ConnectionError and
    builds again on the next ask. The sweep keeps looking, logs it once and asks Schwab for
    nothing; once the token file is saved and the client built, it asks. STAND-IN (named): the
    built client is the real builder of the client (client_from_token_file_atomic) on the
    stand-in's transport, which build_client_from_token takes none of."""
    schwab = LocalSchwab()
    token = tmp_path / "schwab_token.json"

    def build():
        if not token.exists():
            return sc.build_client_from_token(str(token), "LiveLookingKey", "LiveLookingSecret")
        return sc.SchwabClientState(ok=True, message="", client=sc.client_from_token_file_atomic(
            str(token), "k", "s", transport=_ToLocal(schwab.server.server_address[1])))
    schwab_client = capture.one_schwab_client(build)
    try:
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING):
            assert _work(sweep, schwab_client, 20), "the sweep ended or never looked again"
        waits = [r.getMessage() for r in caplog.records]
        assert len(waits) == 1 and waits[0].startswith("chain sweep waits for the daemon's Schwab client: no Schwab client (")
        assert schwab.requests == []
        _new_sign_in(token, "fresh")
        assert _work(sweep, schwab_client, 1)
    finally:
        schwab.close()
    assert _asked(schwab)


def test_a_token_file_that_is_not_utf8_text_is_reported_unreadable(tmp_path):
    """A token file saved as UTF-16 (as Windows PowerShell 5.1's Out-File saves text): the daemon's
    builder reads it as a token file that is not valid, a client it cannot build (the sweep waits
    for one: the test above), never an error that ends the sweep's thread."""
    token = tmp_path / "schwab_token.json"
    token.write_bytes(json.dumps(_FRESH).encode("utf-16"))
    got = sc.inspect_token_file(str(token))
    assert got.file_exists and not got.json_valid and got.message.startswith("Invalid JSON in token file")


@pytest.mark.parametrize("held", ["{not a sign-in", "[]", '{"token": "x", "creation_timestamp": 1}',
                                  '{"token": {}, "creation_timestamp": 1}'],
                         ids=["not JSON", "JSON, not a sign-in", "a token that is not one", "an empty token"])
def test_a_token_file_that_cannot_be_read_is_logged_once_and_the_sweep_goes_on(tmp_path, caplog, held):
    """Schwab having refused the sign-in, the token file then holding what is not a sign-in: the
    chain sweep keeps looking (each look reads the file for a new sign-in), it is logged once,
    and the sign-in saved after it is taken."""
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        with pytest.raises(sc.SignInRefused):
            client.get_option_expiration_chain("SPY")
        token = tmp_path / "schwab_token.json"
        bad = tmp_path / "not_a_sign_in.json"
        bad.write_text(held)
        bad.replace(token)                                  # saved whole, as every writer saves
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
    """A token file with an access token and a refresh token but no expiry is not a sign-in the
    builder can use. The sweep logs it once, does not take it, and takes the sign-in saved after."""
    held = '{"token": {"access_token": "a", "refresh_token": "r"}, "creation_timestamp": 1}'
    schwab = LocalSchwab()
    schwab.token = "refuses"
    try:
        client = schwab.client(tmp_path, 100)
        with pytest.raises(sc.SignInRefused):
            client.get_option_expiration_chain("SPY")
        token = tmp_path / "schwab_token.json"
        bad = tmp_path / "not_a_sign_in.json"
        bad.write_text(held)
        bad.replace(token)
        assert "expires_at" in sc.sign_in_problem(sc.inspect_token_file(str(token)), str(token))
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING, logger=sc.log.name):
            assert _work(sweep, lambda: client, 20), "the sweep's thread ended"
            assert _work(sweep, lambda: client, 20)
        assert len([r for r in caplog.records if "holds no sign-in" in r.getMessage()]) == 1
        with pytest.raises(sc.SignInRefused):
            client.get_option_expiration_chain("SPY")
        _new_sign_in(token, "fresh")
        client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert _asked(schwab) == [(EXPIRATIONS, "Bearer fresh")]
