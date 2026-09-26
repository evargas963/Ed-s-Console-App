"""STACK-WIRE-3 — call_engine + prediction_engine overlay (FIND-WIRE3-1..7)."""

from __future__ import annotations

import ast
from pathlib import Path
























def test_no_legacy_timeframe_keys_in_call_engine_consumer_source():
    root = Path(__file__).resolve().parents[1]
    src = (root / "call_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    allowed = {"15m", "60m"}
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if not isinstance(node.args[0].value, str):
            continue
        base = func.value
        if isinstance(base, ast.Name) and base.id == "_tf":
            key = node.args[0].value
            if key not in allowed:
                bad.append(key)
    assert bad == []
