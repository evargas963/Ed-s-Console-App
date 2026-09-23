"""Terrain producer admission book: the RC-146 deliberate-skip channel and the RC-148
per-symbol quarantine (streak counter, soft exponential backoff, permanent hard-reject hold,
operator release, append-only audit ledger). Extracted from server.py (RC-REHAB-1,
2026-09-23, fortieth slice) as one unit -- every dict here is guarded by its own lock and
mutated in place, never rebound, and nothing reads a server.py runtime object.

Callers reach these names through this module (`import terrain_quarantine as _tq`), so a
test that monkeypatches one of them patches the single home every consumer reads.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from instrument_identity import ticker_storage_key
from runtime_layout import reports_dir
from time_et import now_et

log = logging.getLogger(__name__)

#: RC-146: the producer's DELIBERATE skips, per ticker. Distinct channel from the error dict
#: above on purpose — a budget-justified pause is not a failure, and collapsing the two would
#: report a working scheduler as broken. Written by _terrain_loop at the moment it drops a
#: ticker from the cycle, read by terrain_staleness so every stale payload carries the real
#: reason. A degradation that records nothing is indistinguishable from a malfunction.
_terrain_skipped_reason: dict[str, str] = {}
_terrain_skip_lock = threading.Lock()

#: RC-148 — QUARANTINE. Visibility is not sufficiency: RTY and XXT are rejected by the vendor
#: (`chain fetch failed (HTTP 400)`, no spot, no expiries) yet the loop re-requested them every
#: 60 s against a 2-slot chain gate, indefinitely. A permanently-rejected symbol is not a
#: transient error to retry — it is a symbol that will never answer, and retrying it spends a
#: scarce vendor slot the healthy book needs. Hard rejections (HTTP 4xx: the symbol itself is
#: refused) quarantine PERMANENTLY after TERRAIN_QUARANTINE_HARD_FAILS consecutive hits and stay
#: out until an operator re-admits. Soft failures (timeout / 5xx / 429: the venue is busy, the
#: symbol is fine) back off exponentially and re-admit themselves.
TERRAIN_QUARANTINE_HARD_FAILS: int = 3
TERRAIN_QUARANTINE_SOFT_BASE_SEC: float = 60.0
TERRAIN_QUARANTINE_SOFT_MAX_SEC: float = 900.0
#: Env override exists for TESTS ONLY (set in tests/conftest.py before any import, so a
#: lazy mid-test `import server` can never write the tracked operator audit file — the
#: class CI's ledger firewall caught 2026-08-24). Production never sets the variable.
TERRAIN_QUARANTINE_LEDGER = Path(
    os.environ.get("ED_TERRAIN_QUARANTINE_LEDGER")
    or (reports_dir() / "terrain_quarantine_ledger.jsonl"))   # RC-523: artifacts root

_terrain_quarantine: dict[str, dict] = {}
_terrain_consecutive_fails: dict[str, int] = {}
_terrain_quarantine_skips: dict[str, int] = {}
_terrain_quarantine_lock = threading.Lock()


def _quarantine_ledger_append(event: str, tk: str, payload: dict) -> None:
    """Append-only record of every quarantine decision. A control the operator cannot audit
    after the fact is a control they have to take on trust."""
    try:
        TERRAIN_QUARANTINE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts_utc": time.time(), "et": now_et().isoformat(), "event": event,
               "ticker": tk, **payload}
        with open(TERRAIN_QUARANTINE_LEDGER, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError as e:                      # a ledger that cannot write must not stop the loop
        log.warning("quarantine ledger write failed for %s: %s", tk, e)


def _classify_chain_failure(status_code: int | None, exc_name: str | None) -> str:
    """"hard" = the vendor refuses THIS SYMBOL (4xx); "soft" = the venue is busy (timeout/5xx/429).

    Fail-closed to "soft": an unrecognised failure must never earn a permanent quarantine, because
    a wrong permanent verdict silently removes a real instrument from the board.
    """
    if status_code is not None:
        code = int(status_code)
        if code == 429:
            return "soft"                     # rate limit is about US, never about the symbol
        if 400 <= code < 500:
            return "hard"
        return "soft"
    if exc_name in ("ReadTimeout", "ConnectTimeout", "TimeoutException"):
        return "soft"
    return "soft"


def terrain_quarantine_state(ticker: str | None = None) -> dict:
    """Snapshot of the quarantine book (whole book, or one ticker's entry)."""
    with _terrain_quarantine_lock:
        if ticker:
            tk = ticker_storage_key(ticker)
            e = _terrain_quarantine.get(tk)
            return dict(e) if e else {}
        return {k: dict(v) for k, v in _terrain_quarantine.items()}


def terrain_quarantine_reason(ticker: str | None) -> str:
    """Why this ticker is not being requested at all, or "" when it is in the rotation."""
    if not ticker:
        return ""
    tk = ticker_storage_key(ticker)
    with _terrain_quarantine_lock:
        e = _terrain_quarantine.get(tk)
        if not e:
            return ""
        if e.get("permanent"):
            return (f"QUARANTINED after {e.get('failures')} consecutive hard rejections — "
                    f"{e.get('reason')}. The vendor refuses this symbol, so the loop has stopped "
                    f"requesting it; it stays out until an operator re-admits it "
                    f"(POST /api/terrain/quarantine/release?ticker={tk})")
        # RC-281: every constructor supplies until_ts, so absence is MALFORMED STATE, not
        # "no cooldown". My earlier reason claimed the latter; Cursor's runtime probe showed
        # it releases the hold and erases the entry, turning an invariant failure into an
        # immediate vendor retry with the evidence gone.
        from numeric_contract import float_finite_or_none as _fin_q
        until = _fin_q(e.get("until_ts"))
        if until is None:
            return (f"backing off after {e.get('failures')} consecutive failures — "
                    f"{e.get('reason')}; hold has NO expiry recorded (malformed entry), "
                    f"so it is held until an operator releases it")
        left = max(0.0, until - time.time())
        return (f"backing off after {e.get('failures')} consecutive failures — {e.get('reason')}; "
                f"next attempt in {left:.0f}s")


def _terrain_quarantine_blocks(tk: str) -> bool:
    """True when this ticker must NOT be requested this cycle. Expired soft holds self-release."""
    now = time.time()
    with _terrain_quarantine_lock:
        e = _terrain_quarantine.get(tk)
        if not e:
            return False
        if e.get("permanent"):
            _terrain_quarantine_skips[tk] = _terrain_quarantine_skips.get(tk, 0) + 1
            return True
        # RC-281: fail CLOSED on a malformed hold. `or 0.0` dated the expiry to 1970, so the
        # branch never fired, the entry was popped, and the ticker went straight back into
        # rotation — the opposite of a quarantine, reached by a missing field.
        from numeric_contract import float_finite_or_none as _fin_qb
        until = _fin_qb(e.get("until_ts"))
        if until is None or now < until:
            _terrain_quarantine_skips[tk] = _terrain_quarantine_skips.get(tk, 0) + 1
            return True
        _terrain_quarantine.pop(tk, None)      # soft hold expired — back into the rotation
    _quarantine_ledger_append("soft_release", tk, {"note": "backoff elapsed, retrying"})
    return False


def _note_terrain_failure(tk: str, reason: str, kind: str) -> None:
    """Record a failed refresh and quarantine when the pattern earns it.

    The streak counter lives under the SAME lock as the quarantine book it feeds. TERRAIN_WORKERS
    threads run the rotation while `/api/terrain` can drive `_terrain_refresh_one(priority=True)`
    for the same ticker concurrently, so a read-modify-write outside the lock can drop a failure —
    and a dropped failure is a retry storm that never reaches its own threshold.
    """
    log_msg: tuple | None = None
    ledger: tuple | None = None
    with _terrain_quarantine_lock:
        n = _terrain_consecutive_fails.get(tk, 0) + 1
        _terrain_consecutive_fails[tk] = n
        if n >= TERRAIN_QUARANTINE_HARD_FAILS:
            if kind == "hard":
                already = bool(_terrain_quarantine.get(tk, {}).get("permanent"))
                _terrain_quarantine[tk] = {"reason": reason, "failures": n, "permanent": True,
                                           "since_ts": time.time(), "until_ts": None,
                                           "kind": kind}
                if not already:
                    log_msg = ("terrain QUARANTINE (permanent) %s after %d hard rejections: %s",
                               tk, n, reason)
                    ledger = ("quarantine_permanent", {"failures": n, "reason": reason})
            else:
                wait = min(TERRAIN_QUARANTINE_SOFT_MAX_SEC,
                           TERRAIN_QUARANTINE_SOFT_BASE_SEC
                           * (2 ** (n - TERRAIN_QUARANTINE_HARD_FAILS)))
                _terrain_quarantine[tk] = {"reason": reason, "failures": n, "permanent": False,
                                           "since_ts": time.time(),
                                           "until_ts": time.time() + wait, "kind": kind}
                log_msg = ("terrain backoff %s for %.0fs after %d failures: %s",
                           tk, wait, n, reason)
                ledger = ("backoff", {"failures": n, "reason": reason,
                                      "wait_sec": round(wait, 1)})
    # Disk and logging stay OUTSIDE the lock: a slow ledger write must never hold the producer.
    if log_msg:
        log.warning(*log_msg)
    if ledger:
        _quarantine_ledger_append(ledger[0], tk, ledger[1])


def _note_terrain_success(tk: str) -> None:
    """A success clears the streak AND any soft hold — the symbol answered."""
    with _terrain_quarantine_lock:
        _terrain_consecutive_fails.pop(tk, None)
        had = _terrain_quarantine.pop(tk, None)
    if had and not had.get("permanent"):
        _quarantine_ledger_append("cleared_by_success", tk, {})


def terrain_quarantine_release(ticker: str) -> dict:
    """Operator re-admission. Explicit, logged, and the ONLY way out of a permanent hold."""
    tk = ticker_storage_key(ticker)
    with _terrain_quarantine_lock:
        had = _terrain_quarantine.pop(tk, None)
        _terrain_consecutive_fails.pop(tk, None)
        _terrain_quarantine_skips.pop(tk, None)
    _quarantine_ledger_append("operator_release", tk, {"was": had or {}})
    log.warning("terrain quarantine RELEASED by operator: %s (was %s)", tk, had)
    return {"ticker": tk, "released": bool(had), "was": had or {}}


def _note_terrain_skip(tickers: list[str], reason: str) -> None:
    """Record WHY these tickers were dropped from a cycle; clear everyone else.

    Keyed through `ticker_storage_key` — the ONE normalisation authority (RC-126) — because
    `_terrain_refresh_last_error` beside it is keyed that way too. Two dicts describing the same
    ticker under two different spellings is how a reader silently misses one of them.
    """
    keep = {ticker_storage_key(t) for t in tickers if t}
    with _terrain_skip_lock:
        _terrain_skipped_reason.clear()
        for t in keep:
            _terrain_skipped_reason[t] = reason


def _clear_terrain_skips() -> None:
    with _terrain_skip_lock:
        _terrain_skipped_reason.clear()


def terrain_skip_reason(ticker: str | None) -> str:
    """The producer's own reason for not refreshing this ticker, or "" when none."""
    if not ticker:
        return ""
    with _terrain_skip_lock:
        return _terrain_skipped_reason.get(ticker_storage_key(ticker), "")
