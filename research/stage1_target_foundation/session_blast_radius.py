"""Open-world RTH/session blast-radius sweep (Stage 1 research; read-only).

OBJECTIVE D. Walk the whole repository and classify EVERY site that touches a
market session / RTH concept into a machine-readable artifact, so a future
production-migration mission (separately authorized) has a complete inventory.

This module does NOT fix any production site. It only READS and CLASSIFIES.
It is complementary to research/stage1_target_foundation/rth_integrity_audit.py
(which is a narrow detector for the three known contradiction sites); this sweep
is open-world across the tree.

Classification (per matched line):
  STORED_CLOCK_AUTHORITY  — uses stored et_hour/et_minute/market_session/ts_et as
                            a session authority (the RTH-integrity defect class).
  TS_UTC_ET_AUTHORITY     — derives session from ts_utc via DST-aware ET
                            (time_et / America/New_York) — correct-but-ET.
  CT_CALENDAR_AUTHORITY   — Central-Time + exchange-calendar authority (ct_session,
                            America/Chicago, trading_calendar).
  EXCHANGE_CONVENTION     — ET wall-clock constants (09:30/16:00/13:00) used as the
                            exchange convention only.
  SESSION_REFERENCE       — mentions rth/premarket/afterhours/session without a
                            clear authority (label, comment, string, feature).
Each record also carries is_production / is_test / is_research / is_contract and
do_not_fix_in_this_mission=True for production sites.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# .gitignore-class + noise exclusions (prefixes relative to repo root)
EXCLUDE_DIR_PARTS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "site-packages", ".idea", ".vscode",
}
EXCLUDE_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".ico", ".pdf", ".zip", ".gz", ".pyc", ".parquet", ".pkl", ".joblib",
    ".woff", ".woff2", ".ttf", ".map",
}
# Data/record-keeping artifacts (field dictionaries + the register), not session
# AUTHORITY sites. These are Schwab's own field DESCRIPTIONS / inventory data —
# inputs, not code that classifies sessions — so they are gitignore-class
# excluded (same class as the V4 register). The exclusion is disclosed in the
# artifact; it removes ZERO session-authority code sites.
EXCLUDE_NAME_SUBSTR = (
    "SCHWAB_UNIVERSAL_COVERAGE_REGISTER", "schwab_field_dictionary",
    "schwab_ablation_field_registry", "schwab_canonical_fields",
)
# whole directories that are pure market-field inventory DATA (not session code)
EXCLUDE_DIR_PREFIXES = ("schwab_field_inventory/",)

TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".sql", ".json",
    ".yaml", ".yml", ".toml", ".md", ".txt", ".cfg", ".ini",
}

# ---- session concept detectors (case-insensitive word-ish patterns) ----
_STORED_CLOCK = re.compile(
    r"\b(et_hour|et_minute|market_session|ts_et|stored[_ ]clock|session_bucket)\b",
    re.IGNORECASE,
)
_CT_CAL = re.compile(
    r"(America/Chicago|ct_session|classify_session|trading_calendar|central[_ ]time|"
    r"\bCST\b|\bCDT\b|early_close|full_closure|rth_bounds_utc)",
    re.IGNORECASE,
)
_TS_UTC_ET = re.compile(
    r"(America/New_York|is_rth_ts_utc|rth_where_clause|filter_df_to_rth_ts_utc|"
    r"stamp_et_clock_columns|ts_utc.{0,20}(rth|session))",
    re.IGNORECASE,
)
_EXCHANGE_CONST = re.compile(r"(09:30|16:00|13:00|08:30|15:00|open_et|close_et)")
# MARKET session tokens only — deliberately excludes the bare word "session"
# (Flask/requests/DB sessions are not market sessions and are noise).
_SESSION_REF = re.compile(
    r"\b(rth|premarket|pre-market|afterhours|after-hours|regular[_ ]session|"
    r"market[_ ]session|trading[_ ]session|session_bucket|opening[_ ]bell|"
    r"closing[_ ]bell|market[_ ]hours|intraday[_ ]bucket)\b",
    re.IGNORECASE,
)


def _iter_files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        parts = set(p.relative_to(ROOT).parts)
        if parts & EXCLUDE_DIR_PARTS:
            continue
        if any(rel.startswith(pre) for pre in EXCLUDE_DIR_PREFIXES):
            continue
        if p.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        if any(s in p.name for s in EXCLUDE_NAME_SUBSTR):
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield p


def _classify(line: str) -> str | None:
    if _STORED_CLOCK.search(line):
        return "STORED_CLOCK_AUTHORITY"
    if _CT_CAL.search(line):
        return "CT_CALENDAR_AUTHORITY"
    if _TS_UTC_ET.search(line):
        return "TS_UTC_ET_AUTHORITY"
    if _EXCHANGE_CONST.search(line) and _SESSION_REF.search(line):
        return "EXCHANGE_CONVENTION"
    if _SESSION_REF.search(line):
        return "SESSION_REFERENCE"
    return None


def _role(rel: str) -> dict:
    is_test = rel.startswith("tests/") or "/tests/" in rel or rel.split("/")[-1].startswith("test_")
    is_research = rel.startswith("research/") or "stage1_target_label_foundation" in rel
    is_contract = rel.endswith(".json") and "stage1_target_label_foundation" in rel
    is_doc = rel.endswith(".md")
    is_production = not (is_test or is_research or is_contract or is_doc)
    return {
        "is_production": is_production,
        "is_test": is_test,
        "is_research": is_research,
        "is_contract": is_contract,
        "is_doc": is_doc,
    }


def sweep() -> dict:
    records: list[dict] = []
    for p in _iter_files():
        rel = p.relative_to(ROOT).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            cat = _classify(line)
            if cat is None:
                continue
            role = _role(rel)
            # NOTE: no source snippet is stored — the artifact is a classification
            # index (path:line -> category/role), not a copy of repo source. The
            # migration mission opens path:line directly.
            rec = {
                "path": rel,
                "line": i,
                "category": cat,
                **role,
                "do_not_fix_in_this_mission": bool(role["is_production"]),
            }
            records.append(rec)

    by_cat: dict[str, int] = {}
    by_role_prod = 0
    for r in records:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
        if r["is_production"]:
            by_role_prod += 1
    stored_clock_prod = sorted({
        f"{r['path']}:{r['line']}" for r in records
        if r["category"] == "STORED_CLOCK_AUTHORITY" and r["is_production"]
    })
    return {
        "schema": "STAGE1_SESSION_BLAST_RADIUS",
        "schema_version": 1,
        "authority": "RESEARCH FOUNDATION ONLY — open-world session/RTH inventory. "
        "Read-only. Production sites are classified with do_not_fix_in_this_mission=true; "
        "fixing them is a SEPARATELY AUTHORIZED production-migration mission.",
        "scan_root": ROOT.name,
        "partial_scan": False,
        "excluded_dir_parts": sorted(EXCLUDE_DIR_PARTS),
        "excluded_dir_prefixes": list(EXCLUDE_DIR_PREFIXES),
        "excluded_name_substr": list(EXCLUDE_NAME_SUBSTR),
        "exclusion_rationale": "gitignore-class DATA exclusions only: Schwab field "
        "dictionaries / ablation field registry / canonical-fields inventory and the "
        "V4 register are market-field DESCRIPTION data, not session-authority code. "
        "They contain ZERO session-classification logic; excluding them removes no "
        "authority site and no money-path session coverage.",
        "category_definitions": {
            "STORED_CLOCK_AUTHORITY": "stored et_hour/et_minute/market_session/session_bucket used as session authority (RTH-integrity defect class)",
            "TS_UTC_ET_AUTHORITY": "session derived from ts_utc via DST-aware ET (correct-but-ET)",
            "CT_CALENDAR_AUTHORITY": "Central-Time + exchange-calendar authority (canonical Stage 1 target state)",
            "EXCHANGE_CONVENTION": "ET wall-clock constants used as the exchange convention",
            "SESSION_REFERENCE": "session/rth mention without a clear authority (label/comment/string/feature)",
        },
        "totals": {
            "sites": len(records),
            "by_category": by_cat,
            "production_sites": by_role_prod,
        },
        "stored_clock_authority_production_sites": stored_clock_prod,
        "records": records,
    }


def write_artifact(path: Path) -> dict:
    art = sweep()
    path.write_text(json.dumps(art, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return art


if __name__ == "__main__":
    import sys

    out = ROOT / "governance" / "research" / "stage1_target_label_foundation" / "session_blast_radius_v1.json"
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
    art = write_artifact(out)
    print(f"session blast radius: {art['totals']['sites']} sites "
          f"({art['totals']['production_sites']} production) -> {out}")
    for c, n in sorted(art["totals"]["by_category"].items()):
        print(f"  {c}: {n}")
    print("stored-clock production sites:", len(art["stored_clock_authority_production_sites"]))
