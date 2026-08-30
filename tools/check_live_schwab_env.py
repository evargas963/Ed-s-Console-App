#!/usr/bin/env python3
"""Fail-closed preflight: refuse desk launch when live Schwab would be blocked.

Proven failure (2026-08-29, production HEAD 9c195333): start_ed_console.bat was
invoked from an agent/pytest shell that exported ED_CI_OFFLINE=1, CI=true, and
SCHWAB_API_KEY/SCHWAB_APP_SECRET='test'. Health stayed 200 while analytics bg
failed on every ticker with::

    RuntimeError: Schwab CI offline mode — live API call blocked (...)

Root cause is contaminated *parent* environment, not the CI gate itself. The desk
launcher must strip known contamination and refuse when live calls would still be
blocked — without weakening authorization or swallowing the RuntimeError.
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


def live_schwab_launch_violations() -> list[str]:
    """Return human-readable violations; empty means safe to launch uvicorn."""
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

    violations = live_schwab_launch_violations()
    if violations:
        print("LAUNCH BLOCKED: live Schwab environment is not production-safe:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        print(
            "Unset CI/test vars (ED_CI_OFFLINE, CI, test SCHWAB_*), ensure live "
            "SCHWAB_API_KEY/SCHWAB_APP_SECRET (or .env), then relaunch via start_ed_console.bat.",
            file=sys.stderr,
        )
        return 1
    print("live_schwab_env: OK (live Schwab not CI-blocked)")
    return 0


if __name__ == "__main__":
    # Ensure repo root on path when invoked as tools\check_live_schwab_env.py
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    raise SystemExit(main())
