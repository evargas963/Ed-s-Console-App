#!/usr/bin/env python3
"""Build machine-derived universal repository inventory (UNIVERSAL_FIX_IMPACT_GATE_V1).

Regenerates governance/artifacts/universal_repository_inventory.json from AST scans
and authoritative registries. The inventory is the dynamic truth source for future-
entity omission detection — new routes, writers, loaders, etc. must appear here or
the freshness gate fails after regen.

Regen: python tools/build_universal_repository_inventory.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "governance" / "artifacts" / "universal_repository_inventory.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_horizon import ML_HORIZON_SLUGS  # noqa: E402
from governed_stack_contract import FULL_STACK_MODEL_LAYERS  # noqa: E402
from scheduler_user_tickers import TRAINING_ANCHOR_TICKERS  # noqa: E402
from tools.check_universal_ticker_lock import (  # noqa: E402
    LOCKED_TICKER_LITERALS,
    is_production_python,
)

_DESERIALIZATION_CALLS = {
    ("pickle", "load"),
    ("pickle", "loads"),
    ("joblib", "load"),
    ("torch", "load"),
    ("xgb", "Booster"),
}
_ROUTE_RE = re.compile(r'@app\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)')
_INSERT_RE = re.compile(r'INSERT\s+INTO\s+([`"\[]?)(\w+)\1', re.I)
_CARD_ID_RE = re.compile(r'id\s*=\s*["\']([^"\']+)["\']', re.I)
_HORIZON_SLUGS = tuple(ML_HORIZON_SLUGS)


def _git_tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=True,
    ).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _iter_production_py() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for rel in _git_tracked():
        if not is_production_python(rel):
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            rows.append((rel, p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return rows


def _scan_routes() -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    for rel, src in _iter_production_py():
        if rel != "server.py" and "/server" not in rel:
            continue
        for m in _ROUTE_RE.finditer(src):
            routes.append({"method": m.group(1).upper(), "path": m.group(2), "file": rel})
    return sorted(routes, key=lambda r: (r["path"], r["method"]))


def _scan_writers() -> list[dict[str, str]]:
    writers: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for rel, src in _iter_production_py():
        for m in _INSERT_RE.finditer(src):
            table = m.group(2)
            key = (rel, table)
            if key in seen:
                continue
            seen.add(key)
            writers.append({"file": rel, "table": table})
    return sorted(writers, key=lambda w: (w["table"], w["file"]))


def _scan_loaders() -> list[dict[str, str]]:
    loaders: list[dict[str, str]] = []
    for rel, src in _iter_production_py():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                pair = (f.value.id, f.attr)
                if pair in _DESERIALIZATION_CALLS or (
                    f.value.id == "pickle" and f.attr in ("load", "loads")
                ):
                    loaders.append(
                        {
                            "file": rel,
                            "line": str(node.lineno),
                            "call": f"{f.value.id}.{f.attr}",
                        }
                    )
    return sorted(loaders, key=lambda x: (x["file"], int(x["line"])))


def _scan_ui_cards() -> list[str]:
    cards: set[str] = set()
    for rel in _git_tracked():
        rp = rel.replace("\\", "/")
        if not (rp.startswith("static/") or rp.startswith("templates/")):
            continue
        if not rp.endswith((".html", ".js")):
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in _CARD_ID_RE.finditer(text):
            cid = m.group(1)
            if "card" in cid.lower() or cid.startswith("tf-"):
                cards.add(cid)
    return sorted(cards)


def build_inventory() -> dict:
    tickers = {
        "training_anchors": list(TRAINING_ANCHOR_TICKERS),
        "locked_literals": sorted(LOCKED_TICKER_LITERALS),
        "ticker_like_pattern": r"^[A-Z]{1,5}$|^\$[A-Z]{1,5}$",
    }
    horizons = {
        "canonical_slugs": list(_HORIZON_SLUGS),
        "source": "ml_horizon.ML_HORIZON_SLUGS",
    }
    models = {
        "full_stack_layers": list(FULL_STACK_MODEL_LAYERS),
        "source": "governed_stack_contract.FULL_STACK_MODEL_LAYERS",
    }
    runtime_classes = [
        "full",
        "reduced",
        "degraded",
        "fail_closed",
        "quote_only",
        "not_applicable",
    ]
    payload = {
        "schema_version": 1,
        "artifact": "governance/artifacts/universal_repository_inventory.json",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "regen_command": "python tools/build_universal_repository_inventory.py",
        "tickers": tickers,
        "horizons": horizons,
        "models": models,
        "runtime_classes": runtime_classes,
        "routes": _scan_routes(),
        "persistence_writers": _scan_writers(),
        "model_loaders": _scan_loaders(),
        "ui_card_ids": _scan_ui_cards(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["content_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload


def main() -> int:
    doc = build_inventory()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(
        f"universal_repository_inventory: wrote {OUT.relative_to(ROOT)} "
        f"routes={len(doc['routes'])} writers={len(doc['persistence_writers'])} "
        f"loaders={len(doc['model_loaders'])} cards={len(doc['ui_card_ids'])} "
        f"sha256={doc['content_sha256'][:16]}..."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
