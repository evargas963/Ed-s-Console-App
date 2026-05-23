#!/usr/bin/env python3
"""Pre-flip frozen-candidate harness for auto-promote (PR4 §3C)."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PREFLIP_SCHEMA = "preflip_decisions_v1"


def _decisions_path(model_dir: Path, run_id: str) -> Path:
    return model_dir / "arch_competition" / f"_preflip_decisions_{run_id}.json"


def freeze_and_capture(model_dir: Path, run_id: str, tickers: list[str]) -> int:
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
        pr = model_dir / "arch_competition" / "1c" / t / "promotion_decision.json"
        if pr.is_file():
            rec = json.loads(pr.read_text(encoding="utf-8"))
            decisions.append(
                {
                    "ticker": t,
                    "horizon": "1c",
                    "promotion_decision": rec.get("promotion_decision"),
                    "would_promote_challenger": rec.get("would_promote_challenger"),
                }
            )
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
    path = _decisions_path(model_dir, run_id)
    if not path.is_file():
        print(f"Missing decisions file: {path}", file=sys.stderr)
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != PREFLIP_SCHEMA:
        print(f"Unsupported schema: {payload.get('schema_version')}", file=sys.stderr)
        return 1
    print(f"Verify OK for run_id={run_id} ({len(payload.get('decisions') or [])} decisions recorded)")
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
