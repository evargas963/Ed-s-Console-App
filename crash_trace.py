"""
crash_trace.py — Diagnostic logging to pinpoint crash location.
Enable with: set DIAG=1  (Windows) or export DIAG=1 (Unix)
Run server, then when it crashes the last [DIAG] line shows where it got to.
"""
import os
import logging
import traceback

_diag = os.environ.get("DIAG", "").strip().lower() in ("1", "true", "yes")
log = logging.getLogger("ed_server")


def _on() -> bool:
    return _diag


def step(name: str, ticker: str = ""):
    """Log checkpoint — last one before crash = failure point."""
    if _diag:
        ctx = f" [{ticker}]" if ticker else ""
        log.info(f"[DIAG] {name}{ctx}")


def step_done(name: str, ticker: str = ""):
    if _diag:
        ctx = f" [{ticker}]" if ticker else ""
        log.info(f"[DIAG] {name} DONE{ctx}")


def trace_crash(step_name: str, exc: BaseException, ticker: str = ""):
    """Log full traceback with step name — call from except handler."""
    ctx = f" [{ticker}]" if ticker else ""
    log.error(f"[DIAG] CRASH at {step_name}{ctx}: {exc}")
    log.error(traceback.format_exc())
