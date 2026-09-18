"""Canonical typed contracts for a money-path field observation (RC-REHAB-1).

Repo-wide architectural rehab, Phase 1: this repo's most persistent "same name,
semantically different meaning" defects (found and repaired across this rehab's earlier
no-fallback work) share one root cause: a market field's provenance -- WHERE a value came
from, WHEN it was observed, HOW stale it may be -- traveled as loose, ad hoc dict keys that
every producer spelled slightly differently: `spot_source` vs `bid_source` vs
`quote_ts_clock` vs `fast_generation_id` vs `exchange_quote_ts`, no two producers agreeing
on the full set, none of it typed.

This module is the ONE typed shape for "a single field's observation" and "a quote's
observed fields" going forward. It does not, by itself, migrate every producer/consumer --
that is Phase 2's job, one vertical at a time. What it DOES do: give every NEW producer a
real type to construct instead of another ad hoc dict, and give `QuoteObservation` a
`to_legacy_dict()` so the first real producer (`live_market_plane.py`) can store this typed
object as its single source of truth while old, not-yet-migrated consumers keep reading the
dict shape they already expect -- a transitional view, not a second authority: the dict is
always DERIVED from the typed object, never independently constructed.

`to_legacy_dict()` is verified field-for-field against `live_market_plane.py`'s
`record_from_level_one_equity` (the one real producer today, read in full for this
revision) -- not against this module's own earlier assumptions. Two provenance strings this
producer computes independently today -- top-level `spread_source` (which MID FORMULA fed
the fraction) and `quote_source_detail["spread"]` (a raw literal, `"schwab_bid_ask"`,
naming which RAW FIELDS were present) -- are DELIBERATELY reproduced as two distinct
strings here rather than unified, even though they describe overlapping ground. Unifying
them is real, in-scope work for Phase 2's order-flow-vertical sweep (this module's own
Phase-2 target list already names duplicate spread-provenance computations); doing it here,
inside a Phase 1 contract module with no consumer sweep behind it, would be an undisclosed
behavior change smuggled into what is supposed to be a faithful transitional shim.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class FreshnessState(str, Enum):
    """The three, and only three, states a field observation may be in. A field is never
    silently "probably fine" -- it is one of these, always disclosed, never inferred by a
    consumer from the mere presence of a numeric value."""

    LIVE = "live"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class FieldObservation:
    """One field's value with its full provenance -- the unit this rehab keeps finding
    conflated (a stale value presented with no state distinct from a live one; a value's
    source silently swapped for a different meaning under the same field name).

    `value` is None exactly when `state` is UNAVAILABLE -- there is no other legitimate
    reason for a None value on an observation that exists at all. A FieldObservation is
    never constructed to paper over a missing/failed read; the caller that cannot resolve
    a field constructs `FieldObservation.unavailable(...)`, not a None-valued "live" one.

    Scope note: this None-iff-UNAVAILABLE invariant is sound for the fields Phase 1 models
    (spot/bid/ask/mark -- always positive when present, never legitimately zero or
    negative). It will NOT generalize as-is to a field where zero or a negative number is a
    legitimate live value (a signed delta, a percent change) -- that case needs a distinct
    sentinel-vs-None design and is deliberately deferred until a real producer of such a
    field is actually typed (Phase 2+), not guessed at here.

    `generation` is deliberately NOT a field on this class: this producer's only real
    generation counter (`next_fast_generation()` in `live_market_plane.py`) increments once
    per QUOTE TICK, not once per field, so quote-level bookkeeping belongs on
    `QuoteObservation.fast_generation_id`, not duplicated per-field here with no real
    relationship to it.
    """

    value: Optional[float]
    source: str
    native_ts: Optional[float]
    received_ts: float
    state: FreshnessState

    def __post_init__(self) -> None:
        if self.state is FreshnessState.UNAVAILABLE and self.value is not None:
            raise ValueError(
                f"FieldObservation: state=UNAVAILABLE but value={self.value!r} -- "
                f"an unavailable field must carry no value, never a stale/default number "
                f"wearing the unavailable label"
            )
        if self.state is not FreshnessState.UNAVAILABLE and self.value is None:
            raise ValueError(
                f"FieldObservation: state={self.state.value} but value is None -- "
                f"a live or stale field must carry the value it is live/stale ABOUT; "
                f"use FieldObservation.unavailable(...) when there is no value"
            )
        if self.value is not None and self.value <= 0:
            raise ValueError(
                f"FieldObservation: value={self.value!r} is not positive -- this type "
                f"models spot/bid/ask/mark, which are never legitimately zero or negative "
                f"when present (the real producer gates a MARK read on `mark_f > 0` before "
                f"ever using it as a mid: live_market_plane.py:167). A zero/negative value "
                f"reaching here is a bug in whatever resolved it, not a value this type "
                f"should carry silently into a division (to_legacy_dict's spread fraction "
                f"divides by `mark.value`) or into a sign-flipped spread with no error at "
                f"all. Construct FieldObservation.unavailable(...) instead of passing a "
                f"non-positive read through."
            )

    @classmethod
    def unavailable(cls, *, source: str, received_ts: float) -> "FieldObservation":
        """The explicit, only-legitimate shape for "this field could not be resolved."
        `source` still names WHICH resolution path was attempted and failed -- unavailable
        is a fact about the attempt, not an excuse to drop provenance too."""
        return cls(
            value=None, source=source, native_ts=None,
            received_ts=received_ts, state=FreshnessState.UNAVAILABLE,
        )

    @classmethod
    def live(cls, value: float, *, source: str, native_ts: Optional[float],
              received_ts: float) -> "FieldObservation":
        return cls(
            value=value, source=source, native_ts=native_ts,
            received_ts=received_ts, state=FreshnessState.LIVE,
        )

    @classmethod
    def stale(cls, value: float, *, source: str, native_ts: Optional[float],
              received_ts: float) -> "FieldObservation":
        """A carried-forward value from a PRIOR observation, explicitly marked stale --
        never silently re-presented under the LIVE state.

        Caller contract for `native_ts`: pass the PRIOR observation's own `native_ts`
        through unchanged, not a freshly-read clock value for the current tick. A carried
        value's native timestamp is when it was ORIGINALLY observed; re-stamping it with
        the current tick's clock would silently make an old print look freshly timestamped,
        exactly the defect class this type exists to make impossible. (Today's real
        producer, `live_market_plane.py:119-126`, carries the value forward but does not
        yet mark it stale at all -- wiring this constructor into that call site, so
        `carried_forward` finally reflects reality instead of the current hardcoded
        `False`, is deferred to the Phase 1 wiring step, not done as a silent side effect of
        introducing this type.)
        """
        return cls(
            value=value, source=source, native_ts=native_ts,
            received_ts=received_ts, state=FreshnessState.STALE,
        )


@dataclass(frozen=True)
class QuoteObservation:
    """A ticker's spot/bid/ask/mark as independently-provenanced FieldObservations, plus
    the identity and bookkeeping every consumer of the old `live_market_plane` dict shape
    already expects. This is the canonical in-process quote-plane row going forward --
    `live_market_plane.py` stores one of these per ticker; `to_legacy_dict()` is its
    transitional view for consumers not yet migrated (Phase 2).

    `mark` is the vendor-supplied mid (Schwab's own MARK field) -- a real fourth observed
    field in today's producer, independent of bid/ask, and the ONLY source `quote_mid`
    currently has (`live_market_plane.py:162-174`: `quote_mid`/`mid_source` are set if and
    only if a positive `MARK` was read; a bid/ask-derived mid is a live ternary branch in
    the spread-source labeling but is never actually produced by this producer today).
    Omitting `mark` as its own field -- as the first draft of this module did -- is what
    made `to_legacy_dict()` silently drop `quote_mid`/`mid_source`/`spread`/`spread_pts`/
    `spread_source`/`spread_pts_source`, fields real consumers (`merge_into_state`,
    `apply_l1_live_quote_overlay`) branch on with `if k in q and q[k] is not None`.

    `quote_ts` is the resolved exchange clock reading for THIS tick (`exchange_quote_ts` in
    the legacy dict) and `quote_ts_clock` names WHICH raw exchange field resolved it --
    `"QUOTE_TIME_MILLIS"`, `"TRADE_TIME_MILLIS_proxy"` (a labeled fallback, never silently
    conflated with a true quote clock -- see M6 in `live_market_plane.py:132-139`), or
    `"unavailable"`. Both are QUOTE-level facts, resolved once per tick from the tick's own
    raw payload (`live_market_plane.py:140-150`) independent of whether spot/bid/ask
    themselves were freshly read or carried forward from a prior tick -- deliberately NOT
    read off any single FieldObservation's `native_ts`. A carried-forward spot's
    `native_ts` correctly FREEZES at its original observation time per `FieldObservation.
    stale()`'s own contract above; production's exchange clock does not freeze along with
    it (`live_market_plane.py:119-128` decides only `spot_f`/`spot_source`, never touches
    the clock resolution that follows at 140-150) -- collapsing the two would make
    `exchange_quote_ts` silently stop advancing on a bid/ask-only tick where production
    still advances it, exactly the kind of same-name-different-meaning defect this module
    exists to prevent.

    `previous_{spot,bid,ask}_available` are producer-side bookkeeping about the PRIOR tick,
    not a property of the current observation -- they do not fit inside `FieldObservation`
    either. The producer (not this type) is responsible for populating them from its own
    prior-row state.
    """

    ticker: str
    spot: FieldObservation
    bid: FieldObservation
    ask: FieldObservation
    mark: FieldObservation
    ingestion: str
    quote_ts: Optional[float]
    quote_ts_clock: str
    fast_generation_id: int
    server_received_ts: float
    previous_spot_available: bool
    previous_bid_available: bool
    previous_ask_available: bool

    def to_legacy_dict(self) -> dict[str, Any]:
        """The exact dict shape `live_market_plane.record_from_level_one_equity` builds
        today, derived entirely from this object -- never a second, independently-
        maintained construction. Every key below is cross-checked against that function's
        real `out` dict (`live_market_plane.py:177-218`), not assumed."""
        spread_frac: Optional[float] = None
        spread_source: Optional[str] = None
        if (
            self.mark.value is not None
            and self.bid.value is not None
            and self.ask.value is not None
        ):
            spread_frac = (self.ask.value - self.bid.value) / self.mark.value
            if self.mark.source == "schwab_streaming_mark":
                spread_source = "derived_bid_ask_fraction_schwab_mark_denom"
            elif self.mark.source == "derived_bid_ask_mid":
                spread_source = "derived_bid_ask_mid_fraction"

        have_bid_ask = self.bid.value is not None and self.ask.value is not None
        spread_pts = round(self.ask.value - self.bid.value, 4) if have_bid_ask else None
        spread_pts_source = "derived_bid_ask_pts" if have_bid_ask else None

        out: dict[str, Any] = {
            "ticker": self.ticker,
            "spot": self.spot.value,
            "bid": self.bid.value,
            "ask": self.ask.value,
            "spot_disp": f"{self.spot.value:.2f}" if self.spot.value is not None else "—",
            "bid_disp": f"{self.bid.value:.2f}" if self.bid.value is not None else "—",
            "ask_disp": f"{self.ask.value:.2f}" if self.ask.value is not None else "—",
            "quote_mid": self.mark.value,
            "mid_source": self.mark.source if self.mark.value is not None else None,
            "spread": spread_frac,
            "spread_pts": spread_pts,
            "spread_source": spread_source,
            "spread_pts_source": spread_pts_source,
            "fast_generation_id": self.fast_generation_id,
            "exchange_quote_ts": self.quote_ts,
            "quote_time_source": self.ingestion if self.quote_ts is not None else "unavailable",
            "server_received_ts": self.server_received_ts,
            "quote_ingestion": self.ingestion,
            "quote_source_detail": {
                "spot": self.spot.source if self.spot.value is not None else None,
                "bid": self.bid.source if self.bid.value is not None else None,
                "ask": self.ask.source if self.ask.value is not None else None,
                "mid": self.mark.source if self.mark.value is not None else "unavailable_missing_mark_and_bid_ask",
                "spread": "schwab_bid_ask" if have_bid_ask else "unavailable_missing_bid_or_ask",
                "quote_ts": self.quote_ts_clock,
                "carried_forward": self.spot.state is FreshnessState.STALE,
                "previous_spot_available": self.previous_spot_available,
                "previous_bid_available": self.previous_bid_available,
                "previous_ask_available": self.previous_ask_available,
            },
        }
        return out
