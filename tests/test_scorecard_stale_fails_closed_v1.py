"""RC-78: the coach scorecard fails closed on STALE, not only on ABSENT.

The endpoint's docstring claimed it "never" served a stale rate while it was serving hold-rates
111.6 hours (4.6 days) old under the coach's "Measured on our own history". It validated that the
report PARSED, never that it was RECENT — age was displayed as a footnote instead of being a
precondition to serve, and a date printed beside a number does not stop the number being read.

The budget counts TRADING days on purpose: a wall-clock budget would condemn every scorecard each
weekend and teach the operator to ignore the warning.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

import server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "static" / "chart.html"


def _age(s: str | None) -> int | None:
    return server.scorecard_trading_day_age(s)


def test_weekend_does_not_age_a_scorecard():
    """Friday's run is still the latest run on Monday — a weekend adds ZERO trading days.

    REPAIRED 2026-07-28: the first version hard-coded 2026-07-24 and asserted == 1, which was
    only true ON Monday 07-27 — a date-frozen test rots one day later (it failed Tuesday at
    HEAD, proven by swap-test). The invariant is calendar-relative: the age of the most recent
    Friday equals the count of trading days after it, and the Saturday/Sunday between never
    add to it. Computed against the SAME trading-day authority the function uses, over a
    window that always contains a weekend."""
    import datetime
    from time_et import is_trading_day_et
    today = datetime.datetime.now(server.ET_ZONE).date() if hasattr(server, "ET_ZONE") else (
        datetime.datetime.now(datetime.timezone.utc).astimezone(
            __import__("zoneinfo").ZoneInfo("America/New_York")).date())
    # walk back to the most recent Friday strictly before today
    d = today - datetime.timedelta(days=1)
    while d.weekday() != 4:
        d -= datetime.timedelta(days=1)
    expected = sum(1 for k in range(1, (today - d).days + 1)
                   if is_trading_day_et(d + datetime.timedelta(days=k)))
    got = _age(d.isoformat())
    assert got == expected, (
        f"Friday {d} -> today {today}: expected {expected} trading day(s), got {got} — "
        f"the weekend between them must add nothing"
    )
    assert (today - d).days > expected, "the window must actually contain non-trading days"


def test_unusable_stamps_are_never_fresh():
    """Absence of a readable age must not resolve to age zero."""
    for bad in (None, "", "not-a-date", "2099-01-01"):
        assert _age(bad) is None, f"{bad!r} produced a usable age"


def test_stale_report_withholds_the_numbers_and_says_why():
    """The failure the operator actually suffers: a present, parseable, OUT-OF-DATE report."""
    body = json.loads(bytes(server.get_terrain_scorecard().body).decode())
    if not body:
        return                                  # no report on disk — covered by the absent case
    if body.get("stale"):
        assert "wall_hold_trusted" not in body, "stale hold-rates were served anyway"
        assert "weighting_scorecard" not in body, "stale weighting numbers were served anyway"
        assert body.get("stale_reason"), "withheld the numbers without saying why"
        assert body.get("age_trading_days") != 0
    else:
        assert body.get("age_trading_days") is not None
        assert body["age_trading_days"] <= server.SCORECARD_MAX_TRADING_DAY_AGE


def test_budget_is_one_trading_day():
    """A daily job older than one session means a run was MISSED — exactly when it must stop
    speaking. If this constant grows, the reason must grow with it."""
    assert server.SCORECARD_MAX_TRADING_DAY_AGE == 1


def test_client_refuses_a_stale_scorecard_and_states_the_reason():
    src = CHART.read_text(encoding="utf-8")
    assert "sc.generated_utc && !sc.stale" in src, (
        "the client accepts any parseable scorecard again — a stale one would render as measured"
    )
    assert "scorecardStale" in src and "stale_reason" in src, (
        "staleness is not surfaced, so the coach silently goes quiet with no explanation"
    )


# ── RC-108: Schwab token death is calendar-predictable; the console must warn BEFORE it ──────

def test_schwab_token_countdown_urgency_tiers():
    """7-day hard limit: quiet before day 5, warn at 5, red at 6, honest unknown on no file."""
    import time
    now = time.time()
    ok = server.schwab_token_countdown(now - 2 * 86400)
    assert ok["schwab_token_urgency"] == "ok" and ok["schwab_token_note"] == ""
    warn = server.schwab_token_countdown(now - 5.5 * 86400)
    assert warn["schwab_token_urgency"] == "warn"
    assert "reauth_schwab.py" in warn["schwab_token_note"], "the warning must carry the remedy"
    red = server.schwab_token_countdown(now - 6.5 * 86400)
    assert red["schwab_token_urgency"] == "red"
    assert "reauth_schwab.py" in red["schwab_token_note"]
    unknown = server.schwab_token_countdown(None)
    assert unknown["schwab_token_urgency"] == "unknown"
    assert unknown["schwab_token_age_days"] is None, "an unreadable file must never fake an age"


def test_terrain_staleness_carries_the_token_countdown():
    """The countdown rides the SAME payload the levels ride — one faucet, every terrain reply,
    including the no-snapshot stub (which is exactly the state a dead token produces)."""
    stub = server.terrain_staleness(None)
    assert "schwab_token_urgency" in stub and "schwab_token_note" in stub
    import time
    live = server.terrain_staleness(time.time())
    assert "schwab_token_urgency" in live


def test_visible_token_chip_binds_the_urgency_field():
    """Surface-bound (RC-106 contract): #sb-token-warn must be painted FROM schwab_token_urgency
    by one writer, and both terrain receive sites must call that writer."""
    import re
    src = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="sb-token-warn"' in src, "the visible chip markup is gone"
    i = src.find("function edPaintTokenWarn")
    assert i > 0, "the one token-chip writer is gone"
    body = re.sub(r"//.*$", "", src[i:i + 1600], flags=re.M)
    assert "sb-token-warn" in body and "schwab_token_urgency" in body
    assert src.count("edPaintTokenWarn(") >= 3, (
        "both terrain receive sites must feed the chip (definition + 2 call sites)"
    )


# ── RC-146: a deliberate pause must not be reported as a malfunction, and a pre-open ─────────
# ── snapshot must not be reported as a market fact. ──────────────────────────────────────────

def test_morning_window_skip_is_recorded_by_the_producer():
    """The 09:30-10:00 ET sentinel-only filter was a SILENT list comprehension: nothing recorded
    that MSFT/NVDA/AAPL were dropped on purpose, so every reader downstream had to guess. Drive
    the real recorder and prove a reason survives exactly as long as the pause does."""
    try:
        server._note_terrain_skip(["MSFT", "nvda"], "paused until 10:00 ET")
        assert server.terrain_skip_reason("MSFT") == "paused until 10:00 ET"
        assert server.terrain_skip_reason("NVDA") == "paused until 10:00 ET", "case must not matter"
        assert server.terrain_skip_reason("SPY") == "", "a refreshed ticker carries no skip reason"
        assert server.terrain_skip_reason(None) == "", "absent ticker fails closed to no reason"
    finally:
        server._clear_terrain_skips()
    assert server.terrain_skip_reason("MSFT") == "", (
        "a skip reason outlived the pause — the panel would keep telling the operator to wait"
    )


def test_terrain_staleness_prefers_the_producers_reason_over_the_clock():
    """RC-146 root: age alone cannot tell a deliberate pause from a broken loop, and answering
    'inside its window but not producing' for a scheduler working as designed sent the operator
    hunting a bug that did not exist."""
    import time
    old = time.time() - (server.TERRAIN_STALE_AFTER_SEC + 600.0)
    try:
        blind = server.terrain_staleness(old, "MSFT")
        assert blind["levels_stale"] is True
        assert blind["levels_paused_on_purpose"] is False, (
            "no recorded skip must never be dressed up as a deliberate pause"
        )
        server._note_terrain_skip(["MSFT"], "the morning wide-chain capture holds the chain slots")
        told = server.terrain_staleness(old, "MSFT")
        assert told["levels_paused_on_purpose"] is True
        assert "chain slots" in told["levels_stale_reason"], (
            "the producer's own reason must reach the payload, not a clock-derived guess"
        )
        assert "not producing" not in told["levels_stale_reason"]
        # a ticker that was NOT skipped keeps the honest clock-only reason
        other = server.terrain_staleness(old, "SPY")
        assert other["levels_paused_on_purpose"] is False
    finally:
        server._clear_terrain_skips()


def test_recorded_failure_reaches_the_payload_once_a_snapshot_exists():
    """RC-147: `_terrain_refresh_last_error` had exactly ONE reader — the not-ready branch of
    /api/terrain, reachable only when NO snapshot exists. The instant a ticker had any cached
    snapshot that branch was dead, so a ticker failing every refresh reported error '' and a
    generic clock sentence ($SPX, 2,737 s old, chain_basis already degraded to dte<=120)."""
    import time
    old = time.time() - (server.TERRAIN_STALE_AFTER_SEC + 600.0)
    try:
        server._terrain_refresh_last_error["$SPX"] = "chain fetch failed (HTTP 400)"
        told = server.terrain_staleness(old, "$SPX")
        assert told["levels_failing"] is True
        assert "HTTP 400" in told["levels_stale_reason"], (
            "the recorded exception must reach the payload once a snapshot exists — this is the "
            "exact state in which it used to become unreachable"
        )
        assert told["levels_paused_on_purpose"] is False, "a failure is not a deliberate pause"
        # the no-snapshot branch must carry it too (RTY/XXT: rejected symbol, never computed)
        never = server.terrain_staleness(None, "$SPX")
        assert never["levels_failing"] is True and "HTTP 400" in never["levels_stale_reason"]
        # a DELIBERATE pause outranks a stale prior failure — it is why it is not refreshing now
        server._note_terrain_skip(["$SPX"], "paused until 10:00 ET")
        paused = server.terrain_staleness(old, "$SPX")
        assert paused["levels_paused_on_purpose"] is True
        assert paused["levels_failing"] is False
        assert "HTTP 400" not in paused["levels_stale_reason"]
    finally:
        server._terrain_refresh_last_error.pop("$SPX", None)
        server._clear_terrain_skips()
    clean = server.terrain_staleness(old, "$SPX")
    assert clean["levels_failing"] is False, "a cleared failure must not linger"


def test_skip_and_error_dicts_share_one_ticker_normalisation():
    """Two dicts describing the same ticker under two spellings is how a reader silently misses
    one. `_terrain_refresh_last_error` is keyed by ticker_storage_key (RC-126), so the skip dict
    must be too — SPX and $SPX are the same instrument to exactly one of them otherwise."""
    try:
        server._note_terrain_skip(["SPX"], "paused")
        assert server.terrain_skip_reason("$SPX") == "paused", (
            "the skip dict normalises differently from the error dict beside it"
        )
        assert server.terrain_skip_reason("SPX") == "paused"
    finally:
        server._clear_terrain_skips()


def test_hard_rejection_quarantines_and_stops_touching_the_gate():
    """RC-148: RTY/XXT were re-requested every ~60s all session for a symbol Schwab answers with
    HTTP 400 — two permanently-wasted slots per minute out of a 2-slot gate. Visibility alone is
    not a fix; the retry must actually STOP."""
    tk = "ZZTESTHARD"
    try:
        msg = "chain fetch failed (HTTP 400)"
        for i in range(server.TERRAIN_QUARANTINE_HARD_FAILS - 1):
            server._note_terrain_failure(tk, msg, "hard")
            assert not server._terrain_quarantine_blocks(tk), (
                f"quarantined after only {i + 1} failures — a transient blip must not evict a "
                f"real instrument"
            )
        server._note_terrain_failure(tk, msg, "hard")
        assert server._terrain_quarantine_blocks(tk) is True, "the retry storm was not stopped"
        st = server.terrain_quarantine_state(tk)
        assert st["permanent"] is True and st["failures"] >= server.TERRAIN_QUARANTINE_HARD_FAILS
        why = server.terrain_quarantine_reason(tk)
        assert "QUARANTINED" in why and "re-admit" in why, (
            "a hold with no stated way back is a deletion the operator never approved"
        )
        # the producer must refuse BEFORE spending any vendor budget, priority or not
        assert server._terrain_refresh_one(tk, priority=True) == "skip:quarantined"
        assert server._terrain_quarantine_skips.get(tk, 0) >= 1, "avoided fetches are not counted"
        # a permanent hold NEVER self-releases, however long you wait
        with server._terrain_quarantine_lock:
            server._terrain_quarantine[tk]["until_ts"] = 0.0
        assert server._terrain_quarantine_blocks(tk) is True
        # ...only the operator releases it
        out = server.terrain_quarantine_release(tk)
        assert out["released"] is True
        assert server._terrain_quarantine_blocks(tk) is False
    finally:
        server.terrain_quarantine_release(tk)


def test_soft_failure_backs_off_and_self_releases():
    """A timeout is the venue being busy, not the symbol being wrong. It must back off — and it
    must come back on its own, because a permanent hold on a healthy instrument is the more
    expensive mistake."""
    tk = "ZZTESTSOFT"
    try:
        for _ in range(server.TERRAIN_QUARANTINE_HARD_FAILS):
            server._note_terrain_failure(tk, "chain fetch failed (HTTP timeout)", "soft")
        st = server.terrain_quarantine_state(tk)
        assert st["permanent"] is False, "a timeout must never earn a permanent hold"
        assert server._terrain_quarantine_blocks(tk) is True
        assert "backing off" in server.terrain_quarantine_reason(tk)
        with server._terrain_quarantine_lock:      # simulate the backoff elapsing
            server._terrain_quarantine[tk]["until_ts"] = 0.0
        assert server._terrain_quarantine_blocks(tk) is False, "soft hold failed to self-release"
        assert server.terrain_quarantine_state(tk) == {}
    finally:
        server.terrain_quarantine_release(tk)


def test_success_clears_the_failure_streak():
    """Otherwise a ticker that fails twice a day for a week eventually gets evicted for being
    healthy — consecutive means consecutive."""
    tk = "ZZTESTSTREAK"
    try:
        server._note_terrain_failure(tk, "boom", "hard")
        server._note_terrain_failure(tk, "boom", "hard")
        assert server._terrain_consecutive_fails.get(tk) == 2
        server._note_terrain_success(tk)
        assert server._terrain_consecutive_fails.get(tk) is None
        server._note_terrain_failure(tk, "boom", "hard")
        assert not server._terrain_quarantine_blocks(tk), (
            "the streak survived a success, so non-consecutive failures accumulate to eviction"
        )
    finally:
        server.terrain_quarantine_release(tk)


def test_quarantine_state_is_distinguishable_from_pause_and_failure():
    """Four states, four operator actions. A hard quarantine is FAILING (the vendor refuses it)
    and NOT paused (it will not resume on its own) — collapsing either way restores the ambiguity
    RC-146/147 removed."""
    import time
    tk = "ZZTESTFLAGS"
    old = time.time() - (server.TERRAIN_STALE_AFTER_SEC + 600.0)
    try:
        for _ in range(server.TERRAIN_QUARANTINE_HARD_FAILS):
            server._note_terrain_failure(tk, "chain fetch failed (HTTP 400)", "hard")
        s = server.terrain_staleness(old, tk)
        assert s["levels_quarantined"] is True
        assert s["levels_failing"] is True, "a vendor-refused symbol is failing, not merely idle"
        assert s["levels_paused_on_purpose"] is False, "a quarantine does not resume on its own"
        assert "QUARANTINED" in s["levels_stale_reason"]
        # and on the no-snapshot branch, which is exactly RTY/XXT's state
        n = server.terrain_staleness(None, tk)
        assert n["levels_quarantined"] is True and n["levels_failing"] is True
        assert "QUARANTINED" in n["levels_stale_reason"]
    finally:
        server.terrain_quarantine_release(tk)


def _fake_chain(n_expiries: int, spot: float = 7400.0) -> list:
    """Minimal contracts with a regular strike grid across N expiry dates."""
    out = []
    for e in range(n_expiries):
        for k in range(int(spot) - 50, int(spot) + 60, 10):
            out.append({"expirationDate": f"2026-{8 + e // 28:02d}-{1 + e % 28:02d}T00:00:00.000Z",
                        "strikePrice": float(k), "putCall": "CALL", "openInterest": 10})
    return out


def test_narrowed_chain_never_lowers_the_expiry_count():
    """RC-149: n_exp is the DENOMINATOR of the width budget. Learning it from a date-narrowed
    chain makes it small, which makes the next ceiling LARGE, which asks for a wider chain over
    the full date range and blows the contract budget — the narrower the rung that rescued us,
    the more certain the next request is to fail. $SPX rode that loop for 2h10m of HTTP 502."""
    tk = "ZZTESTGEO"
    try:
        assert server._learn_strike_geometry(tk, _fake_chain(54), 7400.0) is True
        with server._strike_geometry_lock:
            assert server._strike_expiry_count[tk] == 54
        wide = server.resolve_chain_strike_count(tk)
        # a NARROWED chain reports fewer expiries — it must not overwrite the full-basis truth
        assert server._learn_strike_geometry(tk, _fake_chain(12), 7400.0,
                                             date_window_narrowed=True) is True
        with server._strike_geometry_lock:
            assert server._strike_expiry_count[tk] == 54, (
                "a date-narrowed chain lowered the expiry count — the next full request will be "
                "sized for 12 expiries and asked over all 54"
            )
        assert server.resolve_chain_strike_count(tk) == wide, (
            "the width authority moved on a narrowed rung; this is the 502 feedback loop"
        )
        # ...but it may still SEED an instrument we know nothing about
        with server._strike_geometry_lock:
            server._strike_expiry_count.pop(tk, None)
        server._learn_strike_geometry(tk, _fake_chain(12), 7400.0, date_window_narrowed=True)
        with server._strike_geometry_lock:
            assert server._strike_expiry_count[tk] == 12, "a floor must still seed an unknown"
    finally:
        with server._strike_geometry_lock:
            server._strike_geometry.pop(tk, None)
            server._strike_expiry_count.pop(tk, None)


def test_width_budget_shrinks_as_expiries_grow():
    """The vendor limit is on CONTRACTS (~strikeCount * 2 * expiries), so an instrument listing
    more expiries must be asked for fewer strikes. This is the invariant the 502 violated."""
    a, b = "ZZTESTFEW", "ZZTESTMANY"
    try:
        server._learn_strike_geometry(a, _fake_chain(8), 7400.0)
        server._learn_strike_geometry(b, _fake_chain(54), 7400.0)
        wa, wb = server.resolve_chain_strike_count(a), server.resolve_chain_strike_count(b)
        assert wb <= wa, f"more expiries got a wider ask ({b}={wb} vs {a}={wa})"
        assert wb * 2 * 54 <= server.SCHWAB_CHAIN_CONTRACT_BUDGET, (
            f"width {wb} over 54 expiries implies {wb * 2 * 54} contracts, above the "
            f"{server.SCHWAB_CHAIN_CONTRACT_BUDGET} budget the vendor 502s on"
        )
    finally:
        with server._strike_geometry_lock:
            for t in (a, b):
                server._strike_geometry.pop(t, None)
                server._strike_expiry_count.pop(t, None)


def test_ladder_narrows_on_over_budget_status_not_only_on_timeout():
    """RC-149 root: the rungs advanced on a TIMEOUT EXCEPTION only. An over-budget chain does not
    time out — the vendor answers HTTP 502 — so `break` fired on rung 1 and the ladder built for
    exactly this case was never reached."""
    import re
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    i = src.find('for _basis, _to_days in (("full", None)')
    assert i > 0, "the timeout ladder is gone"
    body = re.sub(r"#.*$", "", src[i:i + 1400], flags=re.M)
    assert "_OVER_BUDGET_CODES" in body, (
        "the ladder still advances only on a timeout exception, so a 502 breaks out at rung 1"
    )
    assert "resp = None" in body, (
        "a failed response is kept as the answer instead of falling through to the next rung"
    )
    codes = src[src.find("_OVER_BUDGET_CODES = "):][:60]
    assert "502" in codes, f"502 is not treated as over-budget: {codes!r}"


def test_no_bars_payload_survives_so_the_reason_can_be_painted():
    """RC-150: `strikes` is nulled when there are no renderable bars, which also threw away
    levels_stale_reason / levels_failing / levels_quarantined — the diagnosis — at exactly the
    moment it became the only thing worth showing. MEASURED in the rendered DOM 2026-07-30 12:03
    ET: RTY printed "feed activates at the next console start" while /api/terrain/strikes was
    returning levels_failing true and "chain fetch failed (HTTP 400)". RC-147 got the reason onto
    the payload; this is what kept it off the screen."""
    src = CHART.read_text(encoding="utf-8")
    assert "let strikesMeta = null;" in src, "the surviving-payload variable is gone"
    assert "strikesMeta = s || null;" in src, (
        "the payload is not retained unconditionally, so a no-bars ticker loses its reason again"
    )
    # the two branches that render when there are NO bars must read the survivor, not `strikes`
    i = src.find("const _why = (strikesMeta")
    assert i > 0, "the empty-panel branch reads `strikes`, which is null in exactly that branch"
    j = src.find("if (!(strikes && strikes.today_source))")
    assert j > 0, "the no-source branch is gone"
    block = src[j:j + 900]
    assert "strikesMeta" in block, (
        "the no-source branch still prints 'activates at the next console start' for every cause, "
        "including a vendor-rejected symbol no restart can fix"
    )
    assert "FAILING · QUARANTINED" in block


def test_empty_gamma_panel_states_the_producers_reason():
    """Surface-bound: an empty panel blamed the console ('activates at the next console start')
    for RTY/XXT, whose chains Schwab rejects outright with HTTP 400. A restart was never the
    remedy, and the message sent the operator to the wrong one every cycle."""
    src = CHART.read_text(encoding="utf-8")
    i = src.find("GAMMA PANEL — migration + volume by strike")
    assert i > 0, "the empty-panel branch is gone"
    body = src[i:i + 1200]
    assert "levels_stale_reason" in body, (
        "the empty panel still has one explanation for every cause"
    )
    assert "levels_failing" in src, "the panel cannot distinguish FAILING from STALE"
    assert "'FAILING'" in src, "the source line has no FAILING state"


def test_zero_volume_panel_distinguishes_snapshot_from_session():
    """Surface-bound: the panel asserted 'no option volume yet this session' about MSFT thirteen
    minutes after the bell, off a chain read at 09:29:52 ET. The zero-volume branch must read
    staleness before it makes a claim about the market."""
    src = CHART.read_text(encoding="utf-8")
    i = src.find("const _totVol")
    assert i > 0, "the zero-volume branch is gone"
    body = src[i:i + 900]
    assert "levels_stale" in body, (
        "the message still asserts a session fact without checking whether the snapshot is stale"
    )
    assert "SNAPSHOT, not the session" in body
    assert "levels_paused_on_purpose" in src, (
        "the source line cannot distinguish PAUSED from STALE, so a working scheduler still "
        "reads as broken"
    )
