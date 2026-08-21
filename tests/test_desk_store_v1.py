"""Desk fact store — the no-lookahead guarantee, driven on the real module.

The Desk exists to answer "what was knowable at 09:15 on Tuesday". Every test here attacks the
one way that answer can be quietly wrong: a fact reaching the surface before we were entitled to
act on it. Substring checks would prove nothing, so these drive the real writer, the real reader
and the real endpoint assembler.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

import pytest  # noqa: E402

import desk_store as ds  # noqa: E402


def _t(offset_sec: float) -> float:
    return time.time() + offset_sec


def _rth_session_stamps(n: int) -> list[float]:
    """`n` regular-session timestamps, most recent last, walking back over real trading days.

    Derived from the `time_et` authority rather than `now - k*86400`: a fixture pinned to a
    fixed offset lands on a weekend or a holiday depending on the day the suite runs, which is
    the same going-stale-by-construction defect as a hard-coded date (RC-169).

    RC-176: the first version asked `is_rth_ts_utc` alone, which answers only the CLOCK question
    — Saturday 11:00 passed as a session, so the whole suite went red the first Saturday morning
    it ran. The calendar question belongs to `is_trading_day_et`; a stamp must satisfy both.

    RC-210 (2026-08-04): a third question was still missing — COMPLETENESS. `materialize_dollar_volume`
    excludes sessions still in progress (RC-173: a live session contributes a fraction of a day's
    turnover and drags the median down), so a fixture that walks back from *today* silently loses
    one session whenever the suite runs during RTH and lands below `_MIN_SESSIONS_FOR_ADV`. These
    four desk tests therefore passed after the close and failed mid-session — the same
    stale-by-construction class the docstring above warns about, in the time dimension instead of
    the calendar one. A stamp must satisfy clock AND calendar AND completeness, judged by the
    same `session_is_complete` the production reader uses, so the fixture cannot disagree with it.
    """
    from datetime import datetime, timedelta

    from time_et import ET, is_rth_ts_utc, is_trading_day_et

    now = time.time()
    out: list[float] = []
    probe = datetime.now(ET).date()
    guard = 0
    while len(out) < n and guard < 40:
        guard += 1
        day = probe.isoformat()
        ts = datetime(probe.year, probe.month, probe.day, 11, 0, tzinfo=ET).timestamp()
        if (is_trading_day_et(day) and is_rth_ts_utc(ts)
                and ds.session_is_complete(day, now)):
            out.append(ts)
        probe = probe - timedelta(days=1)
    assert len(out) == n, "could not find enough COMPLETE regular sessions in the last 40 days"
    return list(reversed(out))


def _recent_non_session_stamp(window_days: int = 20) -> tuple[str, float]:
    """The most recent NON-trading ET date (weekend or holiday) whose 11:00 ET bar still lands
    INSIDE `materialize_dollar_volume`'s window (`now - window_days*86400`), walking back over the
    real calendar.

    Window-relative by construction, for the same reason `_rth_session_stamps` is: the original
    fixture hard-coded a Saturday (`2026-08-01`). As real time advanced past that date + 20 days,
    the weekend bar fell out of the rolling ADV window, so the `bar_end_ts_utc >= cutoff` filter
    dropped it BEFORE the RTH/calendar filter (`is_rth_trading_ts`) could exclude it — leaving
    `skipped_non_rth_bars == 0` and silently retiring the very gate the test exists to lock. That
    is the stale-by-construction defect RC-169/RC-176 warn about, in the calendar dimension.
    Production was never affected: an in-window weekend bar is still excluded (proven here)."""
    from datetime import datetime, timedelta

    from time_et import ET, is_trading_day_et

    now = time.time()
    cutoff = now - window_days * 86400.0
    probe = datetime.now(ET).date() - timedelta(days=1)  # start yesterday: a past day is complete
    guard = 0
    while guard < window_days + 10:
        guard += 1
        day = probe.isoformat()
        ts = datetime(probe.year, probe.month, probe.day, 11, 0, tzinfo=ET).timestamp()
        if cutoff <= ts < now and not is_trading_day_et(day):
            return day, ts
        probe = probe - timedelta(days=1)
    raise AssertionError("no in-window non-trading day found — window too small?")


def _weekday_premarket_stamp(window_days: int = 20) -> tuple[str, float]:
    """The most recent COMPLETE regular-session ET date's 08:00 ET (pre-market) bar, in-window.

    Extended-hours bars live in `price_bars_1m` BY DESIGN (RC-170); ADV intentionally excludes them
    because session membership is a `time_et` call, not a bar count. This gives a real trading-day
    timestamp that is outside RTH, to prove the session gate excludes pre/post-market turnover
    without deleting the underlying bars."""
    from datetime import datetime, timedelta

    from time_et import ET, is_rth_ts_utc, is_trading_day_et

    now = time.time()
    cutoff = now - window_days * 86400.0
    probe = datetime.now(ET).date() - timedelta(days=1)
    guard = 0
    while guard < window_days + 10:
        guard += 1
        day = probe.isoformat()
        pre = datetime(probe.year, probe.month, probe.day, 8, 0, tzinfo=ET).timestamp()
        if (cutoff <= pre < now and is_trading_day_et(day)
                and not is_rth_ts_utc(pre) and ds.session_is_complete(day, now)):
            return day, pre
        probe = probe - timedelta(days=1)
    raise AssertionError("no in-window complete trading day with a pre-market slot found?")


def test_reader_filters_on_knowledge_time_not_event_time(tmp_path):
    """The whole module in one assertion: an old event we learned about LATE stays invisible
    until its knowledge time passes, even though its event time is long gone."""
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    event, knowledge = _t(-600_000), _t(-100)
    ds.put_fact(db, subject="ZZTEST", kind="short_volume_ratio", event_time_utc=event,
                knowledge_time_utc=knowledge, source="unit", tier="MEASURED", value_num=0.41)

    just_after_event = ds.facts_as_of(db, event + 60)
    assert just_after_event == [], (
        "a fact was served at a moment we had not yet received it — this is lookahead, and it "
        "is the failure the whole store exists to prevent"
    )
    assert len(ds.facts_as_of(db, knowledge + 1)) == 1
    assert len(ds.facts_as_of(db, knowledge - 1)) == 0


def test_knowledge_time_is_never_invented(tmp_path):
    """No default, no `or time.time()`. A source that cannot say when we learned something
    yields no row rather than a plausible one."""
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    base = dict(subject="ZZ", kind="k", event_time_utc=_t(-100), source="unit", tier="MEASURED")
    for bad in (None, 0, -1, "2026-07-31"):
        with pytest.raises(ds.DeskFactError):
            ds.put_fact(db, knowledge_time_utc=bad, **base)  # type: ignore[arg-type]


def test_we_cannot_have_known_it_before_it_happened(tmp_path):
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    with pytest.raises(ds.DeskFactError):
        ds.put_fact(db, subject="ZZ", kind="k", event_time_utc=_t(-10),
                    knowledge_time_utc=_t(-500), source="unit", tier="MEASURED")


def test_tier_is_closed_vocabulary(tmp_path):
    """Nothing below ESTIMATED may drive an action, so the tier cannot be a free-text field."""
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    assert ds.TIERS == ("MEASURED", "DERIVED", "ESTIMATED", "UNPROVEN")
    with pytest.raises(ds.DeskFactError):
        ds.put_fact(db, subject="ZZ", kind="k", event_time_utc=_t(-100),
                    knowledge_time_utc=_t(-10), source="unit", tier="PROBABLY")


def test_naive_timestamps_resolve_to_the_LATEST_instant_they_could_mean():
    """The world_* tables stamp `fetched_at` with no timezone. Read as UTC it is the earliest
    possible reading; read as US/Eastern it is up to 5h later. We take the later one, because
    over-claiming knowledge time is the one error nothing downstream can detect."""
    utc_reading = 1784638947.0  # 2026-07-21 13:02:27 UTC
    got = ds._naive_text_to_utc_conservative("2026-07-21 13:02:27")
    assert got is not None
    assert got - utc_reading == pytest.approx(5 * 3600, abs=1), (
        "a naive stamp was resolved to the EARLIEST instant it could mean, which silently "
        "licenses up to five hours of lookahead"
    )
    assert ds._naive_text_to_utc_conservative("") is None
    assert ds._naive_text_to_utc_conservative("garbage") is None


def test_absence_reaches_the_surface_as_absence(tmp_path):
    """A missing table or an empty store returns nothing and says why — never zeros."""
    assert ds.facts_as_of(tmp_path / "nope.db", time.time()) == []
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    payload = ds.radar_rows(db, time.time())
    assert payload["rows"] == []
    assert payload["n_total"] == 0
    assert payload["empty_reason"], "an empty Radar gave no reason for being empty"


def test_radar_rank_makes_no_forecast(tmp_path):
    """Rank is measured structure. The moment it encodes an expected return it needs an
    ADMITTED claim, and `governance/decision_path_admissions.json` is empty."""
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    now = time.time()
    for sym, adv in (("AAA", 5.0e6), ("BBB", 9.0e7)):
        ds.put_fact(db, subject=sym, kind="adv_dollar", event_time_utc=now - 300,
                    knowledge_time_utc=now - 300, source="unit", tier="DERIVED", value_num=adv)
    payload = ds.radar_rows(db, now)
    assert [r["subject"] for r in payload["rows"]] == ["BBB", "AAA"]
    assert "expected return" in payload["rank_basis"]
    assert "not expected return" in payload["rank_basis"]


def test_replay_removes_rows_that_were_not_yet_knowable(tmp_path):
    """The operator-visible behaviour: drag the control back and candidates DISAPPEAR."""
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    now = time.time()
    ds.put_fact(db, subject="EARLY", kind="adv_dollar", event_time_utc=now - 86400,
                knowledge_time_utc=now - 86400, source="unit", tier="DERIVED", value_num=1e6)
    ds.put_fact(db, subject="LATE", kind="adv_dollar", event_time_utc=now - 600,
                knowledge_time_utc=now - 600, source="unit", tier="DERIVED", value_num=9e9)
    assert {r["subject"] for r in ds.radar_rows(db, now)["rows"]} == {"EARLY", "LATE"}
    earlier = ds.radar_rows(db, now - 3600)["rows"]
    assert {r["subject"] for r in earlier} == {"EARLY"}, (
        "replaying to an earlier instant still served a fact we had not yet received"
    )


def test_endpoint_is_wired_to_the_real_reader_and_defaults_to_now():
    """Seam: the route drives `desk_store`, not a private copy of the logic."""
    import inspect

    import server as s

    src = inspect.getsource(s.get_desk_radar)
    assert "desk_store.radar_rows" in src, "the endpoint no longer calls the real reader"
    assert "time.time()" in src, "as_of=0 must mean now"
    assert "rows\": []" in src or '"rows": []' in src, (
        "a failure path must return empty rows, never a fabricated shape"
    )


def test_desk_page_is_served_and_carries_no_fixture_data():
    """VISIBLE_SURFACE: /desk. The page must be reachable and must not ship illustrative rows."""
    import inspect
    from pathlib import Path

    import server as s

    assert "desk.html" in inspect.getsource(s.desk_page)
    ui = (Path(__file__).resolve().parent.parent / "static" / "desk.html").read_text(
        encoding="utf-8")
    assert "/api/desk/radar" in ui, "the page never calls the endpoint"
    assert "radar-body" in ui
    for ghost in ("HURN", "DFNS", "SPRC", "MPLT", "GWAV"):
        assert ghost not in ui, f"fixture ticker {ghost} shipped in a live trading surface"
    assert "Not built" in ui, "unbuilt subtabs must say so rather than paint something"


def test_desk_page_is_token_only():
    """Desk is the first fully tokenized surface. MEASURED 2026-07-31: index.html carries 410
    raw hex against 125 var() uses and chart.html uses the tokens zero times — three hand-copied
    palettes. A fourth would make light mode a rewrite instead of 16 values."""
    import re
    from pathlib import Path

    ui = (Path(__file__).resolve().parent.parent / "static" / "desk.html").read_text(
        encoding="utf-8")
    root = ui[ui.find(":root{"):ui.find("}", ui.find(":root{"))]
    outside = ui.replace(root, "")
    stray = re.findall(r"#[0-9a-fA-F]{3,8}\b", outside)
    stray = [h for h in stray if not h.lower().startswith("#9679")]  # &#9679; entity, not a colour
    assert stray == [], f"raw colour literals outside :root — {stray[:6]}"
    assert len(re.findall(r"var\(--cv-", ui)) > 40


def test_cash_indices_carry_no_dollar_volume():
    """RC-167: `$SPX` was published at $108,127,149,193,795 a day. `close * volume` is dollars
    only when volume counts SHARES, and an index has none."""
    assert ds.is_cash_index("$SPX") is True
    assert ds.is_cash_index("$VIX") is True
    assert ds.is_cash_index("SPY") is False
    assert ds.is_cash_index("") is False


def test_adv_is_a_median_and_reports_its_own_suspect_sessions(tmp_path):
    """RC-167/RC-168: one blown session must not become the capacity number, and the fact that
    it exists must survive into the payload rather than being smoothed away.

    Fixture mirrors the measured MSFT shape: three ordinary sessions and one 36x outlier.
    """
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    con = __import__("sqlite3").connect(str(db))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    for ts, shares in zip(_rth_session_stamps(4),
                          (10_000.0, 10_500.0, 9_800.0, 360_000.0), strict=True):
        con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                    ("ZZZ", ts - 60, ts, 1, 1, 1, 100.0, shares, "unit"))
    idx_ts = _rth_session_stamps(1)[0]
    con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                ("$IDX", idx_ts - 60, idx_ts, 1, 1, 1, 5000.0, 999_999.0, "unit"))
    con.commit()
    con.close()

    ds.materialize_dollar_volume(db)
    facts = ds.latest_by_subject(db, time.time() + 5, "adv_dollar")
    assert "$IDX" not in facts, "a cash index was published with a dollar volume"
    row = facts["ZZZ"]
    assert row["value_num"] == pytest.approx(1_025_000.0), (
        f"ADV is not the median session — got {row['value_num']}, so one blown session is "
        "still setting the capacity number"
    )
    assert row["payload"]["suspect_sessions"] == 1, (
        "the outlier was absorbed silently; RC-168 is unfixed and must stay visible"
    )


def test_adv_counts_only_the_regular_session(tmp_path):
    """RC-170: `price_bars_1m` carries extended hours BY DESIGN and coverage differs per name.

    MEASURED 2026-07-31 before the filter: SPY averaged 687 bars per session against MSFT's 358,
    so one name's ADV counted pre- and post-market turnover and the other's did not — the column
    ranked names against each other on two different definitions of a day. Session membership is
    the `time_et` authority's call, never a bar count.
    """
    import sqlite3
    from datetime import datetime, timedelta

    from time_et import ET, is_rth_ts_utc, is_trading_day_et

    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    # Three RTH sessions of equal size, each shadowed by a huge pre-market bar.
    # RC-176: the trading-day check is part of the condition — without it this loop planted a
    # Saturday pair whenever the suite ran on a weekend, and the count assertion drifted by one.
    # RC-210 (2026-08-04): completeness belongs in the condition too — an in-progress session
    # is excluded by the reader (RC-173), so planting a pair on today made this test pass after
    # the close and fail mid-session. Same three-part rule as _rth_session_stamps.
    day = datetime.now(ET).date()
    sessions = 0
    probe = day
    _now = time.time()
    while sessions < 3:
        rth = datetime(probe.year, probe.month, probe.day, 11, 0, tzinfo=ET).timestamp()
        pre = datetime(probe.year, probe.month, probe.day, 5, 0, tzinfo=ET).timestamp()
        if is_trading_day_et(probe.isoformat()) and is_rth_ts_utc(rth) \
                and ds.session_is_complete(probe.isoformat(), _now) \
                and not is_rth_ts_utc(pre):
            con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                        ("ZZZ", rth - 60, rth, 1, 1, 1, 100.0, 10_000.0, "unit"))
            con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                        ("ZZZ", pre - 60, pre, 1, 1, 1, 100.0, 500_000.0, "unit"))
            sessions += 1
        probe = probe - timedelta(days=1)
    con.commit()
    con.close()

    res = ds.materialize_dollar_volume(db)
    assert res["skipped_non_rth_bars"] == 3, (
        "pre-market bars reached the ADV derivation — extended-hours turnover is being counted "
        "as regular-session capacity"
    )
    row = ds.latest_by_subject(db, time.time() + 5, "adv_dollar")["ZZZ"]
    assert row["value_num"] == pytest.approx(1_000_000.0), (
        f"ADV is {row['value_num']}, not the RTH-only session value — the pre-market bar is "
        "still in the number"
    )


def test_too_few_sessions_yields_no_adv_rather_than_a_confident_one(tmp_path):
    """A median of one session is that session. Below the floor the honest output is nothing."""
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    con = __import__("sqlite3").connect(str(db))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    now = time.time()
    con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                ("ZZZ", now - 60, now, 1, 1, 1, 100.0, 10_000.0, "unit"))
    con.commit()
    con.close()
    assert ds._MIN_SESSIONS_FOR_ADV == 3
    ds.materialize_dollar_volume(db)
    assert ds.latest_by_subject(db, time.time() + 5, "adv_dollar") == {}


def test_vertical_payoff_is_checkable_by_hand():
    """The calculator earns trust by being arithmetic anyone can verify on paper. 145/150 for
    3.85/2.32 on 10 lots: debit (3.85-2.32)*100*10 = 1530, width 5*100*10 = 5000, so max gain
    3470, max loss 1530, breakeven 145 + 1.53 = 146.53."""
    v = ds.vertical_spread(145, 150, 3.85, 2.32, contracts=10)
    assert v["net_debit"] == 1530.0
    assert v["max_gain"] == 3470.0
    assert v["max_loss"] == -1530.0
    assert v["breakeven"] == 146.53
    assert v["tier"] == "DERIVED", "payoff arithmetic must never be labelled a model output"
    with pytest.raises(ds.DeskFactError):
        ds.vertical_spread(150, 150, 1.0, 0.5)


def test_capacity_is_driven_by_volatility_and_publishes_its_assumption():
    """RC-171: capacity was computed from a ratio of impact budget to quoted SPREAD, which is
    not a volatility and has no units that make the square-root law true. It returned
    $5,601,230,345 for SPY — a quarter of the name's entire daily turnover — because the
    participation cap was the only term still binding."""
    import inspect

    src = inspect.getsource(ds.dossier)
    assert "daily_sigma_bps" in src, "capacity is no longer driven by a measured volatility"
    assert "_IMPACT_COEFFICIENT" in src
    assert ds._MAX_PARTICIPATION == 0.25
    # the assumed coefficient must reach the payload, or the number cannot be argued with
    assert "coefficient_Y" in src
    assert "participation_capped" in src, (
        "a binding ceiling must be declared — otherwise a cap masquerades as a model output"
    )


def test_pop_refuses_to_report_a_certainty():
    """RC-171: a POP of exactly 1.0 or 0.0 is never something the sample supports — it means the
    breakeven lies outside every path drawn. Printing 1.0000 beside a real position is how a
    mis-keyed strike becomes a conviction."""
    dist = {"available": True, "n_paths": 100,
            "density": {"lo": 100.0, "hi": 110.0, "bin_width": 1.0, "counts": [10] * 10}}
    inside = ds.probability_of_profit(dist, 105.0)
    assert inside["outside_sampled_range"] is False
    assert 0.0 < inside["pop"] < 1.0
    for impossible in (5.0, 5000.0):
        out = ds.probability_of_profit(dist, impossible)
        assert out["pop"] is None, f"a certainty was reported for breakeven {impossible}"
        assert out["outside_sampled_range"] is True
        assert out["sampled_range"] == [100.0, 110.0]
    assert ds.probability_of_profit({"available": False}, 1.0) is None


def test_risk_neutral_refusal_is_stated_once_and_identically():
    """Every surface must refuse for the same reason in the same words, or a reader will assume
    two different causes and go looking for the one that can be worked around."""
    dist = {"available": True, "n_paths": 10,
            "density": {"lo": 1.0, "hi": 2.0, "bin_width": 0.5, "counts": [5, 5]}}
    pop = ds.probability_of_profit(dist, 1.5)
    assert pop["risk_neutral_pop"] is None
    assert pop["risk_neutral_reason"] == ds._RISK_NEUTRAL_UNAVAILABLE
    assert "no option PRICES" in ds._RISK_NEUTRAL_UNAVAILABLE


def test_bootstrap_is_deterministic_and_refuses_a_thin_series(tmp_path):
    """A desk number that changes on refresh cannot be checked, and a number that cannot be
    checked is not evidence. Same question, same answer."""
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    thin = ds.terminal_distribution(db, "ZZZ", time.time())
    assert thin["available"] is False
    assert str(ds._MIN_RETURNS_FOR_BOOTSTRAP) in thin["reason"]
    assert thin["risk_neutral_available"] is False
    assert ds._BOOTSTRAP_BLOCK_BARS > 1, (
        "block length 1 is an independent draw, which destroys the volatility clustering the "
        "bootstrap exists to preserve"
    )
    assert ds._BARS_PER_RTH_SESSION == 390


def test_evidence_is_read_from_the_scoreboard_not_retyped():
    """Retyping is how a scoreboard drifts from the studies it summarises — and this is the one
    surface the rest of the Desk defers to when it refuses to make a claim."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    ev = ds.evidence_rows(root)
    assert ev["rows"], "the scoreboard produced no rows"
    assert "fp_scoreboard_latest.json" in ev["source"]
    assert ev["existence_pass_cells"] == 0, (
        "a study now passes — the promotion rule says other subtabs may begin consuming it, so "
        "this assertion is the tripwire that forces that decision to be made deliberately"
    )
    for r in ev["rows"]:
        if not isinstance(r["n_pass"], int) or r["n_pass"] <= 0:
            assert r["tier"] == "UNPROVEN", f"{r['study']} is tiered above its own evidence"


def test_brief_blocks_must_carry_their_own_age(tmp_path):
    """A brief is stored as structured blocks, never as rendered HTML: blocks can go stale
    individually and can be scored; a blob can do neither."""
    db = tmp_path / "d.db"
    now = time.time()
    with pytest.raises(ds.DeskFactError):
        ds.put_brief(db, et_date="2026-07-31", title="t", producer="p", generated_utc=now,
                     blocks=[{"heading": "no age here"}], sources=[])
    with pytest.raises(ds.DeskFactError):
        ds.put_brief(db, et_date="2026-07-31", title="t", producer="p", generated_utc=now,
                     blocks=[], sources=[])
    ds.put_brief(db, et_date="2026-07-31", title="Playbook", producer="unit",
                 generated_utc=now,
                 blocks=[{"heading": "fresh", "as_of_utc": now - 60},
                         {"heading": "old", "as_of_utc": now - (72 * 3600)}],
                 sources=[{"url": "https://example.invalid"}])
    got = ds.latest_brief(db, now)
    assert got["stale_blocks"] == 1, "a 72-hour-old block was not marked stale"
    assert got["blocks"][0]["stale"] is False
    assert got["blocks"][1]["stale"] is True
    assert ds.latest_brief(db, now - 86400) is None, (
        "a brief was served at an instant before it was generated"
    )


def test_every_desk_endpoint_exists_and_fails_closed():
    """Seam: each route drives the real producer, and each failure path returns absence rather
    than a fabricated shape."""
    import inspect

    import server as s

    for fn, producer in ((s.get_desk_dossier, "desk_store.dossier"),
                         (s.get_desk_evidence, "desk_store.evidence_rows"),
                         (s.get_desk_structure, "desk_store.terminal_distribution"),
                         (s.get_desk_brief, "desk_store.latest_brief")):
        src = inspect.getsource(fn)
        assert producer in src, f"{fn.__name__} does not call {producer}"
    assert "empty_reason" in inspect.getsource(s.get_desk_brief)


def test_desk_page_renders_every_subtab_from_an_endpoint_or_says_not_built():
    """VISIBLE_SURFACE contract: no subtab may paint a shape it did not fetch."""
    from pathlib import Path

    ui = (Path(__file__).resolve().parent.parent / "static" / "desk.html").read_text(
        encoding="utf-8")
    for ep in ("/api/desk/radar", "/api/desk/brief", "/api/desk/dossier",
               "/api/desk/evidence", "/api/desk/structure"):
        assert ep in ui, f"{ep} is never called by the page"
    # Book is the one subtab with no producer, and it must say so rather than paint
    i = ui.find('$("p-book")')
    assert i > 0 and "Not built" in ui[i:i + 700], "Book no longer declares itself unbuilt"
    assert "outside every path drawn" in ui, (
        "the POP range guard never reaches the screen — RC-171 would be invisible to the "
        "operator, which is the only place it matters"
    )


def test_evidence_refuses_a_scoreboard_from_the_future(tmp_path):
    """RC-172: Evidence ignored the replay clock, so dragging the Desk into the past still
    rendered whatever scoreboard exists on disk NOW. On a tab whose premise is judging a screen
    by what was knowable, the surface that adjudicates claims was the one reading ahead."""
    import json as _json

    root = tmp_path
    (root / "reports").mkdir()
    gen = "2026-07-17T14:10:43Z"
    (root / "reports" / "fp_scoreboard_latest.json").write_text(_json.dumps({
        "generated_utc": gen, "money_path": "WAIT",
        "studies": {"FP-X": {"verdict": "NO_SIGNAL_DETECTED", "n_pass": 0, "n_fail": 4}},
        "totals": {"existence_pass_cells_sum": 0}}), encoding="utf-8")

    gen_ts = ds._iso_utc_to_epoch(gen)
    assert gen_ts is not None
    after = ds.evidence_rows(root, gen_ts + 60)
    assert len(after["rows"]) == 1, "a scoreboard we already held was withheld"
    before = ds.evidence_rows(root, gen_ts - 60)
    assert before["rows"] == [], "a scoreboard was served before it was generated"
    assert "after the instant being replayed" in before["empty_reason"]
    # no clock supplied at all keeps the old unconditional behaviour for callers that want it
    assert len(ds.evidence_rows(root)["rows"]) == 1


def test_iso_parser_requires_a_declared_zone():
    """Distinct from the conservative naive parser on purpose: this input declares its zone, so
    adding a safety margin would be wrong, and a stamp with NO zone must be refused rather than
    guessed at."""
    assert ds._iso_utc_to_epoch("2026-07-17T14:10:43Z") == pytest.approx(
        ds._iso_utc_to_epoch("2026-07-17T14:10:43+00:00"))
    assert ds._iso_utc_to_epoch("2026-07-17T14:10:43") is None, (
        "a zone-less stamp was silently treated as UTC"
    )
    assert ds._iso_utc_to_epoch("") is None
    assert ds._iso_utc_to_epoch("not a date") is None


def test_latest_by_subject_reduces_in_sql_not_in_python(tmp_path):
    """RC-172: the Python reduction pulled 48,564 rows across the wire on every Radar request to
    keep 12,617 of them, against a database with an open contention root cause (RC-166)."""
    import inspect

    src = inspect.getsource(ds.latest_by_subject)
    assert "ROW_NUMBER() OVER" in src, "the newest-per-subject reduction left SQL"
    assert "facts_as_of(" not in src, "still fanning every row into Python"

    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    now = time.time()
    for i, val in enumerate((1.0, 2.0, 3.0)):
        ds.put_fact(db, subject="ZZ", kind="k", event_time_utc=now - 500,
                    knowledge_time_utc=now - 300 + i, source=f"s{i}", tier="MEASURED",
                    value_num=val)
    got = ds.latest_by_subject(db, now, "k")
    assert got["ZZ"]["value_num"] == 3.0, "SQL kept the wrong row as newest"
    # and the knowledge-time filter must survive the rewrite
    assert ds.latest_by_subject(db, now - 400, "k") == {}


def test_materialize_is_not_reachable_by_a_speculative_get():
    """RC-172: a GET that rewrites tens of thousands of rows is fired by any link prefetch,
    crawler or preconnect — against a database that already has an open write-contention root
    cause."""
    import inspect

    import server as s

    src = inspect.getsource(s)
    i = src.find("def post_desk_materialize")
    assert i > 0
    decorator = src[max(0, i - 260):i]
    assert '@app.post("/api/desk/materialize")' in decorator, (
        "the materialize route is not POST-only — a speculative GET can trigger a full rewrite"
    )
    assert '@app.get("/api/desk/materialize")' not in src


def test_payoff_refuses_a_non_positive_price():
    """RC-173: a negative price was accepted and rendered `max_loss = -0.0` — a screen saying
    this trade cannot lose money. A mis-keyed minus sign must not produce a risk-free position.
    """
    for bad in ((145, 150, -3.0, 2.0), (145, 150, 0.0, 0.0), (145, 150, 3.85, -1.0),
                (145, 150, 3.85, 0.0)):
        with pytest.raises(ds.DeskFactError):
            ds.vertical_spread(*bad)
    ok = ds.vertical_spread(145, 150, 3.85, 2.32)
    assert ok["max_loss"] < 0, "a real debit spread must carry a real loss"


def test_a_session_in_progress_is_not_a_completed_session():
    """RC-173: daily statistics took the last regular-session bar of each date as that date's
    close. After the bell that IS the close; at 11:00 ET it is an intraday print, so the newest
    daily return became a partial-day move and the newest session volume a fraction of a
    session. The distortion appears only while the market is open, which is exactly when the
    operator is reading the number."""
    from datetime import datetime

    from time_et import ET, is_trading_day_et

    # find a real trading day inside the window
    probe = datetime.now(ET).date()
    for _ in range(10):
        if is_trading_day_et(probe.isoformat()):
            break
        probe = probe.fromordinal(probe.toordinal() - 1)
    d = probe.isoformat()

    mid = datetime(probe.year, probe.month, probe.day, 11, 0, tzinfo=ET).timestamp()
    after = datetime(probe.year, probe.month, probe.day, 20, 0, tzinfo=ET).timestamp()
    assert ds.session_is_complete(d, mid) is False, (
        "an 11:00 ET instant was treated as a closed session"
    )
    assert ds.session_is_complete(d, after) is True
    # a prior date is closed by construction, whatever the clock says
    earlier = probe.fromordinal(probe.toordinal() - 7).isoformat()
    assert ds.session_is_complete(earlier, mid) is True


def test_sigma_drops_the_session_in_progress(tmp_path):
    """The operative consequence of RC-173: asked mid-session, the sample must be one session
    shorter than it is after the bell."""
    import sqlite3
    from datetime import datetime

    from time_et import ET, is_rth_ts_utc

    db = tmp_path / "d.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    stamps = _rth_session_stamps(ds._MIN_SESSIONS_FOR_SIGMA + 2)
    for i, ts in enumerate(stamps):
        con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                    ("ZZZ", ts - 60, ts, 1, 1, 1, 100.0 + i, 1000.0, "unit"))
    con.commit()
    con.close()

    last = stamps[-1]
    day = datetime.fromtimestamp(last, ET).date()
    after = datetime(day.year, day.month, day.day, 20, 0, tzinfo=ET).timestamp()
    mid = datetime(day.year, day.month, day.day, 11, 0, tzinfo=ET).timestamp()
    assert is_rth_ts_utc(mid)

    closed = ds.daily_sigma_bps(db, "ZZZ", after)
    open_now = ds.daily_sigma_bps(db, "ZZZ", mid)
    assert closed and open_now
    assert open_now["n_sessions"] == closed["n_sessions"] - 1, (
        "the session in progress was counted as a completed one"
    )


def test_adv_reports_the_bars_it_dropped_for_being_mid_session():
    """A silent exclusion reads as 'covered everything'. The count travels with the answer."""
    import inspect

    src = inspect.getsource(ds.materialize_dollar_volume)
    assert "session_is_complete" in src
    assert "skipped_incomplete_session_bars" in src


def test_no_api_response_hands_the_operator_home_path_to_a_browser():
    """RC-174: the Evidence payload carried
    `C:\\Users\\<operator>\\Documents\\Trading\\EdWebConsole\\reports\\...`. This repo already
    forbids operator-home paths in tracked evidence for the same reason — a path discloses who
    is running the process and from where — and an API response reaches further than a file
    does."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for payload in (ds.evidence_rows(root), ds.evidence_rows(root, time.time()),
                    ds.evidence_rows(root, 1.0)):
        src = str(payload.get("source", ""))
        assert src == "reports/fp_scoreboard_latest.json", src
        assert "Users" not in src and ":" not in src, f"absolute path leaked: {src}"


def test_radar_says_how_many_rows_are_actually_screened(tmp_path):
    """RC-174: the footer read "12,617 subjects knowable" under a header saying "Candidates".
    MEASURED 2026-07-31: of 60 rendered rows only 37 carried dollar volume, a chain AND a short
    ratio; 23 carried a short ratio alone — no capacity, no chain, nothing that makes a name
    tradeable. A count that mixes the two is a count of rows in a file."""
    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    now = time.time()
    ds.put_fact(db, subject="FULL", kind="adv_dollar", event_time_utc=now - 60,
                knowledge_time_utc=now - 60, source="u", tier="DERIVED", value_num=1e7)
    ds.put_fact(db, subject="FULL", kind="options_listed", event_time_utc=now - 60,
                knowledge_time_utc=now - 60, source="u", tier="MEASURED", value_num=50)
    ds.put_fact(db, subject="THIN", kind="short_volume_ratio", event_time_utc=now - 600,
                knowledge_time_utc=now - 60, source="u", tier="MEASURED", value_num=0.3)
    p = ds.radar_rows(db, now)
    assert p["n_total"] == 2
    assert p["n_structural"] == 1, "a single-fact row was counted as screened structure"
    assert p["n_single_fact"] == 1
    assert "listed, not screened" in p["coverage_note"]


def test_desk_nav_links_go_where_they_say():
    """A link labelled Terrain pointed at `/`, which lands on Console. index.html honours
    `#terrain`, so the link was wrong rather than the destination being unreachable."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    ui = (root / "static" / "desk.html").read_text(encoding="utf-8")
    nav = dict((lbl, href) for href, lbl in
               re.findall(r'href="([^"]*)"[^>]*>(Console|Terrain|Chart|Desk)', ui))
    assert nav["Terrain"] == "/#terrain", nav
    assert nav["Chart"] == "/chart"
    assert nav["Desk"] == "/desk"
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    assert "'#terrain'" in index or '"#terrain"' in index, (
        "the Desk links to a deep link the console no longer honours"
    )


def test_the_distribution_is_deterministic_against_the_same_bars(tmp_path):
    """RC-175: the docstring promised the same question returns the same answer, and the live
    path broke it. The seed included `int(as_of_utc)`, and on the live path `as_of` is NOW —
    MEASURED 2026-07-31, two calls a second apart gave p50 745.3444 then 744.9982. A number that
    changes on refresh cannot be checked, and a promise in a docstring that the code does not
    keep is worse than no promise."""
    import ast
    import inspect
    import sqlite3

    # Search the CODE, not the prose. The docstring documents the defect by name, and a naive
    # substring check matched the explanation rather than the thing explained — the same trap
    # that fired earlier this session when a guard blocked the text describing its own removal.
    tree = ast.parse(inspect.getsource(ds.terminal_distribution).lstrip())
    fn = tree.body[0]
    assert isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
    body = fn.body[1:] if isinstance(fn.body[0], ast.Expr) and isinstance(
        fn.body[0].value, ast.Constant) else fn.body
    seed_stmt = [n for n in ast.walk(ast.Module(body=body, type_ignores=[]))
                 if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", "") == "seed" for t in n.targets)]
    assert seed_stmt, "no `seed` is constructed at all"
    seed_src = ast.dump(seed_stmt[0])
    assert "as_of_utc" not in seed_src, "the wall clock is back in the seed"

    db = tmp_path / "d.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    # Fill whole regular sessions. Walking back minute-by-minute from one session's midpoint
    # leaves the session after 90 bars and starves the bootstrap — the filter is doing its job,
    # the fixture was wrong.
    from time_et import is_rth_ts_utc

    px, n_rth = 100.0, 0
    for day_ts in _rth_session_stamps(3):
        for k in range(390):
            ts = day_ts - (90 * 60) + (k * 60)   # 09:30 ET onward
            if not is_rth_ts_utc(ts):
                continue
            n_rth += 1
            px *= 1.0 + (0.0004 if k % 3 else -0.0005)
            con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                        ("ZZZ", ts - 60, ts, 1, 1, 1, px, 100.0, "unit"))
    con.commit()
    con.close()
    assert n_rth > ds._MIN_RETURNS_FOR_BOOTSTRAP, (
        f"fixture only produced {n_rth} regular-session bars"
    )

    now = time.time()
    a = ds.terminal_distribution(db, "ZZZ", now)
    b = ds.terminal_distribution(db, "ZZZ", now + 900)  # a later clock, identical bars
    assert a["available"] and b["available"]
    assert a["quantiles"] == b["quantiles"], (
        "the same bars produced two different distributions — the clock is still in the seed"
    )
    assert a["seed"] == b["seed"]
    c = ds.terminal_distribution(db, "ZZZ", now, horizon_sessions=9)
    assert c["quantiles"] != a["quantiles"], "a different question gave an identical answer"


def test_a_slow_response_cannot_repaint_over_a_newer_one():
    """RC-175: no request-sequence guard existed, so a slow reply could overwrite a fresher one
    after a ticker change or a fast tab switch. This session already shipped that failure class
    through a different door — an orphaned in-flight guard that threw on every Chart load."""
    from pathlib import Path

    ui = (Path(__file__).resolve().parent.parent / "static" / "desk.html").read_text(
        encoding="utf-8")
    i = ui.find("function grab(")
    assert i > 0
    body = ui[i:i + 700]
    assert "SEQ[box]" in body, "responses are still applied without checking they are current"
    assert body.count("if(SEQ[box]!==n) return;") >= 2, (
        "the guard must cover the error path too — a stale FAILURE overwriting a good render "
        "is the same defect wearing a different face"
    )


def test_desk_page_is_navigable_without_a_mouse():
    """Tabs that cannot be reached or announced are not a surface for everyone who has to read
    a position off this screen."""
    from pathlib import Path

    ui = (Path(__file__).resolve().parent.parent / "static" / "desk.html").read_text(
        encoding="utf-8")
    assert ui.count('role="tabpanel"') == 6, "not every panel is announced as a tab panel"
    for p in ("radar", "brief", "dossier", "struct", "book", "evid"):
        assert f'aria-controls="p-{p}"' in ui and f'aria-labelledby="t-{p}"' in ui, p
    assert "<h1" in ui, "the page has no top-level heading"
    assert ".sr{" in ui, "the visually-hidden helper the h1 relies on is undefined"
    assert "focus-visible" in ui, "keyboard focus has no visible state"


def _make_bars_db(tmp_path, rows: list[tuple]):
    """A throwaway `price_bars_1m` db seeded with (ticker, bar_end_ts, close, volume) rows."""
    import sqlite3

    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    con.executemany(
        "INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
        [(sym, ts - 60, ts, 1, 1, 1, close, vol, "unit") for (sym, ts, close, vol) in rows],
    )
    con.commit()
    con.close()
    return db


def test_saturday_is_not_a_session_anywhere_in_the_desk(tmp_path):
    """RC-176 — the defect that turned the suite red the first Saturday it ran, and was REAL in
    production: `price_bars_1m` carries weekend/holiday rows, and every Desk reader filtered on the
    CLOCK alone, so those rows counted as sessions.

    RC-176 REPAIR (2026-08-21): the fixture used to hard-code `2026-08-01`. Once real time passed
    that date + the 20-day ADV window, the weekend bar left the window and the `bar_end_ts_utc >=
    cutoff` filter dropped it BEFORE `is_rth_trading_ts` could exclude it — so `skipped_non_rth_bars`
    fell to 0 and the test failed while asserting a production defect that did not exist. The gate
    was always correct; the fixture aged out (RC-169). The non-session bar is now WINDOW-RELATIVE,
    so the calendar half of the gate is exercised on every run, forever."""
    non_day, non_ts = _recent_non_session_stamp()

    # the combined authority: right clock, wrong day -> not a session
    assert ds.is_rth_trading_ts(non_ts) is False, (
        f"{non_day} 11:00 ET passed the RTH filter — the calendar half of the question is unasked"
    )
    # nothing can be 'in progress' on a day with no session
    assert ds.session_is_complete(non_day, non_ts) is True, (
        "a non-trading day read as an open session — weekend runs would freeze out the day's data"
    )

    # and the weekend/holiday bar must not become an ADV session — the RTH filter, not the window
    # filter, must be what excludes it (the bar is in-window by construction).
    rows = [("ZZZ", ts, 100.0, 10_000.0) for ts in _rth_session_stamps(ds._MIN_SESSIONS_FOR_ADV)]
    rows.append(("ZZZ", non_ts, 100.0, 9_999_999.0))
    db = _make_bars_db(tmp_path, rows)
    res = ds.materialize_dollar_volume(db)
    assert res["skipped_non_rth_bars"] >= 1, "the in-window non-session bar was not excluded"
    row = ds.latest_by_subject(db, time.time() + 5, "adv_dollar").get("ZZZ")
    assert row is not None
    assert row["payload"]["sessions"] == ds._MIN_SESSIONS_FOR_ADV, (
        "a non-trading-day bar was counted as a trading session"
    )
    assert row["value_num"] == pytest.approx(1_000_000.0), (
        "the non-session bar's dollars leaked into the median"
    )


@pytest.mark.parametrize("sym", ["ZZZ", "spy", "AaPl", "BRK.B"])
@pytest.mark.parametrize(
    "non_trading_ts_fn",
    [
        # a weekend (Saturday 2026-08-08) and two US market holidays (New Year's Day 2027;
        # Independence Day observed 2026-07-03) — fixed calendar facts, so the CALENDAR gate is
        # exercised independently of any rolling window. is_rth_trading_ts needs no window.
        lambda ET, dt: dt(2026, 8, 8, 11, 0, tzinfo=ET).timestamp(),   # Saturday
        lambda ET, dt: dt(2026, 8, 9, 14, 0, tzinfo=ET).timestamp(),   # Sunday
        lambda ET, dt: dt(2027, 1, 1, 11, 0, tzinfo=ET).timestamp(),   # New Year's Day
        lambda ET, dt: dt(2026, 7, 3, 11, 0, tzinfo=ET).timestamp(),   # Independence Day (obs.)
    ],
)
def test_rth_calendar_gate_is_date_and_ticker_agnostic(non_trading_ts_fn, sym):
    """The calendar gate holds for ANY non-trading day and is independent of ticker: no symbol,
    no weekend or holiday, ever reads as a regular session."""
    from datetime import datetime

    from time_et import ET

    ts = non_trading_ts_fn(ET, datetime)
    assert ds.is_rth_trading_ts(ts) is False
    # session_is_complete is ticker-free, but assert the full desk agrees a no-session day is done.
    from time_et import et_date_str_from_ts_utc
    assert ds.session_is_complete(et_date_str_from_ts_utc(ts), time.time()) is True


@pytest.mark.parametrize("sym", ["ZZZ", "qqq", "MSFT"])
def test_weekday_premarket_bar_is_excluded_from_adv_but_bars_are_retained(tmp_path, sym):
    """The intended extended-hours path: pre-market bars exist in `price_bars_1m` BY DESIGN
    (RC-170) and are NOT deleted, but ADV excludes them because session membership is a `time_et`
    call, not a bar count. A weekday 08:00 ET bar must be skipped as non-RTH while the real RTH
    sessions still produce the ADV — and the pre-market row must remain queryable in the table."""
    import sqlite3

    pre_day, pre_ts = _weekday_premarket_stamp()
    assert ds.is_rth_trading_ts(pre_ts) is False, "a weekday pre-market slot is not RTH"

    rows = [(sym, ts, 100.0, 10_000.0) for ts in _rth_session_stamps(ds._MIN_SESSIONS_FOR_ADV)]
    rows.append((sym, pre_ts, 100.0, 5_000_000.0))   # huge pre-market turnover that must NOT count
    db = _make_bars_db(tmp_path, rows)
    res = ds.materialize_dollar_volume(db)

    assert res["skipped_non_rth_bars"] >= 1, "the weekday pre-market bar was not excluded from ADV"
    row = ds.latest_by_subject(db, time.time() + 5, "adv_dollar").get(sym.upper())
    assert row is not None
    assert row["payload"]["sessions"] == ds._MIN_SESSIONS_FOR_ADV
    assert row["value_num"] == pytest.approx(1_000_000.0), "pre-market turnover leaked into ADV"

    # the underlying pre-market bar is RETAINED, not deleted — extended hours are preserved.
    con = sqlite3.connect(str(db))
    kept = con.execute(
        "SELECT COUNT(*) FROM price_bars_1m WHERE ticker=? AND bar_end_ts_utc=?", (sym, pre_ts)
    ).fetchone()[0]
    con.close()
    assert kept == 1, "the pre-market bar was deleted from price_bars_1m; extended hours must persist"


def test_session_stamps_only_land_on_trading_days():
    """The fixture helper itself is under test now — it broke the suite before the code did."""
    from datetime import datetime

    from time_et import ET, is_trading_day_et

    for ts in _rth_session_stamps(5):
        d = datetime.fromtimestamp(ts, ET).date().isoformat()
        assert is_trading_day_et(d), f"fixture stamp landed on non-trading day {d}"


def test_decide_untouched_admissions_empty():
    """This slice is Collect and a visible surface. Nothing may reach the decision path."""
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parent.parent / "governance" / "decision_path_admissions.json"
    reg = json.loads(p.read_text(encoding="utf-8"))
    admitted = reg.get("admissions") or reg.get("admitted") or []
    assert admitted == [], f"decision path is no longer empty: {admitted}"
