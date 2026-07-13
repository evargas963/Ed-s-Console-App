#!/usr/bin/env python3
"""UNIVERSAL_FIX_IMPACT_GATE_V1 — mechanical rejection of falsely universal fixes.

Focused defects may have focused root causes; material fixes must declare scope,
connected consumers, proof matrix, and recurrence controls validated against
machine-derived inventories.

Failure codes are stable for CI and agent diagnostics. Wired into:
  * repo-wide static audit (check_fix_everything_we_touch)
  * enforce_all_rules --objective-audit (via static + dedicated pass)
  * pre-push parity (tools/check_prepush_parity.py)

Schwab CSV authority checked: yes
CSV row(s): NO_SCHWAB_EQUIVALENT — governance enforcement only.
SCHWAB_CSV_CHECKED
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_horizon import ML_HORIZON_SLUGS  # noqa: E402
from tools.check_universal_ticker_lock import (  # noqa: E402
    GUARDED_PARENT_LANES,
    LOCKED_TICKER_LITERALS,
    TICKER_LITERAL_ALLOWLIST,
    check_packet_text,
    check_production_ticker_literals,
    is_production_python,
)

# ── Stable failure codes ─────────────────────────────────────────────────────
FC_MANIFEST_MISSING = "UNIVERSAL_IMPACT_MANIFEST_MISSING"
FC_ROOT_CAUSE = "ROOT_CAUSE_SCOPE_NOT_DECLARED"
FC_CONSUMER = "CONNECTED_CONSUMER_OMITTED"
FC_TICKER = "TICKER_UNIVERSE_INCOMPLETE"
FC_HORIZON = "HORIZON_UNIVERSE_INCOMPLETE"
FC_ROUTE = "ROUTE_UNIVERSE_INCOMPLETE"
FC_WRITER = "WRITER_UNIVERSE_INCOMPLETE"
FC_REPLAY = "REPLAY_PATH_OMITTED"
FC_UI = "UI_CONSUMER_OMITTED"
FC_REPRESENTATIVE = "REPRESENTATIVE_PROOF_INFLATED"
FC_PARENT_CHILD = "PARENT_CLOSED_FROM_CHILD_SCOPE"
FC_NOT_PROVEN = "MATERIAL_ACCEPTANCE_NOT_PROVEN"
FC_INVENTORY = "FUTURE_ENTITY_INVENTORY_DRIFT"
FC_EXCEPTION = "UNIVERSAL_EXCEPTION_MISSING_OR_EXPIRED"
FC_PREPUSH = "PREPUSH_TIER_PARITY_FAILURE"

INVENTORY_PATH = ROOT / "governance" / "artifacts" / "universal_repository_inventory.json"
MANIFEST_PATH = ROOT / "governance" / "universal_fix_impact_manifest.json"
EXCEPTION_REGISTER = ROOT / "governance" / "artifacts" / "universal_fix_exception_register.json"

CONTROL_RECORDS: tuple[str, ...] = (
    "OPEN_ITEMS.md",
    "ACTIVE_PROGRAM.md",
)

MANIFEST_REQUIRED_FIELDS: tuple[str, ...] = (
    "change_id",
    "claimed_scope",
    "root_cause_artifact",
    "affected_production_paths",
    "connected_consumers",
    "ticker_classes",
    "horizons",
    "runtime_classes",
    "proof_matrix",
    "recurrence_guard",
    "lanes_not_closed",
)

SCOPED_HONEST_VALUES: frozenset[str] = frozenset(
    {
        "SCOPED_AND_HONEST",
        "BASE_ANCHOR_EVIDENCED_ONLY",
        "REPRESENTATIVE_ONLY_NOT_PROVEN",
        "SUBSET_EVIDENCED_ONLY",
        "UNIVERSAL_BY_CONSTRUCTION_WITH_MECHANICAL_LOCK",
        "UNIVERSAL_BY_CONSTRUCTION_STATIC_PROVEN",
    }
)

UNIVERSAL_CLAIM_VALUES: frozenset[str] = frozenset(
    {
        "UNIVERSAL_BY_CONSTRUCTION",
        "UNIVERSAL_BEHAVIOR_PROVEN",
        "UNIVERSAL_TICKER_AGNOSTIC_PROVEN",
    }
)

# Producer → materially connected consumers (minimum manifest coverage).
CONNECTED_PATH_FAMILIES: dict[str, tuple[str, ...]] = {
    "signals.py": (
        "prediction_engine.py",
        "server.py",
        "call_engine.py",
        "live_decision_bundle.py",
    ),
    "prediction_engine.py": (
        "signals.py",
        "server.py",
        "multi_horizon_decision.py",
        "bayesian_fusion.py",
    ),
    "ml_predict.py": (
        "prediction_engine.py",
        "signals.py",
        "active_bundle_contract.py",
    ),
    "db.py": (
        "server.py",
        "calibration/writer.py",
        "market_state.py",
    ),
    "bayesian_fusion.py": (
        "prediction_engine.py",
        "signals.py",
        "mc_fusion_adjustment.py",
    ),
    "execution_identity.py": (
        "active_bundle_contract.py",
        "ml_predict.py",
        "calibration/writer.py",
    ),
}

MATERIAL_PREFIXES: tuple[str, ...] = (
    "signals.py",
    "call_engine.py",
    "prediction_engine.py",
    "server.py",
    "ml_predict.py",
    "market_state.py",
    "db.py",
    "bayesian_fusion.py",
    "execution_identity.py",
    "static/",
    "templates/",
    "calibration/",
)

NON_MATERIAL_PREFIXES: tuple[str, ...] = (
    "tests/",
    "governance/artifacts/schwab_v4",
    "governance/mission_authorization/",
    ".pytest_cache/",
)

_COMMON_NON_TICKERS: frozenset[str] = frozenset(
    {
        "API", "URL", "HTTP", "HTTPS", "JSON", "YAML", "SQL", "UTC", "ET", "DB",
        "ML", "UI", "OK", "FAIL", "GET", "POST", "PUT", "DELETE", "SSE", "RTH",
        "ETF", "USD", "EPS", "PE", "IV", "ATR", "VIX", "MACD", "RSI", "EMA",
        "SMA", "OHLC", "TRUE", "FALSE", "NONE", "NULL", "NAN", "ALL", "ANY",
        "MAX", "MIN", "AVG", "SUM", "STD", "VAR", "CPU", "GPU", "RAM", "SSD",
        "SHA", "HMAC", "JWT", "TLS", "SSL", "DNS", "TCP", "UDP", "IPC", "PID",
        "ENV", "CLI", "REPL", "AST", "UTF", "ASCII", "UUID", "ISO", "GMT",
        "EST", "PST", "CST", "MST", "EDT", "PDT", "CDT", "MDT",
    }
)

_TICKER_LIKE_RE = re.compile(r"^[A-Z]{1,5}$|^\$[A-Z]{1,5}$")
_HORIZON_SET = frozenset(ML_HORIZON_SLUGS)
_CLOSED_ACCEPTANCE_RE = re.compile(
    r"(?P<lane>[A-Z0-9_\-]+)\s*=\s*CLOSED_WITH_EVIDENCE\b"
)
_NOT_PROVEN_ACCEPTANCE_RE = re.compile(
    r"(?P<lane>[A-Z0-9_\-]+)\s*=\s*NOT_PROVEN\b"
)


def _git_tracked(root: Path = ROOT) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=str(root),
        check=True,
    ).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _err(code: str, message: str) -> str:
    return f"[{code}] {message}"


def is_material_path(relpath: str) -> bool:
    rp = relpath.replace("\\", "/")
    if any(rp.startswith(p) for p in NON_MATERIAL_PREFIXES):
        return False
    if rp.startswith("tools/check_") or rp.startswith("tools/build_"):
        return False
    if rp.endswith(".py") and is_production_python(rp):
        return True
    if any(rp.startswith(p) for p in MATERIAL_PREFIXES):
        return True
    if rp.startswith("static/") or rp.startswith("templates/"):
        return True
    return False


def _is_conditional_branch(parent_map: dict[ast.AST, ast.AST], node: ast.Compare) -> bool:
    cur: ast.AST = node
    while cur in parent_map:
        cur = parent_map[cur]
        if isinstance(cur, (ast.If, ast.IfExp, ast.While, ast.Assert)):
            return True
    return False


def _compare_names(comp: ast.Compare) -> tuple[Optional[str], Optional[str]]:
    """Return (variable_name, literal) when comparing name to string constant."""
    if len(comp.ops) != 1 or not isinstance(comp.ops[0], (ast.Eq, ast.NotEq)):
        return None, None
    left, right = comp.left, comp.comparators[0]
    if isinstance(left, ast.Name) and isinstance(right, ast.Constant) and isinstance(right.value, str):
        return left.id, right.value.strip()
    if isinstance(right, ast.Name) and isinstance(left, ast.Constant) and isinstance(left.value, str):
        return right.id, left.value.strip()
    return None, None


_TICKER_VAR_NAMES = frozenset({"ticker", "symbol", "sym", "tkr", "underlying", "anchor"})
_HORIZON_VAR_NAMES = frozenset({"horizon", "horizon_slug", "slug", "hz", "tf", "timeframe"})


def scan_conditional_universality_violations(src: str, relpath: str) -> list[str]:
    """Flag explicit if-branch equality on a single ticker or horizon slug."""
    errors: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return errors
    parent_map: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[child] = node
    rel_norm = relpath.replace("\\", "/")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        branch_tickers: set[str] = set()
        branch_horizons: set[str] = set()
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Compare):
                continue
            if not _is_conditional_branch(parent_map, sub):
                continue
            var_name, lit = _compare_names(sub)
            if var_name is None or lit is None:
                continue
            low = var_name.lower()
            if any(tok in low for tok in _TICKER_VAR_NAMES) or low.endswith("_ticker"):
                if lit in LOCKED_TICKER_LITERALS or (
                    _TICKER_LIKE_RE.match(lit)
                    and lit not in _COMMON_NON_TICKERS
                    and len(lit) >= 2
                ):
                    key = (rel_norm, node.name, lit)
                    if key in TICKER_LITERAL_ALLOWLIST:
                        continue
                    branch_tickers.add(lit)
            if any(tok in low for tok in _HORIZON_VAR_NAMES) or low.endswith("_horizon"):
                if lit.lower() in _HORIZON_SET:
                    branch_horizons.add(lit.lower())
        if len(branch_tickers) == 1:
            t = next(iter(branch_tickers))
            errors.append(
                _err(
                    FC_TICKER,
                    f"{relpath}:{node.lineno} conditional single-ticker branch on {t!r} "
                    f"in {node.name!r} — ticker-specific production logic forbidden "
                    f"without governed exception",
                )
            )
        if len(branch_horizons) == 1:
            h = next(iter(branch_horizons))
            errors.append(
                _err(
                    FC_HORIZON,
                    f"{relpath}:{node.lineno} conditional single-horizon branch on {h!r} "
                    f"in {node.name!r} — declare SCOPED_AND_HONEST manifest with "
                    f"explicit horizon exclusions",
                )
            )
    return errors


def check_production_universality_scans(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    errors.extend(check_production_ticker_literals(root))
    for rel in _git_tracked(root):
        if not is_production_python(rel):
            continue
        p = root / rel
        if not p.is_file():
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        errors.extend(scan_conditional_universality_violations(src, rel))
    return errors


def check_control_record_closures(root: Path = ROOT) -> list[str]:
    """OPEN_ITEMS / ACTIVE_PROGRAM closure inflation — audit gap fix."""
    errors: list[str] = []
    for rel in CONTROL_RECORDS:
        p = root / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        errors.extend(check_packet_text(text, rel))
        for i, line in enumerate(text.splitlines(), 1):
            if _NOT_PROVEN_ACCEPTANCE_RE.search(line) and _CLOSED_ACCEPTANCE_RE.search(line):
                errors.append(
                    _err(
                        FC_NOT_PROVEN,
                        f"{rel}:{i} lane carries both CLOSED/PROVEN and NOT_PROVEN on same "
                        f"line — material acceptance contradiction",
                    )
                )
            for lane in GUARDED_PARENT_LANES:
                if re.search(rf"{lane}\s*=\s*CLOSED_WITH_EVIDENCE", line):
                    if "UNIVERSALITY_CLASSIFICATION" not in text:
                        errors.append(
                            _err(
                                FC_PARENT_CHILD,
                                f"{rel}:{i} guarded parent {lane} CLOSED_WITH_EVIDENCE "
                                f"without universality packet in {rel}",
                            )
                        )
    return errors


def _load_manifest(root: Path = ROOT) -> Optional[dict[str, Any]]:
    p = root / MANIFEST_PATH.relative_to(ROOT)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"__parse_error__": str(e)}


def check_manifest_schema(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "__parse_error__" in manifest:
        return [_err(FC_MANIFEST_MISSING, f"manifest JSON parse error: {manifest['__parse_error__']}")]
    missing = [f for f in MANIFEST_REQUIRED_FIELDS if f not in manifest]
    if missing:
        errors.append(_err(FC_MANIFEST_MISSING, f"manifest missing required fields: {missing}"))
    if not str(manifest.get("root_cause_artifact") or "").strip():
        errors.append(_err(FC_ROOT_CAUSE, "manifest root_cause_artifact empty"))
    scope = str(manifest.get("claimed_scope") or "")
    if scope in UNIVERSAL_CLAIM_VALUES:
        pm = manifest.get("proof_matrix") or {}
        if not pm or not isinstance(pm, dict):
            errors.append(
                _err(FC_REPRESENTATIVE, f"claimed_scope={scope!r} requires non-empty proof_matrix")
            )
        if scope == "UNIVERSAL_BEHAVIOR_PROVEN" and manifest.get("representative_only_limitations"):
            errors.append(
                _err(
                    FC_REPRESENTATIVE,
                    "UNIVERSAL_BEHAVIOR_PROVEN incompatible with representative_only_limitations",
                )
            )
    if scope == "REPRESENTATIVE_ONLY_NOT_PROVEN":
        if not manifest.get("representative_only_limitations"):
            errors.append(
                _err(
                    FC_REPRESENTATIVE,
                    "REPRESENTATIVE_ONLY_NOT_PROVEN requires representative_only_limitations",
                )
            )
    return errors


def check_manifest_connected_paths(
    manifest: dict[str, Any],
    changed_material: list[str],
) -> list[str]:
    errors: list[str] = []
    affected = {p.replace("\\", "/") for p in (manifest.get("affected_production_paths") or [])}
    consumers = manifest.get("connected_consumers") or {}
    if not isinstance(consumers, dict):
        return [_err(FC_CONSUMER, "manifest connected_consumers must be an object")]
    for ch in changed_material:
        ch = ch.replace("\\", "/")
        if ch not in affected and not any(ch.endswith(a) for a in affected):
            errors.append(
                _err(
                    FC_MANIFEST_MISSING,
                    f"material change {ch!r} not listed in manifest affected_production_paths",
                )
            )
        base = ch.rsplit("/", 1)[-1]
        family = CONNECTED_PATH_FAMILIES.get(base) or CONNECTED_PATH_FAMILIES.get(ch)
        if not family:
            continue
        declared: set[str] = set()
        for v in consumers.values():
            if isinstance(v, list):
                declared.update(x.replace("\\", "/") for x in v)
            elif isinstance(v, str):
                declared.add(v.replace("\\", "/"))
        for req in family:
            if req not in declared and not any(d.endswith(req) for d in declared):
                scope = str(manifest.get("claimed_scope") or "")
                if scope == "SCOPED_AND_HONEST":
                    consumer_check_required = True
                elif scope in SCOPED_HONEST_VALUES:
                    consumer_check_required = False
                else:
                    consumer_check_required = True
                if consumer_check_required:
                    errors.append(
                        _err(
                            FC_CONSUMER,
                            f"manifest omits connected consumer {req!r} for changed "
                            f"{ch!r} (required by CONNECTED_PATH_FAMILIES)",
                        )
                    )
    return errors


def check_manifest_for_changes(changed_files: list[str], root: Path = ROOT) -> list[str]:
    material = [f for f in changed_files if is_material_path(f)]
    if not material:
        return []
    manifest = _load_manifest(root)
    if manifest is None:
        return [
            _err(
                FC_MANIFEST_MISSING,
                f"material paths changed {material} but "
                f"{MANIFEST_PATH.relative_to(root)} missing",
            )
        ]
    errors = check_manifest_schema(manifest)
    errors.extend(check_manifest_connected_paths(manifest, material))
    return errors


def check_inventory_freshness(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if not INVENTORY_PATH.is_file():
        return [
            _err(
                FC_INVENTORY,
                f"missing {INVENTORY_PATH.relative_to(root)} — run "
                "python tools/build_universal_repository_inventory.py",
            )
        ]
    try:
        on_disk = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [_err(FC_INVENTORY, f"inventory unreadable: {e}")]
    pinned = on_disk.get("content_sha256")
    if not pinned:
        return [_err(FC_INVENTORY, "inventory missing content_sha256 pin")]
    doc = dict(on_disk)
    doc.pop("content_sha256", None)
    import hashlib

    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    live = hashlib.sha256(canonical.encode()).hexdigest()
    if live != pinned:
        errors.append(
            _err(
                FC_INVENTORY,
                f"inventory stale: pin {pinned[:16]}… != live {live[:16]}… — regen with "
                "python tools/build_universal_repository_inventory.py",
            )
        )
    # Live rebuild drift — catches new routes/writers/loaders not yet in artifact.
    try:
        from tools.build_universal_repository_inventory import build_inventory

        rebuilt = build_inventory()
        for key in ("routes", "persistence_writers", "model_loaders", "ui_card_ids"):
            if rebuilt.get(key) != on_disk.get(key):
                errors.append(
                    _err(
                        FC_INVENTORY,
                        f"inventory drift on {key}: live scan differs from pinned artifact — "
                        "run python tools/build_universal_repository_inventory.py",
                    )
                )
                break
    except Exception as exc:
        errors.append(_err(FC_INVENTORY, f"live inventory rebuild failed: {exc}"))
    return errors


def check_exception_register(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if not EXCEPTION_REGISTER.is_file():
        return []
    try:
        doc = json.loads(EXCEPTION_REGISTER.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [_err(FC_EXCEPTION, f"exception register unreadable: {e}")]
    now = datetime.now(timezone.utc)
    for row in doc.get("exceptions") or []:
        exp = str(row.get("expires_utc") or "").strip()
        if not exp:
            errors.append(
                _err(
                    FC_EXCEPTION,
                    f"exception {row.get('exception_id')!r} missing expires_utc",
                )
            )
            continue
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        except ValueError:
            errors.append(
                _err(FC_EXCEPTION, f"exception {row.get('exception_id')!r} bad expires_utc")
            )
            continue
        if exp_dt < now:
            errors.append(
                _err(
                    FC_EXCEPTION,
                    f"exception {row.get('exception_id')!r} expired at {exp}",
                )
            )
        if not str(row.get("parent_lanes_remain_open") or "").strip():
            errors.append(
                _err(
                    FC_EXCEPTION,
                    f"exception {row.get('exception_id')!r} missing parent_lanes_remain_open",
                )
            )
    return errors


def run_static_checks(
    *,
    changed_files: Optional[list[str]] = None,
    root: Path = ROOT,
) -> list[str]:
    """Repo-wide static checks — always-on universality enforcement."""
    errors: list[str] = []
    errors.extend(check_production_universality_scans(root))
    errors.extend(check_control_record_closures(root))
    errors.extend(check_inventory_freshness(root))
    errors.extend(check_exception_register(root))
    if changed_files:
        errors.extend(check_manifest_for_changes(changed_files, root))
    return errors


def outgoing_changed_files(base_ref: str = "origin/main", root: Path = ROOT) -> list[str]:
    files: list[str] = []
    for args in (
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "diff", "--name-only", "HEAD"],
    ):
        r = subprocess.run(args, capture_output=True, text=True, cwd=str(root), timeout=60)
        files.extend(ln.strip() for ln in r.stdout.splitlines() if ln.strip())
    return sorted(set(files))


def main() -> int:
    parser = argparse.ArgumentParser(description="UNIVERSAL_FIX_IMPACT_GATE_V1")
    parser.add_argument("--prepush", action="store_true", help="Pre-push mode with outgoing diff")
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--changed-file", action="append", default=[])
    args = parser.parse_args()
    changed: Optional[list[str]] = None
    if args.prepush:
        changed = outgoing_changed_files(args.base_ref)
    elif args.changed_file:
        changed = args.changed_file
    errors = run_static_checks(changed_files=changed)
    if errors:
        print("check_universal_fix_impact_gate: FAIL", file=sys.stderr)
        for e in errors:
            print(f"- {e}", file=sys.stderr)
        return 1
    mode = "prepush+diff" if changed else "static"
    print(
        f"check_universal_fix_impact_gate: PASS ({mode}) — "
        "production universality scans, control-record closure guard, inventory pin, "
        "exception register"
        + ("; manifest validated for material diff" if changed else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
