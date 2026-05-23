#!/usr/bin/env python3
"""Pre-flip frozen-candidate harness for auto-promote (PR4 §3C)."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PREFLIP_SCHEMA = "preflip_decisions_v1"


def _decisions_path(model_dir: Path, run_id: str) -> Path:
    return model_dir / "arch_competition" / f"_preflip_decisions_{run_id}.json"


def _dir_checksum(root: Path) -> str:
    """sha256 over sorted file paths + contents (empty dir → sha256 of empty)."""
    h = hashlib.sha256()
    if not root.is_dir():
        return "sha256:" + h.hexdigest()
    for fp in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = fp.relative_to(root).as_posix().encode("utf-8")
        h.update(rel)
        h.update(fp.read_bytes())
    return "sha256:" + h.hexdigest()


def _winner_architecture(promotion_record: dict) -> str | None:
    if not promotion_record.get("would_promote_challenger"):
        return None
    if promotion_record.get("promotion_decision") == "promote_cascade":
        return "cascade"
    return None


def _capture_decision_row(
    model_dir: Path,
    *,
    ticker: str,
    hz: str,
    dest_root: Path,
) -> dict | None:
    from active_bundle_contract import horizon_bundle_filenames, scheduler_active_root
    from arch_competition.scheduler_integration import (
        evaluation_manifest_path,
        promotion_decision_path,
    )

    t = ticker.upper()
    pr_path = promotion_decision_path(model_dir, hz, t)
    ev_path = evaluation_manifest_path(model_dir, hz, t)
    if not pr_path.is_file():
        return None
    record = json.loads(pr_path.read_text(encoding="utf-8"))
    manifest_path = str(ev_path.resolve()) if ev_path.is_file() else None
    frozen_par = dest_root / t / "parallel"
    frozen_cas = dest_root / t / "cascade"
    return {
        "ticker": t,
        "horizon": hz,
        "would_promote": bool(record.get("would_promote_challenger")),
        "winner_architecture": _winner_architecture(record),
        "manifest_path": manifest_path,
        "promotion_decision_path": str(pr_path.resolve()),
        "blocked_promotion_flags": record.get("blocked_promotion_flags") or [],
        "candidate_checksums": {
            "parallel": _dir_checksum(frozen_par) if frozen_par.is_dir() else None,
            "cascade": _dir_checksum(frozen_cas) if frozen_cas.is_dir() else None,
        },
        "expected_active_files": list(horizon_bundle_filenames(t, hz)),
        "active_bundle_dir": str((scheduler_active_root(model_dir, hz) / t).resolve()),
    }


def freeze_and_capture(model_dir: Path, run_id: str, tickers: list[str]) -> int:
    from ml_horizon import PRIMARY_DECISION_HORIZONS

    dest_root = model_dir / f"_preflip_{run_id}"
    decisions: list[dict] = []
    for tku in tickers:
        t = tku.upper()
        for arch in ("parallel", "cascade"):
            src = model_dir / arch / t
            if not src.is_dir():
                continue
            dst = dest_root / t / arch
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        for hz in PRIMARY_DECISION_HORIZONS:
            row = _capture_decision_row(model_dir, ticker=t, hz=hz, dest_root=dest_root)
            if row is not None:
                decisions.append(row)
    payload = {
        "schema_version": PREFLIP_SCHEMA,
        "run_id": run_id,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_root": str(dest_root.relative_to(model_dir)),
        "decisions": decisions,
    }
    _decisions_path(model_dir, run_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Captured {len(decisions)} decision(s) -> {_decisions_path(model_dir, run_id)}")
    return 0


def verify(model_dir: Path, run_id: str) -> int:
    from active_bundle_contract import scheduler_active_root

    path = _decisions_path(model_dir, run_id)
    if not path.is_file():
        print(f"Missing decisions file: {path}", file=sys.stderr)
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != PREFLIP_SCHEMA:
        print(f"Unsupported schema: {payload.get('schema_version')}", file=sys.stderr)
        return 1

    errors: list[str] = []
    for row in payload.get("decisions") or []:
        if not isinstance(row, dict):
            errors.append("invalid decision row (not object)")
            continue
        ticker = str(row.get("ticker") or "").upper()
        hz = str(row.get("horizon") or "").strip().lower()
        if not ticker or not hz:
            errors.append("decision row missing ticker or horizon")
            continue
        if not row.get("would_promote"):
            continue
        winner = row.get("winner_architecture")
        if winner not in ("cascade", "parallel"):
            errors.append(f"{ticker}/{hz}: would_promote but winner_architecture missing")
            continue
        active_dir = scheduler_active_root(model_dir, hz) / ticker
        expected = row.get("expected_active_files") or []
        missing = [name for name in expected if not (active_dir / str(name)).is_file()]
        if missing:
            errors.append(f"{ticker}/{hz}: active missing files: {missing}")
        try:
            from arch_competition.manual_control import _load_arch_state

            st = _load_arch_state(model_dir, hz).get(ticker) or {}
            active_arch = st.get("active_architecture")
            if active_arch and str(active_arch) != winner:
                errors.append(
                    f"{ticker}/{hz}: arch_state active_architecture={active_arch!r} "
                    f"!= winner_architecture={winner!r}"
                )
        except Exception as e:
            errors.append(f"{ticker}/{hz}: arch_state read failed: {e}")

    if errors:
        for err in errors:
            print(f"VERIFY FAIL: {err}", file=sys.stderr)
        return 1
    print(f"Verify OK for run_id={run_id} ({len(payload.get('decisions') or [])} decisions checked)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Auto-promote pre-flip harness (PR4)")
    p.add_argument("--run-id", required=True)
    p.add_argument("--model-dir", default="models")
    p.add_argument("--tickers", default="SPY,QQQ,IWM")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--freeze-and-capture", action="store_true")
    g.add_argument("--verify", action="store_true")
    args = p.parse_args()
    model_dir = Path(args.model_dir)
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.freeze_and_capture:
        return freeze_and_capture(model_dir, args.run_id, tickers)
    return verify(model_dir, args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
