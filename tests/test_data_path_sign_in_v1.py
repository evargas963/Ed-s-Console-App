"""The daemon's Schwab sign-in, whose one record is the token file: a sign-in saved there is taken
before the next request, without a restart; once Schwab refuses the sign-in, nothing more is sent
to Schwab until a new one is saved.

Through the real schwab-py client (schwab_client.client_from_token_file_atomic) against the local
stand-in for Schwab's host (tests/schwab_rest_standin.py: its real data and stand-ins are named
there, Schwab's refusal REFUSED among them), and the daemon's real chain sweep (ChainSweep.work) on
a fixed clock: 2026-10-07 20:00 ET, after that day's option close, a day Schwab's /markets answer
was captured for. STAND-INS (named): the token files.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import traceback
from datetime import datetime

import pytest

import schwab_client as sc
from app.market_data.schwab.streaming.capture import CaptureWriter
from calibration import complete_chain_capture as cch
from tests.schwab_rest_standin import CHAIN, EXPIRATIONS, TOKEN, LocalSchwab
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
    """A new sign-in saved to the token file, as reauth_schwab.py saves one (whole, by
    os.replace): its creation time."""
    created = int(time.time()) + 1
    saved = token_path.with_suffix(".new")
    saved.write_text(json.dumps({"creation_timestamp": created, "token": {
        "access_token": access, "refresh_token": "r2", "token_type": "Bearer", "expires_in": 1800,
        "expires_at": int(time.time() + 3600)}}))
    saved.replace(token_path)
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


def test_a_new_sign_in_saved_while_signed_in_is_taken_and_never_overwritten(tmp_path):
    """A sign-in saved while the daemon still holds the old one (before it would be refused): the
    next request carries the new token, nothing is refreshed with the old one, and the token file
    still holds the new sign-in."""
    schwab = LocalSchwab()
    try:
        client = schwab.client(tmp_path, 100)              # the old sign-in, in its refresh window
        token = tmp_path / "schwab_token.json"
        created = _new_sign_in(token, "fresh")
        resp = client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert resp.status_code == 200 and (_posts(schwab), _asked(schwab)) == (0, [(EXPIRATIONS, "Bearer fresh")])
    saved = json.loads(token.read_text())
    assert saved["token"]["access_token"] == "fresh" and saved["creation_timestamp"] == created


def test_a_sign_in_saved_while_the_refresh_is_asked_is_taken_and_not_overwritten(tmp_path):
    """python reauth_schwab.py saving a new sign-in while the daemon's refresh is on its way to
    Schwab: the refreshed token is not written over it; the token file keeps the new sign-in and
    the next request carries its token."""
    schwab = LocalSchwab()
    token = tmp_path / "schwab_token.json"
    schwab.answering = lambda: _new_sign_in(token, "fresh")
    try:
        client = schwab.client(tmp_path, 100)              # the old sign-in, in its refresh window
        client.get_option_expiration_chain("SPY")          # the refresh, and the new sign-in saved
        schwab.answering = lambda: None
        client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert json.loads(token.read_text())["token"]["access_token"] == "fresh"
    assert _posts(schwab) == 1 and _asked(schwab)[-1] == (EXPIRATIONS, "Bearer fresh")


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
    """The daemon's client cannot be built (no usable token file: capture.one_schwab_client
    raises ConnectionError and builds again on the next ask): the sweep keeps looking, logs it
    once and asks Schwab for nothing; built, it asks."""
    schwab = LocalSchwab()
    built: list = []

    def schwab_client():
        if not built:
            raise ConnectionError("no Schwab client (token file missing)")
        return built[0]
    try:
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING):
            assert _work(sweep, schwab_client, 20), "the sweep ended or never looked again"
        assert [r.getMessage() for r in caplog.records] == [
            "chain sweep waits for the daemon's Schwab client: no Schwab client (token file missing)"]
        assert schwab.requests == []
        built.append(schwab.client(tmp_path))
        assert _work(sweep, schwab_client, 1)
    finally:
        schwab.close()
    assert _asked(schwab)


def test_a_sweep_whose_every_chain_fails_waits_its_second_before_asking_again(tmp_path):
    """Signed in, after the close, Schwab answering every quotes request 502: each round delivers
    nothing, and the sweep waits its second before the next (a round asked again at once is a
    request storm for as long as Schwab fails); 5 looks, 5 rounds."""
    schwab = LocalSchwab()
    schwab.quotes_status = 502
    try:
        client = schwab.client(tmp_path)
        assert _work(_sweep(tmp_path), lambda: client, 5), "the sweep asked again at once, never stopping to look"
    finally:
        schwab.close()
    assert sum(1 for r in schwab.requests if r[0] == EXPIRATIONS) <= 1
    assert sum(1 for r in schwab.requests if r[0] == CHAIN) == 5           # each round: its one listed expiry


def test_a_token_file_that_cannot_be_read_is_logged_once_and_the_sweep_goes_on(tmp_path, caplog):
    """The token file holding what is not a sign-in (not JSON): the chain sweep keeps looking, it
    is logged once, and the sign-in saved after it is taken."""
    schwab = LocalSchwab()
    try:
        client = schwab.client(tmp_path)
        token = tmp_path / "schwab_token.json"
        token.write_text("{not a sign-in")
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING, logger=sc.log.name):
            assert _work(sweep, lambda: client, 20), "the sweep's thread ended"
            assert _work(sweep, lambda: client, 20)
        assert len([r for r in caplog.records if "could not be read" in r.getMessage()]) == 1
        _new_sign_in(token, "fresh")
        client.get_option_expiration_chain("SPY")
    finally:
        schwab.close()
    assert _asked(schwab)[-1] == (EXPIRATIONS, "Bearer fresh")
