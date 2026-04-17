"""
Downstream notification delivery for governed operational policy / alert_routing only.

Does not evaluate policy, promote, rollback, or change runtime. Emits delivery audit records.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ml_horizon import normalize_ml_horizon_slug

from arch_competition.operational_policy import ALERT_ROUTING_SCHEMA_VERSION

NOTIFICATION_DELIVERY_RECORD_SCHEMA_VERSION = "1"
DEDUP_STATE_SCHEMA_VERSION = "1"

SINK_FILE = "file"
SINK_WEBHOOK = "webhook"
SINK_EMAIL_STUB = "email_stub"
SINK_SLACK_ROUTING = "slack_routing"

REQUIRED_ALERT_KEYS = frozenset(
    {"alert_id", "reason_code", "severity", "routing_class", "suppression_key", "evidence_refs"}
)


class NotificationDeliveryError(ValueError):
    """Invalid governed payload, sink config, or delivery contract violation."""


@dataclass(frozen=True)
class NotificationDeliveryConfig:
    file_sink_enabled: bool
    webhook_enabled: bool
    webhook_url: str
    email_enabled: bool
    slack_enabled: bool


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def load_notification_delivery_config_from_env() -> NotificationDeliveryConfig:
    return NotificationDeliveryConfig(
        file_sink_enabled=_truthy(os.environ.get("ED_NOTIFICATION_SINK_FILE", "1")),
        webhook_enabled=_truthy(os.environ.get("ED_NOTIFICATION_WEBHOOK_ENABLED", "0")),
        webhook_url=(os.environ.get("ED_NOTIFICATION_WEBHOOK_URL") or "").strip(),
        email_enabled=_truthy(os.environ.get("ED_NOTIFICATION_SINK_EMAIL_ENABLED", "0")),
        slack_enabled=_truthy(os.environ.get("ED_NOTIFICATION_SINK_SLACK_ENABLED", "0")),
    )


def summarize_notification_config_safe(cfg: NotificationDeliveryConfig) -> dict[str, Any]:
    """No secrets — for governance panel diagnostics."""
    return {
        "schema_version": NOTIFICATION_DELIVERY_RECORD_SCHEMA_VERSION,
        "file_sink_enabled": cfg.file_sink_enabled,
        "webhook_enabled": cfg.webhook_enabled,
        "webhook_configured": bool(cfg.webhook_url),
        "email_enabled": cfg.email_enabled,
        "slack_enabled": cfg.slack_enabled,
    }


def notification_delivery_log_path(model_dir: Path, ml_horizon_slug: str, ticker: str) -> Path:
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    return model_dir / "arch_competition" / hz / ticker.upper() / "notification_delivery_log.jsonl"


def notification_dedup_state_path(model_dir: Path, ml_horizon_slug: str, ticker: str) -> Path:
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    return model_dir / "arch_competition" / hz / ticker.upper() / "notification_dedup_state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedup_fingerprint(sink: str, alert: dict[str, Any]) -> str:
    """Stable across policy evaluation timestamps when alert routing fields are unchanged (approved fields only)."""
    raw = "|".join(
        [
            sink,
            str(alert.get("suppression_key", "")),
            str(alert.get("reason_code", "")),
            str(alert.get("severity", "")),
            str(alert.get("routing_class", "")),
            json.dumps(alert.get("evidence_refs"), sort_keys=True, default=str),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_evidence_refs(refs: Any) -> None:
    if not isinstance(refs, list):
        raise NotificationDeliveryError("evidence_refs must be a list")
    for i, ref in enumerate(refs):
        if not isinstance(ref, dict):
            raise NotificationDeliveryError(f"evidence_refs[{i}] must be an object")
        if "kind" not in ref or "path" not in ref:
            raise NotificationDeliveryError(f"evidence_refs[{i}] requires kind and path")


def validate_governed_alert_for_delivery(alert: Any) -> dict[str, Any]:
    if not isinstance(alert, dict):
        raise NotificationDeliveryError("alert must be an object")
    missing = REQUIRED_ALERT_KEYS - set(alert.keys())
    if missing:
        raise NotificationDeliveryError(f"governed alert missing required keys: {sorted(missing)}")
    _validate_evidence_refs(alert.get("evidence_refs"))
    return alert


def validate_alert_routing_payload(ar: Any) -> dict[str, Any]:
    if not isinstance(ar, dict):
        raise NotificationDeliveryError("alert_routing must be an object")
    if str(ar.get("schema_version")) != ALERT_ROUTING_SCHEMA_VERSION:
        raise NotificationDeliveryError(
            f"alert_routing.schema_version must be {ALERT_ROUTING_SCHEMA_VERSION!r}"
        )
    alerts = ar.get("alerts")
    if not isinstance(alerts, list):
        raise NotificationDeliveryError("alert_routing.alerts must be a list")
    return ar


def _load_dedup_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": DEDUP_STATE_SCHEMA_VERSION, "delivered_fingerprints": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema_version": DEDUP_STATE_SCHEMA_VERSION, "delivered_fingerprints": {}}
    if not isinstance(data, dict):
        return {"schema_version": DEDUP_STATE_SCHEMA_VERSION, "delivered_fingerprints": {}}
    fp = data.get("delivered_fingerprints")
    if not isinstance(fp, dict):
        fp = {}
    return {"schema_version": DEDUP_STATE_SCHEMA_VERSION, "delivered_fingerprints": fp}


def _save_dedup_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # cap fingerprints to last 2000 sink:key entries
    fp = state.get("delivered_fingerprints")
    if isinstance(fp, dict) and len(fp) > 2000:
        keys = sorted(fp.keys())[-2000:]
        state = {**state, "delivered_fingerprints": {k: fp[k] for k in keys}}
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def _validate_config_for_enabled_sinks(cfg: NotificationDeliveryConfig) -> None:
    if cfg.webhook_enabled and not cfg.webhook_url:
        raise NotificationDeliveryError(
            "ED_NOTIFICATION_WEBHOOK_ENABLED is true but ED_NOTIFICATION_WEBHOOK_URL is empty"
        )


def deliver_webhook(url: str, body: dict[str, Any]) -> tuple[bool, str | None]:
    try:
        payload = json.dumps(body).encode("utf-8")
        req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=15) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            if code and int(code) >= 400:
                return False, f"HTTP {code}"
        return True, None
    except HTTPError as e:
        return False, f"HTTPError {e.code}: {e.reason}"
    except URLError as e:
        return False, f"URLError: {e.reason}"
    except OSError as e:
        return False, str(e)


# Application code may assign real callables; defaults fail closed when sink enabled without impl.
EmailDeliverFn = Callable[[dict[str, Any]], tuple[bool, str | None]]
SlackDeliverFn = Callable[[dict[str, Any]], tuple[bool, str | None]]


def default_email_deliver(_body: dict[str, Any]) -> tuple[bool, str | None]:
    return (False, "EMAIL_STUB_NO_BACKEND_CONFIGURED")


def default_slack_deliver(_body: dict[str, Any]) -> tuple[bool, str | None]:
    return (False, "SLACK_ROUTING_STUB_NO_BACKEND_CONFIGURED")


email_deliver: EmailDeliverFn = default_email_deliver
slack_deliver: SlackDeliverFn = default_slack_deliver


def process_notification_deliveries(
    model_dir: Path,
    ml_horizon_slug: str,
    ticker: str,
    operational_policy_payload: dict[str, Any],
    *,
    config: NotificationDeliveryConfig | None = None,
) -> dict[str, Any]:
    """
    Consume ``operational_policy_payload`` only; emit delivery records and optional outbound sends.

    Does not mutate architecture, promotion state, or policy content.
    """
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    tku = ticker.upper()
    cfg = config if config is not None else load_notification_delivery_config_from_env()
    log_path = notification_delivery_log_path(model_dir, hz, tku)
    dedup_path = notification_dedup_state_path(model_dir, hz, tku)
    policy_ts = str(operational_policy_payload.get("last_policy_evaluation_timestamp") or "")

    summary: dict[str, Any] = {
        "ok": True,
        "error": None,
        "records_written": 0,
        "batch_error_record": None,
    }

    try:
        _validate_config_for_enabled_sinks(cfg)
    except NotificationDeliveryError as e:
        rec = _delivery_record(
            sink_type="batch",
            alert={},
            policy_ts=policy_ts,
            outcome="delivery_error",
            err=str(e),
            dedup="n_a",
            evidence_refs=[],
        )
        _append_jsonl(log_path, rec)
        summary["ok"] = False
        summary["error"] = str(e)
        summary["records_written"] = 1
        summary["batch_error_record"] = rec
        return summary

    try:
        ar = validate_alert_routing_payload(operational_policy_payload.get("alert_routing"))
    except NotificationDeliveryError as e:
        rec = _delivery_record(
            sink_type="batch",
            alert={},
            policy_ts=policy_ts,
            outcome="failed_validation",
            err=str(e),
            dedup="n_a",
            evidence_refs=[],
        )
        _append_jsonl(log_path, rec)
        summary["ok"] = False
        summary["error"] = str(e)
        summary["records_written"] = 1
        return summary

    alerts = ar.get("alerts") or []
    had_alert_validation_error = False
    dedup_state = _load_dedup_state(dedup_path)
    fingerprints: dict[str, Any] = dedup_state.setdefault("delivered_fingerprints", {})
    if not isinstance(fingerprints, dict):
        fingerprints = {}
        dedup_state["delivered_fingerprints"] = fingerprints

    sinks: list[tuple[str, bool, Any]] = [
        (SINK_FILE, cfg.file_sink_enabled, None),
        (SINK_WEBHOOK, cfg.webhook_enabled and bool(cfg.webhook_url), cfg.webhook_url),
        (SINK_EMAIL_STUB, cfg.email_enabled, None),
        (SINK_SLACK_ROUTING, cfg.slack_enabled, None),
    ]

    for alert in alerts:
        try:
            va = validate_governed_alert_for_delivery(alert)
        except NotificationDeliveryError as e:
            had_alert_validation_error = True
            rec = _delivery_record(
                sink_type="batch",
                alert=alert if isinstance(alert, dict) else {},
                policy_ts=policy_ts,
                outcome="failed_validation",
                err=str(e),
                dedup="n_a",
                evidence_refs=[],
            )
            _append_jsonl(log_path, rec)
            summary["records_written"] += 1
            continue

        evidence_refs = va.get("evidence_refs") or []

        for sink_type, enabled, extra in sinks:
            fp = _dedup_fingerprint(sink_type, va)
            key = f"{sink_type}:{fp}"

            if not enabled:
                rec = _delivery_record(
                    sink_type=sink_type,
                    alert=va,
                    policy_ts=policy_ts,
                    outcome="skipped_disabled",
                    err=None,
                    dedup="n_a",
                    evidence_refs=evidence_refs,
                )
                _append_jsonl(log_path, rec)
                summary["records_written"] += 1
                continue

            if fingerprints.get(key):
                rec = _delivery_record(
                    sink_type=sink_type,
                    alert=va,
                    policy_ts=policy_ts,
                    outcome="suppressed_duplicate",
                    err=None,
                    dedup="suppressed_same_policy_cycle",
                    evidence_refs=evidence_refs,
                )
                _append_jsonl(log_path, rec)
                summary["records_written"] += 1
                continue

            body = {
                "governed_notification": True,
                "schema_version": NOTIFICATION_DELIVERY_RECORD_SCHEMA_VERSION,
                "policy_evaluation_timestamp": policy_ts,
                "alert": va,
            }

            ok = True
            err_msg: str | None = None

            if sink_type == SINK_FILE:
                rec = _delivery_record(
                    sink_type=sink_type,
                    alert=va,
                    policy_ts=policy_ts,
                    outcome="delivered",
                    err=None,
                    dedup="emitted",
                    evidence_refs=evidence_refs,
                )
                _append_jsonl(log_path, rec)
                fingerprints[key] = _now_iso()
                summary["records_written"] += 1
                continue

            if sink_type == SINK_WEBHOOK:
                ok, err_msg = deliver_webhook(str(extra), body)
            elif sink_type == SINK_EMAIL_STUB:
                ok, err_msg = email_deliver(body)
            elif sink_type == SINK_SLACK_ROUTING:
                ok, err_msg = slack_deliver(body)

            outcome = "delivered" if ok else "delivery_error"
            rec = _delivery_record(
                sink_type=sink_type,
                alert=va,
                policy_ts=policy_ts,
                outcome=outcome,
                err=err_msg,
                dedup="emitted" if ok else "n_a",
                evidence_refs=evidence_refs,
            )
            _append_jsonl(log_path, rec)
            summary["records_written"] += 1
            if ok:
                fingerprints[key] = _now_iso()

    if had_alert_validation_error:
        summary["ok"] = False
        summary["error"] = summary.get("error") or "governed_alert_validation_failed"

    try:
        _save_dedup_state(dedup_path, dedup_state)
    except OSError:
        pass

    return summary


def _delivery_record(
    *,
    sink_type: str,
    alert: dict[str, Any],
    policy_ts: str,
    outcome: str,
    err: str | None,
    dedup: str,
    evidence_refs: list[Any],
) -> dict[str, Any]:
    return {
        "schema_version": NOTIFICATION_DELIVERY_RECORD_SCHEMA_VERSION,
        "timestamp_utc": _now_iso(),
        "sink_type": sink_type,
        "alert_id": alert.get("alert_id"),
        "reason_code": alert.get("reason_code"),
        "severity": alert.get("severity"),
        "routing_class": alert.get("routing_class"),
        "delivery_outcome": outcome,
        "delivery_error": err,
        "evidence_refs": evidence_refs,
        "suppression_key": alert.get("suppression_key"),
        "dedup_decision": dedup,
        "policy_evaluation_timestamp_ref": policy_ts,
    }


class EmailNotificationAdapter:
    """Pluggable email backend; default uses ``email_deliver`` hook."""

    def deliver(self, body: dict[str, Any]) -> tuple[bool, str | None]:
        return email_deliver(body)


class SlackRoutingAdapter:
    """Pluggable Slack / desktop-compatible routing; default uses ``slack_deliver`` hook."""

    def deliver(self, body: dict[str, Any]) -> tuple[bool, str | None]:
        return slack_deliver(body)


def read_recent_notification_delivery_records(
    model_dir: Path,
    ml_horizon_slug: str,
    ticker: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    path = notification_delivery_log_path(model_dir, ml_horizon_slug, ticker)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
