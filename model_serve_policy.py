"""MODEL-04 canonical serve-eligibility policy (operator-approved 2026-07-10).

Single policy owner for whether an ACTIVE bundle may be DIRECTLY served.
Anchor routing (governed_stack_contract.resolve_guest_anchor_route) is a
separate, independently governed layer and is never decided here — withholding
a direct bundle must never silently select a substitute.

Approved classification (manifest `trained_at` is authoritative; directory
mtimes are promote/copy dates and are NOT provenance):

  trained_at <  2026-05-28                  -> SERVE_TEMPORARILY_WITHHELD
      (pre-correctness era: predates leakage closure, label corrections and
       the replay-unit correction; operator: must not be directly served)
  2026-05-28 <= trained_at <= 2026-05-31    -> REVALIDATION_REQUIRED
      (serves WITH explicit status; not proven invalid, not re-proven either)
  trained_at >= 2026-06-01 and ticker in
      {SPY, QQQ, IWM}                       -> SERVE_APPROVED
      (operator-approved base bundles: SPY/QQQ trained 2026-06-04,
       IWM 2026-06-09)
  trained_at >= 2026-06-01, other ticker    -> REVALIDATION_REQUIRED
  missing / malformed provenance            -> NOT_PROVEN (fail closed for
      direct serving; explicit reason; artifact stays inspectable)

Blocking statuses for DIRECT serving: SERVE_TEMPORARILY_WITHHELD, NOT_PROVEN.
Non-blocking-with-status: SERVE_APPROVED, REVALIDATION_REQUIRED.

Schwab CSV authority checked: yes
CSV row(s): NO_SCHWAB_EQUIVALENT — model-artifact governance only; no market
  field read, derivation, or emission.
Derived-field disposition: none required.
All consumers checked: yes — ml_predict strict serve path (fail-closed gate)
  and read-only diagnostics; evaluation/ablation paths intentionally bypass
  (they must inspect withheld artifacts without serving them).
SCHWAB_CSV_CHECKED
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from instrument_identity import ticker_storage_key

MODEL_SERVE_POLICY_VERSION = "1.0.0"

SERVE_APPROVED = "SERVE_APPROVED"
SERVE_TEMPORARILY_WITHHELD = "SERVE_TEMPORARILY_WITHHELD"
REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
NOT_PROVEN = "NOT_PROVEN"

# Statuses that block DIRECT serving (fail closed with explicit reason).
DIRECT_SERVE_BLOCKING_STATUSES = frozenset({SERVE_TEMPORARILY_WITHHELD, NOT_PROVEN})

_PRE_CORRECTNESS_END = date(2026, 5, 28)      # exclusive floor of the band
_REVALIDATION_BAND_END = date(2026, 5, 31)    # inclusive

# Operator-approved base bundles (2026-07-10): post-correctness anchors. SINGLE AUTHORITY —
# imported from money_path_ticker_tiers so the serving gate and the training/regime base
# universe can never desync.
from money_path_ticker_tiers import base_money_path_tickers_upper as _base_upper
_APPROVED_BASE_TICKERS = _base_upper()


def parse_trained_at(raw: Any) -> Optional[date]:
    """Manifest `trained_at` ('YYYY-MM-DD HH:MM:SS' or ISO) -> date, else None."""
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def classify_trained_at(ticker: str, trained_at: Optional[date]) -> tuple[str, str]:
    """(status, reason) for one bundle vintage under the approved policy."""
    sym = ticker_storage_key(ticker)  # RC-345/F25: canonical membership vs _APPROVED_BASE_TICKERS
    if trained_at is None:
        return (
            NOT_PROVEN,
            "bundle provenance missing or malformed (no parseable trained_at) — "
            "direct serving fails closed until provenance is proven",
        )
    if trained_at < _PRE_CORRECTNESS_END:
        return (
            SERVE_TEMPORARILY_WITHHELD,
            f"trained_at {trained_at.isoformat()} predates the correctness era "
            f"(leakage closure, label corrections, replay-unit correction) — "
            f"operator policy 2026-07-10: must not be directly served",
        )
    if trained_at <= _REVALIDATION_BAND_END:
        return (
            REVALIDATION_REQUIRED,
            f"trained_at {trained_at.isoformat()} is in the 2026-05-28..31 "
            f"revalidation band — serving continues with explicit status until "
            f"revalidated against the quality-circle scoreboard",
        )
    if sym in _APPROVED_BASE_TICKERS:
        return (
            SERVE_APPROVED,
            f"operator-approved post-correctness base bundle "
            f"(trained_at {trained_at.isoformat()})",
        )
    return (
        REVALIDATION_REQUIRED,
        f"trained_at {trained_at.isoformat()} is post-correctness but this "
        f"ticker's bundle has no operator serve approval — explicit "
        f"revalidation status until approved",
    )


def bundle_serve_eligibility(ticker: str, hz: str, bundle_dir: Path) -> dict[str, Any]:
    """Serve-eligibility record for the bundle at bundle_dir.

    Provenance anchor: the XGB meta manifest (every governed bundle carries
    one per horizon). Missing/unreadable manifest -> NOT_PROVEN (fail closed
    for direct serving); the artifact itself remains inspectable by tooling.
    """
    sym = ticker_storage_key(ticker)  # RC-345/F25: artifact meta filename identity is canonical (bare SPX must find $SPX meta)
    meta_path = Path(bundle_dir) / f"xgb_{sym}_{hz}_meta.json"
    trained_at_raw: Any = None
    provenance_source = "xgb_meta_manifest"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            trained_at_raw = meta.get("trained_at")
        except (OSError, json.JSONDecodeError):
            trained_at_raw = None
            provenance_source = "xgb_meta_manifest_unreadable"
    else:
        provenance_source = "xgb_meta_manifest_missing"
    trained_at = parse_trained_at(trained_at_raw)
    status, reason = classify_trained_at(sym, trained_at)
    return {
        "policy_version": MODEL_SERVE_POLICY_VERSION,
        "ticker": sym,
        "horizon": hz,
        "bundle_dir": str(bundle_dir),
        "trained_at": trained_at.isoformat() if trained_at else None,
        "provenance_source": provenance_source,
        "status": status,
        "reason": reason,
        "direct_serve_blocked": status in DIRECT_SERVE_BLOCKING_STATUSES,
    }
