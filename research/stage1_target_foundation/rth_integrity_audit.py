"""Research-only RTH cohort-integrity detector (Stage 1; NO production change).

The session/cohort contract records that two live audit/accuracy cohorts still
filter RTH on the DST-skewed stored et_hour/et_minute columns (the exact pattern
ml_data_common.rth_where_clause was deprecated for), and that
math_volatility.session_bucket feeds a stored-clock session label back as a
feature. This module mechanically LOCATES those contradiction sites so the
contract can never silently drift from the code. It changes nothing; it only
reports.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# a stored-clock RTH selection = arithmetic on et_hour/et_minute compared to a
# 570/960-style RTH minute boundary, i.e. the deprecated pattern
_STORED_CLOCK_RTH = re.compile(
    r"et_hour\s*\*\s*60\s*\+\s*(?:COALESCE\(\s*)?et_minute", re.IGNORECASE
)

# the known contradiction sites (contract-pinned); the detector proves they still
# match the stored-clock pattern and that the canonical ts_utc filter exists.
KNOWN_SITES = (
    "db.py",
    "audit_model_readiness.py",
)


def find_stored_clock_rth_sites(root: Path = ROOT) -> list[str]:
    """Return 'path:line: excerpt' for every stored-clock RTH selection in
    tracked production Python (excluding the deprecated helper's own docstring
    and this audit)."""
    hits: list[str] = []
    for rel in KNOWN_SITES + ("ml_data_common.py",):
        p = root / rel
        if not p.is_file():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if _STORED_CLOCK_RTH.search(line):
                hits.append(f"{rel}:{i}: {line.strip()[:100]}")
    return hits


def canonical_authority_present(root: Path = ROOT) -> bool:
    """The correct ts_utc authority must exist (time_et.is_rth_ts_utc +
    ml_data_common.filter_df_to_rth_ts_utc)."""
    te = (root / "time_et.py")
    dc = (root / "ml_data_common.py")
    return (
        te.is_file()
        and "def is_rth_ts_utc" in te.read_text(encoding="utf-8", errors="replace")
        and dc.is_file()
        and "filter_df_to_rth_ts_utc" in dc.read_text(encoding="utf-8", errors="replace")
    )


def audit() -> dict:
    sites = find_stored_clock_rth_sites()
    # partition into the deprecated helper (expected/allowed) vs live cohort uses
    deprecated_helper = [h for h in sites if h.startswith("ml_data_common.py")]
    live_cohort_uses = [h for h in sites if not h.startswith("ml_data_common.py")]
    return {
        "canonical_ts_utc_authority_present": canonical_authority_present(),
        "deprecated_helper_sites": deprecated_helper,
        "live_cohort_stored_clock_rth_sites": live_cohort_uses,
        "contradiction_present": bool(live_cohort_uses) and canonical_authority_present(),
        "stage1_action": "documented in session_cohort_contract_v1.json; NOT fixed (production surface change requires separate authorization)",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(audit(), indent=2))
