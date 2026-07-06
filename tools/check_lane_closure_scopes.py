#!/usr/bin/env python3
"""
STACK_SCOPE_CLOSURE_GOVERNANCE_LOCK_V1 (alias FULL_STACK_ALL_HORIZON_SCOPE_LOCK_V1).

Operator-approved lock (2026-07-06): a parent/composite lane may hold a
closed-class status ONLY when caveat-free (or explicitly operator-waived)
child lanes jointly cover the parent's full required scope — active stack
layers x ticker universe x decision horizons — at or above the required
environment rung. Scoped evidence (xgb-only, SPY-only, 5c/15c-only,
research_scratch) is structurally unable to close full-stack / universal /
all-horizon / production parents.

Scope authorities are resolved FROM CODE at check time (never hardcoded):
  layers   -> governed_stack_contract.FULL_STACK_MODEL_LAYERS
  tickers  -> governed_stack_contract.ML_AUTHORITATIVE_TICKERS
  horizons -> ml_horizon.PRIMARY_DECISION_HORIZONS
Horizon-authority drift guard: OUTCOME_BAR_SPECS and
calibration/fusion_temperature.HORIZON_SLUGS must agree with
PRIMARY_DECISION_HORIZONS or this checker fails loudly.

Also validates governance/standards/EXTERNAL_STANDARDS_CONTROL_MAP_V1.yaml:
every cited repo control path must exist (traceability map may not dangle).

Wired into `enforce_all_rules --objective-audit` (no new CI workflow).

Schwab CSV authority checked: yes
CSV row(s): NO_SCHWAB_EQUIVALENT — governance lane-closure accounting only;
  no market field read, derivation, emission, or actionability logic.
Derived-field disposition: none required.
All consumers checked: yes — read-only governance validation.
SCHWAB_CSV_CHECKED
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REGISTER_PATH = ROOT / "governance" / "artifacts" / "lane_closure_register_v1.json"
STANDARDS_MAP_PATH = (
    ROOT / "governance" / "standards" / "EXTERNAL_STANDARDS_CONTROL_MAP_V1.yaml"
)

ENV_LADDER = ("research_scratch", "local", "ci", "rth", "production")
CLOSED_CLASS_STATUSES = frozenset(
    {"CLOSED", "CLOSED_WITH_EVIDENCE", "PROVEN", "APPROVED", "APPROVED_FOR_PRODUCTION"}
)
CHILD_CONTRIBUTING_STATUSES = frozenset({"CLOSED_WITH_EVIDENCE", "SCOPED_CLOSED_READY"})


def _authorities() -> dict[str, tuple[str, ...]]:
    from governed_stack_contract import FULL_STACK_MODEL_LAYERS, ML_AUTHORITATIVE_TICKERS
    from ml_horizon import PRIMARY_DECISION_HORIZONS

    return {
        "FULL_STACK_MODEL_LAYERS": tuple(FULL_STACK_MODEL_LAYERS),
        "ML_AUTHORITATIVE_TICKERS": tuple(ML_AUTHORITATIVE_TICKERS),
        "PRIMARY_DECISION_HORIZONS": tuple(PRIMARY_DECISION_HORIZONS),
    }


def check_horizon_authority_consistency() -> list[str]:
    """PRIMARY_DECISION_HORIZONS is the authority; the label writer and the
    calibration module must agree or the lock fails loudly (drift guard)."""
    errors: list[str] = []
    from calibration.fusion_temperature import HORIZON_SLUGS
    from horizon_outcomes import OUTCOME_BAR_SPECS
    from ml_horizon import PRIMARY_DECISION_HORIZONS

    primary = set(PRIMARY_DECISION_HORIZONS)
    writer = {f"{n_min}c" for _odir, _opt, n_min in OUTCOME_BAR_SPECS}
    if writer != primary:
        errors.append(
            f"horizon authority drift: OUTCOME_BAR_SPECS={sorted(writer)} != "
            f"PRIMARY_DECISION_HORIZONS={sorted(primary)}"
        )
    if set(HORIZON_SLUGS) != primary:
        errors.append(
            f"horizon authority drift: fusion_temperature.HORIZON_SLUGS="
            f"{sorted(HORIZON_SLUGS)} != PRIMARY_DECISION_HORIZONS={sorted(primary)}"
        )
    return errors


def _env_rank(env: str) -> int:
    try:
        return ENV_LADDER.index(env)
    except ValueError:
        return -1


def _caveats_block(lane: dict[str, Any]) -> str | None:
    """None when caveats do not block; else the blocking reason."""
    caveats = lane.get("caveats") or []
    disp = str(lane.get("caveats_disposition") or "open")
    if not caveats:
        return None
    if disp == "resolved":
        return None
    if disp.startswith("operator_waived:"):
        ref = disp.split(":", 1)[1].strip()
        if not ref:
            return "operator_waived requires a non-empty operator reference"
        return None
    return f"open caveats block parent closure: {caveats}"


def check_register(register: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    auth = _authorities()
    lanes = register.get("lanes") or []
    by_name = {ln.get("lane"): ln for ln in lanes}
    if len(by_name) != len(lanes):
        errors.append("duplicate lane names in register")

    for ln in lanes:
        name = ln.get("lane") or "<unnamed>"
        kind = ln.get("kind")
        if kind not in ("parent", "child"):
            errors.append(f"{name}: kind must be parent|child")
            continue
        scope_key = "required_scope" if kind == "parent" else "scope"
        scope_block = ln.get(scope_key) or {}
        for dim in ("layers", "tickers", "horizons", "environment"):
            if scope_block.get(dim) is None:
                errors.append(f"{name}: {scope_key} missing dimension {dim!r}")
        env = scope_block.get("environment")
        if isinstance(env, str) and _env_rank(env) < 0:
            errors.append(f"{name}: unknown environment {env!r} (ladder={ENV_LADDER})")
        if kind == "parent":
            for dim in ("layers", "tickers", "horizons"):
                sym = scope_block.get(dim)
                if sym not in auth:
                    errors.append(
                        f"{name}: parent {dim} must be a symbolic authority "
                        f"({sorted(auth)}), got {sym!r}"
                    )
        else:
            disp = str(ln.get("caveats_disposition") or "open")
            if disp.startswith("operator_waived:") and not disp.split(":", 1)[1].strip():
                errors.append(f"{name}: operator_waived requires a non-empty reference")
            if ln.get("parent") and ln["parent"] not in by_name:
                errors.append(f"{name}: parent {ln['parent']!r} not in register")

    # Closure coverage: any parent holding a closed-class status must be
    # covered by contributing, non-blocked children at/above the required rung.
    for ln in lanes:
        if ln.get("kind") != "parent":
            continue
        name = ln.get("lane")
        status = str(ln.get("status") or "")
        if status not in CLOSED_CLASS_STATUSES:
            continue
        req = ln.get("required_scope") or {}
        need = {
            dim: set(auth.get(req.get(dim), ()))
            for dim in ("layers", "tickers", "horizons")
        }
        need_env = _env_rank(str(req.get("environment") or "production"))
        covered: dict[str, set] = {dim: set() for dim in need}
        for ch in lanes:
            if ch.get("kind") != "child" or ch.get("parent") != name:
                continue
            if str(ch.get("status") or "") not in CHILD_CONTRIBUTING_STATUSES:
                continue
            if _caveats_block(ch) is not None:
                continue
            ch_scope = ch.get("scope") or {}
            if _env_rank(str(ch_scope.get("environment") or "")) < need_env:
                continue
            for dim in covered:
                covered[dim] |= set(ch_scope.get(dim) or ())
        for dim, required in need.items():
            missing = required - covered[dim]
            if missing:
                errors.append(
                    f"{name}: closed-class status {status!r} without full {dim} "
                    f"coverage — missing {sorted(missing)} (scoped/caveated/"
                    f"under-environment children cannot close a parent)"
                )
    return errors


def check_standards_map() -> list[str]:
    errors: list[str] = []
    if not STANDARDS_MAP_PATH.is_file():
        return [f"standards map missing: {STANDARDS_MAP_PATH}"]
    import yaml

    doc = yaml.safe_load(STANDARDS_MAP_PATH.read_text(encoding="utf-8"))
    for ctl in (doc or {}).get("controls") or []:
        cid = ctl.get("id") or "<no-id>"
        for ref in ctl.get("repo_controls") or []:
            p = str(ref).split("::")[0]
            if not (ROOT / p).exists():
                errors.append(f"standards map {cid}: cited repo control missing: {p}")
    return errors


def run_check() -> dict[str, Any]:
    errors: list[str] = []
    if not REGISTER_PATH.is_file():
        errors.append(f"register missing: {REGISTER_PATH}")
    else:
        try:
            register = json.loads(REGISTER_PATH.read_text(encoding="utf-8"))
        except ValueError as e:
            errors.append(f"register unreadable: {e}")
        else:
            errors += check_register(register)
    errors += check_horizon_authority_consistency()
    errors += check_standards_map()
    return {"ok": not errors, "errors": errors}


def main() -> int:
    result = run_check()
    if not result["ok"]:
        print("check_lane_closure_scopes: FAIL", file=sys.stderr)
        for e in result["errors"]:
            print(f"- {e}", file=sys.stderr)
        return 1
    print(
        "check_lane_closure_scopes: PASS "
        "(STACK_SCOPE_CLOSURE_GOVERNANCE_LOCK_V1 — register scopes valid; "
        "horizon authorities consistent; standards map cites existing controls)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
