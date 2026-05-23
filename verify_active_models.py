#!/usr/bin/env python3
"""
verify_active_models.py — Active Artifact Compliance & Verification
===================================================================
Verifies that all active per-ticker ML artifacts under models/active/{ticker}/
are compliant with the governed pipeline (provenance, timeframe, target).

Run: python verify_active_models.py

Exit codes:
  0 — all active artifacts compliant
  1 — one or more non-compliant; see output
  2 — no active artifacts or error
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# Windows cp1252: avoid UnicodeEncodeError for console
if sys.stdout.encoding and "cp1252" in sys.stdout.encoding.lower():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception as e:
        log.debug("stdout reconfigure: %s", e, exc_info=True)
APP_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(APP_DIR))

ACTIVE_DIR = APP_DIR / "models" / "active"
MODELS_DIR = APP_DIR / "models"


def _get_active_tickers() -> list[str]:
    """
    Authoritative production universe for verification:
    EdDB.logging_universe (core + pinned + user_persisted), normalized + validated.
    """
    import sqlite3

    from production_universe import filter_valid_tickers, normalize_production_ticker
    from scheduler_user_tickers import load_user_scheduler_tickers_or_empty
    from db import get_db

    tickers = filter_valid_tickers(load_user_scheduler_tickers_or_empty())
    # Operational gate: must have at least one normalized 1m snapshot row.
    con = sqlite3.connect(str(get_db().db_path))
    cur = con.cursor()
    out: list[str] = []
    for t in tickers:
        c = normalize_production_ticker(t)
        n = cur.execute(
            "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE ticker=?",
            (c,),
        ).fetchone()[0]
        if int(n) > 0:
            out.append(c)
    return out


def _active_bundle_dir(ticker: str, hz: str) -> Path:
    from active_bundle_contract import active_bundle_dir

    return active_bundle_dir(ticker, hz, models_dir=MODELS_DIR)


def check_artifact_compliance(ticker: str) -> dict:
    """
    Check compliance of all artifacts for one ticker.
    Returns: {
        "ticker": str,
        "compliant": bool,
        "artifacts": {name: {"exists": bool, "has_provenance": bool, "issues": [str]}},
        "issues": [str],
        "provenance": {...} or None,
    }
    """
    from training_provenance import load_provenance, is_provenance_compliant
    from ml_horizon import PRIMARY_DECISION_HORIZONS
    from active_bundle_contract import check_active_bundle_complete

    result = {
        "ticker": ticker,
        "compliant": True,
        "artifacts": {},
        "issues": [],
        "provenance": None,
    }

    primary_prov = None
    for hz in PRIMARY_DECISION_HORIZONS:
        bundle = check_active_bundle_complete(ticker, hz, models_dir=MODELS_DIR)
        if not bundle["compliant"]:
            result["compliant"] = False
            result["issues"].extend(bundle.get("issues") or [])
        bundle_dir = Path(bundle["bundle_dir"])

        triple = [
            ("xgb", f"xgb_{ticker}_{hz}.pkl", f"xgb_{ticker}_{hz}_meta.json"),
            ("lstm", f"lstm_{ticker}_{hz}.pt", f"lstm_{ticker}_{hz}_meta.json"),
            ("transformer", f"transformer_{ticker}_{hz}.pt", f"transformer_{ticker}_{hz}_meta.json"),
        ]

        for name, model_file, meta_file in triple:
            key = f"{hz}:{name}"
            model_path = bundle_dir / model_file
            meta_path = bundle_dir / meta_file
            art = {"exists": model_path.exists(), "has_provenance": False, "issues": []}

            if not model_path.exists():
                art["issues"].append(f"{model_file} missing")
                result["compliant"] = False
            if not meta_path.exists():
                art["issues"].append(f"{meta_file} missing")
                result["compliant"] = False
            else:
                prov = load_provenance(meta_path)
                if prov:
                    art["has_provenance"] = is_provenance_compliant(prov, horizon_slug=hz)
                    if not art["has_provenance"]:
                        art["issues"].append(
                            "metadata lacks provenance (training_timeframe, target_definition)"
                        )
                        result["compliant"] = False
                    if primary_prov is None:
                        primary_prov = prov
                else:
                    art["issues"].append("could not load provenance (missing or invalid metadata)")
                    result["compliant"] = False

            result["artifacts"][key] = art

    result["provenance"] = primary_prov.to_dict() if primary_prov else None
    if result["compliant"] and not primary_prov:
        result["compliant"] = False
        result["issues"].append("no provenance found in any artifact")

    return result


def verify_single_bundle(ticker: str, hz: str, *, models_dir: Path | None = None) -> dict:
    """
    Compliance check for one (ticker, horizon) canonical active bundle (P3-4b).
    """
    from training_provenance import load_provenance, is_provenance_compliant
    from active_bundle_contract import check_active_bundle_complete

    models_dir = models_dir or MODELS_DIR
    result: dict = {
        "ticker": ticker.upper(),
        "horizon": hz,
        "compliant": True,
        "artifacts": {},
        "issues": [],
    }
    bundle = check_active_bundle_complete(ticker, hz, models_dir=models_dir)
    if not bundle["compliant"]:
        result["compliant"] = False
        result["issues"].extend(bundle.get("issues") or [])
        return result

    bundle_dir = Path(bundle["bundle_dir"])
    triple = [
        ("xgb", f"xgb_{ticker.upper()}_{hz}.pkl", f"xgb_{ticker.upper()}_{hz}_meta.json"),
        ("lstm", f"lstm_{ticker.upper()}_{hz}.pt", f"lstm_{ticker.upper()}_{hz}_meta.json"),
        (
            "transformer",
            f"transformer_{ticker.upper()}_{hz}.pt",
            f"transformer_{ticker.upper()}_{hz}_meta.json",
        ),
    ]
    for name, model_file, meta_file in triple:
        model_path = bundle_dir / model_file
        meta_path = bundle_dir / meta_file
        art = {"exists": model_path.exists(), "has_provenance": False, "issues": []}
        if not model_path.exists():
            art["issues"].append(f"{model_file} missing")
            result["compliant"] = False
        if not meta_path.exists():
            art["issues"].append(f"{meta_file} missing")
            result["compliant"] = False
        else:
            prov = load_provenance(meta_path)
            if prov and is_provenance_compliant(prov, horizon_slug=hz):
                art["has_provenance"] = True
            else:
                art["issues"].append("metadata lacks compliant provenance")
                result["compliant"] = False
        result["artifacts"][name] = art
        result["issues"].extend(art["issues"])

    return result


def main() -> int:
    print("=" * 72)
    print("ACTIVE MODEL COMPLIANCE VERIFICATION")
    print("=" * 72)

    tickers = _get_active_tickers()
    if not tickers:
        print("No active tickers found.")
        return 2

    print(f"Checking {len(tickers)} tickers: {', '.join(tickers)}")
    print()

    all_ok = True
    non_compliant = []

    for ticker in tickers:
        r = check_artifact_compliance(ticker)
        status = "COMPLIANT" if r["compliant"] else "NON-COMPLIANT"
        if not r["compliant"]:
            all_ok = False
            non_compliant.append(ticker)

        print(f"  {ticker}: {status}")
        for art_name, art in r["artifacts"].items():
            sym = "OK" if art["exists"] and art["has_provenance"] else "X"
            issues = "; ".join(art["issues"]) if art["issues"] else ""
            print(f"    {sym} {art_name}: exists={art['exists']}, provenance={art['has_provenance']} {issues}")
        if r["issues"]:
            for issue in r["issues"]:
                print(f"    ! {issue}")
        print()

    if non_compliant:
        print("NON-COMPLIANT TICKERS (require clean retrain):", ", ".join(non_compliant))
        print()
        print("To rebuild under governed pipeline:")
        print("  python ml_scheduler.py --run-now --force-retrain")
        print("  (--force-retrain allows promotion even when new score < existing)")
        from ml_horizon import default_training_label_column

        print(
            f"  (Ensure DB has 1m snapshots with {default_training_label_column()} NOT NULL for training rows)"
        )
        return 1

    print("All active artifacts compliant.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
