"""Prices and chart bars straight from the capture daemon to the browser over WebSocket.

The daemon owns the Schwab connection. This server keeps the latest value of every
LEVELONE_EQUITIES field (live_market_plane, fed here in the daemon's own process), knows
whether the feed is alive (the daemon's own heartbeat, applied every HEARTBEAT_SEC), and
pushes the FINISHED displayed row (live_price_rows.price_row -- the one producer) to every
browser that asked for the symbol, the moment a Schwab message changes it. It keeps each
symbol's 1-minute bars of the day (Schwab CHART_EQUITY, live_price_rows.minute_bar; every span
the stream did not cover from Schwab's price history) and pushes, for each new bar, the chart
bar it completes or extends at every chart timeframe when all its minutes are covered
(live_price_rows.bar_update).

No web server sits in this path, so no analytics load can delay a price.

Protocol (JSON text frames):
  browser -> {"op": "subscribe", "symbols": ["SPY", "AAPL", ...]}   (replaces the set; after a
             "disconnected_since": the last beat's feed.ts, when the   drop, the gap it has in
             browser comes back after a drop)                          its live bars is named)
  server  -> {"type": "bars_gap", "gap": {from_ts, to_ts, note}}     (on a subscribe after a
                                                                     drop: no bar is resent;
                                                                     the charts say they have
                                                                     no live bars for that time)
  server  -> {"type": "symbols", "symbols": [{requested, key, display}, ...]}  (on subscribe:
                                                                     what each asked-for symbol
                                                                     is -- "SPX" is key "$SPX",
                                                                     shown "SPX")
  server  -> {"type": "quotes", "rows": [price_row, ...]}            (snapshot on subscribe,
                                                                     then every change)
  server  -> {"type": "feed", "feed": {...}, "rows": [...]}           (every HEARTBEAT_SEC:
                                                                     the feed verdict and a
                                                                     fresh row per symbol, so
                                                                     a dead feed reads dead
                                                                     within FEED_HEARTBEAT_
                                                                     MAX_AGE_SEC)
  server  -> {"type": "bars", "bars": [bar_update, ...]}             (each completed minute of
                                                                     a subscribed symbol: its
                                                                     chart bar at every
                                                                     timeframe)

Rows are delivered latest-value-per-symbol per client (conflation, as Lightstreamer MERGE /
LSEG conflated feeds do): a slow browser gets the newest row for each symbol it is behind
on, never a queue of stale ones, and never loses a symbol's only update. Bars are not
conflated: every bar update is sent, in arrival order.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

import live_market_plane as lmp
import live_price_rows
from instrument_identity import display_symbol, ticker_storage_key
from stream_spine import (CONNECTION, CONNECTION_CLOSED, CONNECTION_LOSS, COUNT_DROPS, MessageBus, bar_days_msg,
                          bar_msg, bar_state_msg, held_minutes_msg, price_history_msg)
from time_et import ET, ct_label

log = logging.getLogger(__name__)

#: The browser connects to this port on the console's own host name. Binds like the console
#: (0.0.0.0): the page is served to whatever address the operator opened it on.
LIVE_UI_HOST = os.environ.get("ED_LIVE_UI_HOST", "0.0.0.0")  # caps-ok: operator bind config with its declared default, not market data
LIVE_UI_PORT = int(os.environ.get("ED_LIVE_UI_PORT", "8800"))  # caps-ok: operator port config with its declared default, not market data
#: feed verdict + row beat cadence (the heartbeat that keeps "live" honest)
HEARTBEAT_SEC = 1.0
#: a browser may watch at most this many symbols (the daemon holds ~50)
MAX_SYMBOLS_PER_CLIENT = 200


#: where a held minute came from: Schwab's stream (CHART_EQUITY) or Schwab's 1-minute price
#: history (asked for every span of the day's minutes the stream did not cover). The stream's
#: minute stands wherever both exist.
SRC_STREAM, SRC_PRICEHISTORY = "schwab_chart", "schwab_pricehistory"
#: price-history requests in flight at once: the uncovered spans of ~45 symbols are asked at the
#: daemon's start, at the open and after a reconnect. Schwab's Trader API is said to allow
#: about 120 requests a minute per app [UNVERIFIED: not found in Schwab's documents in this
#: repository], shared with the console's chain downloads, so the requests go two at a time.
#: Two in flight bounds the burst, not the rate per minute (a request's latency is unmeasured).
HISTORY_IN_FLIGHT = 2
#: how far back a symbol's daily candles are asked (the daily chart, the daily ATR's 15 days,
#: the prior day's high and low)
DAILY_HISTORY_DAYS = 400
#: a symbol whose day still has an uncovered span is asked again at most this often on the
#: daemon's clock (and on each of its streamed minutes), so a thin ticker never waits for a trade
PRICE_HISTORY_RETRY_SEC = 60.0
#: how long a console's connect waits for the daemon's bar queue to empty before reading the held
#: minutes (held_minutes; the queue empties in milliseconds, a minute's bars for the board at once)
HELD_DRAIN_MAX_SEC = 5.0


def _et_day_start(t: float) -> float:
    return datetime.fromtimestamp(t, ET).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _cover(covered: "list[tuple[float, float]]", a: float, b: float) -> "list[tuple[float, float]]":
    """`covered` (sorted inclusive minute-start spans) with the minutes `a` to `b` added, merged."""
    out: "list[tuple[float, float]]" = []
    for x, y in sorted(covered + [(a, b)]):
        if out and x <= out[-1][1] + 60.0:
            out[-1] = (out[-1][0], max(out[-1][1], y))
        else:
            out.append((x, y))
    return out


@dataclass
class _Day:
    """One symbol's minutes of one ET day, each with its source, and the spans of minutes whose
    every Schwab bar is held (`covered`; inside them a minute with no bar is a minute with no
    trade): the stream's span (LiveUiServer.streaming) and every price-history reply's (the
    request's start through the reply's newest completed minute). `asking`: a request for the
    uncovered spans is out, `asked_at` when the last one started; `problem`: why the last request
    failed."""
    start: float
    minutes: dict[float, dict] = field(default_factory=dict)
    source: dict[float, str] = field(default_factory=dict)
    covered: "list[tuple[float, float]]" = field(default_factory=list)
    asking: bool = False
    asked_at: float = float("-inf")
    problem: "str | None" = None


@dataclass
class _Daily:
    """One symbol's daily candles of the days before `day` (00:00 ET), Schwab's daily price
    history as served (`candles`), or none with why (`problem`); `asking`/`asked_at` as _Day's."""
    day: float
    candles: "list[dict] | None" = None
    problem: "str | None" = None
    asking: bool = False
    asked_at: float = float("-inf")


class _Client:
    __slots__ = ("ws", "symbols", "pending", "bars", "gap", "identity", "wake")

    def __init__(self, ws) -> None:
        self.ws = ws
        self.symbols: frozenset[str] = frozenset()
        self.pending: set[str] = set()      # symbols changed since the last send
        self.bars: list[dict] = []          # the bar updates not yet sent, in arrival order
        self.gap: dict | None = None        # its live bars' gap after a drop, not yet sent
        self.identity: list[dict] | None = None   # the last subscribe's answer, not yet sent
        self.wake = asyncio.Event()


class LiveUiServer:
    def __init__(self, bus: MessageBus, heartbeat_fn, stats: dict, *, clock, history_fn, daily_fn) -> None:
        self.bus = bus
        self.heartbeat_fn = heartbeat_fn
        #: the entry point's clock (epoch seconds): every row, beat and gap is judged at its time
        self.clock = clock
        #: Schwab's 1-minute price history: (streamed symbol, start, end epoch seconds) -> its
        #: candles as sent (capture.schwab_minutes); blocking, run off the event loop
        self.history_fn = history_fn
        #: Schwab's daily price history: (symbol, start, end epoch seconds) -> its daily candles as
        #: sent (capture.schwab_days); blocking, run off the event loop
        self.daily_fn = daily_fn
        #: each streamed symbol's daily candles before today (_Daily), asked once a day
        self.daily: dict[str, _Daily] = {}
        self.stats = stats
        self.clients: set[_Client] = set()
        #: each symbol's minutes of the current ET day: the ones Schwab streams and, for every span
        #: the stream did not cover, the ones its price history gave. Nothing here reads the
        #: database.
        self.days: dict[str, _Day] = {}
        #: per symbol whose CHART_EQUITY subscription Schwab acknowledged, on the socket still
        #: open: the first minute the stream covers (the first to start after the acknowledgement)
        self.streaming: dict[str, float] = {}
        self._asks: set[asyncio.Task] = set()
        self._in_flight = asyncio.Semaphore(HISTORY_IN_FLIGHT)
        #: its one queue of bars and subscription answers while it serves (serve_live_ui)
        self.bars_queue = None
        #: per symbol, today's streamed minutes that differed from Schwab's price history
        self.mismatches: dict[str, int] = {}
        stats.update(clients=0, rows_sent=0, frames_sent=0, ingest_failures=0,
                     beat_send_failures=0, listening=None, last_send_ms=None, bars_sent=0,
                     bar_source_mismatches=0, price_history_failures=0, stream_losses=0, tick_failures=0,
                     bad_subscription_messages=0)

    def on_subscription(self, msg) -> None:
        """A `sub.*` bus message (capture.Daemon): a CHART_EQUITY subscription Schwab acknowledged
        (SUBS or ADD, a first one or again) starts the symbol's stream coverage afresh at the
        first minute to start after the acknowledgement (`ts`, the daemon's receive time of
        Schwab's answer); it runs through every completed minute while the subscription and the
        socket are unbroken. An acknowledged UNSUBS, or the Schwab socket closing (service
        CONNECTION; the daemon closes it when no Schwab frame, heartbeats included, arrived for
        capture.DEAD_SEC), ends it; a loss the daemon cannot attribute (CONNECTION LOSS) restarts
        every symbol's at the first minute after it. The minutes not covered are asked of the
        price history. A message the daemon cannot read (no time, symbols not a list) is counted
        and logged and taken as a loss: which subscription it answered is unknown."""
        ts = msg.get("ts") if isinstance(msg, dict) else None
        if (not isinstance(ts, (int, float)) or isinstance(ts, bool) or not math.isfinite(ts)
                or not isinstance(msg.get("symbols", []), list)):
            self.stats["bad_subscription_messages"] += 1
            log.warning("live ui: a subscription message the daemon cannot read: %r", msg)
            msg = {"service": CONNECTION, "command": CONNECTION_LOSS, "code": 0, "ts": self.clock(),
                   "reason": "a subscription message the daemon could not read"}
        if msg.get("code") != 0:
            return
        after = math.ceil(float(msg["ts"]) / 60.0) * 60.0
        if msg.get("service") == CONNECTION and msg.get("command") == CONNECTION_CLOSED:
            self.streaming.clear()
        elif msg.get("service") == CONNECTION and msg.get("command") == CONNECTION_LOSS:
            self.stats["stream_losses"] += 1
            log.warning("live ui: %s at %s: every symbol's stream coverage restarts at %s", msg.get("reason"),
                        ct_label(float(msg["ts"])), ct_label(after))
            self.streaming = dict.fromkeys(self.streaming, after)
        elif msg.get("service") == "CHART_EQUITY":
            for sym in {ticker_storage_key(s) for s in msg.get("symbols") or ()}:
                if msg.get("command") == "UNSUBS":
                    self.streaming.pop(sym, None)
                else:
                    self.streaming[sym] = after
                    self._ask_daily(sym, self.clock())
        self.publish_states(self.clock())

    def _ask_daily(self, sym: str, now: float) -> None:
        """Ask Schwab's daily price history for `sym`'s days before today, once a day (again on
        the daemon's clock every PRICE_HISTORY_RETRY_SEC while it has failed), through the same
        two requests in flight as the minutes."""
        today = _et_day_start(now)
        held = self.daily.get(sym)
        if held is None or held.day != today:
            held = self.daily[sym] = _Daily(today)
        if held.candles is not None or held.asking or now - held.asked_at < PRICE_HISTORY_RETRY_SEC:
            return
        held.asking, held.asked_at = True, now
        task = asyncio.get_running_loop().create_task(self._ask_days(sym, held))
        self._asks.add(task)
        task.add_done_callback(self._asks.discard)

    async def _ask_days(self, sym: str, held: _Daily) -> None:
        """One daily price-history request (DAILY_HISTORY_DAYS before today): its candles held and
        published (bardays.SYM, as served daily bars), or the failure's reason."""
        try:
            async with self._in_flight:
                try:
                    candles = await asyncio.to_thread(self.daily_fn, sym, held.day - DAILY_HISTORY_DAYS * 86400.0,
                                                      held.day)
                except Exception as e:  # noqa: BLE001 -- counted, its reason served; asked again
                    held.problem = self._failed(sym, e)
                    return
            held.candles, held.problem = live_price_rows.daily_candles(candles, held.day), None
        finally:
            held.asking = False
            self.bus.publish(f"bardays.{sym}", bar_days_msg(symbol=sym, candles=held.candles or [],
                                                            problem=held.problem, ts=self.clock()))

    def _failed(self, sym: str, e: Exception) -> str:
        """A failed price-history request (Schwab's rate limit holding it back included,
        capture.RateHold): counted, logged, its reason returned."""
        self.stats["price_history_failures"] += 1
        problem = f"Schwab's price history: {type(e).__name__}: {e}"
        log.warning("live ui: %s %s", sym, problem)
        return problem

    # -- plane side -------------------------------------------------------------------

    def ingest(self, msg) -> None:
        """One daemon quote message -> the plane (per-field state, the daemon's receive time)."""
        if not isinstance(msg, dict):
            return
        sym, ts, item = msg.get("symbol"), msg.get("ts_recv"), msg.get("native")
        if not sym or not isinstance(ts, (int, float)) or not isinstance(item, dict):
            return
        try:
            lmp.record_from_level_one_equity(sym, item, received_ts=float(ts))
        except Exception as e:  # noqa: BLE001 -- counted; one malformed item never ends the feed
            self.stats["ingest_failures"] += 1
            log.warning("live ui ingest %s: %s: %s", sym, type(e).__name__, e)

    def on_row(self, ticker: str) -> None:
        """Plane row listener: mark the symbol changed for every browser watching it."""
        for c in self.clients:
            if ticker in c.symbols:
                c.pending.add(ticker)
                c.wake.set()

    def on_bar(self, msg) -> None:
        """One streamed minute (a bus bar message) -> the symbol's minutes of the day -> the chart
        bar it makes at every timeframe, for every browser watching the symbol. While the symbol's
        subscription is unbroken the stream covers every minute from its first through this one
        (a minute with no bar in it had no trade). Every span of the day's minutes still
        uncovered is asked of Schwab's price history (`ask_uncovered`); a bar above 1 minute is
        pushed only when its minutes are all covered."""
        if not isinstance(msg, dict) or not msg.get("symbol"):
            return
        bar = live_price_rows.minute_bar(msg)
        if bar is None:
            return
        sym = ticker_storage_key(msg["symbol"])
        day = self.days.get(sym)
        if day is None or day.start != _et_day_start(bar["t"]):
            day = self.days[sym] = _Day(_et_day_start(bar["t"]))
        self._hold(sym, day, bar, SRC_STREAM)
        if sym in self.streaming:
            # the stream's span, from its first minute (or the session's) through this one
            start = max(self.streaming[sym], live_price_rows.session_first_minute(bar["t"]))
            if bar["t"] >= start:
                day.covered = _cover(day.covered, start, bar["t"])
        self._ask_uncovered(sym, day, self.clock())
        self._push(sym, day, bar, float(msg["ts_recv"]))

    def _ask_uncovered(self, sym: str, day: _Day, now: float) -> None:
        """Ask the price history for every span of `sym`'s day from 09:15 ET through the newest
        minute completed at `now` that neither its held spans nor its unbroken stream cover,
        unless a request is out (Schwab's rate limit is judged when the request's turn comes)."""
        gaps = live_price_rows.day_gaps(day.covered, self.streaming.get(sym), now)
        if not gaps or day.asking:
            return
        day.asking, day.asked_at = True, now
        task = asyncio.get_running_loop().create_task(self._ask(sym, day, gaps))
        self._asks.add(task)
        task.add_done_callback(self._asks.discard)

    def tick(self, now: float) -> None:
        """The daemon's clock, every beat: each symbol with an uncovered span not asked for
        PRICE_HISTORY_RETRY_SEC is asked again (a thin ticker does not wait for its next trade),
        and every symbol's bar state is published."""
        today = _et_day_start(now)
        for sym in set(self.streaming) | set(self.days):
            day = self.days.get(sym)
            if day is None or day.start != today:
                if sym not in self.streaming:
                    continue
                day = self.days[sym] = _Day(today)
            if now - day.asked_at >= PRICE_HISTORY_RETRY_SEC:
                self._ask_uncovered(sym, day, now)
        for sym in self.streaming:
            self._ask_daily(sym, now)
        self.publish_states(now)

    def _hold(self, sym: str, day: _Day, bar: dict, src: str) -> None:
        """Hold one minute with its source. The stream's minute stands: a price-history minute
        never replaces it, and a difference between the two is counted and logged with both."""
        prev, prev_src = day.minutes.get(bar["t"]), day.source.get(bar["t"])
        if prev is not None and prev_src != src and prev != bar:
            self.stats["bar_source_mismatches"] += 1
            self.mismatches[sym] = self.mismatches.get(sym, 0) + 1
            stream, history = (prev, bar) if prev_src == SRC_STREAM else (bar, prev)
            log.warning("%s %s: the streamed bar %s and Schwab's price-history bar %s differ; the "
                        "streamed bar stands (%d such minutes for %s today, %d across the board)",
                        sym, ct_label(bar["t"]), stream, history, self.mismatches[sym], sym,
                        self.stats["bar_source_mismatches"])
        if prev is None or src == SRC_STREAM or prev_src == SRC_PRICEHISTORY:
            day.minutes[bar["t"]], day.source[bar["t"]] = bar, src

    async def held_minutes(self) -> "list[tuple[str, dict]]":
        """Every symbol's held minutes of the day (barheld.SYM, stream_spine.held_minutes_msg),
        each as a bar1m message with its own source, read once when a console connects to the
        push (live_push) so its store backfills what it missed while away. Read after this
        server's bar queue is empty: every bar published before the console's own queue began is
        then held (a bar is held in the same step it is taken from the queue), and every later one
        reaches the console as a bar event, so no minute falls between."""
        deadline = time.monotonic() + HELD_DRAIN_MAX_SEC
        while self.bars_queue is not None and not self.bars_queue.queue.empty():
            if time.monotonic() > deadline:
                log.warning("live ui: the bar queue did not empty in %.0f s; held minutes read with %d queued",
                            HELD_DRAIN_MAX_SEC, self.bars_queue.queue.qsize())
                break
            await asyncio.sleep(0.005)
        now, out = self.clock(), []
        for sym, day in self.days.items():
            if day.start == _et_day_start(now) and day.minutes:
                out.append((f"barheld.{sym}", held_minutes_msg(symbol=sym, ts=now, bars=[
                    bar_msg(symbol=sym, bar_start_ms=int(t * 1000), open=m["o"], high=m["h"], low=m["l"],
                            close=m["c"], volume=m["v"], src=day.source[t], ts_recv=now)
                    for t, m in sorted(day.minutes.items())])))
        return out

    async def _ask(self, sym: str, day: _Day, gaps: "list[tuple[float, float]]") -> None:
        """Ask Schwab's price history for the uncovered `gaps` of `sym`'s day, one request per
        span still uncovered when its turn comes, from the span's start to now (at most
        HISTORY_IN_FLIGHT at once). A reply
        covers from the request's start through its newest completed minute: one reaching the
        stream's resumption covers the whole span, a minute with no candle in it being a minute
        with no trade; an empty reply covers nothing. Its minutes are held and published for the
        store in one message (the console's bar writer backfills what it lacks). A failed request
        is counted and its reason kept (Schwab's rate limit holding it back: capture.RateHold).
        Whatever stays uncovered is asked again (`tick`, `on_bar`). When a reply held a minute or
        the reason changed, the bars are pushed again."""
        before = (list(day.covered), day.problem)
        try:
            for a, b in gaps:
                if not live_price_rows.uncovered(day.covered, a, b):
                    continue                   # an earlier reply reached it
                async with self._in_flight:
                    now = self.clock()
                    try:
                        candles = await asyncio.to_thread(self.history_fn, sym, a, now)
                    except Exception as e:  # noqa: BLE001 -- counted, its reason served; asked again
                        day.problem = self._failed(sym, e)
                        continue
                received, held, newest = self.clock(), [], None
                for c in candles:
                    msg = bar_msg(symbol=sym, bar_start_ms=c.get("datetime"), open=c.get("open"),
                                  high=c.get("high"), low=c.get("low"), close=c.get("close"),
                                  volume=c.get("volume"), src=SRC_PRICEHISTORY, ts_recv=received)
                    bar = live_price_rows.minute_bar(msg)
                    if bar is None or bar["t"] < a or bar["t"] + 60.0 > now:
                        continue               # not a chart bar, before the request, or not completed
                    self._hold(sym, day, bar, SRC_PRICEHISTORY)
                    held.append(msg)
                    newest = bar["t"] if newest is None else max(newest, bar["t"])
                day.problem = None
                if held:
                    day.covered = _cover(day.covered, a, newest)
                    self.bus.publish(f"barhist.{sym}", price_history_msg(symbol=sym, bars=held, ts_recv=received))
        finally:
            day.asking = False
        if self.days.get(sym) is day and day.minutes and (list(day.covered), day.problem) != before:
            self._push(sym, day, day.minutes[max(day.minutes)], self.clock())
        self.publish_states(self.clock(), [sym])

    def _push(self, sym: str, day: _Day, bar: dict, ts_recv: float) -> None:
        minutes = sorted(day.minutes.values(), key=lambda m: m["t"])
        update = live_price_rows.bar_update(sym, minutes, bar, ts_recv, day.covered)
        if day.problem:
            update["unavailable"] = {k: f"{v} ({day.problem})" for k, v in update["unavailable"].items()}
        for c in self.clients:
            if sym in c.symbols:
                c.bars.append(update)
                c.wake.set()
        self.publish_states(self.clock(), [sym])

    def publish_states(self, now: float, symbols=None) -> None:
        """Publish the bar state at `now` (barstate.SYM, stream_spine.bar_state_msg) of each of
        `symbols` (None: every symbol streamed or held; every beat publishes them all, so the
        console can tell a verdict it stopped receiving): whether today's minutes are covered
        through now, with the reason, and the minutes held -- the one authority every value built
        from today's bars takes its currency from (the console's session levels and VWAP)."""
        today = _et_day_start(now)
        for sym in (set(self.streaming) | set(self.days)) if symbols is None else symbols:
            day = self.days.get(sym)
            day = day if day is not None and day.start == today else _Day(today)
            state, reason = live_price_rows.coverage_now(day.covered, self.streaming.get(sym), now)
            if state != live_price_rows.COVERAGE_CURRENT and day.problem:
                reason = f"{reason} ({day.problem})"
            self.bus.publish(f"barstate.{sym}", bar_state_msg(
                symbol=sym, coverage=state, coverage_reason=reason, minutes=len(day.minutes),
                newest=max(day.minutes, default=None), ts=now))

    @staticmethod
    def bars_gap(since: float, now: float) -> dict:
        """The gap in a browser's live bars after a drop: from the last beat it had (`since`),
        less two beats (a bar and a beat go out on their own tasks, so a bar received just before
        that beat may not have reached it), to `now`. Live bars are only the ones Schwab sends
        while the browser is connected: none received in the gap is resent."""
        start = since - 2 * HEARTBEAT_SEC
        return {"from_ts": start, "to_ts": now,
                "note": f"No live bars from {ct_label(start)} to {ct_label(now)}: this page was "
                        f"disconnected from the price feed, and bars completed then are not drawn. "
                        f"Reopening the chart loads the stored history."}

    def beat(self, now: float) -> dict:
        hb = self.heartbeat_fn()
        lmp.record_feed_heartbeat(hb, now)
        return {"ts": hb.get("ts"), "schwab_socket_open": hb.get("schwab_socket_open") is True}

    # -- browser side -----------------------------------------------------------------

    async def _send(self, c: _Client, payload: dict) -> None:
        t0 = time.perf_counter()
        await c.ws.send(json.dumps(payload, separators=(",", ":"), default=str))
        self.stats["frames_sent"] += 1
        self.stats["rows_sent"] += len(payload.get("rows") or ())
        self.stats["last_send_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)

    async def _pump(self, c: _Client) -> None:
        while True:
            await c.wake.wait()
            c.wake.clear()
            if c.identity is not None:
                identity, c.identity = c.identity, None
                await self._send(c, {"type": "symbols", "symbols": identity})
            syms, c.pending = c.pending, set()
            now = self.clock()
            rows = [live_price_rows.price_row(s, now) for s in syms if s in c.symbols]
            if rows:
                await self._send(c, {"type": "quotes", "rows": rows})
            if c.gap is not None:
                gap, c.gap = c.gap, None
                await self._send(c, {"type": "bars_gap", "gap": gap})
            bars, c.bars = c.bars, []
            bars = [b for b in bars if b["ticker"] in c.symbols]
            if bars:
                await self._send(c, {"type": "bars", "bars": bars})
                self.stats["bars_sent"] += len(bars)

    async def _read(self, c: _Client) -> None:
        async for frame in c.ws:
            try:
                req = json.loads(frame)
            except (TypeError, ValueError):
                continue
            if not isinstance(req, dict) or req.get("op") != "subscribe":
                continue
            raw = req.get("symbols")
            if not isinstance(raw, list):
                continue
            keys, identity = [], []
            for s in raw[:MAX_SYMBOLS_PER_CLIENT]:
                k = ticker_storage_key(s) if isinstance(s, str) else ""
                if not k:
                    continue
                identity.append({"requested": s, "key": k, "display": display_symbol(k)})
                if k not in keys:
                    keys.append(k)
            c.symbols = frozenset(keys)
            c.identity = identity            # what each asked-for symbol is, before its rows
            c.pending = set(keys)            # snapshot: the current row for each, now
            since = req.get("disconnected_since")   # a browser back from a drop
            if isinstance(since, (int, float)) and not isinstance(since, bool):
                c.gap = self.bars_gap(float(since), self.clock())
            c.wake.set()

    async def serve_client(self, ws) -> None:
        c = _Client(ws)
        self.clients.add(c)
        self.stats["clients"] = len(self.clients)
        pump = asyncio.create_task(self._pump(c))
        read = asyncio.create_task(self._read(c))
        try:
            await asyncio.wait({pump, read}, return_when=asyncio.FIRST_COMPLETED)
            for t in (pump, read):
                if t.done() and not t.cancelled() and t.exception() is not None:
                    e = t.exception()
                    log.info("live ui client ended: %s: %s", type(e).__name__, e)
        finally:
            for t in (pump, read):
                t.cancel()
            await asyncio.gather(pump, read, return_exceptions=True)
            self.clients.discard(c)
            self.stats["clients"] = len(self.clients)

    async def beat_loop(self) -> None:
        while True:
            now = self.clock()
            try:
                self.tick(now)
            except Exception as e:  # noqa: BLE001 -- counted and logged; the beat and the next tick go on
                self.stats["tick_failures"] += 1
                log.warning("live ui tick: %s: %s", type(e).__name__, e)
            try:
                feed = self.beat(now)
            except Exception as e:  # noqa: BLE001 -- a failed beat leaves the feed unproven (it ages out)
                log.warning("live ui heartbeat: %s: %s", type(e).__name__, e)
                feed = None
            for c in list(self.clients):
                # one browser can neither stop the beat nor hold it: an error is logged and the
                # next browser still gets its beat; a browser that does not take its beat within
                # a beat is not reading and is closed (2026-09-26: the beat stopped for every
                # browser and the whole screen read "no live feed" on a healthy Schwab socket)
                try:
                    rows = [live_price_rows.price_row(s, now) for s in sorted(c.symbols)]
                    await asyncio.wait_for(
                        self._send(c, {"type": "feed", "feed": feed, "rows": rows}),
                        timeout=HEARTBEAT_SEC)
                except asyncio.TimeoutError:
                    self.stats["beat_send_failures"] += 1
                    log.warning("live ui: a browser stopped reading; closing it")
                    asyncio.create_task(c.ws.close())
                except Exception as e:  # noqa: BLE001 -- logged; the other browsers' beats go out
                    self.stats["beat_send_failures"] += 1
                    log.warning("live ui beat to one browser: %s: %s", type(e).__name__, e)
            await asyncio.sleep(HEARTBEAT_SEC)


async def serve_live_ui(srv: LiveUiServer, stop: asyncio.Event, *,
                        host: str = LIVE_UI_HOST, port: int = LIVE_UI_PORT) -> None:
    """Serve `srv` (its bus, its clock -- the entry point's, the time every row, beat and gap is
    judged at -- Schwab's 1-minute and daily price history, its stats) until `stop` is set. Start
    it BEFORE the Schwab connection so the plane sees the first messages (Schwab sends each field
    once, then only changes). The daemon's `sub.*` messages say when each symbol's stream
    coverage starts and ends. Nothing here reads the database."""
    from websockets.asyncio.server import serve

    bus, stats = srv.bus, srv.stats
    for topic, msg in list(bus.snapshot().items()):         # whatever arrived before we started
        if topic.startswith("quote."):
            srv.ingest(msg)
    sub = bus.subscribe("quote.", policy=COUNT_DROPS, maxsize=65536, name="live_ui")
    # bars and subscription answers on ONE queue, in publish order: a bar is judged against the
    # subscriptions as they were when it was published
    bsub = srv.bars_queue = bus.subscribe(("bar1m.", "sub."), policy=COUNT_DROPS, maxsize=8192, name="live_ui_bars")
    lmp.add_row_listener(srv.on_row)

    async def _track() -> None:
        while True:
            _topic, msg = await sub.get()
            srv.ingest(msg)

    async def _track_bars() -> None:
        dropped = 0
        while True:
            topic, msg = await bsub.get()
            if bsub.dropped != dropped:        # bars or answers lost here: no stream is whole now
                srv.on_subscription({"service": CONNECTION, "command": CONNECTION_LOSS, "code": 0,
                                     "ts": srv.clock(), "reason": f"the daemon's bar queue dropped "
                                                                 f"{bsub.dropped - dropped} messages"})
                dropped = bsub.dropped
            if topic.startswith("sub."):
                srv.on_subscription(msg)
                continue
            try:
                srv.on_bar(msg)
            except Exception as e:  # noqa: BLE001 -- counted; one bad bar never ends the feed
                srv.stats["ingest_failures"] += 1
                log.warning("live ui bar %s: %s: %s", msg.get("symbol") if isinstance(msg, dict) else None,
                            type(e).__name__, e)

    tasks = [asyncio.create_task(_track()), asyncio.create_task(_track_bars()),
             asyncio.create_task(srv.beat_loop())]
    try:
        async with serve(srv.serve_client, host, port, max_size=65536, compression=None,
                         ping_interval=20, ping_timeout=20):
            stats["listening"] = f"ws://{host}:{port}"
            log.info("live ui: serving price rows to browsers on ws://%s:%s", host, port)
            stopped = asyncio.create_task(stop.wait())
            done, _ = await asyncio.wait({stopped, *tasks}, return_when=asyncio.FIRST_COMPLETED)
            stopped.cancel()
            for t in done - {stopped}:         # a tracker ended: the daemon cannot go on serving
                log.error("live ui: %s ended (%r): the daemon stops so it is restarted", t.get_coro().__name__,
                          t.exception() if not t.cancelled() else "cancelled")
                raise RuntimeError(f"live ui {t.get_coro().__name__} ended") from (
                    None if t.cancelled() else t.exception())
    finally:
        tasks += list(srv._asks)               # the price-history requests still out
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        lmp.remove_row_listener(srv.on_row)
        bus.unsubscribe(sub)
        bus.unsubscribe(bsub)
        srv.bars_queue = None
