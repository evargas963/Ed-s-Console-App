"""
test_centralization.py — Phase 8 Production Hardening
=====================================================

Guardrail tests for the EdWebConsole trading engine.
Run before AND after every change to detect drift.

Usage:
    python test_centralization.py          ← quick tests
    python test_centralization.py --full   ← full suite including DB + import chain

Tests:
    1. Architecture — correct files exist, no orphans
    2. Formula ownership — no duplicate formulas across modules
    3. Import chain — all modules import cleanly
    4. Dataclass integrity — SnapshotRow, MarketState, SignalInput fields
    5. Payload stability — all expected API fields present
    6. Model health — checkpoint files valid
    7. DB schema — migration columns match SnapshotRow
"""
from __future__ import annotations

import sys
import os
# Windows console: avoid UnicodeEncodeError for emoji/arrows
if sys.stdout.encoding and "cp1252" in sys.stdout.encoding.lower():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ast
import functools
import json
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

PASS = 0
FAIL = 0
WARN = 0

#: Failures recorded by the current test, asserted empty by @fails_closed below —
#: without it these checks only printed and every test passed unconditionally (587 lines,
#: 0 asserts). A guardrail that cannot fail is not a guardrail.
FAILURES: list[str] = []


def fails_closed(fn):
    """Turn recorded `_fail(...)` messages into a real test failure.

    Every check below reports through `_fail`, which only printed. Without this the whole
    file passed unconditionally (587 lines, 0 asserts). Applied per test so violations
    surface as a failure in the test itself, not as a teardown error.
    """
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        FAILURES.clear()
        result = fn(*a, **kw)
        sep = "\n  - "
        assert not FAILURES, "centralization violations:" + sep + sep.join(FAILURES)
        return result
    return wrapper


def _pass(msg):
    global PASS
    PASS += 1
    print(f"  [OK] {msg}")

def _fail(msg):
    global FAIL
    FAIL += 1
    FAILURES.append(str(msg))
    print(f"  [FAIL] {msg}")

def _warn(msg):
    global WARN
    WARN += 1
    print(f"  [WARN] {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1: ARCHITECTURE — correct files exist
# ══════════════════════════════════════════════════════════════════════════════

@fails_closed
def test_architecture():
    print("\n1. ARCHITECTURE — file existence")

    REQUIRED = [
        # Core pipeline
        "server.py", "signals.py", "signal_types.py",
        "rules_engine.py", "prediction_engine.py", "call_engine.py",
        "market_state.py",
        # Math layer
        "math_exposure.py", "math_exposure_core.py",
        "math_levels.py", "math_volatility.py", "math_probabilities.py",
        # Model layer
        "regime_engine.py", "bayesian_fusion.py",
        "lstm_model.py",
        "monte_carlo.py",
        # Data layer
        "db.py", "micro_structure.py", "market_context.py",
        # Training
        "ml_train.py", "ml_predict.py", "lstm_data.py", "transformer_train.py",
        "training_provenance.py", "verify_active_models.py",
        # Support
        "config.py", "schwab_client.py",
        # Frontend
        "index.html",
    ]

    for f in REQUIRED:
        # index.html might be in templates/ or static/
        candidates = [ROOT / f]
        if f == "index.html":
            candidates += [ROOT / "templates" / f, ROOT / "static" / f]
        if any(c.exists() for c in candidates):
            _pass(f)
        else:
            _fail(f"{f} MISSING")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2: FORMULA OWNERSHIP — no duplicates
# ══════════════════════════════════════════════════════════════════════════════

@fails_closed
def test_formula_ownership(repo_index):
    print("\n2. FORMULA OWNERSHIP — no duplicate formulas")

    # Key formulas and their canonical owners
    FORMULAS = {
        "compute_exposures_by_strike": "math_exposure_core.py",
        "compute_net_charm": "math_exposure_core.py",
        "compute_gamma_flip_v2": "math_levels.py",
        "compute_hvl": "math_levels.py",
        "compute_max_pain": "math_levels.py",
        "compute_gamma_void_zones": "math_levels.py",
        "compute_level_density": "math_levels.py",
        "compute_expected_move_straddle": "math_volatility.py",
        "compute_expected_move_iv": "math_volatility.py",
        "compute_atr": "math_volatility.py",
        "compute_iv_skew": "math_volatility.py",
        "compute_realized_vol": "math_volatility.py",
        "compute_iv_rank": "math_volatility.py",
        "compute_iv_percentile": "math_volatility.py",
        "compute_volatility_envelope": "math_volatility.py",
        "compute_dealer_pressure_index": "math_probabilities.py",
        "compute_hedging_flow_score": "math_probabilities.py",
        "compute_gamma_gradient": "math_probabilities.py",
        "compute_breakout_score": "math_probabilities.py",
        "compute_pin_score": "math_probabilities.py",
        "compute_vol_expansion_signal": "math_probabilities.py",
        "compute_sweep_score": "math_probabilities.py",
        "compute_position_size": "call_engine.py",
    }

    # TEST_SYSTEM_REHAB_V2: was an independent ROOT.glob("*.py") + per-file
    # read+parse -- now sources from the shared `repo_index` corpus, filtered to
    # top-level (root-directory) modules only, matching the original non-recursive
    # glob's scope exactly.
    func_locations = {}  # func_name → [file1, file2, ...]

    for rel, _text, tree in repo_index.items():
        if len(rel.parts) != 1 or rel.name.startswith("test_"):
            continue
        if tree is None:
            continue  # unparseable, same as the original except clause
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                name = node.name
                if name in FORMULAS:
                    func_locations.setdefault(name, []).append(rel.name)

    for func, expected_owner in FORMULAS.items():
        locs = func_locations.get(func, [])
        if not locs:
            _warn(f"{func} not found anywhere")
        elif locs == [expected_owner]:
            _pass(f"{func} -> {expected_owner}")
        elif expected_owner in locs and len(locs) > 1:
            others = [f for f in locs if f != expected_owner]
            # Wrappers re-exporting via `from X import *` don't count as duplicates
            # Only flag if the function body is actually defined (not just imported)
            _warn(f"{func} in {expected_owner} but also in {others} (check if re-export)")
        else:
            _fail(f"{func} expected in {expected_owner} but found in {locs}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3: IMPORT CHAIN — all modules import cleanly
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# TEST 4: DATACLASS INTEGRITY
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# TEST 5: GEX FORMULA CORRECTNESS
# ══════════════════════════════════════════════════════════════════════════════

@fails_closed
def test_gex_formula():
    print("\n5. GEX FORMULA — Spot² check")

    try:
        with open(ROOT / "math_exposure_core.py", encoding="utf-8") as f:
            src = f.read()

        # The correct formula has spt * spt * 0.01
        if "spt * spt * 0.01" in src:
            _pass("GEX formula: gamma * oi * mult * spt * spt * 0.01 (Spot² correct)")
        elif "spt * 0.01" in src and "spt * spt" not in src:
            _fail("GEX formula: only spt * 0.01 — MISSING one factor of Spot")
        else:
            _warn("GEX formula: could not confirm pattern")
    except Exception as e:
        _fail(f"GEX formula check: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6: MODEL HEALTH
# ══════════════════════════════════════════════════════════════════════════════

@fails_closed
def test_model_health():
    print("\n6. MODEL HEALTH — per-ticker 1c checkpoint files (active/SPY)")

    try:
        from training_provenance import is_provenance_compliant, load_provenance
    except ImportError:
        is_provenance_compliant = load_provenance = None

    models_dir = ROOT / "models"
    active_dir = models_dir / "active" / "SPY"

    checks = [
        (active_dir / "xgb_SPY_1c.pkl", active_dir / "xgb_SPY_1c_meta.json"),
        (active_dir / "lstm_SPY_1c.pt", active_dir / "lstm_SPY_1c_meta.json"),
        (active_dir / "transformer_SPY_1c.pt", active_dir / "transformer_SPY_1c_meta.json"),
    ]

    for mp, meta_path in checks:
        if mp.exists():
            size_kb = mp.stat().st_size / 1024
            _pass(f"{mp.name}: {size_kb:.0f}KB")

            if meta_path and meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                    edge = meta.get("edge_pp", meta.get("val_accuracy", meta.get("train_accuracy", 0)))
                    edge_pp = float(edge) * 100 if isinstance(edge, (int, float)) and 0 < edge < 1 else float(edge or 0)
                    # Governance-aware status: LIVE = compliant, NON-COMPLIANT = exists but not compliant
                    if load_provenance and is_provenance_compliant:
                        prov = load_provenance(meta_path)
                        status = "LIVE" if is_provenance_compliant(prov) else "NON-COMPLIANT"
                        _pass(f"  {meta_path.name}: {status}, edge={edge_pp:+.1f}pp")
                        if status == "NON-COMPLIANT":
                            _warn(f"  {meta_path.name}: non-compliant (run ml_scheduler --force-retrain)")
                    else:
                        _pass(f"  {meta_path.name}: edge={edge_pp:+.1f}pp")
                except Exception as e:
                    _warn(f"  {meta_path.name}: parse error: {e}")
            elif meta_path:
                _warn(f"  {meta_path.name}: not found")
        else:
            _warn(f"{mp.name}: not trained yet")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 7: DB SCHEMA ALIGNMENT
# ══════════════════════════════════════════════════════════════════════════════

@fails_closed
def test_db_schema(full=False):
    print("\n7. DB SCHEMA — migration alignment")

    if not full:
        _warn("Skipped (use --full to test DB)")
        return

    try:
        from db import DB_PATH as db_path, EdDB, SnapshotRow
        if not db_path.exists():
            _warn(f"DB not found at {db_path}")
            return

        EdDB(db_path)

        # Get actual DB columns
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("PRAGMA table_info(snapshots)")
        db_columns = set(row[1] for row in cursor.fetchall())
        conn.close()

        # Get dataclass fields
        dc_fields_set = set(SnapshotRow.__dataclass_fields__.keys())
        dc_fields_set.discard("snapshot_id")  # auto-generated

        # Fields in dataclass but not in DB
        missing_in_db = dc_fields_set - db_columns - {"snapshot_id", "created_at"}
        if missing_in_db:
            for f in sorted(missing_in_db):
                _warn(f"  SnapshotRow.{f} not in DB (needs migration)")
        else:
            _pass("All SnapshotRow fields present in DB")

        # Fields in DB but not in dataclass
        extra_in_db = db_columns - dc_fields_set - {"snapshot_id", "created_at"}
        if extra_in_db:
            for f in sorted(extra_in_db):
                _warn(f"  DB column '{f}' not in SnapshotRow (orphaned)")
        else:
            _pass("No orphaned DB columns")

    except Exception as e:
        _fail(f"DB schema test: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 8: SYNTAX CHECK — all .py files parse
# ══════════════════════════════════════════════════════════════════════════════

@fails_closed
def test_syntax(repo_index):
    print("\n8. SYNTAX — all Python files parse")

    # TEST_SYSTEM_REHAB_V2: was an independent ROOT.glob("*.py") + per-file
    # re-parse -- repo_index already parses every file once (tree is None on a
    # SyntaxError), so this reuses that result instead of parsing a second time.
    for rel, text, tree in sorted(repo_index.items()):
        if len(rel.parts) != 1:
            continue
        if tree is not None:
            _pass(f"{rel.name}")
        else:
            try:
                ast.parse(text)
            except SyntaxError as e:
                _fail(f"{rel.name}: line {e.lineno}: {e.msg}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 9: WRAPPER HEALTH — math_exposure.py re-exports correctly
# ══════════════════════════════════════════════════════════════════════════════

@fails_closed
def test_wrapper():
    print("\n9. WRAPPER — math_exposure.py re-exports")

    # TEST_SYSTEM_REHAB_V2 final remediation: `hasattr(me, name)` only proves SOME
    # attribute with that name exists on math_exposure -- it is satisfied identically
    # by a genuine `from math_levels import *` re-export, a locally-redefined stale
    # duplicate under the same name, or a mis-aliased import wiring the WRONG split
    # module's function in under this name (e.g. `from math_levels import
    # compute_gamma_flip_v1 as compute_gamma_flip_v2`). Object IDENTITY against the
    # actual owning split module is what "wrapper" means; presence alone is not.
    try:
        import math_exposure as me
        import math_exposure_core
        import math_levels
        import math_probabilities
        import math_volatility
        owners = {
            "math_exposure_core": math_exposure_core, "math_levels": math_levels,
            "math_volatility": math_volatility, "math_probabilities": math_probabilities,
        }
        critical_exports = [
            "compute_exposures_by_strike",
            "compute_gamma_flip_v2",
            "compute_gamma_void_zones",
            "compute_expected_move_straddle",
            "compute_atr",
            "compute_iv_skew",
            "compute_dealer_pressure_index",
            "compute_level_density",
            "compute_volatility_envelope",
        ]
        for name in critical_exports:
            wrapped = getattr(me, name, None)
            if wrapped is None:
                _fail(f"math_exposure.{name} NOT exported")
                continue
            owning = [mn for mn, m in owners.items() if getattr(m, name, None) is wrapped]
            if owning:
                _pass(f"math_exposure.{name} (identical to {owning[0]}.{name})")
            else:
                _fail(f"math_exposure.{name} is not object-identical to any split "
                     f"module's own {name} -- a locally-redefined stub or a "
                     f"mis-aliased import, not a genuine re-export")
    except Exception as e:
        _fail(f"Wrapper import: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 10: MONTE CARLO v2 REGIME BEHAVIOR
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
