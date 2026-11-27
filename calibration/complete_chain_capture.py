"""The chain history (DATA_FLOW decisions 1 and 7): a capture as the Recorder takes it.

Each capture the chain sweep (feed/chain_sweep.py) takes -- the first chain of each ticker begun
at or after its option market's close, once a day (chain_sweep.capture_slot) -- is a capture
message (capture_message), which the Recorder writes (stream_spine.CaptureWriter.store_capture,
store_capture_message) in one transaction, one row per expiry, compressed, with Schwab's own
underlying price, before the console hears of the chain: stored first. Schwab has no past option
chains, so a chain not saved is gone. The console reads each ticker's two newest days' captures
back (db.last_capture_per_day) as StoredCapture records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict

from instrument_identity import ticker_storage_key
from option_contract import OptionContract
from time_et import ET

#: why the daemon's captures are complete: every listed expiry, every strike. The daemon writes
#: only this basis, and rows of any other are not read. The basis is stored before the chain
#: blob, so filtering on it never reads a chain (measured: filtering on `source`, stored after
#: the blob, read every chain -- 15 s for SPY, 80 s at startup).
CAPTURE_BASIS = (
    "every_expiry_strike_range_ALL"  # the only basis read: rows of any other are partial
)


class CaptureExpiry(TypedDict):
    """One expiry of a capture: its underlyingPrice, contracts and /chains answer as received.

    `chains_answer` None: not recorded.
    """

    expiry: str
    spot: float | None
    contracts: list[dict[str, Any]]
    chains_answer: str | None


class CaptureMessage(TypedDict):
    """A capture as the Recorder takes it (topic `capture.<TICKER>`): every expiry of one chain.

    `chain_spot` / `chain_spot_ts`: the chain's one spot and its trade time.
    """

    ticker: str
    ts_utc: float
    chain_spot: float | None
    chain_spot_ts: float | None
    expiries: list[CaptureExpiry]


def capture_message(
    ticker: str,
    ts_utc: float,
    chain_spot: tuple[float | None, float | None],
    expiries: list[CaptureExpiry],
) -> CaptureMessage:
    """Return a capture as the Recorder takes it (topic `capture.<TICKER>`).

    `expiries`: each expiry's underlyingPrice, contracts and /chains answer as received;
    `chain_spot`: the chain's one spot and its trade time.
    """
    return {
        "ticker": ticker_storage_key(ticker),
        "ts_utc": ts_utc,
        "chain_spot": chain_spot[0],
        "chain_spot_ts": chain_spot[1],
        "expiries": expiries,
    }


@dataclass(frozen=True)
class StoredCapture:
    """One stored capture: a ticker's whole chain as the sweep took it, every expiry.

    `spot` is the chain's one spot with its trade time `spot_ts`: Schwab's LAST_PRICE when the
    chain was complete. A capture stored without one has no spot (None, None): the
    underlyingPrice of its /chains answers is recorded beside it and read by nothing.
    """

    et_date: str
    ts_utc: float
    spot: float | None
    spot_ts: float | None
    basis: str
    contracts: list[OptionContract]

    @classmethod
    def taken(
        cls,
        ts_utc: float,
        spot: tuple[float | None, float | None],
        contracts: list[OptionContract],
        basis: str = CAPTURE_BASIS,
    ) -> StoredCapture:
        """Return the capture of a chain begun at `ts_utc`, on its ET date; `spot` (price, time)."""
        return cls(
            et_date=datetime.fromtimestamp(ts_utc, ET).date().isoformat(),
            ts_utc=ts_utc,
            spot=spot[0],
            spot_ts=None if spot[0] is None else spot[1],  # a trade time without its price
            basis=basis,
            contracts=contracts,
        )
