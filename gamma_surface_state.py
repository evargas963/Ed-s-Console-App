"""Gamma-surface runtime state: the demand registry (which tickers a viewer asked for), the
stream-staleness bound, the per-ticker publication counter (`_next_gamma_surface_seq`, which
also pushes the light-SSE notify), the desired-contract / option-admission views, and the
per-cell stream-state stamping + coverage summary. Extracted from server.py (RC-REHAB-1,
2026-09-23, forty-second slice) as one unit; every dict here is mutated in place, never
rebound. The only server runtime it touches, the L1 light-SSE queue, is read through a lazy
`import server as _srv` at call time.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


# RC-UI-1 #1: gamma-surface demand registry — the /api/options/gamma-surface endpoint marks a
# ticker "wanted" on each request; _terrain_refresh_one projects the (measurable) strike x expiry
# surface only for tickers wanted within the TTL, so unviewed tickers pay no surface cost.
_gamma_surface_demand: dict = {}
GAMMA_SURFACE_DEMAND_TTL = 300.0


def _note_gamma_surface_demand(tk: str) -> None:
    now = time.time()
    _gamma_surface_demand[tk] = now
    # opportunistic hygiene (no background thread): drop expired keys so the registry can't grow
    # unbounded from arbitrary/expired tickers.
    if len(_gamma_surface_demand) > 64:
        for _k in [k for k, ts in list(_gamma_surface_demand.items()) if now - ts >= GAMMA_SURFACE_DEMAND_TTL]:
            _gamma_surface_demand.pop(_k, None)


def _gamma_surface_wanted(tk: str) -> bool:
    return (time.time() - _gamma_surface_demand.get(tk, 0.0)) < GAMMA_SURFACE_DEMAND_TTL


#: A streamed GAMMA/DELTA/OPEN_INTEREST value older than this is not trusted AT ALL, even if
#: it is newer than the REST baseline it would override — an app-side absolute bound (not a
#: vendor-documented cadence), chosen to be well inside a stalled-feed operator would notice,
#: composed with (never a substitute for) the REST-baseline precedence check below.
GAMMA_SURFACE_STREAM_STALENESS_SEC = 10.0

#: RETIRED (2026-09-12): a leading-edge per-ticker time debounce used to live here. Independent
#: review found it provided ZERO protection against the exact backlog it was written for: a
#: leading-edge debounce rejects a call only if it arrives too soon after the PREVIOUS call's
#: own start, but when the computation itself is slow, that previous call's own duration
#: already exceeds any reasonable debounce window by the time the next one can even arrive --
#: sequential bursts each still paid the full per-call cost. Worse, a debounced call was
#: silently dropped with nothing scheduling a trailing publication, so the LAST update of a
#: burst could go permanently unpublished. Replaced with per-batch coalescing in
#: app.options.order_flow.streaming._replay_option_contract_rows itself: every row in a poll
#: batch still updates OrderFlowState, but the (expensive) hook fires ONCE per batch using the
#: freshest row, not once per row -- bounding the real worst-case rate to "one recompute per
#: poll-loop iteration that has new data" without ever silently discarding the batch's own
#: latest observation. See that function's own comment for the full reasoning, and
#: tests/test_streamed_greeks_hook_v1.py::test_hook_coalescing_avoids_the_real_per_call_
#: cost_at_spxw_scale for the actual, reproducible, rerunnable per-call latency this hook's
#: real consumer (refresh_gamma_surface_from_stream, below) pays at full SPXW scale --
#: independent-review performance-assurance finding (2026-09-12): the per-call cost figure
#: previously hardcoded here traced to no committed benchmark; it now traces to that test's
#: own measured output instead.

#: Per-ticker counter bumped every time `_gamma_surface` is (re)published — by the REST cycle
#: or the eager stream refresh alike. Independent-review finding (2026-09-12), REPRODUCED: the
#: browser's renderSurface() skips its table rebuild when its own revision key (built from
#: chain_as_of_ts_utc/spot_as_of_ts_utc — REST-only fields) is unchanged; the eager refresh
#: changes cell VALUES without ever touching those REST fields, so a genuinely new surface
#: rendered as the old one until the next REST cycle happened to land. This counter is a
#: revision identity ANY publication bumps, REST or streamed, so the browser has something
#: that actually changes when the data does. Guarded by _terrain_cache_lock, like the cache
#: it describes.
_gamma_surface_seq: dict[str, int] = {}


def _next_gamma_surface_seq(tk: str) -> int:
    """Caller must hold _terrain_cache_lock. Also PUSHES a lightweight SSE notify -- no data of
    its own, just {ticker, surface_seq} -- to any /api/analytics/light/stream client currently
    viewing this ticker, so the browser refetches the instant a new generation publishes
    instead of waiting out the slow 3s/12s poll.

    Independent-review finding (2026-09-12): "the browser still polls every 12 seconds. The
    new Playwright test manually triggers the refresh event, bypassing that wait. It proves
    rendering after delivery, not timely delivery." True of the prior commit: surface_seq made
    a change DETECTABLE once the browser next asked, but nothing made it ASK sooner. This
    reuses the EXISTING SSE connection/queue/dispatch pipe wholesale
    (_l1_put_thread_queue_notify -> _l1_light_sse_dispatch_loop -> the /api/analytics/light/
    stream generator, which now picks the wire event name from the envelope instead of
    hardcoding "l1_projection") -- no second SSE endpoint, connection, or daemon. Best-effort:
    a failed push here still leaves surface_seq bumped and the slow poll as an honest fallback
    (SSE down/stalled already falls back to polling on the client)."""
    import server as _srv                      # runtime: the L1 light-SSE notify queue

    n = _gamma_surface_seq.get(tk, 0) + 1
    _gamma_surface_seq[tk] = n
    try:
        _srv._l1_put_thread_queue_notify(
            (tk, "__auto__"),
            {"_sse_event_name": "gamma_surface_seq", "scope": {"ticker": tk}, "surface_seq": n},
        )
    except Exception as e:  # institutional-swallow-ok: push notify is best-effort; poll fallback still exists
        log.debug("gamma_surface_seq SSE notify failed for %s: %s", tk, e)
    return n


def _desired_stream_greeks_for_ticker(tk: str) -> dict:
    """Every currently-live streamed GAMMA/DELTA/OPEN_INTEREST/VOLUME entry for a
    contract belonging to `tk` — the PRIMARY/pinned contract AND every ADDITIONALLY-
    desired contract (RC-UI-3 multi-contract coverage), gathered FRESH on every call.

    Independent-review finding (2026-09-12), root cause of the "refreshing B loses A's
    update" defect: the two callers below used to build a single-entry
    `{contract_symbol: greeks}` map for whichever ONE contract triggered that particular
    refresh, then overlay it onto the untouched REST baseline — so refreshing B always
    discarded A's already-fresh streamed value, because the baseline itself carries no
    memory of a prior overlay. Fixed at the root by never relying on such memory: this
    reconstructs the FULL multi-contract streamed set from scratch every call.
    `get_stream_greeks` IS the live per-symbol store (app.options.order_flow.state),
    cleared exactly when a symbol's coverage genuinely ends (clear_symbol) — so
    re-querying it for every currently-desired symbol on every refresh, no matter which
    one triggered it, always reconstructs every symbol's latest known state, and a symbol
    whose coverage has ended is correctly absent (never lingers as a stale entry here).

    Native contract identity uses app.options.order_flow.streaming.contract_matches_underlying
    (chain-aware: a vendor root that genuinely differs from the ticker's own root, e.g.
    Schwab's $SPX -> SPXW weekly, is still recognized via the nearest banked complete chain) —
    independent-review finding (2026-09-12): a bare vendor-root == ticker-root equality check
    silently excludes exactly this legitimate case."""
    from app.options.order_flow.state import get_stream_greeks
    out: dict = {}
    for sym in _desired_option_symbols_for_ticker(tk):
        greeks = get_stream_greeks(sym)
        if greeks:
            out[sym] = greeks
    return out


def _desired_option_symbols_for_ticker(tk: str) -> "list[str]":
    """Every option-contract symbol this daemon currently DESIRES for `tk` — the primary/
    pinned contract AND every additionally-desired contract (RC-UI-3 multi-contract
    coverage) — regardless of whether a stream tick has landed for it yet.

    Extracted from `_desired_stream_greeks_for_ticker` (2026-09-16, coverage-summary
    'pending' state): that function's own candidate set already IS "desired", but it only
    ever surfaced the subset with an existing `get_stream_greeks` entry — a symbol the
    vendor has genuinely admitted but which has not yet produced its first tick was
    therefore indistinguishable from a symbol nobody ever asked for. This is the desired
    set on its own, so a caller can tell "requested, awaiting first tick" (PENDING) apart
    from "never desired at all" (UNAVAILABLE)."""
    from app.options.order_flow.streaming import (
        get_active_option_contract, get_active_option_contracts, contract_matches_underlying)
    out: "list[str]" = []
    candidates = list(get_active_option_contracts())
    primary = get_active_option_contract()
    if primary:
        candidates.append(primary)
    for sym in candidates:
        if sym and sym not in out and contract_matches_underlying(sym, tk):
            out.append(sym)
    return out


def _option_contract_admission_summary(tk: str) -> dict:
    """Per-symbol admitted/observed/active/pending/rejected accounting for `tk`'s desired
    option contracts, sourced ENTIRELY from PRODUCER acknowledgements (2026-09-16,
    independent-review follow-up mandate item 1: "expose the exact admitted, active,
    pending and rejected contracts"). Every bucket answers a materially different
    question about a desired symbol:
      'active'   — has produced a tick WITHIN the canonical staleness window
                   (GAMMA_SURFACE_STREAM_STALENESS_SEC, the SAME bound
                   overlay_streamed_contract_fields/the 'live' cell state already use) —
                   freshness-gated, not merely "has ever ticked". A symbol whose only
                   observation is older than this window is 'observed', not 'active':
                   correctness finding (2026-09-17) — a harness or UI claiming a stale
                   historical observation is "currently active" is exactly the false-
                   success shape the operator's own negative controls exist to catch.
      'observed' — has produced at least one real tick EVER (present in
                   _desired_stream_greeks_for_ticker's own output) but that tick is
                   OLDER than the staleness window — the vendor genuinely sent data at
                   some point; it is not necessarily still fresh right now.
      'admitted' — the DAEMON's own durable, heartbeat-confirmed open coverage epoch names
                   this symbol (streaming.read_producer_admitted_option_contracts,
                   LEVELONE_OPTIONS service) but no tick has EVER arrived — the vendor
                   subscription itself is confirmed, only the first observation is still
                   outstanding.
      'pending'  — desired, the daemon is CONFIRMED alive, but neither a tick nor a
                   confirmed admission has landed yet — requested, outcome not yet known.
      'rejected' — {symbol: vendor_error} for every desired symbol the vendor's most
                   recent batched subscribe attempt explicitly refused.
    A desired symbol that fits none of the above (daemon unreachable) is simply omitted
    from every bucket — unknown is never fabricated as any of these five claims; the
    `daemon_available` flag on the returned dict is how a caller tells "genuinely nothing
    to report yet" apart from "cannot know right now". `active` and `observed` are
    mutually exclusive (a symbol is one or the other, never both), and a REJECTED symbol
    is reported ONLY in `rejected` — never also counted as `active`/`observed`/`admitted`/
    `pending`, so a caller cannot mistake "the vendor refused this" for any flavor of
    success by unioning buckets carelessly."""
    from app.options.order_flow.streaming import (
        read_producer_admitted_option_contracts, read_producer_rejected_option_contracts,
        is_option_producer_daemon_available)
    desired = _desired_option_symbols_for_ticker(tk)
    daemon_available = is_option_producer_daemon_available()
    rejected_all = read_producer_rejected_option_contracts()
    admitted_l1 = set((read_producer_admitted_option_contracts() or {}).get("LEVELONE_OPTIONS") or [])
    streamed = _desired_stream_greeks_for_ticker(tk)
    now = time.time()
    admitted, active, observed, pending = [], [], [], []
    rejected: "dict[str, str]" = {}
    for sym in desired:
        if sym in rejected_all:
            rejected[sym] = rejected_all[sym]
        elif sym in streamed:
            ts_recv = _leg_stream_ts_recv(streamed.get(sym))
            if ts_recv is not None and (now - ts_recv) <= GAMMA_SURFACE_STREAM_STALENESS_SEC:
                active.append(sym)
            else:
                observed.append(sym)
        elif sym in admitted_l1:
            admitted.append(sym)
        elif daemon_available:
            pending.append(sym)
        # else: daemon unavailable -- genuinely unknown, omitted from every bucket
    return {
        "daemon_available": daemon_available,
        "admitted": sorted(admitted), "active": sorted(active), "observed": sorted(observed),
        "pending": sorted(pending), "rejected": rejected,
    }


def _overlaid_symbols(pre: list, post: list) -> list[str]:
    """Which contracts' own dicts `overlay_streamed_contract_fields` actually replaced with a
    freshened copy -- that function's own contract is "sparse, non-destructive... a contract
    absent from streamed_by_symbol is passed through UNCHANGED (SAME dict, not a copy)", so a
    changed contract is identifiable by object identity alone (`is not`), with no need to
    diff field values or touch that function's own return signature.

    A SIXTH independent review (2026-09-13), REPRODUCED: the heatmap's 'observed' demand
    state promoted EVERY currently-accepted column the instant `stream_overlay_contracts`
    (a single surface-wide COUNT) was merely nonzero, whichever contract or expiry
    actually received the freshening -- one overlaid contract on an UNRELATED expiry
    incorrectly marked a completely different column as carrying real observed evidence.
    This is the missing piece: WHICH symbols were actually freshened, so a consumer can
    bind 'observed' to the specific column/contracts it actually covers."""
    return [new.get("symbol") for orig, new in zip(pre, post)
            if new is not orig and isinstance(new, dict) and new.get("symbol")]


def _leg_stream_ts_recv(greeks: dict | None) -> float | None:
    """The freshest of a streamed contract's own per-field `_ts_recv` stamps (get_stream_greeks'
    shape, app.options.order_flow.state), or None if `greeks` is absent/empty. Any one of these
    fields ticking is evidence the contract is actively producing observations right now, so the
    MAX (not a single hardcoded field) is the contract's own last-observed instant."""
    if not greeks:
        return None
    candidates = [greeks.get(k) for k in
                  ("gamma_ts_recv", "open_interest_ts_recv", "delta_ts_recv", "total_volume_ts_recv")]
    candidates = [c for c in candidates if isinstance(c, (int, float))]
    return max(candidates) if candidates else None


def _stamp_gamma_surface_cell_stream_state(surface: dict, streamed: dict, overlay_symbols: set,
                                           rejected_symbols: "dict[str, str] | None" = None,
                                           desired_symbols: "set[str] | None" = None, *,
                                           daemon_available: bool = True) -> None:
    """Operator directive (2026-09-15, always-live heatmap mandate): attach per-leg (call/put)
    and per-cell aggregate STREAM state to an already-projected gamma surface's cells, in place.

    Pure disclosure/gating metadata layered on top of RC-80's single faucet — this NEVER touches
    a cell's already-computed net_gex_1pct/etc value (project_gamma_surface/
    compute_exposures_by_strike remains the sole exposure computation). It only annotates, per
    leg, WHETHER that value is currently backed by a confirmed-fresh Schwab stream tick, so a
    client can honestly render LIVE / PARTIAL / STALE / PENDING / REJECTED / DAEMON_UNAVAILABLE /
    UNAVAILABLE instead of presenting every REST-cadence cell as indistinguishable from a
    genuinely streamed one.

    Per leg, `overlay_symbols` is the EXACT set _gamma_surface_contracts_with_stream_overlay (or
    refresh_gamma_surface_from_stream's own equivalent) already decided passed this cycle's
    REST-precedence + GAMMA_SURFACE_STREAM_STALENESS_SEC check for this specific symbol — reused
    verbatim rather than re-deriving a second staleness policy. `rejected_symbols` (2026-09-16,
    audit finding #6 — "fail the affected cells visibly", bounded-vendor-call reconciliation) is
    the producer's own {symbol: vendor_error} map (streaming.read_producer_rejected_option_
    contracts) — a symbol the vendor explicitly refused, not merely one not yet confirmed.
    `desired_symbols` (2026-09-16, operator's follow-up mandate: disclose PENDING distinctly from
    UNAVAILABLE) is `_desired_option_symbols_for_ticker`'s output — every symbol the daemon has
    asked the vendor for, whether or not a tick has landed yet.

    Independent-review finding (2026-09-16, follow-up mandate): 'pending' used to mean only
    "the CLIENT desires this symbol" — indistinguishable from a daemon that has silently died
    and will never admit anything again. `daemon_available` (streaming.
    is_option_producer_daemon_available — a FRESH producer heartbeat confirmed on this exact
    connection, never inferred) gates 'pending': a desired symbol reads 'pending' only while the
    daemon is confirmed alive; the identical symbol reads 'daemon_unavailable' the instant it
    is not, which is a materially different, and more actionable, fact for an operator ("the
    daemon needs restarting", not "this contract is merely queued behind a live one"):
      'live'                — this symbol's tick was fresh enough to be overlaid THIS cycle.
      'stale'                — the symbol IS currently desired/subscribed (present in
                              `streamed`, which _desired_stream_greeks_for_ticker already
                              filters to symbols matching this ticker) but its tick did not
                              pass this cycle's check.
      'pending'              — the symbol is desired, the daemon is CONFIRMED alive, and no
                              tick/rejection has landed yet — requested, outcome not yet known.
      'daemon_unavailable'   — the symbol is desired but the daemon's own producer heartbeat is
                              stale or absent — the outcome cannot be pending, because nothing
                              is currently working on it.
      'rejected'             — the vendor explicitly refused this contract's subscription; its
                              own error is carried on the leg so the UI can disclose WHY.
      'unavailable'          — no symbol for this leg (missing contract), or a symbol never
                              desired at all — covers unsubscribed, missing, and mismatched-
                              identity alike.

    Cell aggregate, over whichever legs actually exist for this strike/expiry, checked in this
    priority order (live > partial > stale > pending > daemon_unavailable > rejected >
    unavailable) — 'partial' requires at least one live leg, not all; every other aggregate is
    "no leg is any higher-priority state, at least one existing leg is this one"."""
    now = time.time()
    rejected_symbols = rejected_symbols or {}
    desired_symbols = desired_symbols or set()
    for cell in (surface.get("cells") or []):
        contracts_row = cell.get("contracts") or []
        state_row = []
        for pair in contracts_row:
            if not isinstance(pair, dict):
                state_row.append(None)
                continue
            legs: dict = {}
            leg_states: list[str] = []
            for side in ("call", "put"):
                sym = pair.get(side)
                if not sym:
                    continue
                greeks = streamed.get(sym)
                if sym in overlay_symbols:
                    leg_state = "live"
                elif sym in streamed:
                    leg_state = "stale"
                elif sym in rejected_symbols:
                    leg_state = "rejected"
                elif sym in desired_symbols and not daemon_available:
                    leg_state = "daemon_unavailable"
                elif sym in desired_symbols:
                    leg_state = "pending"
                else:
                    leg_state = "unavailable"
                leg_states.append(leg_state)
                ts_recv = _leg_stream_ts_recv(greeks)
                leg_out = {
                    "symbol": sym, "state": leg_state, "ts_recv": ts_recv,
                    "age_sec": (round(now - ts_recv, 1) if ts_recv is not None else None),  # caps-ok: age stays None when the leg has no receive timestamp -- honest absence
                }
                if leg_state == "rejected":
                    leg_out["rejected_reason"] = rejected_symbols.get(sym)
                legs[side] = leg_out
            if not leg_states:
                cell_state = "unavailable"
            elif all(s == "live" for s in leg_states):
                cell_state = "live"
            elif any(s == "live" for s in leg_states):
                cell_state = "partial"
            elif any(s == "stale" for s in leg_states):
                cell_state = "stale"
            elif any(s == "pending" for s in leg_states):
                cell_state = "pending"
            elif any(s == "daemon_unavailable" for s in leg_states):
                cell_state = "daemon_unavailable"
            elif any(s == "rejected" for s in leg_states):
                cell_state = "rejected"
            else:
                cell_state = "unavailable"
            legs["state"] = cell_state
            state_row.append(legs)
        cell["stream"] = state_row


def _gamma_surface_cell_state_counts(surface: dict) -> dict:
    """Tally the per-cell 'state' _stamp_gamma_surface_cell_stream_state already attached into
    cheap surface-level counts — a client or test's one-field check instead of scanning every
    cell. The seven states are mutually exclusive per cell (see that function's docstring)."""
    counts = {"live": 0, "partial": 0, "stale": 0, "pending": 0, "daemon_unavailable": 0,
              "rejected": 0, "unavailable": 0}
    for cell in (surface.get("cells") or []):
        for col in (cell.get("stream") or []):
            if isinstance(col, dict) and col.get("state") in counts:
                counts[col["state"]] += 1
    return counts


def _gamma_surface_coverage_summary(surface: dict) -> dict:
    """The CANONICAL-SURFACE coverage verdict for a projected surface — every strike x
    every expiry the server projected, not merely whichever subset the client happens to
    be scrolled/scoped to (2026-09-16, audit finding #6; independent-review CORRECTION,
    follow-up mandate: this field's scope must be named honestly, because it is NOT the
    same thing as "coverage of what the operator is currently looking at").

    Independent-review finding (2026-09-16): Auto/Wider/All strike-count windowing
    (EdShell.scopeSelect) and expiry-column windowing (ed-gamma.js's own viewCols) are
    BOTH decided entirely client-side and never communicated to the server — the server
    has no way to know which strikes/expiries are actually rendered right now. Computing
    `meets_live_requirement` over this whole canonical surface therefore answers "is the
    full projected book fully live", which can be STRICTER than what the mandate's own
    "every VISIBLE cell" language asks for (a narrower Auto-scoped view could be 100% live
    while a distant, invisible strike this field still counts is merely 'pending'). This
    field stays a genuinely useful, correctly-labelled canonical/diagnostic metric — the
    CLIENT's own "LIVE" word is gated on a SEPARATE, DOM-derived visible-scope computation
    (ed-gamma.js's `_visibleCellCoverage`, counting only the `.hcell` elements this exact
    render painted) which this field must never be mistaken for. The `scope` key on the
    returned dict makes that explicit in the wire payload itself, not only in this
    docstring.

    Coverage is judged only over cells that HAVE a real contract identity (at least one of
    call/put resolved to an actual OSI symbol) — a strike/expiry combination with no
    contract at all was never a viewable data point, and counting it against the bar would
    make `meets_live_requirement` false on nearly every real chain (different expiries
    legitimately cover different strike ranges) for a reason that has nothing to do with
    streaming health.

    `meets_live_requirement` implements the operator's own already-recorded directive
    (2026-09-15, "always-live heatmap mandate"): "every visible heatmap cell must
    correspond to an exact option contract actively receiving streamed Schwab updates" —
    literally 100% of cells-with-a-contract must be 'live', not merely "at least one cell
    is" — over THIS field's own canonical scope; the client's visible-scope computation is
    the actual authority for the on-screen LIVE word.

    `pending` (2026-09-16, operator's follow-up mandate) is counted and reported distinctly
    from `unavailable`: a cell whose contract has been REQUESTED of the vendor but has not
    yet ticked (or been rejected) is materially different from one nobody asked for at all,
    and both the mandate's coverage-disclosure requirement and a fair 'not yet live' verdict
    need that distinction on screen, not folded into the same bucket. `daemon_unavailable`
    (2026-09-16, follow-up mandate) is likewise counted distinctly from `pending`: the
    capture daemon itself being unreachable is a materially different, more actionable fact
    than a contract merely queued behind a live daemon's own poll cycle."""
    counts = {"live": 0, "partial": 0, "stale": 0, "pending": 0, "daemon_unavailable": 0,
              "rejected": 0, "unavailable": 0}
    relevant = 0
    for cell in (surface.get("cells") or []):
        contracts_row = cell.get("contracts") or []
        stream_row = cell.get("stream") or []
        for j, col in enumerate(stream_row):
            if not isinstance(col, dict):
                continue          # no contract identity at all -- never a viewable data cell
            pair = contracts_row[j] if j < len(contracts_row) else None
            has_identity = bool(isinstance(pair, dict) and (pair.get("call") or pair.get("put")))
            if not has_identity:
                continue
            relevant += 1
            state = col.get("state")
            if state in counts:
                counts[state] += 1
            else:
                counts["unavailable"] += 1
    # CAPS RC-REHAB-1: a live percentage over ZERO contract-bearing cells is undefined -> None
    # (was a served 0.0 "0% live" for a surface with nothing to be live).
    live_pct = round(100.0 * counts["live"] / relevant, 1) if relevant else None
    return {
        # Independent-review finding (2026-09-16): explicit, machine-readable scope
        # disclosure, not just a docstring comment -- this whole dict describes the
        # CANONICAL surface (every projected strike x expiry), never the client's current
        # Auto/Wider/All-windowed view. A consumer that needs the on-screen LIVE verdict
        # must use the client's own visible-scope computation, not this field.
        "scope": "canonical_surface",
        "total_visible_cells": relevant,
        "live": counts["live"], "partial": counts["partial"], "stale": counts["stale"],
        "pending": counts["pending"], "daemon_unavailable": counts["daemon_unavailable"],
        "rejected": counts["rejected"], "unavailable": counts["unavailable"],
        "live_pct": live_pct,
        "meets_live_requirement": relevant > 0 and counts["live"] == relevant,
    }
