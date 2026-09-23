"""Terrain freshness authority (RC-91/108/146/147/148/165): whether a terrain snapshot is
current and, when it is not, the producer's own reason -- quarantine > this-cycle pause >
last failure > clock -- plus the Schwab refresh-token countdown every freshness payload
carries. Extracted from server.py (RC-REHAB-1, 2026-09-23, forty-first slice).

The per-ticker failure dict, the cadence floor and the loop's delivered-cycle clock (which
the loop REBINDS) are read from terrain_state at call time; the server-owned logging-session
gate, LOGGER_BUFFER_MINS and APP_DIR through a lazy `import server as _srv`. Never copied.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import terrain_quarantine
import terrain_state
from instrument_identity import ticker_storage_key


#: How old the terrain snapshot may be before it must stop calling itself current. FLOOR only:
#: set when TERRAIN_REFRESH_SEC was 60 (60 + one cycle's slack). The cadence floor is now 5 s, so
#: the live threshold is max(this, two DELIVERED cycles) -- see terrain_staleness (RC-165).
TERRAIN_STALE_AFTER_SEC: float = 180.0


#: RC-108: Schwab refresh tokens die at 7 days, hard. The 2026-07-28 open went fully dark
#: because the expiry sat in schwab_token.json for a week with no forward warning — the system
#: only screamed AFTER the data was lost. Warn from day 5, red from day 6.
_SCHWAB_TOKEN_WARN_DAYS = 5.0
_SCHWAB_TOKEN_RED_DAYS = 6.0


def schwab_token_countdown(creation_ts: float | None) -> dict:
    """Pure urgency computation from the token file's creation_timestamp (unit-tested)."""
    if creation_ts is None:
        return {"schwab_token_age_days": None, "schwab_token_urgency": "unknown",
                "schwab_token_note": "token file unreadable — collection may be dead"}
    age_days = round((time.time() - float(creation_ts)) / 86400.0, 2)
    if age_days >= _SCHWAB_TOKEN_RED_DAYS:
        urgency, note = "red", (f"Schwab token is {age_days:.1f} days old (7-day hard limit) — "
                                f"re-auth NOW: python reauth_schwab.py --manual")
    elif age_days >= _SCHWAB_TOKEN_WARN_DAYS:
        urgency, note = "warn", (f"Schwab token is {age_days:.1f} days old — re-auth before "
                                 f"day 7 kills collection: python reauth_schwab.py --manual")
    else:
        urgency, note = "ok", ""
    return {"schwab_token_age_days": age_days, "schwab_token_urgency": urgency,
            "schwab_token_note": note}


def _schwab_token_creation_ts() -> float | None:
    """creation_timestamp from schwab_token.json; None (never a fake age) when unreadable."""
    import server as _srv                      # runtime: APP_DIR (monkeypatched by tests)

    try:
        raw = json.loads((Path(_srv.APP_DIR) / "schwab_token.json").read_text(encoding="utf-8"))
        return float(raw["creation_timestamp"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def terrain_staleness(computed_ts_utc: float | None, ticker: str | None = None) -> dict:
    """Whether the levels are current, and WHY NOT when they are not (RC-91).

    RC-146 — the reason must come from the PRODUCER, not be inferred from a clock. Age alone
    cannot tell a deliberate pause from a broken loop, so this function used to answer "inside
    its window but not producing" for a scheduler that was working exactly as designed. When a
    ticker was skipped on purpose, `terrain_skip_reason` has the real sentence and it wins.
    Pass `ticker` wherever it is known; omitting it degrades to the old clock-only reason.

    MEASURED 2026-07-27 18:02 ET: /api/terrain computed_ts_utc did not advance across 90s against
    a 60s cadence, the gamma panel served data 90 MINUTES old under a `terrain_live_cache` label,
    and spot beside it was 3 seconds old. The terrain loop refreshes only while
    _is_loggable_session() is true, which ends at LOGGER_BUFFER_MINS (16:30 ET) — 210 minutes
    before the capture window closes. That function is the BACKGROUND LOGGING gate; using it to
    decide whether the screen is current answered a different question with the same switch.

    Stopping the loop after the post-market buffer may well be correct. Serving its last output
    under a live label is not: staleness that is budget-justified gets LABELLED, staleness that is
    not gets removed (the RC-78 rule, applied to the scorecard that day and never to terrain).
    """
    import server as _srv   # runtime: session gate, failure channel, delivered cycle, cadence

    refreshing = _srv._is_loggable_session()
    token = schwab_token_countdown(_schwab_token_creation_ts())   # RC-108: warn BEFORE death
    skipped = terrain_quarantine.terrain_skip_reason(ticker)   # RC-146: the producer's own words, when it has any
    # RC-147: the FAILURE channel, which RC-146 left unread. `_terrain_refresh_last_error` was
    # consulted at exactly ONE call site — the not-ready branch of /api/terrain, reachable only
    # when NO snapshot exists. The moment a ticker has any cached snapshot, that branch is dead
    # and the recorded exception becomes unreachable, so a ticker failing every single refresh
    # reported `error: ""` and a generic "inside its window but not producing". MEASURED
    # 2026-07-30 10:16 ET: $SPX served levels 2,737 s old (45.6 min) with volume bars painting
    # beside them, chain_basis already degraded to `dte<=120`, and no surface anywhere naming
    # the cause. Precedence: a pause recorded for THIS cycle is why it is not refreshing right
    # now and wins; otherwise the last failure is the live reason; the clock is the last resort.
    # RC-148: quarantine outranks both. A quarantined ticker is not merely failing — it is not
    # being REQUESTED, which is a different fact and a different operator action (re-admit it,
    # or accept it is gone). Precedence for the REASON: quarantine > this-cycle pause > last
    # failure > clock. The FLAGS stay orthogonal on purpose: a hard quarantine is still FAILING
    # (the vendor refuses the symbol) and is emphatically NOT "paused, resumes on its own", so
    # collapsing it into either single flag would restore the ambiguity RC-146/147 removed.
    q_entry = terrain_quarantine.terrain_quarantine_state(ticker)
    quarantined = terrain_quarantine.terrain_quarantine_reason(ticker)
    failure = "" if (skipped or quarantined) else str(terrain_state._terrain_refresh_last_error.get(
        ticker_storage_key(ticker) if ticker else "", "") or "")
    hard_quarantine = bool(q_entry.get("permanent"))
    if computed_ts_utc is None:
        return {"levels_stale": True, "levels_age_sec": None, "levels_refresh_active": refreshing,
                "levels_stale_reason": (
                    quarantined or skipped
                    or (f"no terrain snapshot has been computed yet — {failure}" if failure
                        else "no terrain snapshot has been computed yet")),
                "levels_paused_on_purpose": bool(skipped and not quarantined),
                "levels_quarantined": bool(quarantined),
                "levels_failing": bool(failure or hard_quarantine), **token}
    age = round(time.time() - float(computed_ts_utc), 1)
    # RC-165: judge age against the cycle the loop ACTUALLY delivers, not the nominal floor.
    # `TERRAIN_REFRESH_SEC` (60s then, 5s now) is a sleep floor between cycles; the delivered spacing is
    # whatever a full sweep costs, and MEASURED 2026-07-31 12:57 ET that was a 156s median on
    # SPY. With a fixed 180s threshold and a 60s sentence, a ticker 234s old — barely 1.5
    # cycles, entirely healthy — was reported to the operator as "the loop is inside its window
    # but not producing". That is RC-146's defect returning through a different door: a
    # correctly-working scheduler described as broken, this time because the yardstick was a
    # number the loop cannot reach rather than a silence nobody recorded.
    observed = (terrain_state._terrain_last_cycle_sec if terrain_state._terrain_last_cycle_sec > 0
                else terrain_state.TERRAIN_REFRESH_SEC)
    expected = max(float(terrain_state.TERRAIN_REFRESH_SEC), float(observed))
    # Stale only past the FLOOR *and* past two delivered cycles — one missed sweep is normal
    # jitter, two is a real gap. The floor is retained so a fast loop cannot hide staleness.
    stale_after = max(float(TERRAIN_STALE_AFTER_SEC), 2.0 * expected)
    stale = age > stale_after
    reason = ""
    if stale:
        reason = (f"levels are {age:.0f}s old — {quarantined}" if quarantined else
                  f"levels are {age:.0f}s old — {skipped}" if skipped else
                  f"levels are {age:.0f}s old and every refresh since is failing — {failure}"
                  if failure else
                  f"levels are {age:.0f}s old; the terrain loop is not refreshing "
                  f"(outside the background-logging window, which closes at "
                  f"{_srv.LOGGER_BUFFER_MINS // 60:02d}:{_srv.LOGGER_BUFFER_MINS % 60:02d} ET)"
                  if not refreshing else
                  f"levels are {age:.0f}s old — over two full sweeps at the loop's DELIVERED "
                  f"cycle of {expected:.0f}s (nominal floor {terrain_state.TERRAIN_REFRESH_SEC:.0f}s), so this "
                  f"ticker is genuinely behind rather than merely between sweeps")
    return {"levels_stale": stale, "levels_age_sec": age,
            "levels_refresh_active": refreshing, "levels_stale_reason": reason,
            # RC-146: a stale panel must be able to distinguish "paused by design, resumes at a
            # known time" from "should be refreshing and is not". They are different operator
            # actions — wait, versus go find out what broke.
            "levels_paused_on_purpose": bool(stale and skipped and not quarantined),
            # RC-147: and the third state — actively FAILING — is a different action again
            # (the chain call is erroring, the levels will not come back on their own).
            "levels_failing": bool(stale and (failure or hard_quarantine)),
            # RC-148: the fourth — not even being REQUESTED. Distinct from failing: re-admission
            # is an operator act, not something the loop will do on its own.
            "levels_quarantined": bool(quarantined), **token}
