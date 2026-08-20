#!/usr/bin/env python3
"""RC-436 / RC-437 — ENFORCEMENT prove: Path A ML fleet restore is LIVE.

Unlike ``measure_rc435_abstain_impact.py`` (REPORT-ONLY, exit 0 always), this
script exits **1** until the active fleet no longer requires structurally
withheld OI/vanna wall-distance features.

Host Path A acceptance (all must hold before closing RC-436):

  python ./tools/prove_path_a_ml_restore.py
  # exit 0 + ARTIFACTS_RESTORED=1 + RESTORED=1

  python ./tools/prove_path_a_ml_restore.py --require-stack-probs
  # also runs the real unified stack (ml_predict.predict_direction →
  # run_unified_stack_ml_once) and requires a complete stack_probs triplet

Optional live-console corroboration (running uvicorn on ED_DIAG_BASE):

  python ./tools/prove_path_a_ml_restore.py --require-stack-probs --via-api

Do **not** close RC-436 on artifact creation alone — stack_probs must return
from the real unified stack (not a synthetic or bypass probe).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _triclass_xgb_metas(active: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(active.rglob("xgb_*_meta.json")):
        if "_dir_" in p.name or "_move_" in p.name:
            continue
        out.append(p)
    return out


def _artifact_gate() -> tuple[bool, list[str]]:
    """True when no active triclass/sequence contract requires withheld distances."""
    from lstm_data import (
        FEATURES_5M,
        LEGACY_ENCODER_SCHEMA_VERSION,
        LEGACY_V2_FEATURES_5M,
        checkpoint_encoder_schema_version,
    )
    from ml_train import (
        STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS,
        snapshot_missing_structurally_withheld_wall_distances,
        structurally_withheld_wall_distance_feature_names,
        WALL_DISTANCE_COLS,
    )

    lines: list[str] = []
    active = ROOT / "models" / "active"
    live = {c: None for c in STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS}
    withheld_names = structurally_withheld_wall_distance_feature_names()

    # Contract: live WALL_DISTANCE_COLS must already exclude the four bases.
    still_in_contract = [
        c for c in STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS if c in WALL_DISTANCE_COLS
    ]
    if still_in_contract:
        lines.append(
            f"WALL_DISTANCE_COLS still includes withheld bases: {still_in_contract}"
        )

    xgb_tri = _triclass_xgb_metas(active)
    require = 0
    gate_true = 0
    for p in xgb_tri:
        feats = json.loads(p.read_text(encoding="utf-8")).get("features") or []
        if set(feats) & withheld_names:
            require += 1
        if snapshot_missing_structurally_withheld_wall_distances(live, feats):
            gate_true += 1
    lines.append(
        f"xgb_triclass_active={len(xgb_tri)} require_withheld={require} "
        f"live_gate_true={gate_true}"
    )

    try:
        import torch
    except ImportError:
        lines.append("lstm_transformer=SKIP (torch missing)")
        ok = (
            not still_in_contract
            and len(xgb_tri) > 0
            and require == 0
            and gate_true == 0
        )
        return ok, lines

    seq_require = 0
    seq_gate = 0
    seq_n = 0
    for pattern in ("lstm_*.pt", "transformer_*.pt"):
        for pt in sorted(active.rglob(pattern)):
            ck = torch.load(pt, map_location="cpu", weights_only=False)
            ver = checkpoint_encoder_schema_version(ck)
            if ver < LEGACY_ENCODER_SCHEMA_VERSION:
                continue
            seq_n += 1
            feats = (
                LEGACY_V2_FEATURES_5M
                if ver == LEGACY_ENCODER_SCHEMA_VERSION
                else FEATURES_5M
            )
            if set(feats) & withheld_names:
                seq_require += 1
            if snapshot_missing_structurally_withheld_wall_distances(live, feats):
                seq_gate += 1
    lines.append(
        f"serveable_seq={seq_n} require_withheld={seq_require} live_gate_true={seq_gate}"
    )

    ok = (
        not still_in_contract
        and len(xgb_tri) > 0
        and require == 0
        and gate_true == 0
        and seq_n > 0
        and seq_require == 0
        and seq_gate == 0
    )
    return ok, lines


def _latest_snapshot_row(db_path: Path, ticker: str) -> dict[str, Any] | None:
    """Latest 1m normalized (else raw snapshots) row for ticker — host DB authority."""
    from db import configure_sqlite_connection
    from instrument_identity import ticker_storage_key

    tkr = ticker_storage_key(ticker)
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    try:
        for table in ("snapshots_1m_normalized", "snapshots"):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue
            row = conn.execute(
                f"SELECT * FROM {table} WHERE ticker=? ORDER BY ts_utc DESC LIMIT 1",
                (tkr,),
            ).fetchone()
            if row is not None:
                return dict(row)
    finally:
        conn.close()
    return None


def _stack_probs_via_unified_stack(
    ticker: str,
    *,
    db_path: Path,
) -> tuple[bool, str]:
    """Exercise the real live stack authority: ``predict_direction`` → ``run_unified_stack_ml_once``.

    No second computation path. Returns the same ``stack_probs_*`` key the signals
    ml_bundle uses. Fails closed when the triplet is missing (fleet dark / abstain).
    """
    from db import EdDB
    from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
    from governed_stack_contract import stack_probs_triplet_complete
    from ml_predict import predict_direction, stack_probs_bundle_key

    row = _latest_snapshot_row(db_path, ticker)
    if row is None:
        return False, (
            f"no snapshot row for {ticker!r} in {db_path} "
            "(snapshots_1m_normalized/snapshots empty — host Path A needs real Collect data)"
        )
    ts = row.get("ts_utc")
    try:
        as_of = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        return False, f"snapshot ts_utc unusable: {ts!r}"
    if as_of is None:
        return False, "snapshot missing ts_utc"

    try:
        inf_v1 = build_inference_snapshot_v1_from_db_row(
            ticker=ticker,
            expiry=row.get("expiry"),
            as_of_ts=as_of,
            db_row=row,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"build_inference_snapshot_v1_from_db_row: {type(exc).__name__}: {exc}"

    # Read-only prove: allow non-canonical only when the env already permits it.
    allow_nc = os.environ.get("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "").strip() in (
        "1",
        "true",
        "yes",
    )
    try:
        db = EdDB(db_path, allow_noncanonical=True if allow_nc else None)
    except Exception as exc:  # noqa: BLE001
        return False, f"EdDB open failed: {type(exc).__name__}: {exc}"

    overlay = {"ticker": ticker}
    try:
        probs = predict_direction(
            overlay,
            ticker,
            db,
            inference_snapshot_v1=inf_v1,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"predict_direction raised {type(exc).__name__}: {exc}"

    spk = stack_probs_bundle_key()
    if probs is None:
        return False, (
            f"{spk}=None from predict_direction/run_unified_stack_ml_once "
            "(fleet still dark, layers abstained, or rules-only)"
        )
    if not stack_probs_triplet_complete(probs):
        return False, f"{spk} incomplete triplet: {probs!r}"
    return True, f"{spk} ok up={probs.get('up')} down={probs.get('down')} flat={probs.get('flat')}"


def _live_api_layer_corroboration(ticker: str, *, base_url: str) -> tuple[bool, str]:
    """Optional: prove the running console served ML layer probs (same tick path as UI).

    Does not replace stack_probs proof — corroborates that /api/analytics/state is live
    and ml_layer_probs are populated after Path A restore.
    """
    base = base_url.rstrip("/")
    url = f"{base}/api/analytics/state?ticker={urllib.parse.quote(ticker)}&force=1"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        token = (os.environ.get("ED_DIAG_TOKEN") or "").strip()
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} from {url}"
    except Exception as exc:  # noqa: BLE001
        return False, f"GET {url} failed: {type(exc).__name__}: {exc}"

    if not isinstance(payload, dict) or len(payload) < 5:
        return False, f"analytics/state payload not a real MarketState dict ({type(payload)})"

    layers = payload.get("ml_layer_probs") or {}
    avail = {
        "xgb": bool(payload.get("xgb_available")),
        "lstm": bool(payload.get("lstm_available")),
        "transformer": bool(payload.get("transformer_available")),
    }
    finite_layers = 0
    for name in ("xgb", "lstm", "transformer"):
        trip = layers.get(name) if isinstance(layers, dict) else None
        if (
            isinstance(trip, dict)
            and trip.get("up") is not None
            and trip.get("down") is not None
            and trip.get("flat") is not None
        ):
            finite_layers += 1
    if finite_layers < 1 and not any(avail.values()):
        return False, (
            f"live API ml_layer_probs empty and no *_available "
            f"(avail={avail}) — console still rules-only / dark"
        )
    return True, f"live API ok finite_ml_layer_probs={finite_layers} avail={avail}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--require-stack-probs",
        action="store_true",
        help=(
            "Require a complete stack_probs triplet from ml_predict.predict_direction "
            "(→ run_unified_stack_ml_once), the same authority signals uses. "
            "Runs even when the artifact gate still fails so the probe surface is exercised."
        ),
    )
    p.add_argument(
        "--via-api",
        action="store_true",
        help=(
            "Also GET /api/analytics/state on ED_DIAG_BASE (default http://127.0.0.1:8000) "
            "and require live ml_layer_probs / *_available corroboration."
        ),
    )
    p.add_argument("--ticker", default="SPY", help="Ticker for stack / API prove")
    p.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "ed_console.db",
        help="Canonical console DB (host Collect data)",
    )
    p.add_argument(
        "--base-url",
        default=(os.environ.get("ED_DIAG_BASE") or "http://127.0.0.1:8000").rstrip("/"),
        help="Live console base URL for --via-api",
    )
    args = p.parse_args(argv)

    ok, lines = _artifact_gate()
    for line in lines:
        print(line)

    failed = False
    if not ok:
        print("NOT_RESTORED=1  # active fleet still requires withheld OI/vanna distances")
        print("RC-436 must remain OPEN. See reports/rc437_oi_vanna_wall_adjudication.md Path A.")
        failed = True
    else:
        print("ARTIFACTS_RESTORED=1  # no active contract requires withheld *_pct")

    # Always exercise the real unified-stack probe when requested — even while the
    # fleet is still dark — so host acceptance never fails solely because a helper
    # surface is missing (probe_unified_stack_probs never existed).
    if args.require_stack_probs:
        stack_ok, detail = _stack_probs_via_unified_stack(args.ticker, db_path=args.db)
        print(f"stack_probe: {detail}")
        if not stack_ok:
            print(
                "NOT_RESTORED=1  # unified-stack stack_probs not proven "
                "(predict_direction → run_unified_stack_ml_once)"
            )
            failed = True
        else:
            print("STACK_PROBS_RESTORED=1")
            if args.via_api:
                api_ok, api_detail = _live_api_layer_corroboration(
                    args.ticker, base_url=args.base_url
                )
                print(f"api_corroboration: {api_detail}")
                if not api_ok:
                    print(
                        "NOT_RESTORED=1  # unified stack ok locally but "
                        "live console API not corroborated"
                    )
                    failed = True
                else:
                    print("LIVE_API_CORROBORATED=1")

    if failed:
        return 1
    print("RESTORED=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
