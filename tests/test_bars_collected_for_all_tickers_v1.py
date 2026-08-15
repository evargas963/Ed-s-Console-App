"""RC-69: the 1-minute accumulator must build bars from the collection service's call shape.

SUPERSEDED SCOPE NOTE: an earlier version of this file asserted that
`_base_money_path_capture_one` fed and persisted bars. That was a WRONG FIX — it moved bar
collection from one capture path to another instead of making it a service, leaving collection
riding a snapshot writer and covering only the 3 sentinel tickers of 57 enrolled. The
architecture assertions now live in tests/test_bars_collection_service_v1.py; what remains here
is the numeric contract of the accumulator itself.
"""
from __future__ import annotations


def test_accumulator_builds_bars_from_collection_service_call_shape():
    """Drive the REAL accumulator exactly as _bars_collect_one calls it
    (ticker, price, ts, total_volume=) and prove completed bars appear."""
    import os

    os.environ.setdefault("PYTEST_CURRENT_TEST", "rc69")
    import server as srv

    tk = "ZZRC69"
    base = 1_785_168_000.0
    for i, px in enumerate((740.0, 740.5, 741.0, 740.8)):
        srv._candles_1m.tick(tk, px, base + i * 60, total_volume=1000 * (i + 1))
    bars = srv._candles_1m.get_bars(tk)
    assert len(bars) >= 3, f"expected completed bars from sequential ticks, got {len(bars)}"
    assert bars[0].open == 740.0


def test_accumulator_rejects_a_nonpositive_price_at_the_service_boundary(monkeypatch):
    """_bars_collect_one refuses to tick on a missing/zero price — absence must read as
    absence, never a fabricated bar.

    RC-308: this asserted the SPELLING of the guard, `"float(px) <= 0" in seg`, read out of
    server.py's source. RC-38 then replaced that expression with
    `numeric_contract.float_positive_or_none`, which is STRICTER — it rejects NaN and inf as
    well as zero and negatives — and the test went red on the improvement while a genuine
    removal of the guard would have looked exactly the same. So it now drives the real
    function and watches whether a tick happens.
    """
    import server as srv

    ticked: list[tuple] = []

    class _Q:
        status_code = 200

        def __init__(self, node):
            self._node = node

        def json(self):
            return {"ZZGUARD": self._node}

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv._candles_1m, "tick",
                        lambda *a, **k: ticked.append((a, k)))

    def _drive(quote: dict) -> str:
        # The real Schwab per-ticker node shape, so the real parser runs too.
        monkeypatch.setattr(srv, "_memoized_quote_response",
                            lambda tk, client=None: _Q({"quote": quote}))
        return srv._bars_collect_one("ZZGUARD")

    # Every shape of "no usable price" must reach the same honest verdict and tick nothing.
    for quote in ({}, {"lastPrice": 0.0, "mark": 0.0},
                  {"lastPrice": -3.5, "mark": None},
                  {"lastPrice": float("nan"), "mark": float("nan")},
                  {"lastPrice": float("inf"), "mark": None}):
        assert _drive(quote) == "skip:no_price", f"a bar was admitted for {quote}"
    assert ticked == [], f"the accumulator was ticked on a non-price: {ticked}"

    # Positive control: a real price DOES tick, so the guard is not simply refusing everything.
    assert _drive({"lastPrice": 742.31}) != "skip:no_price", "the guard rejects a real price"
    assert len(ticked) == 1 and ticked[0][0][1] == 742.31
