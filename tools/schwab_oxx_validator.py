"""V4 Deliverable 18 — GOVERNED_EXCEPTION rows must cite O-XX in governed_ref with operator-register body."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

OXX_TAG = re.compile(r"\b(O-\d+)\b", re.IGNORECASE)
DISP_OXX = re.compile(r"GOVERNED_EXCEPTION\s*\(\s*(O-\d+)\s*\)", re.IGNORECASE)
HEADING = re.compile(
    r"^(#{1,6})\s+\*{0,2}(O-\d+)\*{0,2}\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _sections_by_oxx(md: str) -> dict[str, str]:
    """Map O-NN (uppercase) to body text after heading until next heading of same or higher level."""
    matches = list(HEADING.finditer(md))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        level = len(m.group(1))
        oxx = m.group(2).upper()
        start = m.end()
        end = len(md)
        for m2 in matches[i + 1 :]:
            if len(m2.group(1)) <= level:
                end = m2.start()
                break
        out[oxx] = md[start:end]
    return out


def _body_valid(body: str) -> bool:
    b = body.strip()
    if "Why:" not in b:
        return False
    if "Constraint:" not in b:
        return False
    if "Permanent or interim:" not in b:
        return False
    return True


def oxx_narrative_valid(operator_md: str, oxx: str) -> bool:
    oxx_u = oxx.upper()
    sections = _sections_by_oxx(operator_md)
    body = sections.get(oxx_u)
    if body is None:
        return False
    return _body_valid(body)


def perf_proof_basename(governed_ref: str) -> str | None:
    """Return ``pp_*.json`` filename from a register ``governed_ref`` path."""
    g = (governed_ref or "").strip().replace("\\", "/")
    if not g:
        return None
    name = Path(g).name
    if name.startswith("pp_") and name.endswith(".json"):
        return name
    return None


def _is_composite_perf_doc(doc: dict) -> bool:
    rl = doc.get("register_link") or {}
    return bool(rl.get("wrapped_proof_ids"))


def collect_replaced_perf_violations(
    register_csv: Path,
    perf_dir: Path,
) -> list[str]:
    """V4-B perf-proof bundle ↔ register binding for REPLACED rows."""
    if not register_csv.is_file():
        return []
    replaced_by_id: dict[str, dict[str, str]] = {}
    ids_by_proof: dict[str, set[str]] = {}
    with register_csv.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            if (row.get("disposition") or "").strip() != "REPLACED":
                continue
            rid = (row.get("register_id") or "").strip()
            if not rid:
                continue
            replaced_by_id[rid] = row
            proof = perf_proof_basename(row.get("governed_ref") or "")
            if proof:
                ids_by_proof.setdefault(proof, set()).add(rid)

    violations: list[str] = []
    with register_csv.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            if (row.get("disposition") or "").strip() != "REPLACED":
                continue
            rid = (row.get("register_id") or "").strip()
            gref = (row.get("governed_ref") or "").strip()
            proof = perf_proof_basename(gref)
            if not proof:
                violations.append(
                    f"row {i} register_id={rid!r}: REPLACED requires governed_ref "
                    "to governance/artifacts/perf_proof/replacements/pp_*.json"
                )
                continue
            if not (perf_dir / proof).is_file():
                violations.append(
                    f"row {i} register_id={rid!r}: governed_ref points to missing perf proof {proof!r}"
                )

    if perf_dir.is_dir():
        for path in sorted(perf_dir.glob("pp_*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                violations.append(f"{path.name}: unreadable perf proof JSON")
                continue
            rl = doc.get("register_link") or {}
            linked = {
                x.strip()
                for x in rl.get("replaced_register_ids") or []
                if str(x).strip()
            }
            if not linked:
                continue
            if _is_composite_perf_doc(doc):
                wrapped = {
                    perf_proof_basename(str(x)) or Path(str(x)).name
                    for x in (rl.get("wrapped_proof_ids") or [])
                }
                expected = set()
                for wname in wrapped:
                    if wname:
                        expected |= ids_by_proof.get(wname, set())
                orphans = linked - set(replaced_by_id)
                if orphans:
                    violations.append(
                        f"{path.name}: register_link lists {len(orphans)} id(s) not REPLACED in register"
                    )
                if linked != expected:
                    violations.append(
                        f"{path.name}: composite replaced_register_ids must equal union of wrapped proofs "
                        f"({len(expected)} expected, {len(linked)} linked)"
                    )
                continue
            expected = ids_by_proof.get(path.name, set())
            orphans = linked - set(replaced_by_id)
            if orphans:
                violations.append(
                    f"{path.name}: register_link lists {len(orphans)} id(s) not REPLACED in register"
                )
            missing_from_proof = expected - linked
            if missing_from_proof:
                violations.append(
                    f"{path.name}: register has {len(missing_from_proof)} REPLACED row(s) "
                    f"citing this proof but register_link omits them"
                )
            for rid in linked & set(replaced_by_id):
                row_proof = perf_proof_basename(replaced_by_id[rid].get("governed_ref") or "")
                if row_proof != path.name:
                    violations.append(
                        f"{path.name}: register_id={rid!r} governed_ref cites {row_proof!r}, not this bundle"
                    )

    for proof, rids in sorted(ids_by_proof.items()):
        if not (perf_dir / proof).is_file():
            continue
        try:
            doc = json.loads((perf_dir / proof).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _is_composite_perf_doc(doc):
            continue
        linked = {
            x.strip()
            for x in (doc.get("register_link") or {}).get("replaced_register_ids") or []
            if str(x).strip()
        }
        if not linked.intersection(rids):
            violations.append(
                f"{proof}: {len(rids)} REPLACED register row(s) cite this proof but register_link is empty/stale"
            )

    return violations


def validate_replaced_perf_bindings(
    register_csv: Path,
    perf_dir: Path,
) -> list[str]:
    return collect_replaced_perf_violations(register_csv, perf_dir)


def collect_v4_a_violations(register_csv: Path, operator_register_md: Path) -> list[str]:
    if not register_csv.is_file():
        return []
    text = operator_register_md.read_text(encoding="utf-8")
    bad: list[str] = []
    with register_csv.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            disp = (row.get("disposition") or "").strip()
            if not disp.startswith("GOVERNED_EXCEPTION"):
                continue
            rid = (row.get("register_id") or "").strip()
            dm = DISP_OXX.search(disp)
            if not dm:
                bad.append(rid)
                continue
            disp_id = dm.group(1).upper()
            gref = (row.get("governed_ref") or "").strip()
            m = OXX_TAG.search(gref)
            if not m:
                bad.append(rid)
                continue
            oid = m.group(1).upper()
            if oid != disp_id:
                bad.append(rid)
                continue
            if not oxx_narrative_valid(text, oid):
                bad.append(rid)
    return bad


def validate_register_messages(
    register_csv: Path,
    operator_register_md: Path,
) -> list[str]:
    if not register_csv.is_file():
        return []
    text = operator_register_md.read_text(encoding="utf-8")
    msgs: list[str] = []
    with register_csv.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            disp = (row.get("disposition") or "").strip()
            if not disp.startswith("GOVERNED_EXCEPTION"):
                continue
            rid = row.get("register_id", "")
            dm = DISP_OXX.search(disp)
            if not dm:
                msgs.append(
                    f"row {i} register_id={rid!r}: disposition must be "
                    "'GOVERNED_EXCEPTION (O-NN)'"
                )
                continue
            disp_id = dm.group(1).upper()
            gref = (row.get("governed_ref") or "").strip()
            m = OXX_TAG.search(gref)
            if not m:
                msgs.append(
                    f"row {i} register_id={rid!r}: GOVERNED_EXCEPTION requires O-XX in governed_ref"
                )
                continue
            oid = m.group(1).upper()
            if oid != disp_id:
                msgs.append(
                    f"row {i} register_id={rid!r}: governed_ref {oid} != disposition {disp_id}"
                )
                continue
            if not oxx_narrative_valid(text, oid):
                msgs.append(
                    f"row {i} register_id={rid!r}: {oid} missing valid heading narrative "
                    "(Why: / Constraint: / Permanent or interim:)"
                )
    return msgs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--register", type=Path, required=True)
    p.add_argument(
        "--operator-register",
        type=Path,
        default=Path("governance/OPERATOR_DECISION_REGISTER.md"),
    )
    p.add_argument(
        "--perf-dir",
        type=Path,
        default=Path("governance/artifacts/perf_proof/replacements"),
        help="Validate REPLACED governed_ref ↔ pp_*.json register_link binding (V4-B).",
    )
    p.add_argument(
        "--skip-replaced-perf",
        action="store_true",
        help="Only validate GOVERNED_EXCEPTION O-XX rows (legacy mode).",
    )
    args = p.parse_args(argv)
    if not args.operator_register.is_file():
        print(f"Missing {args.operator_register}", file=sys.stderr)
        return 2
    msgs = validate_register_messages(args.register, args.operator_register)
    if not args.skip_replaced_perf:
        msgs.extend(validate_replaced_perf_bindings(args.register, args.perf_dir))
    for m in msgs:
        print(m, file=sys.stderr)
    return 1 if msgs else 0


if __name__ == "__main__":
    raise SystemExit(main())
