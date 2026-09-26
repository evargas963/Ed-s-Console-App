"""I-01: fetch_market_context never raises; partial context on quote failure."""
from __future__ import annotations































# ── VOL_INPUT_CONTRACT 1.0.0 (lane V1) — per-cycle context + stamp parity ────

import ast as _ast
from pathlib import Path as _Path



_REPO = _Path(__file__).resolve().parent.parent












def test_canonical_signal_input_construction_lock(repo_index):
    """Money-path SignalInput construction happens only in the two canonical
    builders (market_state live stamp; replay builder). Production code must
    not bypass the vol boundary with an independent SignalInput(...)."""
    # TEST_SYSTEM_REHAB_V2: was two independent globs (_REPO.glob("*.py"),
    # (_REPO/"features").glob("*.py")) + per-file read+parse -- now sources from the
    # shared `repo_index` corpus, filtered to the same two top-level scopes.
    allowed = {"market_state.py", "features/replay_signal_input_v1.py", "signal_types.py"}
    offenders: list[str] = []
    for rel, _text, tree in repo_index.items():
        in_root = len(rel.parts) == 1
        in_features = len(rel.parts) == 2 and rel.parts[0] == "features"
        if not (in_root or in_features):
            continue
        rel_s = rel.name if in_root else f"features/{rel.name}"
        if rel_s in allowed or (in_root and rel.name.startswith("test_")):
            continue
        if tree is None:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, _ast.Name) else (
                    fn.attr if isinstance(fn, _ast.Attribute) else ""
                )
                if name == "SignalInput":
                    offenders.append(f"{rel_s}:{node.lineno}")
    assert offenders == [], f"SignalInput constructed outside canonical builders: {offenders}"
