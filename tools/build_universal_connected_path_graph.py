#!/usr/bin/env python3
"""Build universal connected-path graph (UNIVERSAL_FIX_IMPACT_GATE_V1).

Hybrid graph: AST import/call edges plus governed edges where static derivation
is unreliable. Regenerates governance/artifacts/universal_connected_path_graph.json.

Regen: python tools/build_universal_connected_path_graph.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "governance" / "artifacts" / "universal_connected_path_graph.json"
GOVERNED = ROOT / "governance" / "artifacts" / "universal_connected_path_governed_edges.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_universal_ticker_lock import is_production_python  # noqa: E402

_MONEY_PATH = frozenset(
    {
        "signals.py",
        "call_engine.py",
        "prediction_engine.py",
        "realized_contract_eval.py",
        "bayesian_fusion.py",
        "mc_fusion_adjustment.py",
        "market_state.py",
        "live_decision_bundle.py",
        "features/signal_layer_v1.py",
        "features/inference_snapshot.py",
        "features/fusion_policy_contract.py",
        "multi_horizon_decision.py",
        "ml_predict.py",
        "db.py",
        "server.py",
        "execution_identity.py",
        "active_bundle_contract.py",
        "calibration/writer.py",
    }
)


def _git_tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=True,
    ).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _mod_to_path(mod: str) -> str | None:
    """Map import module name to repo-relative path if tracked."""
    parts = mod.split(".")
    for n in range(len(parts), 0, -1):
        cand = "/".join(parts[:n]) + ".py"
        if (ROOT / cand).is_file():
            return cand.replace("\\", "/")
        cand_pkg = "/".join(parts[:n]) + "/__init__.py"
        if (ROOT / cand_pkg).is_file():
            return cand_pkg.replace("\\", "/")
    return None


def _scan_import_edges() -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for rel in _git_tracked():
        if not rel.endswith(".py") or not is_production_python(rel):
            continue
        p = ROOT / rel
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    tgt = _mod_to_path(alias.name)
                    if tgt and tgt != rel:
                        key = (rel, tgt, "import")
                        if key not in seen:
                            seen.add(key)
                            edges.append(
                                {
                                    "source": rel,
                                    "target": tgt,
                                    "kind": "import",
                                    "discovery": "automatic",
                                }
                            )
            elif isinstance(node, ast.ImportFrom) and node.module:
                tgt = _mod_to_path(node.module)
                if tgt and tgt != rel:
                    key = (rel, tgt, "import_from")
                    if key not in seen:
                        seen.add(key)
                        edges.append(
                            {
                                "source": rel,
                                "target": tgt,
                                "kind": "import_from",
                                "discovery": "automatic",
                            }
                        )
    return sorted(edges, key=lambda e: (e["source"], e["target"], e["kind"]))


def _load_governed_edges() -> list[dict[str, str]]:
    if not GOVERNED.is_file():
        return []
    doc = json.loads(GOVERNED.read_text(encoding="utf-8"))
    out: list[dict[str, str]] = []
    for row in doc.get("edges") or []:
        out.append(
            {
                "source": str(row["source"]),
                "target": str(row["target"]),
                "kind": str(row.get("kind") or "governed"),
                "discovery": "governed",
                "rationale": str(row.get("rationale") or ""),
            }
        )
    return out


def build_graph() -> dict:
    auto = _scan_import_edges()
    governed = _load_governed_edges()
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for e in auto + governed:
        key = (e["source"], e["target"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(e)
    merged.sort(key=lambda e: (e["source"], e["target"], e["kind"]))
    payload = {
        "schema_version": 1,
        "artifact": "governance/artifacts/universal_connected_path_graph.json",
        "regen_command": "python tools/build_universal_connected_path_graph.py",
        "money_path_modules": sorted(_MONEY_PATH),
        "edge_count": len(merged),
        "edges": merged,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["content_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload


def main() -> int:
    doc = build_graph()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(
        f"universal_connected_path_graph: wrote {OUT.relative_to(ROOT)} "
        f"edges={doc['edge_count']} sha256={doc['content_sha256'][:16]}..."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
