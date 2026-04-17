"""
Whitelisted maintenance/training commands for the optional web ops panel (/ops).

Security:
  - Disabled unless ED_OPS_RUNNER=1 (or true/yes/on) and server restarted.
  - POST /api/ops/run* allowed only from localhost unless ED_OPS_ALLOW_REMOTE=1.

No arbitrary shell — only fixed job IDs defined below.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def is_ops_runner_enabled() -> bool:
    return os.environ.get("ED_OPS_RUNNER", "").strip().lower() in ("1", "true", "yes", "on")


def allow_remote() -> bool:
    return os.environ.get("ED_OPS_ALLOW_REMOTE", "").strip().lower() in ("1", "true", "yes", "on")


def client_may_trigger(host: str | None) -> bool:
    if allow_remote():
        return True
    h = (host or "").strip()
    if not h:
        return False
    if h in ("127.0.0.1", "::1", "localhost"):
        return True
    if h.startswith("::ffff:") and "127.0.0.1" in h:
        return True
    return False


def _py() -> str:
    return sys.executable


@dataclass
class OpsJob:
    id: str
    label: str
    cadence: str
    script_args: list[str]
    timeout_sec: int = 900
    warn: str = ""

    def argv(self) -> list[str]:
        return [_py(), str(APP_DIR / self.script_args[0]), *self.script_args[1:]]


# fmt: off
JOBS: dict[str, OpsJob] = {
    "db_health_audit": OpsJob(
        "db_health_audit",
        "DB health audit (integrity, schema, normalized checks, flow sample)",
        "After large imports; weekly if actively trading",
        ["db_health_audit.py"],
        timeout_sec=900,
    ),
    "db_health_audit_deep": OpsJob(
        "db_health_audit_deep",
        "DB health audit — deep flow scan + strict exit",
        "Before declaring DB golden; monthly",
        ["db_health_audit.py", "--deep-flow", "--strict-flow"],
        timeout_sec=7200,
        warn="Can take many minutes on large DBs.",
    ),
    "snapshot_normalizer": OpsJob(
        "snapshot_normalizer",
        "Rebuild snapshots_1m_normalized",
        "After backfills that touch columns used for 1m training",
        ["snapshot_normalizer.py"],
        timeout_sec=3600,
    ),
    "snapshot_normalizer_validate": OpsJob(
        "snapshot_normalizer_validate",
        "Validate normalized table only (no rebuild)",
        "Quick check anytime",
        ["snapshot_normalizer.py", "--validate"],
        timeout_sec=300,
    ),
    "backfill_flow": OpsJob(
        "backfill_flow",
        "Backfill flow_imbalance / smart_money from option_chain_json (NULL/0 only)",
        "After replay; when chain JSON exists but flow empty",
        ["backfill_flow_imbalance.py"],
        timeout_sec=3600,
    ),
    "backfill_flow_force": OpsJob(
        "backfill_flow_force",
        "Backfill flow — FORCE recompute all from chain JSON",
        "When chain JSON is source of truth for history",
        ["backfill_flow_imbalance.py", "--force"],
        timeout_sec=7200,
        warn="Overwrites existing flow_imbalance values. Then run normalizer.",
    ),
    "backfill_derived": OpsJob(
        "backfill_derived",
        "Backfill VWAP gaps, IV rank/percentile, pressure fields",
        "When those columns are historically sparse",
        ["backfill_snapshot_derived.py"],
        timeout_sec=7200,
    ),
    "audit_training_data": OpsJob(
        "audit_training_data",
        "Audit raw snapshots (RTH counts, signals, 0DTE, …)",
        "Before training; after data pushes",
        ["audit_training_data.py"],
        timeout_sec=600,
    ),
    "audit_snapshot_data": OpsJob(
        "audit_snapshot_data",
        "Audit snapshot spacing / intrabar cadence",
        "When timing quality matters",
        ["audit_snapshot_data.py"],
        timeout_sec=600,
    ),
    "audit_model_readiness": OpsJob(
        "audit_model_readiness",
        "Model readiness GO/NO-GO (normalized 1m table)",
        "Before ml_scheduler or promote",
        ["audit_model_readiness.py"],
        timeout_sec=1200,
    ),
    "ml_scheduler_now": OpsJob(
        "ml_scheduler_now",
        "ML scheduler — run once now (parallel + cascade + promote pipeline)",
        "Manual train day; after audits pass",
        ["ml_scheduler.py", "--run-now"],
        timeout_sec=14400,
        warn="Long run (hours possible). Watch server terminal or logs.",
    ),
    "train_all_parallel": OpsJob(
        "train_all_parallel",
        "train_all.py — full parallel stack (XGB+LSTM+Transformer+Meta)",
        "Alternative to scheduler for ad-hoc full train",
        ["train_all.py"],
        timeout_sec=14400,
    ),
}

SEQUENCES: dict[str, dict[str, object]] = {
    "after_flow_backfill": {
        "label": "Flow backfill → rematerialize 1m",
        "cadence": "After imports/replay with option_chain_json",
        "steps": ["backfill_flow", "snapshot_normalizer"],
        "description": "Fills NULL/0 flow from JSON, then rebuilds snapshots_1m_normalized.",
    },
    "after_flow_force": {
        "label": "FORCE flow from JSON → rematerialize 1m",
        "cadence": "When JSON is authoritative for historical flow",
        "steps": ["backfill_flow_force", "snapshot_normalizer"],
        "description": "Overwrites flow from chain, then normalizer.",
    },
    "pre_train_gate": {
        "label": "Audit gate before training",
        "cadence": "Same day before ml_scheduler --run-now",
        "steps": ["db_health_audit", "audit_model_readiness"],
        "description": "Quick health + model readiness; fix failures before training.",
    },
}
# fmt: on


def jobs_public_list() -> list[dict[str, object]]:
    out = []
    for j in JOBS.values():
        d: dict[str, object] = {
            "id": j.id,
            "label": j.label,
            "cadence": j.cadence,
            "timeout_sec": j.timeout_sec,
        }
        if j.warn:
            d["warn"] = j.warn
        d["command_preview"] = " ".join(j.argv())
        out.append(d)
    return sorted(out, key=lambda x: str(x["label"]))


def sequences_public_list() -> list[dict[str, object]]:
    out = []
    for sid, meta in SEQUENCES.items():
        out.append(
            {
                "id": sid,
                "label": meta["label"],
                "cadence": meta["cadence"],
                "steps": meta["steps"],
                "description": meta.get("description", ""),
            }
        )
    return out


def run_job(job_id: str) -> dict[str, object]:
    job = JOBS.get(job_id)
    if not job:
        return {"ok": False, "error": f"unknown job: {job_id}"}
    argv = job.argv()
    t0 = time.perf_counter()
    try:
        cp = subprocess.run(
            argv,
            cwd=str(APP_DIR),
            capture_output=True,
            text=True,
            timeout=job.timeout_sec,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        elapsed = round(time.perf_counter() - t0, 2)
        return {
            "ok": cp.returncode == 0,
            "job_id": job_id,
            "returncode": cp.returncode,
            "stdout": _tail(cp.stdout or "", 120_000),
            "stderr": _tail(cp.stderr or "", 120_000),
            "elapsed_sec": elapsed,
        }
    except subprocess.TimeoutExpired as e:
        elapsed = round(time.perf_counter() - t0, 2)
        return {
            "ok": False,
            "job_id": job_id,
            "error": f"timeout after {job.timeout_sec}s",
            "stdout": _tail((e.stdout or "") if isinstance(e.stdout, str) else "", 80_000),
            "stderr": _tail((e.stderr or "") if isinstance(e.stderr, str) else "", 80_000),
            "elapsed_sec": elapsed,
        }
    except Exception as e:
        return {"ok": False, "job_id": job_id, "error": str(e)}


def run_sequence(sequence_id: str, *, stop_on_error: bool = True) -> dict[str, object]:
    meta = SEQUENCES.get(sequence_id)
    if not meta:
        return {"ok": False, "error": f"unknown sequence: {sequence_id}"}
    steps = list(meta["steps"])
    results: list[dict[str, object]] = []
    overall_ok = True
    for step_id in steps:
        r = run_job(step_id)
        results.append(r)
        if not r.get("ok"):
            overall_ok = False
            if stop_on_error:
                break
    return {
        "ok": overall_ok,
        "sequence_id": sequence_id,
        "stopped_early": overall_ok is False and len(results) < len(steps),
        "steps": steps,
        "results": results,
    }


def _tail(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return "... [truncated]\n" + s[-max_chars:]
