"""The Schwab sign-in's state, pushed to the page header with the session (/api/changes).

The warning used to ride inside /api/terrain's staleness fields, which no screen read: the
sign-in ended with no notice on the page."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

import server
from time_et import CT

#: stand-in (named): a sign-in made Wednesday 2026-09-23 at 2:36 PM Central
MADE = datetime(2026, 9, 23, 14, 36, tzinfo=CT).timestamp()
DAY = 86400.0
ENDS = "Wed 09/30 02:36 PM CT"
REMEDY = "run: python reauth_schwab.py --manual"


def test_the_sign_in_warns_from_day_five_is_red_from_day_six_and_names_when_it_ends():
    at = lambda days: server.schwab_sign_in_status(MADE, MADE + days * DAY)   # noqa: E731
    assert at(4.99) == {"urgency": "ok", "expires": ENDS, "note": ""}
    assert at(5.0) == {"urgency": "warn", "expires": ENDS, "note": f"Schwab sign-in ends {ENDS}; {REMEDY}"}
    assert at(6.0) == {"urgency": "red", "expires": ENDS, "note": f"Schwab sign-in ends {ENDS}; {REMEDY}"}
    assert at(7.0) == {"urgency": "red", "expires": ENDS, "note": f"Schwab sign-in ended {ENDS}; {REMEDY}"}


def test_an_unreadable_token_file_is_unknown_never_ok():
    s = server.schwab_sign_in_status(None, MADE)
    assert s["urgency"] == "unknown" and s["expires"] is None and "unreadable" in s["note"]


def test_the_console_pushes_the_sign_in_with_the_session(monkeypatch):
    """The page is told on connect (and with every status push), whatever it is showing."""
    monkeypatch.setattr(server, "_schwab_token_creation_ts", lambda: MADE)
    monkeypatch.setattr(server.time, "time", lambda: MADE + 6.5 * DAY)

    async def first_frame():
        resp = await server.get_changes(ticker="SPY", view="test-view")
        try:
            return await resp.body_iterator.__anext__()
        finally:
            await resp.body_iterator.aclose()
    frame = asyncio.run(first_frame())
    events = dict(block.split("\ndata: ", 1) for block in frame.strip().split("\n\n"))
    assert set(events) == {"event: session", "event: sign_in"}
    assert json.loads(events["event: sign_in"]) == {
        "urgency": "red", "expires": ENDS, "note": f"Schwab sign-in ends {ENDS}; {REMEDY}"}
    # the levels' staleness no longer carries it
    assert not [k for k in server.terrain_staleness(None, "SPY") if "token" in k]


def test_the_status_keeps_its_own_clock_while_changes_keep_coming(monkeypatch):
    """Measured on the running app 2026-09-30 11:43-12:02 ET (TSLA): 1,238 pushes in 1,124 s,
    never 5 s apart, and the session was sent once, on connect: the status was sent only after
    5 s with no change. Here the ticker changes without a pause, the session turns from RTH to
    After-Hours and the sign-in from warn to red, and the page is told of both. Stand-ins
    (named): the cadences, shortened; the session label and the clock the sign-in is judged at."""
    import push_changes
    monkeypatch.setattr(push_changes, "_clients", {})
    monkeypatch.setattr(push_changes, "_loop", None)
    monkeypatch.setattr(server, "CHANGES_SESSION_SEC", 0.2)
    monkeypatch.setattr(server, "CHANGES_PUSH_MIN_SEC", 0.02)
    monkeypatch.setattr(server, "_schwab_token_creation_ts", lambda: MADE)
    state = {"session": "RTH", "now": MADE + 5.5 * DAY}
    monkeypatch.setattr(server, "session_label", lambda now: state["session"])
    monkeypatch.setattr(server.time, "time", lambda: state["now"])

    async def listen():
        loop = asyncio.get_running_loop()
        push_changes.bind(loop)
        frames = (await server.get_changes(ticker="SPY", view="test-view")).body_iterator
        seen, end = [], loop.time() + 1.2
        try:
            while loop.time() < end:
                push_changes.changed("SPY", push_changes.FLOW)       # a change is always waiting
                seen.append((loop.time(), await frames.__anext__()))
                if loop.time() > end - 0.6:
                    state.update(session="After-Hours", now=MADE + 6.5 * DAY)
        finally:
            await frames.aclose()
        return seen
    seen = asyncio.run(listen())
    flow = [t for t, f in seen if f.startswith("event: flow")]
    status = [f for _, f in seen if f.startswith("event: session")]
    assert len(flow) >= 10 and max(b - a for a, b in zip(flow, flow[1:])) < 0.2, "the changes never paused"
    assert len(status) >= 4, "the status was pushed on its own clock"
    assert status[0].startswith("event: session\ndata: RTH\n") and '"urgency": "warn"' in status[0]
    assert status[-1].startswith("event: session\ndata: After-Hours\n") and '"urgency": "red"' in status[-1]
