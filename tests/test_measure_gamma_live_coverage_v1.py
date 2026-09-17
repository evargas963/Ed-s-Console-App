"""tools/measure_gamma_live_coverage.py's own measurement-negative-control lock (2026-09-17
mandate, 'REPAIR THE MEASUREMENT DEFECTS'). This harness is the thing that will produce the
RTH acceptance proof -- if IT can be fooled into reporting success on a run that actually
failed, every downstream proof it signs off on is worthless. Every test here drives
`measure_one` against a scripted fake HTTP layer (never a live server) and asserts the
harness calls a genuine failure a failure, never quietly relabeling it as a pass.

No live server, no real time.sleep: `_get`/`_post`/`_wide_chain_symbols` are monkeypatched to
a small in-memory fake, and POLL_INTERVAL_SEC / MAX_WAIT_SEC are shrunk so a "never resolves"
case runs in well under a second instead of the real 30s.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.measure_gamma_live_coverage as M  # noqa: E402

TICKER = "ZZZMEASURETEST"
SYM_A = "AAA   260918C00100000"
SYM_B = "BBB   260918C00100000"
BASE = "http://fake"


def _surface(seq, gex_values, admission):
    return {
        "surface_seq": seq,
        "cells": [{"gex": v} for v in gex_values],
        "stream_coverage": {"meets_live_requirement": True},
        "cell_stream_state_counts": {},
        "contract_admission": admission,
    }


def _admission(*, admitted=(), active=(), observed=(), rejected=None, daemon_available=True):
    return {
        "daemon_available": daemon_available,
        "admitted": list(admitted), "active": list(active), "observed": list(observed),
        "rejected": dict(rejected or {}),
    }


class _FakeWorld:
    """A scripted sequence of gamma-surface reads: the first `_get` call in a test is the
    pre-demand baseline; every call after that pops the next canned surface (repeating the
    last one once the script runs out, so a "never resolves" case just keeps returning the
    same stuck state until MAX_WAIT_SEC expires)."""

    def __init__(self, baseline, surfaces):
        self.baseline = baseline
        self.surfaces = list(surfaces)
        self.calls = 0

    def get(self, path):
        assert "/api/options/gamma-surface" in path
        self.calls += 1
        if self.calls == 1:
            return self.baseline
        idx = min(self.calls - 2, len(self.surfaces) - 1)
        return self.surfaces[idx]


def _run(monkeypatch, world, symbols=(SYM_A, SYM_B)):
    monkeypatch.setattr(M, "_wide_chain_symbols", lambda base, ticker, scope: list(symbols))
    monkeypatch.setattr(M, "_get", lambda base, path: world.get(path))
    monkeypatch.setattr(M, "_post", lambda base, path, payload: {})
    monkeypatch.setattr(M, "POLL_INTERVAL_SEC", 0.0)
    monkeypatch.setattr(M, "MAX_WAIT_SEC", 0.2)
    return M.measure_one(BASE, TICKER, "auto")


def test_rejected_symbol_never_reports_accepted_or_active(monkeypatch):
    baseline = _surface(1, [10.0], _admission())
    stuck = _surface(2, [20.0], _admission(
        active=[SYM_A], rejected={SYM_B: "RuntimeError: refused"}))
    r = _run(monkeypatch, _FakeWorld(baseline, [stuck]))
    assert r["time_to_accepted_sec"] is None, (
        "a rejected symbol must make full acceptance of the requested set impossible")
    assert r["time_to_active_sec"] is None
    assert r["ok"] is False
    assert SYM_B in r["admission_snapshot"]["rejected"]


def test_stale_observed_symbol_never_reports_fresh_active(monkeypatch):
    baseline = _surface(1, [10.0], _admission())
    stuck = _surface(2, [20.0], _admission(active=[SYM_A], observed=[SYM_B]))
    r = _run(monkeypatch, _FakeWorld(baseline, [stuck]))
    assert r["time_to_active_sec"] is None, (
        "a stale 'observed' symbol must never satisfy the freshness-gated 'active' metric")
    assert r["time_to_accepted_sec"] is not None, (
        "observed is still a real vendor acknowledgement, so accepted (not active) may pass"
    )


def test_unchanged_surface_seq_never_reports_first_usable_render(monkeypatch):
    baseline = _surface(5, [10.0], _admission())
    stuck = _surface(5, [10.0], _admission(active=[SYM_A, SYM_B]))
    r = _run(monkeypatch, _FakeWorld(baseline, [stuck]))
    assert r["first_usable_render_ms"] is None, (
        "an unchanged surface_seq must never be reported as a new render")
    assert r["ok"] is False


def test_changed_sequence_but_unchanged_gex_fails_ok(monkeypatch):
    baseline = _surface(1, [10.0, 20.0], _admission())
    newer_same_gex = _surface(2, [10.0, 20.0], _admission(active=[SYM_A, SYM_B]))
    r = _run(monkeypatch, _FakeWorld(baseline, [newer_same_gex]))
    assert r["first_usable_render_ms"] is not None, "the generation itself did advance"
    assert r["gex_changed"] is False, (
        "a newer generation with byte-identical GEX cells must not count as a live change")
    assert r["ok"] is False, (
        "changed sequence + unchanged GEX dollars must never pass -- that is exactly the "
        "gap between 'something recomputed' and 'the operator's sentinel actually moved'")


def test_wrong_symbol_admitted_does_not_cover_a_different_requested_symbol(monkeypatch):
    """A cross-contamination guard: if the admission snapshot reports some OTHER symbol as
    active (never one of `requested`), that must never be misread as covering SYM_B."""
    baseline = _surface(1, [10.0], _admission())
    wrong_symbol_active = _surface(2, [20.0], _admission(active=[SYM_A, "NOTREQUESTED   X"]))
    r = _run(monkeypatch, _FakeWorld(baseline, [wrong_symbol_active]))
    assert r["time_to_accepted_sec"] is None
    assert r["time_to_active_sec"] is None
    assert r["ok"] is False
    assert SYM_B in r["admission_snapshot"]["unresolved"], (
        "SYM_B must show up as genuinely unresolved, never silently satisfied by a "
        "different symbol's admission")


def test_daemon_unavailable_fails_ok_even_if_everything_else_looks_fine(monkeypatch):
    baseline = _surface(1, [10.0], _admission())
    looks_fine_but_daemon_down = _surface(2, [20.0], _admission(
        active=[SYM_A, SYM_B], daemon_available=False))
    r = _run(monkeypatch, _FakeWorld(baseline, [looks_fine_but_daemon_down]))
    assert r["ok"] is False, "a daemon-unavailable reading must fail 'ok' even with a fresh render"
    assert any("UNAVAILABLE" in n for n in r["notes"])


def test_one_withheld_contract_fails_ok(monkeypatch):
    """SYM_A resolves cleanly; SYM_B is simply never mentioned by the producer at all --
    the mandate's own 'one withheld contract -> nonzero' negative control."""
    baseline = _surface(1, [10.0], _admission())
    only_a_resolves = _surface(2, [20.0], _admission(active=[SYM_A]))
    r = _run(monkeypatch, _FakeWorld(baseline, [only_a_resolves]))
    assert r["ok"] is False
    assert SYM_B in r["admission_snapshot"]["unresolved"]
    assert any("never reached" in n for n in r["notes"])


def test_observed_only_never_passes_ok(monkeypatch):
    """Stale observed ticks are vendor acknowledgements, not live coverage."""
    baseline = _surface(1, [10.0, 20.0], _admission())
    observed_only = _surface(2, [11.0, 20.0], _admission(observed=[SYM_A, SYM_B]))
    r = _run(monkeypatch, _FakeWorld(baseline, [observed_only]))
    assert r["ok"] is False
    assert r["time_to_active_sec"] is None


def test_admitted_only_never_passes_ok(monkeypatch):
    baseline = _surface(1, [10.0, 20.0], _admission())
    admitted_only = _surface(2, [11.0, 20.0], _admission(admitted=[SYM_A, SYM_B]))
    r = _run(monkeypatch, _FakeWorld(baseline, [admitted_only]))
    assert r["ok"] is False
    assert r["time_to_active_sec"] is None


def test_meets_live_requirement_false_fails_ok(monkeypatch):
    baseline = _surface(1, [10.0, 20.0], _admission())
    not_live = _surface(2, [11.0, 20.0], _admission(active=[SYM_A, SYM_B]))
    not_live["stream_coverage"] = {"meets_live_requirement": False}
    r = _run(monkeypatch, _FakeWorld(baseline, [not_live]))
    assert r["ok"] is False


def test_genuinely_clean_run_passes_ok(monkeypatch):
    """The positive control: without this, every negative-control test above could be
    trivially satisfied by a harness that always returns ok=False."""
    baseline = _surface(1, [10.0, 20.0], _admission())
    clean = _surface(2, [11.0, 20.0], _admission(active=[SYM_A, SYM_B]))
    r = _run(monkeypatch, _FakeWorld(baseline, [clean]))
    assert r["ok"] is True
    assert r["time_to_accepted_sec"] is not None
    assert r["time_to_active_sec"] is not None
    assert r["gex_changed"] is True
    assert r["notes"] == []


def test_main_exits_nonzero_when_any_ticker_scope_fails(monkeypatch, tmp_path):
    results = [
        {"ok": True, "requested_contract_count": 2, "time_to_accepted_sec": 0.1,
         "time_to_active_sec": 0.2, "gex_changed": True, "stream_coverage": {}, "notes": []},
        {"ok": False, "requested_contract_count": 2, "time_to_accepted_sec": None,
         "time_to_active_sec": None, "gex_changed": False, "stream_coverage": {},
         "notes": ["surface never advanced"]},
    ]
    calls = iter(results)
    monkeypatch.setattr(M, "_get", lambda base, path: {"git_sha": "deadbeef", "code_drift": False})
    monkeypatch.setattr(M, "measure_one", lambda base, ticker, scope: next(calls))
    monkeypatch.setattr(sys, "argv", [
        "measure_gamma_live_coverage.py", "--tickers", "SPY,AAPL", "--scopes", "auto",
        "--out", str(tmp_path / "report.json")])
    assert M.main() == 1, "a single failed (ticker, scope) must make the whole run exit nonzero"


def test_main_exits_zero_when_every_ticker_scope_passes(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "_get", lambda base, path: {"git_sha": "deadbeef", "code_drift": False})
    monkeypatch.setattr(M, "measure_one", lambda base, ticker, scope: {
        "ok": True, "requested_contract_count": 1, "time_to_accepted_sec": 0.1,
        "time_to_active_sec": 0.1, "gex_changed": True, "stream_coverage": {}, "notes": []})
    monkeypatch.setattr(sys, "argv", [
        "measure_gamma_live_coverage.py", "--tickers", "SPY", "--scopes", "auto",
        "--out", str(tmp_path / "report.json")])
    assert M.main() == 0
