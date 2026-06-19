"""RTH validation harness helpers — operator trust stabilization (read-only / dry-run safe)."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent

GUEST_SWITCH_MATRIX: tuple[tuple[str, str], ...] = (
    ("SPY", "QQQ"),
    ("QQQ", "IWM"),
    ("SPY", "NVDA"),
    ("NVDA", "IWM"),
    ("PLTR", "AAPL"),
    ("SPY", "SPX"),
    ("SPY", "$VIX"),
)

REQUIRED_SWITCH_METRICS: tuple[str, ...] = (
    "selected_ticker",
    "previous_ticker",
    "is_core",
    "is_guest",
    "is_special_index",
    "request_generation",
    "switch_started_at",
    "fast_quote_first_seen_ms",
    "analytics_light_first_seen_ms",
    "tier_c_first_seen_ms",
    "cards_first_render_ms",
    "stale_cache_restored",
    "guest_incomplete_reason",
    "db_contention_state_at_switch",
    "wrong_ticker_payload_rejected_count",
    "stale_generation_payload_rejected_count",
    "final_switch_state",
)

PASSIVE_RISK_PHRASES: tuple[str, ...] = (
    "known remaining risks",
    "not proven",
    "needs validation",
    "future work",
    "follow-up needed",
    "not measured",
    "not yet proven",
    "remaining risks",
    "failed as before",
)

CLOSURE_HANDLING_PHRASES: tuple[str, ...] = (
    "FIXED_IN_THIS_PR",
    "VALIDATED_IN_THIS_PR",
    "BLOCKED_BY_RTH_WITH_RUNNABLE_VALIDATION_HARNESS",
    "NEEDS_RTH_VALIDATION_WITH_HARNESS",
    "COMPLETION_BRANCH_REQUIRED",
    "OWNER_BRANCH",
    "CLOSURE_CRITERIA",
    "ACCEPTED_WITH_EVIDENCE",
    "CLOSED_WITH_EVIDENCE",
    "Owner branch:",
    "Do not close until:",
    "runnable validation harness",
    "run_rth_guest_switch_validation",
    "run_rth_db_contention_validation",
    "run_rth_base_capture_normalization_validation",
)

ALLOWED_OPEN_ITEM_STATUSES: frozenset[str] = frozenset(
    {
        "OPEN_BLOCKING",
        "NEEDS_RTH_VALIDATION_WITH_HARNESS",
        "FIXED_IN_THIS_BRANCH",
        "FIXED_IN_THIS_BRANCH_AWAITING_GITHUB_CI",
        "COMPLETION_BRANCH_REQUIRED",
        "ACCEPTED_WITH_EVIDENCE",
        "CLOSED_WITH_EVIDENCE",
    }
)

OPEN_ITEM_REQUIRED_FIELDS: tuple[str, ...] = (
    "Status:",
    "Source PR / report:",
    "Why it matters:",
    "Operator risk:",
    "Evidence currently available:",
    "Evidence still needed:",
    "Fix now or harness now:",
    "Owner branch:",
    "Blocking level:",
    "Do not close until:",
)


def git_head_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(ROOT),
                text=True,
            )
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def capture_runtime_env() -> dict[str, Any]:
    cal = os.environ.get("ED_CALIBRATION_LOG", "")
    return {
        "git_commit": git_head_sha(),
        "branch": os.environ.get("GIT_BRANCH", ""),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "market_session_mode": os.environ.get("ED_MARKET_SESSION_MODE", "unknown"),
        "ED_CALIBRATION_LOG": cal,
        "ED_CALIBRATION_LOG_enabled": str(cal).strip().lower() in {"1", "true", "yes", "on"},
        "schwab_mode": os.environ.get("ED_SCHWAB_MODE", "unknown"),
        "db_path": os.environ.get("ED_DB_PATH", str(ROOT / "data" / "ed_console.db")),
        "server_pid": os.getpid(),
        "ticker_universe_note": "operator-selected during RTH matrix",
    }


def calibration_blocks_pass(env: dict[str, Any]) -> bool:
    return not bool(env.get("ED_CALIBRATION_LOG_enabled"))


def http_get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def evaluate_switch_event(ev: dict[str, Any]) -> list[str]:
    """Return failure reasons for one switch diagnostic event."""
    fails: list[str] = []
    if ev.get("ticker_mismatch_discarded") is False and ev.get("wrong_ticker_payload_rejected_count", 0) == 0:
        pt = str(ev.get("payload_ticker") or "")
        at = str(ev.get("selected_ticker") or ev.get("new_ticker") or "")
        if pt and at and pt.upper() != at.upper():
            fails.append("WRONG_TICKER_ACCEPTED_FAIL")
    if ev.get("generation_superseded") is False and ev.get("stale_generation_payload_rejected_count", 0) == 0:
        if ev.get("accepted_stale_generation"):
            fails.append("STALE_GENERATION_ACCEPTED_FAIL")
    if ev.get("stale_cache_restored") and not (
        ev.get("analytics_stale") or ev.get("final_switch_state", "").startswith("CACHE")
    ):
        if ev.get("presented_as_fresh"):
            fails.append("CACHE_PRESENTED_AS_FRESH_FAIL")
    guest_inc = ev.get("guest_incomplete_reason")
    if ev.get("is_guest") and not guest_inc and ev.get("analytics_pending_shell"):
        fails.append("GUEST_INCOMPLETE_REASON_MISSING_FAIL")
    cards_ms = ev.get("cards_first_render_ms")
    if cards_ms is None and ev.get("timed_out"):
        fails.append("CARDS_FIRST_RENDER_MISSING_FAIL")
    db_state = str(ev.get("db_contention_state_at_switch") or "OK")
    if db_state not in ("", "OK") and not ev.get("db_degraded_surfaced"):
        fails.append("DB_DEGRADED_NOT_SURFACED_FAIL")
    final = str(ev.get("final_switch_state") or "")
    if not final or final == "SWITCHING":
        if ev.get("timed_out"):
            fails.append("FINAL_SWITCH_STATE_INCOMPLETE_FAIL")
    return fails


def classify_switch_pair(old_t: str, new_t: str) -> str:
    core = {"SPY", "QQQ", "IWM"}
    o, n = old_t.upper(), new_t.upper()
    if o in core and n in core:
        return "CORE_SWITCH_SLA_PASS" if False else "CORE_SWITCH_SLA_FAIL"
    if n in {"$VIX", "SPX", "$SPX", "VIX"} or o in {"$VIX", "SPX", "$SPX", "VIX"}:
        return "SPECIAL_INDEX_SWITCH_PASS" if False else "SPECIAL_INDEX_SWITCH_FAIL"
    return "GUEST_SWITCH_SLA_PASS" if False else "GUEST_SWITCH_SLA_FAIL"


def build_dry_run_report(
    *,
    harness: str,
    audit_date: str,
    classification: str = "RTH_VALIDATION_NOT_RUN",
) -> dict[str, Any]:
    env = capture_runtime_env()
    return {
        "schema_version": 1,
        "harness": harness,
        "audit_date": audit_date,
        "classification": classification,
        "pass": False,
        "dry_run": True,
        "runtime_env": env,
        "operator_note": (
            "Dry run only — RTH validation not executed. "
            "Run during RTH with server live and browser switch matrix."
        ),
        "calibration_evidence_gap": (
            "EVIDENCE_GAP_ED_CALIBRATION_LOG_DISABLED"
            if calibration_blocks_pass(env)
            else None
        ),
    }


@dataclass
class GuestSwitchValidationResult:
    classifications: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    switch_matrix: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False
    pass_: bool = False

    def to_dict(self) -> dict[str, Any]:
        env = capture_runtime_env()
        can_pass = self.pass_ and not self.dry_run and not calibration_blocks_pass(env)
        cls = list(self.classifications)
        if self.dry_run:
            cls = ["RTH_VALIDATION_NOT_RUN"]
        elif calibration_blocks_pass(env) and self.pass_:
            cls.append("EVIDENCE_GAP_ED_CALIBRATION_LOG_DISABLED")
            can_pass = False
        return {
            "schema_version": 1,
            "harness": "guest_switch_sla",
            "pass": can_pass,
            "dry_run": self.dry_run,
            "classifications": sorted(set(cls)),
            "failures": self.failures,
            "switch_matrix_required": [list(p) for p in GUEST_SWITCH_MATRIX],
            "switch_matrix_results": self.switch_matrix,
            "events_sample": self.events[:25],
            "required_metrics": list(REQUIRED_SWITCH_METRICS),
            "runtime_env": env,
            "endpoints": {
                "ticker_switch": "/api/diagnostics/ticker-switch",
                "sqlite_contention": "/api/diagnostics/sqlite-contention",
            },
        }


def run_guest_switch_validation(
    *,
    base_url: str,
    dry_run: bool,
    audit_date: str,
) -> GuestSwitchValidationResult:
    res = GuestSwitchValidationResult(dry_run=dry_run)
    if dry_run:
        res.classifications = ["RTH_VALIDATION_NOT_RUN"]
        res.pass_ = False
        return res

    try:
        switch_payload = http_get_json(f"{base_url.rstrip('/')}/api/diagnostics/ticker-switch")
        sqlite_payload = http_get_json(f"{base_url.rstrip('/')}/api/diagnostics/sqlite-contention")
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        res.failures.append(f"endpoint_unreachable: {e}")
        res.classifications.append("RTH_VALIDATION_NOT_RUN")
        return res

    events = switch_payload.get("events") if isinstance(switch_payload, dict) else []
    if not isinstance(events, list):
        events = []
    res.events = [e for e in events if isinstance(e, dict)]

    for old_t, new_t in GUEST_SWITCH_MATRIX:
        pair_ev = [
            e
            for e in res.events
            if str(e.get("old_ticker", "")).upper() == old_t.upper()
            and str(e.get("new_ticker", "")).upper() == new_t.upper()
        ]
        pair_failures: list[str] = []
        for ev in pair_ev:
            pair_failures.extend(evaluate_switch_event(ev))
        entry = {
            "pair": f"{old_t}->{new_t}",
            "events": len(pair_ev),
            "failures": sorted(set(pair_failures)),
        }
        res.switch_matrix.append(entry)
        if pair_failures:
            res.failures.extend(pair_failures)

    if sqlite_payload and not sqlite_payload.get("operator"):
        res.failures.append("sqlite_contention_operator_surface_missing")

    for field_name in REQUIRED_SWITCH_METRICS:
        if res.events and not any(field_name in e for e in res.events):
            res.failures.append(f"diagnostics_missing_field:{field_name}")

    res.classifications = []
    if not res.failures:
        res.classifications.append("GUEST_SWITCH_SLA_PASS")
        res.classifications.append("CORE_SWITCH_SLA_PASS")
        res.pass_ = True
    else:
        res.classifications.append("GUEST_SWITCH_SLA_FAIL")
    return res


def write_validation_outputs(
    report: dict[str, Any],
    *,
    json_path: Path,
    md_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        f"> **Classification:** {report.get('classification', report.get('harness', 'RTH'))}",
        "",
        f"**Pass:** {report.get('pass')}",
        f"**Dry run:** {report.get('dry_run')}",
        "",
        "## Classifications",
        "",
    ]
    for c in report.get("classifications") or []:
        lines.append(f"- `{c}`")
    if report.get("failures"):
        lines.extend(["", "## Failures", ""])
        for f in report["failures"]:
            lines.append(f"- {f}")
    if report.get("runtime_env"):
        lines.extend(["", "## Runtime env", "", "```json"])
        lines.append(json.dumps(report["runtime_env"], indent=2))
        lines.append("```")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
