#!/usr/bin/env python3
"""Schwab CAPABILITY preflight: sanitize the environment, then report whether live Schwab works.

Proven failure (2026-08-29, production HEAD 9c195333): start_ed_console.bat was
invoked from an agent/pytest shell that exported ED_CI_OFFLINE=1, CI=true, and
SCHWAB_API_KEY/SCHWAB_APP_SECRET='test'. Health stayed 200 while analytics bg
failed on every ticker with::

    RuntimeError: Schwab CI offline mode — live API call blocked (...)

Root cause is contaminated *parent* environment, not the CI gate itself. The sanitization
half of that fix is unchanged and still runs first: known contamination is stripped from the
parent shell before uvicorn inherits it, and nothing here weakens authorization or swallows
the RuntimeError.

RC-514 CHANGED WHAT A FAILURE MEANS. This module used to answer "may the desk launch", and
`start_ed_console.bat` exited on a non-zero result — so whether Ed Console could exist at all
was decided by whether one upstream vendor's credentials happened to resolve. MEASURED
2026-09-03: a ghost `python-dotenv` distribution made `.env` unloadable (RC-513) and the desk
would not start, with the API, UI, health and observability all perfectly capable of running.

docs/ARCHITECTURE.md §4 separates application availability from capability availability:
Schwab unavailable degrades the Schwab capability and fails Schwab-dependent exposure closed;
it does not kill the application. So this now answers "is the Schwab CAPABILITY available",
the launcher reports rather than aborts, and the fail-closed half lives where it always did —
`config.schwab_live_blocked_for()` and the two refusal sites in `schwab_client`.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Known non-live values that agent/CI shells inject (beyond ci-placeholder-* prefixes).
_NON_LIVE_SCHWAB_VALUES = frozenset(
    {
        "test",
        "dummy",
        "fake",
        "changeme",
        "placeholder",
        "ci",
        "x",
        "none",
        "null",
    }
)

# Only CI/offline/test contamination that makes schwab_live_blocked_for() true
# via ED_CI_OFFLINE or that marks a GitHub-Actions/agent shell. Do NOT strip
# harness flags (ED_CONSOLE_ALLOW_NONCANONICAL_DB) or live SCHWAB_* values —
# those are not Schwab-offline contamination (pytest-full 33283969383: stripping
# the DB harness flag on an xdist worker failed 23 unrelated EdDB tests).
_STRIP_ALWAYS = (
    "ED_CI_OFFLINE",
    "CI",
)


def _is_non_live_schwab_value(raw: str | None) -> bool:
    v = (raw or "").strip()
    if not v:
        return False
    low = v.lower()
    if low in _NON_LIVE_SCHWAB_VALUES:
        return True
    if low.startswith("ci-placeholder-") or low.startswith("ci-not-live-placeholder"):
        return True
    return False


def vars_to_unset(environ: dict[str, str] | None = None) -> list[str]:
    """Return env var names that must be cleared before a live desk launch."""
    env = os.environ if environ is None else environ
    out: list[str] = []
    for k in _STRIP_ALWAYS:
        if k in env and str(env.get(k, "")).strip() != "":
            out.append(k)
    for k in ("SCHWAB_API_KEY", "SCHWAB_APP_SECRET"):
        if _is_non_live_schwab_value(env.get(k)):
            out.append(k)
    # Stable unique order
    seen: set[str] = set()
    ordered: list[str] = []
    for k in out:
        if k not in seen:
            seen.add(k)
            ordered.append(k)
    return ordered


def apply_sanitize(environ: dict[str, str] | None = None) -> list[str]:
    """Clear contaminated keys in-place. Returns names cleared."""
    env = os.environ if environ is None else environ
    cleared = vars_to_unset(env)
    for k in cleared:
        env.pop(k, None)
    return cleared


def schwab_capability_status() -> tuple[str, list[str]]:
    """`("AVAILABLE" | "UNAVAILABLE", reasons)` for the Schwab capability.

    One computation: the reasons ARE `live_schwab_launch_violations()`, which has always
    answered "would live Schwab work here". Only the consequence changed — an unavailable
    capability degrades that capability instead of vetoing the application (RC-514).
    """
    reasons = live_schwab_launch_violations()
    return ("UNAVAILABLE" if reasons else "AVAILABLE"), reasons


def live_schwab_launch_violations() -> list[str]:
    """Reasons live Schwab would NOT work here; empty means the capability is available.

    Kept under its original name because it is the single predicate every caller already uses.
    `schwab_capability_status` formats it; nothing recomputes it.
    """
    # Local import: keeps --bat-unsets usable even if config import is heavy.
    from config import (
        _ensure_dotenv_loaded,
        schwab_credentials_are_ci_placeholders,
        schwab_live_blocked_for,
    )

    _ensure_dotenv_loaded()
    violations: list[str] = []

    still = vars_to_unset()
    if still:
        violations.append(
            "inherited CI/test contamination still set: "
            + ", ".join(still)
            + " (launcher must clear these before uvicorn)"
        )

    key = (os.getenv("SCHWAB_API_KEY") or "").strip()
    secret = (os.getenv("SCHWAB_APP_SECRET") or "").strip()
    if not key or not secret:
        violations.append(
            "SCHWAB_API_KEY / SCHWAB_APP_SECRET missing after sanitize — "
            "set live credentials in the environment or repo .env"
        )
        return violations

    if schwab_credentials_are_ci_placeholders(key, secret) or _is_non_live_schwab_value(key) or _is_non_live_schwab_value(
        secret
    ):
        violations.append(
            "Schwab credentials are CI/test placeholders — refusing live desk launch"
        )

    if schwab_live_blocked_for(api_key=key, app_secret=secret) or schwab_live_blocked_for():
        violations.append(
            "config.schwab_live_blocked_for() is True — live Schwab API calls would raise "
            "RuntimeError (CI offline / placeholder path)"
        )

    offline = os.getenv("ED_CI_OFFLINE", "").strip().lower() in ("1", "true", "yes")
    if offline:
        violations.append("ED_CI_OFFLINE is set — production desk must not run offline")

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bat-unsets",
        action="store_true",
        help="Print 'set VAR=' lines for cmd.exe to clear contaminated parent env",
    )
    parser.add_argument(
        "--sanitize",
        action="store_true",
        help="Clear contaminated keys in this process, then validate",
    )
    args = parser.parse_args(argv)

    if args.bat_unsets:
        for k in vars_to_unset():
            # cmd.exe: `set VAR=` unsets
            sys.stdout.write(f"set {k}=\n")
        return 0

    if args.sanitize:
        cleared = apply_sanitize()
        if cleared:
            print(f"live_schwab_env: cleared inherited contamination: {', '.join(cleared)}")

    status, reasons = schwab_capability_status()
    if reasons:
        print("SCHWAB CAPABILITY UNAVAILABLE — the app runs; this capability does not:",
              file=sys.stderr)
        for v in reasons:
            print(f"  - {v}", file=sys.stderr)
        print(
            "Live Schwab collection will not run and Schwab-dependent decisions fail closed "
            "(no fabricated data, no stale substitute). API, UI, health and observability are "
            "unaffected. To restore the capability: unset CI/test vars (ED_CI_OFFLINE, CI, "
            "test SCHWAB_*), ensure live SCHWAB_API_KEY/SCHWAB_APP_SECRET (or repo .env), "
            "then relaunch via start_ed_console.bat.",
            file=sys.stderr,
        )
        return 1
    print(f"live_schwab_env: {status} (live Schwab not CI-blocked)")
    return 0


if __name__ == "__main__":
    # RC-512: this module lives at the app root, so its own directory IS the repo root.
    # It used `.parent.parent` while it sat in tools/; kept explicit because the launcher
    # invokes it as a script, before any package import has put the root on sys.path.
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    raise SystemExit(main())
