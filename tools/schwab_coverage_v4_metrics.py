"""V4 Deliverable 17 — closure metrics JSON + exit code for CI."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from tools.schwab_universal_coverage_scanner_v3.cli import SCANNER_VERSION
from tools.schwab_oxx_validator import collect_v4_a_violations

DEFAULT_REGISTER = Path("governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv")
DEFAULT_OPERATOR = Path("governance/OPERATOR_DECISION_REGISTER.md")


def _norm_disp(s: str) -> str:
    return (s or "").strip()


def compute_full_metrics(
    register_csv: Path,
    operator_register_md: Path,
) -> dict:
    if not operator_register_md.is_file():
        raise FileNotFoundError(operator_register_md)

    violations_set = set(collect_v4_a_violations(register_csv, operator_register_md))

    replaced = 0
    gov_with = 0
    bare = 0
    no_schwab = 0
    not_market = 0
    unreviewed = 0

    if register_csv.is_file():
        with register_csv.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = _norm_disp(row.get("disposition", ""))
                rid = _norm_disp(row.get("register_id", ""))
                if d == "REPLACED":
                    replaced += 1
                elif d == "NO_SCHWAB_EQUIVALENT":
                    no_schwab += 1
                elif d == "UNREVIEWED":
                    unreviewed += 1
                elif d.startswith("NOT_MARKET_DATA"):
                    not_market += 1
                elif d.startswith("GOVERNED_EXCEPTION"):
                    if rid in violations_set:
                        bare += 1
                    else:
                        gov_with += 1

    closure_admissible = bare == 0 and unreviewed == 0

    return {
        "scanner_version": SCANNER_VERSION,
        "register_path": str(register_csv.resolve()) if register_csv.is_file() else str(register_csv),
        "replaced_count": replaced,
        "governed_exception_with_oxx_count": gov_with,
        "bare_governed_exception_count": bare,
        "no_schwab_equivalent_count": no_schwab,
        "not_market_data_count": not_market,
        "unreviewed_count": unreviewed,
        "v4_a_violations": sorted(violations_set),
        "closure_admissible": closure_admissible,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--register",
        type=Path,
        default=DEFAULT_REGISTER,
        help="V4 register CSV",
    )
    p.add_argument(
        "--operator-register",
        type=Path,
        default=DEFAULT_OPERATOR,
        help="OPERATOR_DECISION_REGISTER.md",
    )
    args = p.parse_args(argv)
    try:
        m = compute_full_metrics(args.register, args.operator_register)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(m, indent=2, sort_keys=True))
    if m["bare_governed_exception_count"] > 0 or m["unreviewed_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
