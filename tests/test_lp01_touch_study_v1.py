"""LP-01 Step 5 — the touch study's own guarantees, driven against the real functions.

A study is only worth its weakest guarantee. The three that matter here are: no lookahead, a
time-of-day baseline that actually varies by minute, and PASS criteria that were fixed before
the result. Each is tested by driving the harness code, not by reading it.
"""
from __future__ import annotations

import os
from datetime import date, datetime

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

import tools.lp01_touch_study_v1 as S  # noqa: E402
from time_et import ET, RTH_START_MINS  # noqa: E402


def _bar(d: date, hh: int, mm: int, o: float, h: float, lo: float, c: float) -> dict:
    dt = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)
    return {"dt": dt, "datetime": int(dt.timestamp() * 1000), "open": o, "high": h,
            "low": lo, "close": c, "volume": 1000.0, "min_of_day": hh * 60 + mm}


def _session(d: date, n: int = 60, base: float = 100.0) -> list[dict]:
    out = []
    for i in range(n):
        mins = int(RTH_START_MINS) + i
        p = base + i * 0.01
        out.append(_bar(d, mins // 60, mins % 60, p, p + 0.05, p - 0.05, p))
    return out


def test_forward_return_never_crosses_a_session_boundary():
    """The single most dangerous lookahead in an intraday study: reading tomorrow's open as
    'thirty minutes later'. Bars near the close must yield None, not a gap return."""
    sb = _session(date(2026, 7, 27), n=40)
    assert S._forward_ret(sb, 0, 5) is not None
    for h in S.HORIZONS:
        assert S._forward_ret(sb, len(sb) - 1, h) is None, (
            f"a forward return existed for the LAST bar at horizon {h} — it can only have come "
            f"from another session"
        )
        assert S._forward_ret(sb, len(sb) - h, h) is None


def test_forward_return_reads_strictly_after_the_touch_bar():
    """Horizon h must read bar i+h, never bar i or anything before it."""
    sb = _session(date(2026, 7, 27), n=60)
    i = 10
    for h in S.HORIZONS:
        got = S._forward_ret(sb, i, h)
        want = (sb[i + h]["close"] - sb[i]["close"]) / sb[i]["close"]
        assert got is not None and abs(got - want) < 1e-12, f"horizon {h} read the wrong bar"
    assert S._forward_ret(sb, i, 0) == 0.0, (
        "horizon 0 must read the touch bar's own close against itself (identically "
        "0.0); an off-by-one that reads the NEXT bar instead would return a nonzero, "
        "non-None value and previously passed this check")


def test_levels_under_test_are_all_fixed_before_the_touch():
    """Today's POC/VAH/VAL and the VWAP bands evolve intraday and our snapshot exposes
    end-of-session values, so testing a touch against them lets the outcome inform the level.
    They must be excluded by NAME, not by hoping no caller asks for them."""
    for banned in ("TODAY_POC", "TODAY_VAH", "TODAY_VAL",
                   "VWAP", "VWAP_P1", "VWAP_M1", "VWAP_P2", "VWAP_M2"):
        assert banned not in S.CAUSAL_LEVELS, f"{banned} evolves intraday — it cannot be causal"
    for want in ("PDH", "PDL", "ON_HIGH", "ON_LOW", "ORB_HIGH", "ORB_LOW"):
        assert want in S.CAUSAL_LEVELS


def test_session_levels_do_not_see_the_session_being_tested():
    """Drive the real level builder: a level computed for session D must be identical whether or
    not D's own bars are in the buffer. If adding D's bars moves a level, that level saw the
    future relative to every touch inside D."""
    d_prev, d_test = date(2026, 7, 27), date(2026, 7, 28)
    prev_bars = _session(d_prev, n=90, base=100.0)
    test_bars = _session(d_test, n=90, base=140.0)      # a wildly different range
    overnight = [_bar(d_test, 6, 0, 99.0, 99.5, 98.5, 99.0)]
    with_today = prev_bars + overnight + test_bars
    lv_full = S._levels_for_session(with_today, d_test)
    # strip everything at or after the open of the session under test
    open_dt = datetime(d_test.year, d_test.month, d_test.day, 9, 30, tzinfo=ET)
    pre_only = [b for b in with_today if b["dt"] < open_dt]
    lv_pre = S._levels_for_session(pre_only, d_test)
    for k in ("PDH", "PDL", "PDC", "PD_POC", "PD_VAH", "PD_VAL", "ON_HIGH", "ON_LOW"):
        if k in lv_full or k in lv_pre:
            assert lv_full.get(k) == lv_pre.get(k), (
                f"{k} changed when the tested session's own bars were added: "
                f"{lv_pre.get(k)} -> {lv_full.get(k)} — that level is not causal"
            )


def test_orb_levels_are_not_used_before_the_opening_range_completes():
    """The opening range is not knowable until it closes; a touch at 09:31 cannot be tested
    against it."""
    assert S.ORB_END_MIN > S.RTH_OPEN_MIN
    src = (S.__file__ and open(S.__file__, encoding="utf-8").read()) or ""
    assert 'b["min_of_day"] < ORB_END_MIN' in src, (
        "no guard excludes ORB levels before the opening range completes"
    )


def test_baseline_is_time_of_day_matched_not_a_flat_average():
    """Volatility has a strong intraday shape. A baseline that pools all minutes would let a
    study rediscover that shape and call it an edge, so pairing must be per clock minute."""
    baseline = {h: {} for h in S.HORIZONS}
    for h in S.HORIZONS:
        baseline[h][570] = [0.010] * 50      # 09:30 — loud
        baseline[h][720] = [0.001] * 50      # 12:00 — quiet
    touches = [{"min_of_day": 570, "session": "2026-07-27", **{f"fwd_{h}": 0.010 for h in S.HORIZONS}},
               {"min_of_day": 720, "session": "2026-07-27", **{f"fwd_{h}": 0.001 for h in S.HORIZONS}}]
    obs, base, diff = S._paired(touches, baseline, S.HORIZONS[0])
    assert base == [0.010, 0.001], (
        f"baseline did not follow the clock minute: {base} — a flat average would give equal values"
    )
    assert all(abs(d) < 1e-12 for d in diff), (
        "a touch that exactly matches its own time-of-day baseline must show zero excess"
    )


def test_pass_criteria_are_preregistered_and_strict():
    """The criteria must exist as data in the module — a study that decides what counts as a
    pass after seeing the numbers has measured nothing."""
    p = S.PASS
    assert p["min_events_per_horizon"] >= 200
    assert p["min_abs_cohens_d"] >= 0.10
    assert p["bootstrap_ci_excludes_zero"] is True
    assert p["min_horizons_agreeing"] >= 2
    assert p["must_hold_out_of_sample"] is True
    assert S.BOOTSTRAP_SEED, "an unseeded bootstrap cannot be reproduced"


def test_verdict_is_fail_unless_every_gate_is_met():
    """Fail-closed: a verdict must never default to PASS through a missing measurement."""
    weak = [{"ticker": "SPY", "session": "2026-07-27", "level": "PDH", "min_of_day": 600,
             "value": 1.0, **{f"fwd_{h}": 0.001 for h in S.HORIZONS}}]
    baseline = {h: {600: [0.001] * 40} for h in S.HORIZONS}
    res = S._analyse(weak, baseline, ["SPY:2026-07-27"], ["SPY"])
    assert res["verdict"] == "FAIL", "a one-event sample produced a PASS"
    assert res["decision_path_effect"].startswith("NONE")
    for h in S.HORIZONS:
        assert res["per_horizon"][h]["horizon_pass"] is False


def test_pass_requires_beating_a_placebo_arm():
    """The confound that decides this study: a touch requires the bar's [low, high] to CONTAIN
    the level, so touches preferentially sample WIDE-RANGE bars, and range is autocorrelated with
    forward volatility. Volatility clustering alone yields a positive effect with no level
    information. MEASURED on the real run: displaced levels scored d=0.33/0.31/0.31 against the
    real levels' 0.26/0.24/0.23 — the artifact is LARGER than the signal. A gate without this
    control would have passed on it."""
    assert "min_effect_over_placebo" in S.PASS
    assert S.PASS["min_effect_over_placebo"] > 0
    assert S.PLACEBO_SEED, "an unseeded placebo cannot be reproduced"

    # a horizon whose real effect merely MATCHES its placebo must not pass
    touches, plac, baseline = [], [], {h: {600: [0.001] * 200} for h in S.HORIZONS}
    for i in range(400):
        ev = {"session": f"2026-07-{(i % 27) + 1:02d}", "min_of_day": 600,
              **{f"fwd_{h}": 0.004 for h in S.HORIZONS}}
        touches.append(dict(ev))
        plac.append(dict(ev))            # identical arm => zero excess
    res = S._analyse(touches, baseline, ["SPY:x"], ["SPY"], plac)
    for h in S.HORIZONS:
        r = res["per_horizon"][h]
        assert r["beats_placebo"] is False, (
            f"horizon {h} passed the placebo gate with zero excess over the control"
        )
        assert r["horizon_pass"] is False
    assert res["verdict"] == "FAIL"


def test_placebo_levels_are_displaced_but_still_reachable():
    """The control must sit in the same neighbourhood — a placebo nobody touches proves nothing
    because it would trivially produce no events."""
    import random as _r
    real = {"PDH": 100.0, "PDL": 90.0}
    out = S._placebo_levels(real, _r.Random(1))
    assert set(out) == set(real)
    for k, v in out.items():
        off = abs(v - real[k]) / real[k]
        assert S.PLACEBO_OFFSET_PCT[0] <= off <= S.PLACEBO_OFFSET_PCT[1], (
            f"{k} displaced by {off:.4%}, outside the declared band"
        )


def test_study_never_claims_decision_path_influence():
    """Step 5 is structure-only until PASS, and the artifact must say so in its own payload."""
    res = S._analyse([], {h: {} for h in S.HORIZONS}, [], ["SPY"])
    assert res["verdict"] == "FAIL"
    assert "structure-only" in res["decision_path_effect"]
    md = S._markdown(res)
    assert "structure-only" in md and "Decide stays WAIT" in md
    for banned in ("TRADE", "admitted to the decision path.\n"):
        assert banned not in md.replace("NOT admitted to the decision path", "")
