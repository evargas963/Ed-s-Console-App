"""Layer 5 training_cache.py fail-closed fingerprint and cache-load guards."""

from __future__ import annotations


# ── ML-PIPE-V2 Phase 6: split entry-point registry (governed splitters only) ──


def test_no_ungoverned_random_splitters_anywhere_in_production_code():
    """Measured 2026-07-11: zero sklearn-style random/shuffled splitters exist in
    the repo — the temporal-split surface is exclusively the governed
    implementations (calibration.v2_a1_calibration.WalkForwardSplit,
    training_cache.expanding_window_oof_folds, training_cache walk-forward).
    This registry lock keeps it that way: ANY new random K-fold/shuffle split on
    time-series data fails here; a legitimate governed addition must be added to
    the ALLOWED registry below in the same reviewed diff."""
    import ast
    import io as _io
    import os as _os

    TOKENS = {
        "train_test_split", "KFold", "StratifiedKFold", "TimeSeriesSplit",
        "GroupKFold", "ShuffleSplit", "StratifiedShuffleSplit",
    }
    ALLOWED: set[tuple[str, str]] = set()  # (path, token) — empty by measurement
    SKIP_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv", "models",
        "data", "reports", ".github", "static", "templates", "docs",
        "tests",  # tests may construct adversarial splitters deliberately
    }
    violations: list[str] = []
    for root, dirs, files in _os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            rel = _os.path.join(root, fn).replace("\\", "/")[2:]
            try:
                src = _io.open(rel, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if not any(t in src for t in TOKENS):
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                name = None
                if isinstance(node, ast.Name) and node.id in TOKENS:
                    name = node.id
                elif isinstance(node, ast.Attribute) and node.attr in TOKENS:
                    name = node.attr
                if name and (rel, name) not in ALLOWED:
                    violations.append(f"{rel}:{node.lineno}: ungoverned splitter {name}")
    assert violations == [], (
        "ungoverned split entry point(s) — temporal data requires the governed "
        f"walk-forward/purged implementations: {violations}"
    )
