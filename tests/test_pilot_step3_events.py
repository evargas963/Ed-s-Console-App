"""DB-free tests for pilot_step3 CUSUM events and EWM session behavior."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.time_et import ET as _ET
def _minimal_prereg(**overrides):
    """Minimal prereg dict for generate_events (subset of prereg_v1.json)."""
    base = {
        "candidate_generator": {
            "candidate_generator_id": "TEST",
            "cusum": {"k": 0.7, "h_threshold": 2.0},
            "ewm_span_bars": 20,
            "daily_ewm_reset": "DEPRECATED",
            "sigma_contract": {
                "contract_id": "CONTINUOUS_EWM_REL_FLOOR_V1",
                "ewm_span_bars": 20,
                "relative_floor": {"enabled": True, "M": 30, "phi": 0.25},
            },
            "exclude_first_30min_rth": True,
            "min_bar_gap": 1,
            "sma": {"fast": 2, "slow": 3, "near_equal_tolerance": 1e-9},
            "side_rule": "SMA_CROSS_TREND_ONLY_V1",
            "trend_following_only": True,
        }
    }
    cg = {**base["candidate_generator"], **overrides.get("candidate_generator", {})}
    return {"candidate_generator": cg}


def test_cusum_fires_on_synthetic_spike():
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.event_generation import generate_events

    bars = []
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=_ET)
    # Need a bar after the signal bar (generate_events skips fire when i is last index).
    for i in range(121):
        if i < 119:
            c = 100.0 + 0.01 * i
        elif i == 119:
            c = 106.0
        else:
            c = 106.0
        ts = (t0 + timedelta(minutes=i)).timestamp()
        bars.append(Bar1m(ts, ts + 60.0, c, c + 0.2, c - 0.2, c, 1.0))
    prereg = _minimal_prereg()
    events, _stats = generate_events(bars, prereg)
    assert len(events) >= 1
    assert events[-1].signal_bar_index == 119


def test_first_30min_rth_suppresses_events():
    import json
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.event_generation import generate_events

    bars = []
    t0 = datetime(2024, 6, 4, 9, 30, tzinfo=_ET)
    for i in range(10):
        c = 100.0 + (3.0 if i >= 3 else 0.0)
        ts = (t0 + timedelta(minutes=i)).timestamp()
        bars.append(Bar1m(ts, ts + 60.0, c, c + 0.5, c - 0.5, c, 1.0))
    for i in range(10, 130):
        c = 100.0
        ts = (t0 + timedelta(minutes=i)).timestamp()
        bars.append(Bar1m(ts, ts + 60.0, c, c + 0.01, c - 0.01, c, 1.0))
    prereg_on = _minimal_prereg()
    ev_on, _ = generate_events(bars, prereg_on)
    prereg_off = json.loads(json.dumps(prereg_on))
    prereg_off["candidate_generator"]["exclude_first_30min_rth"] = False
    ev_off, _ = generate_events(bars, prereg_off)
    assert len(ev_off) >= len(ev_on)


def test_legacy_daily_reset_ewm_drops_at_new_et_day():
    """Legacy helper: per-day EWM std restarts (diagnostic baseline only)."""
    from research.pilot_step3.event_generation import _ewm_std_by_rth_day_legacy
    import numpy as np

    t_d1 = datetime(2024, 6, 5, 11, 0, tzinfo=_ET).timestamp()
    t_d2 = datetime(2024, 6, 6, 11, 0, tzinfo=_ET).timestamp()
    starts = np.array([t_d1 + i * 60 for i in range(40)] + [t_d2 + i * 60 for i in range(40)])
    c1 = np.array([100.0 + 4.0 * ((-1) ** i) for i in range(40)], dtype=float)
    c2 = np.full(40, 100.0, dtype=float)
    closes = np.concatenate([c1, c2])
    sigma = _ewm_std_by_rth_day_legacy(closes, starts, span=10)
    idx_d2 = 40
    assert np.isfinite(sigma[idx_d2])
    assert sigma[idx_d2] < sigma[idx_d2 - 1]


def test_first_30min_suppressed_on_two_et_sessions():
    """Volatile path only in 9:30–9:59 ET on a second session; excluded => no events; else fires."""
    import json
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.event_generation import generate_events

    bars = []
    d1 = datetime(2024, 6, 10, 10, 0, tzinfo=_ET)
    for i in range(90):
        c = 100.0
        ts = (d1 + timedelta(minutes=i)).timestamp()
        bars.append(Bar1m(ts, ts + 60.0, c, c + 0.01, c - 0.01, c, 1.0))
    d2_open = datetime(2024, 6, 11, 9, 30, tzinfo=_ET)
    for i in range(30):
        c = 100.0 + (12.0 if i % 2 == 0 else -10.0)
        ts = (d2_open + timedelta(minutes=i)).timestamp()
        bars.append(Bar1m(ts, ts + 60.0, c, c + 2.0, c - 2.0, c, 1.0))
    t_tail = datetime(2024, 6, 11, 10, 0, tzinfo=_ET)
    ts = t_tail.timestamp()
    bars.append(Bar1m(ts, ts + 60.0, 100.0, 100.01, 99.99, 100.0, 1.0))

    base = _minimal_prereg()["candidate_generator"]
    cg_on = {
        **base,
        "cusum": {"k": 0.005, "h_threshold": 0.04},
        "ewm_span_bars": 5,
        "sigma_contract": {
            "contract_id": "CONTINUOUS_EWM_REL_FLOOR_V1",
            "ewm_span_bars": 5,
            "relative_floor": {"enabled": True, "M": 15, "phi": 0.25},
        },
        "min_bar_gap": 1,
        "exclude_first_30min_rth": True,
        "sma": {"fast": 2, "slow": 3, "near_equal_tolerance": 1e-9},
    }
    pr_on = {"candidate_generator": cg_on}
    ev_on, _ = generate_events(bars, pr_on)
    pr_off = json.loads(json.dumps(pr_on))
    pr_off["candidate_generator"]["exclude_first_30min_rth"] = False
    ev_off, _ = generate_events(bars, pr_off)
    assert len(ev_on) == 0
    assert len(ev_off) >= 1


def test_sma_near_equal_drops_and_counts():
    from research.pilot_step3.data_loader import Bar1m
    from research.pilot_step3.event_generation import generate_events

    bars = []
    t0 = datetime(2024, 6, 7, 11, 0, tzinfo=_ET)
    for i in range(100):
        c = 100.0 + (0.5 if i % 5 == 0 else 0.0) * ((-1) ** i)
        ts = (t0 + timedelta(minutes=i)).timestamp()
        bars.append(Bar1m(ts, ts + 60.0, c, c + 0.5, c - 0.5, c, 1.0))
    base_cg = _minimal_prereg()["candidate_generator"]
    cg = {
        **base_cg,
        "cusum": {"k": 0.01, "h_threshold": 0.15},
        "ewm_span_bars": 10,
        "exclude_first_30min_rth": False,
        "min_bar_gap": 1,
        "sma": {"fast": 3, "slow": 3, "near_equal_tolerance": 1e-9},
    }
    prereg = {"candidate_generator": cg}
    _ev, stats = generate_events(bars, prereg)
    assert stats["dropped_none_sma_near_equal"] >= 1
