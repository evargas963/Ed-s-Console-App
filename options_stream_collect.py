"""Raw options collection, owned by the CAPTURE DAEMON — the single streaming Collect authority.

WHY THIS MODULE EXISTS. Raw options collection was first built into order_flow_streaming.py,
which drives the UI's Schwab stream in the server process. But the repo already defines ONE
streaming Collect authority: tools/run_stream_capture.py (the CR-01 capture daemon), which owns
the only Schwab stream and writes only stream_capture.db. Putting options Collect on the UI
socket created a SECOND stream surface with its own key accounting, its own persistence
lifecycle, and its own coverage epochs — exactly the competing-ownership blast area Cursor
flagged.

So the options Collect subsystem lives HERE and is driven by the DAEMON. order_flow_streaming
returns to being purely observational (live quotes for the UI, persisting nothing). The
functions are the same ones proven under test — the move preserves every truthfulness property
(per-service subscription truth, the key-budget cap against actual held keys, SUBS-establishes /
ADD-extends, roster fail-closed, intersection-based fully-observed coverage) — with two
couplings re-homed off the UI:

  * the KEY BUDGET is derived from the DAEMON's equity load (its symbol count and the number of
    equity services it runs — two: LEVELONE_EQUITIES + CHART_EQUITY — not the UI's three), so
    options can never crowd out the stream the daemon actually holds.
  * the vendor-call lock is this module's OWN asyncio.Lock, serialising a rotation slice against
    the daemon's start/re-establish (a watchdog recycle). There is no UI ticker switch here to
    interleave with.

Options stay OUTSIDE Decide: this writes raw frames to stream_capture.db and nothing else reads
them into the money path. Collection is OFF unless ED_OPTIONS_STREAM is explicitly set.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

ED_OPTIONS_STREAM_ENV = "ED_OPTIONS_STREAM"

#: SUBSCRIPTION TRUTH, PER SERVICE. LEVELONE_OPTIONS and OPTIONS_BOOK are separate vendor
#: services that succeed and fail independently — subscribe_options returns a receipt with a
#: slot for each and reports partial success as the normal case. One service-agnostic list
#: could not represent that: a contract whose LEVELONE_OPTIONS was accepted and whose
#: OPTIONS_BOOK was refused was recorded as "subscribed", so the refused service was never in
#: the next slice's add-set and was never retried, while the coverage record showed one epoch
#: open and the other absent with nothing to reconcile them.
OPTIONS_SERVICES: tuple[str, ...] = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")

#: PERSISTENCE RIDES THE DAEMON'S ONE WRITER. Options frames are PUBLISHED onto the daemon's
#: MessageBus and persisted by the SAME CaptureWriter connection that writes the equity capture —
#: never a second sqlite connection to stream_capture.db. Two connections to one WAL file was the
#: "competing writers" defect that silently lost equity rows to lock contention. So there is no
#: OptionsFrameIngest in the live path: the frame handler is an O(1) bus publish, and the writer's
#: registered option persister (make_capture_topic_writer) does the insert on the shared connection.
_options_bus: Any = None
#: The stream client options are collecting on, held so a CLEAN teardown can UNSUBSCRIBE the vendor
#: (release keys) rather than only dropping local state and leaking the subscription until logout.
_active_stream: Any = None
#: offered on the loop by the handler, written on the loop by the persister — same thread, no lock.
#: offered - written (at drain) is the drop count, flushed to options_stream_ingest_health so the
#: SUBSCRIBED_MAYBE_DROPPED verdict stays answerable after the process exits.
_options_offered: int = 0
_options_written: int = 0
_options_started_ms: int = 0
_options_subscribed: dict[str, set[str]] = {s: set() for s in OPTIONS_SERVICES}
_options_last_receipt: dict[str, Any] | None = None
#: The last slice this process applied — what rotated in, what rotated out, and when. Without it
#: an operator can see that frames are arriving but not that the ROTATION is advancing, which is
#: the difference between "options collection works" and "the intended architecture is running".
_options_last_slice: dict[str, Any] | None = None
#: The rotation task, on the daemon's event loop. Held so teardown can cancel it; an orphaned
#: rotation would keep subscribing against a client being torn down.
_options_rotation_task: Any = None

#: The daemon's equity load, set by start_options_collection. The budget is derived from these so
#: options are sized against the stream that is ACTUALLY held, not a hardcoded topology.
_equity_symbols: int = 1
_equity_key_services: int = 2
_book_enabled: bool = True
#: This module's OWN lock, serialising vendor calls (a rotation slice vs a daemon re-establish).
_options_lock: Any = None


def options_streaming_enabled() -> bool:
    """True only when the operator has explicitly turned options collection on."""
    import os
    return str(os.environ.get(ED_OPTIONS_STREAM_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


#: LEVELONE_OPTIONS rides the 'optionchain' topic KIND, OPTIONS_BOOK the 'optionbook' kind. The
#: kind is what the CaptureWriter dispatches on; the service travels inside the message so the one
#: persister can shape either row from the vendor's own field names.
_TOPIC_KIND = {"LEVELONE_OPTIONS": "optionchain", "OPTIONS_BOOK": "optionbook"}


def _options_frame_handler(service: str) -> Callable[[dict], None]:
    """PUBLISH one options frame onto the daemon's bus and return. O(1), no SQLite on the loop.

    The frame does not touch storage here — it rides the same bus the equity handlers use, and the
    daemon's single CaptureWriter persists it on its own task. Failure containment is DRIVEN: the
    handler closes over module globals only, so a test can point the bus at a raising fake and
    confirm nothing escapes into the shared message loop.
    """
    kind = _TOPIC_KIND.get(service, "optionchain")

    def _handler(msg: dict) -> None:
        global _options_offered
        bus = _options_bus
        if bus is None:
            return
        try:
            key = ""
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list) and content and isinstance(content[0], dict):
                key = str(content[0].get("key") or "")
            _options_offered += 1
            bus.publish(f"{kind}.{key}",
                        {"service": service, "frame": msg,
                         "received_ts_ms": int(time.time() * 1000.0)})
        except Exception as e:                  # noqa: BLE001
            # A publish problem must never propagate into the shared loop that services equities.
            log.debug("options frame publish (%s): %s", service, e)
    return _handler


def make_capture_topic_writer() -> Callable[[Any, str, dict], int]:
    """Build the persister the daemon registers on its CaptureWriter for the option topic kinds.

    fn(conn, topic, msg) -> rows written. It writes options_stream_frames + the per-contract index
    onto the CaptureWriter's OWN connection — the single writer — so options never opens a second
    connection to stream_capture.db. Row shaping is the SHARED shaping from options_stream_frames,
    so this path and any other writer produce byte-identical rows. Schema is ensured lazily on the
    first frame (the writer's connection is the daemon's, created before any option frame arrives).
    """
    from calibration.options_stream_frames import (ensure_options_stream_schema, frame_row_values,
                                                    frame_symbol_rows)
    state = {"schema_ready": False}

    def _write(conn: Any, topic: str, msg: dict) -> int:
        global _options_written
        if not isinstance(msg, dict):
            return 0
        if not state["schema_ready"]:
            ensure_options_stream_schema(conn)
            state["schema_ready"] = True
        service = msg.get("service")
        frame = msg.get("frame")
        rx = msg.get("received_ts_ms")
        vals = frame_row_values(service, frame, rx)
        if vals is None:
            return 0
        cur = conn.execute(
            "INSERT INTO options_stream_frames (service, frame_ts_ms, received_ts_ms, "
            "ingest_lag_ms, n_contracts, payload_json) VALUES (?,?,?,?,?,?)", vals)
        rows = frame_symbol_rows(cur.lastrowid, frame)
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO options_stream_frame_symbols (frame_id, symbol_key, "
                "content_idx) VALUES (?,?,?)", rows)
        _options_written += 1
        return 1
    return _write


def register_options_handlers(sc: Any, make_handler: Callable[[str], Callable[[dict], None]]) -> None:
    """Attach options handlers to the daemon's EXISTING client. Inert until something subscribes.

    Registration is separated from subscription on purpose: a handler with no subscription
    receives nothing, so this is safe to run unconditionally and keeps the enable/disable
    decision in exactly one place (start_options_collection).
    """
    for attr, service in (("add_level_one_option_handler", "LEVELONE_OPTIONS"),
                          ("add_options_book_handler", "OPTIONS_BOOK")):
        fn = getattr(sc, attr, None)
        if fn is None:
            log.warning("stream client has no %s — options %s cannot be collected", attr, service)
            continue
        try:
            fn(make_handler(service))
        except Exception as e:                          # noqa: BLE001
            log.warning("registering %s failed: %s", attr, e)


def options_desired_for_slice(at_epoch_s: float, *, equity_symbols: int,
                              equity_key_services: int = 2,
                              book_enabled: bool = True) -> dict[str, Any]:
    """THE ONE COMPUTATION of "which contracts should be subscribed at this instant".

    Everything downstream — the first subscribe at stream start, every rotation boundary, and
    the diagnostics surface — asks THIS function and reconciles to its answer. A second place
    that decided what to subscribe would be a second coverage authority, and the two would
    disagree the first time either changed.

    CORE underlyings appear in every slice (continuous, money-path); the remaining budget rotates
    deterministically over the rest of the enrolled universe; the budget itself is DERIVED from
    the vendor key limit and the daemon's actual equity load, so options can never crowd out the
    stream the daemon holds. The universe is the ENROLLMENT ROSTER (the sole enrollment authority
    shared by the background logger and ml_scheduler), NOT the freshness-derived chain set, so the
    deterministic cohort really is a pure function of the clock and a governed roster.
    """
    from options_stream_subscription import (
        RotationPolicy, SelectionPolicy, build_chains_for_selection,
        contract_budget_from_key_limit, rotation_cohort, select_contracts, split_budget,
    )

    import dataclasses

    base = RotationPolicy()
    universe: list[str] = []
    roster_ok = False
    roster_error: str | None = None
    try:
        from db import get_db
        universe = sorted(get_db().logging_universe_authoritative_tickers())
        roster_ok = bool(universe)
        if not universe:
            roster_error = "enrollment roster is empty"
    except Exception as e:                              # noqa: BLE001
        roster_error = f"{type(e).__name__}: {e}"

    if not roster_ok:
        # FAIL EXPLICIT, NOT OPEN. The fallback used to be the freshness-derived universe, which
        # reshuffles cohorts as chains age. A plan with no roster carries roster_ok=False and NO
        # symbols, and the reconciler holds the current subscription unchanged rather than
        # reconciling toward a garbage universe (which would UNSUB the current set).
        log.warning("options rotation: enrollment roster unavailable (%s) — holding the current "
                    "subscription unchanged; no deterministic cohort can be computed", roster_error)
        return {
            "at_epoch_s": float(at_epoch_s), "roster_ok": False, "roster_error": roster_error,
            "slice_index": base.slice_index(at_epoch_s), "slice_seconds": base.slice_seconds,
            "core": [], "rotating": [], "non_core_total": 0,
            "full_cycle_slices": 0, "full_cycle_seconds": 0,
            "budget": {}, "split": {}, "useful_depth_contracts": base.useful_depth_contracts,
            "rotating_depth_each": 0, "rotating_per_slice": 0,
            "symbols": [], "per_underlying": {},
            "notes": [f"roster unavailable ({roster_error}) — subscription held unchanged"],
            "policy": base.describe(),
        }

    budget = contract_budget_from_key_limit(
        equity_symbols=max(1, int(equity_symbols)), equity_key_services=equity_key_services,
        book_enabled=book_enabled)

    # THE COHORT SIZE IS DERIVED FROM THE BUDGET. Sizing the cohort first and letting depth fall
    # out of it is how rotating coverage becomes a permanent sliver; depth is the invariant and
    # breadth-per-slice gives way, with the cycle length reported so the gap stays a known
    # quantity.
    n_core = len([c for c in base.core if c in set(universe)])
    provisional = split_budget(budget["contracts_allowed"], n_core, base.rotating_per_slice, base)
    pol = dataclasses.replace(
        base, rotating_per_slice=base.cohort_size_for_budget(provisional["rotating"]))

    cohort = rotation_cohort(universe, at_epoch_s, pol)
    split = split_budget(budget["contracts_allowed"], len(cohort["core"]),
                         len(cohort["rotating"]), pol)

    symbols: list[str] = []
    per_underlying: dict[str, int] = {}
    symbol_underlying: dict[str, str] = {}
    notes: list[str] = []
    # Core and cohort are selected SEPARATELY so a large cohort cannot dilute the core's depth.
    for label, names, ceiling in (("core", cohort["core"], split["core"]),
                                  ("rotating", cohort["rotating"], split["rotating"])):
        if not names or ceiling <= 0:
            continue
        chains = build_chains_for_selection(tickers=names)
        missing = sorted(set(names) - set(chains))
        if missing:
            notes.append(f"{label}: no fresh chain for {missing} — not subscribed this slice")
        sel = select_contracts(chains, SelectionPolicy(max_contracts=int(ceiling)))
        symbols.extend(sel.symbols)
        for k, v in sel.per_underlying.items():
            per_underlying[k] = per_underlying.get(k, 0) + v
        symbol_underlying.update(sel.symbol_underlying)
        notes.extend(f"{label}: {n}" for n in sel.notes)

    return {
        "at_epoch_s": float(at_epoch_s),
        "roster_ok": True,
        "slice_index": cohort["slice_index"],
        "slice_seconds": cohort["slice_seconds"],
        "core": cohort["core"],
        "rotating": cohort["rotating"],
        "non_core_total": cohort["non_core_total"],
        "full_cycle_slices": cohort["full_cycle_slices"],
        "full_cycle_seconds": cohort["full_cycle_seconds"],
        "budget": budget,
        "split": split,
        "useful_depth_contracts": pol.useful_depth_contracts,
        "rotating_depth_each": (split["rotating"] // len(cohort["rotating"])
                                if cohort["rotating"] else 0),
        "rotating_per_slice": pol.rotating_per_slice,
        "symbols": symbols,
        "per_underlying": per_underlying,
        "symbol_underlying": symbol_underlying,
        "notes": notes,
        "policy": cohort["policy"],
    }


async def apply_options_slice(sc: Any, at_epoch_s: float, reason: str) -> dict[str, Any]:
    """Reconcile the live subscription to what this slice should be observing.

    ORDERING IS THE WHOLE POINT: drop then close-epoch (only after the vendor confirms the
    unsubscribe), add then open-epoch (only for services the vendor accepted), so the coverage
    record never claims observability we did not have. Core symbols appear in both the old and
    new set, so they are neither dropped nor re-added — continuous by construction.

    The daemon owns ONE stream. This module's own lock serialises a rotation slice against a
    daemon start / watchdog re-establish so two paths cannot drive the socket at once. The plan
    is computed OUTSIDE the lock (sqlite + arithmetic, no vendor call); only the vendor calls are
    serialised. The key budget is re-derived under the lock from the daemon's equity load.
    """
    global _options_subscribed, _options_last_receipt, _options_last_slice

    from stream_spine import STREAM_DB_DEFAULT as _CAPTURE_DB
    from calibration.options_stream_coverage import close_epochs, open_epochs
    from options_stream_subscription import (contract_budget_from_key_limit, subscribe_options,
                                             unsubscribe_options)

    # PLANNING OFF THE LOOP. options_desired_for_slice reads the enrollment roster and builds and
    # selects option chains — sqlite + selection work. Run inline on the daemon's event loop it
    # would stall the pump that services equity, book and options frames for the whole duration of
    # the plan (a slow slice becomes a stream stall and dropped frames). Hand it to a worker thread
    # so the loop keeps reading the socket while the slice is computed. The plan is a pure function
    # of (clock, equity load, roster); nothing it touches is loop-affine, and the vendor calls that
    # DO need the loop happen afterwards, under the lock, back on the loop.
    plan = await asyncio.to_thread(
        options_desired_for_slice, at_epoch_s, equity_symbols=_equity_symbols,
        equity_key_services=_equity_key_services, book_enabled=_book_enabled)

    if not plan.get("roster_ok", True):   # caps-ok: options_desired_for_slice ALWAYS sets roster_ok; the True default only covers a hand-built plan (tests), and "proceed" is the normal-case reading
        # ROSTER UNAVAILABLE: hold the current subscription EXACTLY as it is rather than
        # reconciling toward an empty want-set (which would UNSUB continuous core on a transient
        # DB read failure). Recorded so the gap is visible.
        _options_last_slice = {"reason": reason, "at_epoch_s": plan["at_epoch_s"],
                               "slice_index": plan["slice_index"], "roster_ok": False,
                               "added": 0, "dropped": 0,
                               "subscribed_by_service": {s: len(_options_subscribed[s])
                                                         for s in OPTIONS_SERVICES},
                               "notes": plan["notes"][:12]}
        log.warning("options slice held unchanged: %s", plan["notes"][:1])
        return _options_last_slice

    want = list(dict.fromkeys(plan["symbols"]))

    lock = _options_lock
    if lock is None:
        # Outside the daemon loop (tests, or a teardown race) there is no shared socket to
        # protect. A null lock must not silently mean "unsynchronised on a live socket", so the
        # only path that reaches here is one where the daemon is not running.
        import contextlib
        lock = contextlib.AsyncExitStack()

    async with lock:
        # RE-DERIVE UNDER THE LOCK against the daemon's equity load.
        fresh = contract_budget_from_key_limit(
            equity_symbols=_equity_symbols, equity_key_services=_equity_key_services,
            book_enabled=_book_enabled)
        allowed = int(fresh["contracts_allowed"])
        if len(want) > allowed:
            plan["notes"].append(
                f"equity load changed while planning: trimmed {len(want)} -> {allowed} contracts "
                f"to stay inside the key budget")
            want = want[:allowed]

        return await _reconcile_options_subscription(
            sc, plan, want, reason, keys_available=int(fresh["keys_available_for_options"]),
            capture_db=_CAPTURE_DB, close_epochs=close_epochs, open_epochs=open_epochs,
            subscribe_options=subscribe_options, unsubscribe_options=unsubscribe_options)


async def _reconcile_options_subscription(sc, plan, want, reason, *, keys_available,
                                          capture_db, close_epochs, open_epochs,
                                          subscribe_options, unsubscribe_options
                                          ) -> dict[str, Any]:
    """The vendor calls and the coverage writes, PER SERVICE, in the order the record depends on.

    Vendor state, internal state and the coverage record are reconciled INDEPENDENTLY PER
    SERVICE; internal state only ever moves on an acknowledged vendor result. A failed
    unsubscribe keeps the contract in our set (its key is still held) and leaves its epoch open;
    a partial subscribe records only the service that accepted, so the refused one retries.
    """
    global _options_subscribed, _options_last_receipt, _options_last_slice
    from calibration.options_stream_coverage import CoverageWriteError
    _CAPTURE_DB = capture_db
    want_set = set(want)
    now_ms = int(time.time() * 1000.0)
    per_service: dict[str, dict[str, int]] = {}

    # ── DROP, per service. Release internally only what the vendor acknowledged releasing. ──
    to_drop = sorted({s for svc in OPTIONS_SERVICES for s in _options_subscribed[svc]} - want_set)
    if to_drop:
        receipt = await unsubscribe_options(sc, to_drop)
        for service, key in (("LEVELONE_OPTIONS", "level_one"), ("OPTIONS_BOOK", "book")):
            held = [s for s in to_drop if s in _options_subscribed[service]]
            if not held:
                continue
            if receipt.get(key):
                try:
                    close_epochs(_CAPTURE_DB, held, service=service, reason=reason, at_ms=now_ms)
                except CoverageWriteError as e:
                    # The vendor released the keys, but the durable epoch close did NOT land.
                    # Keep these in memory so memory and the still-open epoch AGREE they are
                    # covered — never let memory drop ahead of the record. Because they stay in
                    # memory and out of want, the next slice re-drops and RETRIES the close;
                    # once it lands, memory follows. The transient over-hold self-heals.
                    plan["notes"].append(
                        f"{service}: unsubscribe acknowledged but coverage close FAILED for "
                        f"{len(held)} contract(s) — held in memory to match the open epoch, "
                        f"will retry next slice ({e})")
                    log.warning("options %s: coverage close failed after unsubscribe; keeping %d "
                                "in memory so state matches the record", service, len(held))
                    continue
                _options_subscribed[service] -= set(held)
                per_service.setdefault(service, {})["dropped"] = len(held)
            else:
                # STILL SUBSCRIBED AT THE VENDOR. Keep it so the next slice retries and its key
                # stays accounted for; do NOT close its epoch — frames may still arrive and the
                # record must keep matching reality.
                plan["notes"].append(
                    f"{service}: unsubscribe NOT acknowledged for {len(held)} contract(s) — "
                    f"kept subscribed and epoch left open; errors={receipt.get('errors')}")
                log.warning("options %s: unsubscribe not acknowledged for %d contracts; "
                            "keeping them so their keys stay accounted for", service, len(held))

    # ── KEY-BUDGET CAP, against ACTUAL post-drop vendor-held keys. ──
    # |LEVELONE held| + |BOOK held| <= keys_available. Whatever is STILL HELD after the drop
    # phase consumes keys — including contracts the vendor REFUSED to unsubscribe — so additions
    # are admitted one symbol at a time only while they fit. want is CORE-FIRST, so core is
    # funded before any rotating name.
    held_keys = sum(len(_options_subscribed[svc]) for svc in OPTIONS_SERVICES)
    projected = held_keys
    affordable: set[str] = set()
    for s in want:
        cost = sum(1 for svc in OPTIONS_SERVICES if s not in _options_subscribed[svc])
        if cost == 0:
            affordable.add(s)
            continue
        if projected + cost <= keys_available:
            affordable.add(s)
            projected += cost
    if len(affordable) < len(want):
        plan["notes"].append(
            f"key budget: {held_keys}/{keys_available} keys already held (incl. undroppable "
            f"contracts); admitted {len(affordable)}/{len(want)} wanted contracts to stay under "
            f"the limit and protect the equity stream")
        log.warning("options key budget: %d/%d held, admitting %d/%d wanted contracts",
                    held_keys, keys_available, len(affordable), len(want))

    # ── ADD, per service. A service is subscribed only if its own receipt slot says so. ──
    for service, key in (("LEVELONE_OPTIONS", "level_one"), ("OPTIONS_BOOK", "book")):
        missing = [s for s in want if s in affordable and s not in _options_subscribed[service]]
        if not missing:
            continue
        # SUBS ESTABLISHES (replaces the service's whole key list), ADD EXTENDS. An empty
        # post-drop set means establish/re-establish; a non-empty set means extend.
        operation = "subs" if not _options_subscribed[service] else "add"
        receipt = await subscribe_options(
            sc, missing, level_one=(service == "LEVELONE_OPTIONS"),
            book=(service == "OPTIONS_BOOK"), operation=operation)
        _options_last_receipt = receipt
        if receipt.get(key):
            try:
                open_epochs(_CAPTURE_DB, missing, service=service, policy=plan["policy"],
                            reason=reason, at_ms=now_ms)
            except CoverageWriteError as e:
                # The vendor accepted the subscribe, but the durable epoch did NOT open. Do NOT
                # mark these subscribed in memory: memory must never claim coverage the record
                # lacks. Leaving them unmarked means the next slice re-adds (idempotent at the
                # vendor) and retries the epoch open — coverage is UNDER-claimed until it lands,
                # which is the safe direction (a reader sees NOT_SUBSCRIBED, never a false OK).
                plan["notes"].append(
                    f"{service}: subscribe accepted but coverage open FAILED for {len(missing)} "
                    f"contract(s) — NOT marked subscribed so the record stays authoritative, "
                    f"will retry next slice ({e})")
                log.warning("options %s: coverage open failed after subscribe; not advancing "
                            "memory for %d contracts", service, len(missing))
                continue
            _options_subscribed[service] |= set(missing)
            per_service.setdefault(service, {})["added"] = len(missing)
        else:
            plan["notes"].append(
                f"{service}: subscribe REFUSED for {len(missing)} contract(s) — will retry next "
                f"slice; errors={receipt.get('errors')}")
            log.warning("options %s: subscribe refused for %d contracts; will retry",
                        service, len(missing))

    dropped_ok = sum(v.get("dropped", 0) for v in per_service.values())  # caps-ok: per_service is built in THIS function; a service with no drop this slice recorded none, so 0 is the true count
    added = sum(v.get("added", 0) for v in per_service.values())  # caps-ok: per_service is built in THIS function; a service with no add this slice recorded none, so 0 is the true count

    # PLANNED vs ADMITTED, service-aware. per_underlying_admitted is the FULLY-observed depth =
    # the count of contracts held on EVERY service (the intersection of the symbol sets), so
    # different contracts on different services cannot combine into fake full coverage.
    sym_und = dict(plan.get("symbol_underlying") or {})

    def _underlying(sym: str) -> str:
        u = sym_und.get(sym)
        if u:
            return u
        root = sym.split()[0].strip() if isinstance(sym, str) and sym else ""
        return root or "UNKNOWN"

    def _by_underlying(symbols) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in symbols:
            u = _underlying(s)
            out[u] = out.get(u, 0) + 1
        return out

    admitted_by_service = {s: _by_underlying(_options_subscribed[s]) for s in OPTIONS_SERVICES}
    held_all_services = (set.intersection(*(_options_subscribed[s] for s in OPTIONS_SERVICES))
                         if OPTIONS_SERVICES else set())
    per_underlying_admitted = {u: c for u, c in _by_underlying(held_all_services).items() if c > 0}
    admitted_underlyings = set(per_underlying_admitted)
    rotating_admitted = sorted(u for u in plan["rotating"] if u in admitted_underlyings)
    core_admitted = sorted(u for u in plan["core"] if u in admitted_underlyings)
    fully_admitted = all(
        per_underlying_admitted.get(u, 0) >= cnt for u, cnt in plan["per_underlying"].items())
    held_union = set().union(*_options_subscribed.values()) if _options_subscribed else set()

    _options_last_slice = {
        "reason": reason,
        "at_epoch_s": plan["at_epoch_s"],
        "slice_index": plan["slice_index"],
        "core_planned": plan["core"],
        "rotating_planned": plan["rotating"],
        "per_underlying_planned": plan["per_underlying"],
        "core_admitted": core_admitted,
        "rotating_admitted": rotating_admitted,
        "per_underlying_admitted": per_underlying_admitted,
        "admitted_by_service": admitted_by_service,
        "fully_admitted": fully_admitted,
        "added": added,
        "dropped": dropped_ok,
        "subscribed_by_service": {s: len(_options_subscribed[s]) for s in OPTIONS_SERVICES},
        "subscribed_total": len(held_union),
        "services_in_agreement": len({frozenset(v) for v in _options_subscribed.values()}) == 1,
        "full_cycle_seconds": plan["full_cycle_seconds"],
        "notes": plan["notes"][:12],
    }
    log.info("OPTIONS slice %s (%s): +%d -%d; by service %s; ADMITTED %d/%d underlyings "
             "(fully=%s); core=%s cycle=%ss",
             plan["slice_index"], reason, added, dropped_ok,
             _options_last_slice["subscribed_by_service"],
             len(per_underlying_admitted), len(plan["per_underlying"]), fully_admitted,
             core_admitted, plan["full_cycle_seconds"])
    return _options_last_slice


async def _options_rotation_loop(sc: Any) -> None:
    """Advance the rotation at each slice boundary, on the daemon's loop and its ONE client.

    A task on the existing loop, cancelled by stop_options_collection — never a thread and never
    a second client. Boundaries are computed from the clock, not a fixed sleep, so a slow slice
    cannot drift from the deterministic slice_index that replay and the coverage record depend on.
    """
    from options_stream_subscription import RotationPolicy

    pol = RotationPolicy()
    while True:
        now = time.time()
        nxt = (pol.slice_index(now) + 1) * float(pol.slice_seconds)
        try:
            await asyncio.sleep(max(1.0, nxt - now))
        except asyncio.CancelledError:
            raise
        try:
            await apply_options_slice(sc, time.time(), reason="rotation")
        except asyncio.CancelledError:
            raise
        except Exception as e:                          # noqa: BLE001
            log.warning("options rotation slice failed (collection continues): %s", e)


def flush_options_ingest_health(capture_db: Any, *, offered: int, written: int,
                                started_ms: int, at_ms: int | None = None) -> None:
    """Record one options_stream_ingest_health window from the live counters.

    offered is counted by the handler as it publishes; written by the persister as it inserts. Any
    shortfall (offered - written) is a DROP — a frame shed by the bounded bus queue under load, the
    same measured hole OptionsFrameIngest recorded, kept durable so SUBSCRIBED_MAYBE_DROPPED stays
    answerable after the process exits. Best-effort: a failed health write must not fail teardown.
    """
    try:
        import sqlite3
        from calibration.options_stream_ingest import ensure_ingest_health_schema
        dropped = max(0, int(offered) - int(written))
        now = int(at_ms if at_ms is not None else time.time() * 1000.0)  # caps-ok: at_ms unspecified means stamp the health window at the current instant (this call's documented default), not a measurement being replaced
        conn = sqlite3.connect(str(capture_db), timeout=30.0)
        try:
            ensure_ingest_health_schema(conn)
            conn.execute(
                "INSERT INTO options_stream_ingest_health (window_start_ms, window_end_ms, "
                "offered, written, dropped, write_errors, max_queue_depth, max_ingest_lag_ms, "
                "batches, write_ms_total) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(started_ms or now), now, int(offered), int(written), dropped, 0, 0, None, 0, 0.0))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:                              # noqa: BLE001
        log.debug("options ingest health flush: %s", e)


async def start_options_collection(sc: Any, *, bus: Any, equity_symbols: int,
                                   equity_key_services: int = 2, book_enabled: bool = True) -> None:
    """Reconcile any orphaned coverage, wire the bus, subscribe slice zero, run the rotation.

    Called by the capture daemon after it has subscribed its equity services on the ONE stream and
    registered the option persister on its single CaptureWriter. `bus` is that daemon's MessageBus:
    option frames publish onto it and are persisted by the shared writer — no second connection.
    Every failure path is soft: options collection is additive and must never disturb the daemon's
    equity/book capture. `equity_symbols`/`equity_key_services` describe the DAEMON's equity load so
    the options budget is sized against the stream that is actually held.
    """
    global _options_bus, _active_stream, _options_rotation_task
    global _options_offered, _options_written, _options_started_ms
    global _equity_symbols, _equity_key_services, _book_enabled, _options_lock

    _equity_symbols = max(1, int(equity_symbols))
    _equity_key_services = max(1, int(equity_key_services))
    _book_enabled = bool(book_enabled)
    _options_bus = bus
    _active_stream = sc
    if _options_lock is None:
        _options_lock = asyncio.Lock()

    if not options_streaming_enabled():
        log.info("options streaming disabled (%s unset) — LEVELONE_OPTIONS/OPTIONS_BOOK handlers "
                 "registered but nothing subscribed", ED_OPTIONS_STREAM_ENV)
        return
    try:
        # RC-6 law: raw stream capture goes to stream_capture.db, NEVER ed_console.db.
        from stream_spine import STREAM_DB_DEFAULT as _CAPTURE_DB
        from calibration.options_stream_coverage import reconcile_open_epochs_on_start
    except Exception as e:                              # noqa: BLE001
        log.warning("options collection unavailable: %s", e)
        return

    try:
        # RESTART COVERAGE TRUTH: close any epoch left open by a prior UNCLEAN exit at its LAST
        # OBSERVED instant (never `now`), so the record never claims observation across the
        # downtime gap. Runs before any new epoch opens.
        closed = reconcile_open_epochs_on_start(_CAPTURE_DB, services=OPTIONS_SERVICES)
        if any(closed.values()):
            log.warning("options coverage: closed orphaned epochs from an unclean prior exit: %s",
                        closed)

        _options_offered = 0
        _options_written = 0
        _options_started_ms = int(time.time() * 1000.0)

        # Slice zero runs through the SAME reconciler every boundary uses, so start-up and steady
        # state cannot drift apart. Frames only arrive after this subscribe, so the bus is wired
        # (above) before anything can be published.
        await apply_options_slice(sc, time.time(), reason="stream_start")
        if not any(_options_subscribed.values()):
            log.warning("options collection: slice produced no contracts — nothing subscribed "
                        "(a COVERAGE GAP, not a market observation); tearing down cleanly")
            await stop_options_collection("start_no_contracts")
            return

        _options_rotation_task = asyncio.create_task(
            _options_rotation_loop(sc), name="options_rotation")
    except Exception as e:                              # noqa: BLE001
        log.warning("options collection failed to start (equity stream unaffected): %s", e)
        try:
            await stop_options_collection("start_failed")
        except Exception as e2:                         # noqa: BLE001
            log.warning("options collection: cleanup after failed start: %s", e2)


async def stop_options_collection(reason: str = "stream_stop", *, unsubscribe: bool = False,
                                  timeout_s: float = 10.0) -> None:
    """Cancel AND AWAIT the rotation, optionally UNSUBSCRIBE the vendor, then close coverage epochs.

    Teardown is a contract, not a fire-and-forget:
      * the rotation task is cancelled AND AWAITED, so no slice is still mid-flight (opening epochs
        or driving the socket) when the rest of teardown runs;
      * on a clean shutdown (`unsubscribe=True`) the vendor is UNSUBSCRIBED so its keys are released
        rather than leaked until logout — bounded by `timeout_s` so a half-open socket cannot hang
        the shutdown, and best-effort (a recycle passes a dead socket and simply fails soft);
      * epochs are closed per service so none is left claiming observation past this instant;
      * a health window is flushed so the run's drop accounting survives the process.
    """
    global _options_bus, _active_stream, _options_subscribed, _options_rotation_task
    global _options_last_slice, _options_offered, _options_written, _options_started_ms

    # Stop advancing the rotation BEFORE anything else and AWAIT it, so a slice cannot fire into a
    # half-torn-down state (the previous version cancelled without awaiting — the coroutine could
    # still be inside a vendor call or an epoch open when teardown proceeded).
    task, _options_rotation_task = _options_rotation_task, None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:                          # noqa: BLE001
            log.warning("awaiting cancelled options rotation: %s", e)
    _options_last_slice = None

    from stream_spine import STREAM_DB_DEFAULT as _CAPTURE_DB

    # UNSUBSCRIBE the vendor on a clean stop, so held option keys are released rather than leaked.
    sc = _active_stream
    if unsubscribe and sc is not None:
        held = sorted(set().union(*_options_subscribed.values())) if _options_subscribed else []
        if held:
            try:
                from options_stream_subscription import unsubscribe_options
                await asyncio.wait_for(unsubscribe_options(sc, held), timeout=timeout_s)
            except Exception as e:                      # noqa: BLE001
                # A dead/half-open socket (a recycle) or a slow vendor must not hang or fail
                # teardown — the epoch close below still records that observation ended.
                log.warning("options unsubscribe on teardown (%s): %s", reason, e)

    try:
        if any(_options_subscribed.values()):
            from calibration.options_stream_coverage import close_epochs
            now_ms = int(time.time() * 1000.0)
            # PER SERVICE: close exactly what that service actually held. Closing the union would
            # write an end for an epoch that was never opened.
            for service in OPTIONS_SERVICES:
                held = sorted(_options_subscribed[service])
                if held:
                    try:
                        close_epochs(_CAPTURE_DB, held, service=service, reason=reason, at_ms=now_ms)
                    except Exception as e:              # noqa: BLE001
                        log.warning("closing options coverage epochs (%s): %s", service, e)
    finally:
        _options_subscribed = {s: set() for s in OPTIONS_SERVICES}

    # Flush the run's drop accounting (offered - written) before clearing the counters.
    if _options_offered or _options_written:
        flush_options_ingest_health(_CAPTURE_DB, offered=_options_offered,
                                    written=_options_written, started_ms=_options_started_ms)
    _options_offered = 0
    _options_written = 0
    _options_started_ms = 0
    _options_bus = None
    _active_stream = None


def options_stream_status() -> dict[str, Any]:
    """Live options-collection health, for the daemon's diagnostics surface."""
    out: dict[str, Any] = {
        "enabled": options_streaming_enabled(),
        "subscribed_by_service": {s: len(_options_subscribed[s]) for s in OPTIONS_SERVICES},
        "subscribed_contracts": len(set().union(*_options_subscribed.values())
                                    if _options_subscribed else set()),
        "services_in_agreement": len({frozenset(v) for v in _options_subscribed.values()}) == 1,
        "last_receipt": _options_last_receipt,
        "last_slice": _options_last_slice,
        "rotation_running": bool(_options_rotation_task is not None
                                 and not _options_rotation_task.done()),
        # PERSISTENCE rides the daemon's single CaptureWriter, not a private queue. The counters are
        # the frames handed to the bus (offered) and the frames the shared writer persisted
        # (written); their difference is the bus-shed drop count.
        "persistence": "daemon_capture_writer",
        "ingest": {"offered": _options_offered, "written": _options_written,
                   "dropped_est": max(0, _options_offered - _options_written)},
    }
    return out
