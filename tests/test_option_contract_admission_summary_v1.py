"""_option_contract_admission_summary (server.py): the per-symbol admitted/active/
observed/pending/rejected accounting the operator's mandate names explicitly ("expose the
exact admitted, active, pending and rejected contracts"), and the corrected version after
an independent review found `active` conflated "has ticked at some point" with "is
currently fresh" -- a stale historical observation must read `observed`, never `active`,
using the SAME canonical staleness authority (GAMMA_SURFACE_STREAM_STALENESS_SEC) the
per-cell live/stale distinction already uses. Also proves rejected is mutually exclusive
with every other bucket -- a caller unioning buckets carelessly must never be able to
mistake a vendor refusal for any flavor of success."""
from __future__ import annotations

import time

import server
from server import _option_contract_admission_summary, ticker_storage_key

TK = ticker_storage_key("ZZZADMISSIONTEST")
_SYM_ACTIVE = "AAA   260918C00100000"
_SYM_OBSERVED_STALE = "BBB   260918C00100000"
_SYM_ADMITTED_NO_TICK = "CCC   260918C00100000"
_SYM_PENDING = "DDD   260918C00100000"
_SYM_REJECTED = "EEE   260918C00100000"


def _wire(monkeypatch, *, desired, streamed, admitted_l1, rejected, daemon_available):
    monkeypatch.setattr(server, "_desired_option_symbols_for_ticker", lambda tk: list(desired))
    monkeypatch.setattr(server, "_desired_stream_greeks_for_ticker", lambda tk: dict(streamed))
    monkeypatch.setattr(
        "app.options.order_flow.streaming.read_producer_admitted_option_contracts",
        lambda: {"LEVELONE_OPTIONS": list(admitted_l1)})
    monkeypatch.setattr(
        "app.options.order_flow.streaming.read_producer_rejected_option_contracts",
        lambda: dict(rejected))
    monkeypatch.setattr(
        "app.options.order_flow.streaming.is_option_producer_daemon_available",
        lambda: daemon_available)


def test_active_requires_a_tick_within_the_staleness_window_not_merely_ever(monkeypatch):
    now = time.time()
    fresh = {"gamma_ts_recv": now}
    stale = {"gamma_ts_recv": now - (server.GAMMA_SURFACE_STREAM_STALENESS_SEC + 5.0)}
    _wire(monkeypatch,
          desired=[_SYM_ACTIVE, _SYM_OBSERVED_STALE],
          streamed={_SYM_ACTIVE: fresh, _SYM_OBSERVED_STALE: stale},
          admitted_l1=[], rejected={}, daemon_available=True)
    d = _option_contract_admission_summary(TK)
    assert d["active"] == [_SYM_ACTIVE]
    assert d["observed"] == [_SYM_OBSERVED_STALE], (
        "a tick older than the canonical staleness window must report 'observed', "
        "never the same 'active' claim as a genuinely fresh tick")


def test_admitted_means_vendor_confirmed_subscription_with_no_tick_ever(monkeypatch):
    _wire(monkeypatch,
          desired=[_SYM_ADMITTED_NO_TICK],
          streamed={}, admitted_l1=[_SYM_ADMITTED_NO_TICK], rejected={}, daemon_available=True)
    d = _option_contract_admission_summary(TK)
    assert d["admitted"] == [_SYM_ADMITTED_NO_TICK]
    assert d["active"] == [] and d["observed"] == [] and d["pending"] == []


def test_pending_means_desired_daemon_alive_nothing_else_known(monkeypatch):
    _wire(monkeypatch,
          desired=[_SYM_PENDING],
          streamed={}, admitted_l1=[], rejected={}, daemon_available=True)
    d = _option_contract_admission_summary(TK)
    assert d["pending"] == [_SYM_PENDING]


def test_daemon_unavailable_symbol_is_omitted_from_every_bucket_not_fabricated_as_pending(monkeypatch):
    _wire(monkeypatch,
          desired=[_SYM_PENDING],
          streamed={}, admitted_l1=[], rejected={}, daemon_available=False)
    d = _option_contract_admission_summary(TK)
    assert d["daemon_available"] is False
    for bucket in ("admitted", "active", "observed", "pending"):
        assert d[bucket] == [], f"a daemon-unavailable symbol must not appear in '{bucket}'"
    assert d["rejected"] == {}


def test_rejected_is_mutually_exclusive_with_every_other_bucket(monkeypatch):
    """A symbol that is BOTH desired-and-previously-active AND now vendor-rejected (a
    real sequence: admitted, ticked, then a LATER batched reconciliation gets it
    rejected) must report ONLY in 'rejected' -- never double-counted as 'active' too,
    which would let a caller's naive union treat a refusal as a success."""
    now = time.time()
    _wire(monkeypatch,
          desired=[_SYM_REJECTED],
          streamed={_SYM_REJECTED: {"gamma_ts_recv": now}},
          admitted_l1=[_SYM_REJECTED],
          rejected={_SYM_REJECTED: "RuntimeError: refused"},
          daemon_available=True)
    d = _option_contract_admission_summary(TK)
    assert d["rejected"] == {_SYM_REJECTED: "RuntimeError: refused"}
    assert _SYM_REJECTED not in d["active"]
    assert _SYM_REJECTED not in d["observed"]
    assert _SYM_REJECTED not in d["admitted"]
    assert _SYM_REJECTED not in d["pending"]
    union = set(d["active"]) | set(d["observed"]) | set(d["admitted"]) | set(d["pending"]) | set(d["rejected"])
    assert union == {_SYM_REJECTED}, "no symbol may appear in more than one bucket"


def test_every_bucket_together_partitions_the_desired_set_exactly_once(monkeypatch):
    now = time.time()
    _wire(monkeypatch,
          desired=[_SYM_ACTIVE, _SYM_OBSERVED_STALE, _SYM_ADMITTED_NO_TICK, _SYM_PENDING, _SYM_REJECTED],
          streamed={
              _SYM_ACTIVE: {"gamma_ts_recv": now},
              _SYM_OBSERVED_STALE: {"gamma_ts_recv": now - (server.GAMMA_SURFACE_STREAM_STALENESS_SEC + 5.0)},
          },
          admitted_l1=[_SYM_ADMITTED_NO_TICK],
          rejected={_SYM_REJECTED: "RuntimeError: refused"},
          daemon_available=True)
    d = _option_contract_admission_summary(TK)
    seen = []
    for bucket in ("active", "observed", "admitted", "pending"):
        seen.extend(d[bucket])
    seen.extend(d["rejected"].keys())
    assert sorted(seen) == sorted(
        [_SYM_ACTIVE, _SYM_OBSERVED_STALE, _SYM_ADMITTED_NO_TICK, _SYM_PENDING, _SYM_REJECTED])
    assert len(seen) == len(set(seen)), "no symbol may be counted twice across buckets"
