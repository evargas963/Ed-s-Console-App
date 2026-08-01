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
    """
    from datetime import datetime, timedelta

    from time_et import ET, is_rth_ts_utc

    out: list[float] = []
    probe = datetime.now(ET).date()
    guard = 0
    while len(out) < n and guard < 40:
        guard += 1
        ts = datetime(probe.year, probe.month, probe.day, 11, 0, tzinfo=ET).timestamp()
        if is_rth_ts_utc(ts):
            out.append(ts)
        probe = probe - timedelta(days=1)
    assert len(out) == n, "could not find enough regular sessions in the last 40 days"
    return list(reversed(out))


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

    from time_et import ET, is_rth_ts_utc

    db = tmp_path / "d.db"
    ds.ensure_schema(db)
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    # Three RTH sessions of equal size, each shadowed by a huge pre-market bar.
    day = datetime.now(ET).date()
    sessions = 0
    probe = day
    while sessions < 3:
        rth = datetime(probe.year, probe.month, probe.day, 11, 0, tzinfo=ET).timestamp()
        pre = datetime(probe.year, probe.month, probe.day, 5, 0, tzinfo=ET).timestamp()
        if is_rth_ts_utc(rth) and not is_rth_ts_utc(pre):
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


def test_decide_untouched_admissions_empty():
    """This slice is Collect and a visible surface. Nothing may reach the decision path."""
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parent.parent / "governance" / "decision_path_admissions.json"
    reg = json.loads(p.read_text(encoding="utf-8"))
    admitted = reg.get("admissions") or reg.get("admitted") or []
    assert admitted == [], f"decision path is no longer empty: {admitted}"
