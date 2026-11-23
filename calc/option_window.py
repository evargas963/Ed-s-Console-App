"""The matrix's look-back: what one option volume step adds, and what a window reads per strike.

Pure functions (a Calculator). The record they read is kept by the order-flow state as each
LEVELONE_OPTIONS message arrives (app.options.order_flow.state.OrderFlowState): each contract's
volume and volatility at each minute's start, and its running totals of the steps below. A window
starts on a whole minute, the way a bar does, and says its own start (docs/derived_register.md
"Look-back window").
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from calc.confluence_composite import NOT_HELD, StrikeLookBack, iv_by_strike
from calc.l1_trade_observation import trade_sign
from option_contract import OptionContract

#: the running totals each step adds to, in this order: contracts bought (the last trade above the
#: middle of the quote in force), sold (below it), unknown (on it, or no quote in force), the
#: hedging flow in dollars of stock, and the contracts whose flow is not known (no delta or no
#: price of the stock on the message, or no side)
TOTALS = ("bought", "sold", "unknown", "flow", "unpriced")
#: the total a step's side adds it to: above the middle bought, below sold, no side unknown
SIDE_TOTAL = {1: 0, -1: 1, None: 2}
FLOW, UNPRICED = 3, 4
#: contracts a listed option is on (Schwab's multiplier for every contract the matrix reads)
CONTRACT_SHARES = 100.0


def step_totals(
    step: float,
    price: float | None,
    bid: float | None,
    ask: float | None,
    delta: float | None,
    underlying: float | None,
) -> tuple[float, float, float, float, float]:
    """Return what one rise of a contract's TOTAL_VOLUME adds to its running totals (TOTALS).

    The whole step is read by its last trade `price` against the middle of the quote in force
    when it traded (`bid`, `ask`: calc.l1_trade_observation.quote_in_force): above, bought; below,
    sold; on it or with no quote, unknown, never the tick test (decision 64, O-4). Its hedging
    flow is the signed step x Schwab's streamed `delta` x 100 x the stock price the message
    carried (`underlying`): the stock the dealers on the other side would trade, on the
    convention (dealers long calls, short puts); a step with no side, no delta or no price is
    counted apart (`unpriced`), never guessed.
    """
    side = trade_sign(price, bid, ask, None)
    adds = [0.0] * len(TOTALS)
    adds[SIDE_TOTAL[side]] += step
    if side is None or delta is None or underlying is None:
        adds[UNPRICED] += step
    else:
        adds[FLOW] += side * step * delta * CONTRACT_SHARES * underlying
    return adds[0], adds[1], adds[2], adds[3], adds[4]


@dataclass(frozen=True)
class LookBack:
    """One contract over a window: its values at the window's start and now, and the steps between.

    `volume` and `iv`: (at the start, now), each None when not known; `totals`: what its steps
    added in the window, by TOTALS. Read from the order-flow state's record
    (OrderFlowState.look_back), whose record must have begun before the window did.
    """

    volume: tuple[float | None, float | None]
    iv: tuple[float | None, float | None]
    totals: tuple[float, float, float, float, float]


def _blend(looks: list[tuple[OptionContract, LookBack]], end: int) -> float | None:
    """Return the strike's volatility blend (iv_by_strike) on its contracts' volume and volatility.

    At one end of the window (`end`: 0 its start, 1 now); None when a contract's is not known.
    """
    priced = [
        replace(c, volume=look.volume[end], volatility=look.iv[end])
        for c, look in looks
        if look.volume[end] is not None and look.iv[end] is not None
    ]
    if len(priced) != len(looks) or not priced:
        return None
    return next(iter(iv_by_strike(priced).values()))


def strike_look_back(
    contracts: list[OptionContract], held: Mapping[str, LookBack]
) -> StrikeLookBack:
    """Return one strike's readings over the window from its contracts' look-backs (`held`).

    A reading is known only when every contract at the strike was held over the whole window
    (the stream kept it from before the window began): a strike missing one is "-", never a part.
    The volatility blend is iv_by_strike's on Schwab's volatility and volume at each end.
    """
    looks = [(c, held[c.symbol]) for c in contracts if c.symbol is not None and c.symbol in held]
    if not looks or len(looks) != len(contracts):
        return NOT_HELD
    calls = puts = 0.0
    traded: float | None = 0.0
    for c, look in looks:
        start, now = look.volume
        if start is None or now is None:
            traded = None
            continue
        if c.side == "CALL":
            calls += now - start
        else:
            puts += now - start
    start_iv, now_iv = _blend(looks, 0), _blend(looks, 1)
    sums = [sum(look.totals[k] for _c, look in looks) for k in range(len(TOTALS))]
    return StrikeLookBack(
        volume=None if traded is None else (calls, puts),
        iv_change=None if start_iv is None or now_iv is None else now_iv - start_iv,
        bought=sums[0],
        sold=sums[1],
        unknown=sums[2],
        flow=sums[3],
        unpriced=sums[4],
    )
