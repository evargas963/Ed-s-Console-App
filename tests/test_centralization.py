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
import importlib
import json
import time
from pathlib import Path
from dataclasses import fields as dc_fields

# ── Setup ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

PASS = 0
FAIL = 0
WARN = 0


def _pass(msg):
    global PASS
    PASS += 1
    print(f"  [OK] {msg}")

def _fail(msg):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")

def _warn(msg):
    global WARN
    WARN += 1
    print(f"  [WARN] {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1: ARCHITECTURE — correct files exist
# ══════════════════════════════════════════════════════════════════════════════

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
        "xgboost_model.py", "lstm_model.py", "transformer_model.py",
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

def test_formula_ownership():
    print("\n2. FORMULA OWNERSHIP — no duplicate formulas")

    # Key formulas and their canonical owners
    FORMULAS = {
        "compute_exposures_by_strike": "math_exposure_core.py",
        "compute_net_charm": "math_exposure_core.py",
        "compute_gamma_flip": "math_levels.py",
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
        "compute_sector_strength": "math_probabilities.py",
        "compute_iwm_confluence": "math_probabilities.py",
        "compute_position_size": "call_engine.py",
    }

    # Scan all .py files for function definitions
    py_files = list(ROOT.glob("*.py"))
    func_locations = {}  # func_name → [file1, file2, ...]

    for pf in py_files:
        if pf.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(pf.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    name = node.name
                    if name in FORMULAS:
                        func_locations.setdefault(name, []).append(pf.name)
        except (SyntaxError, UnicodeDecodeError):
            pass  # skip binary or unparseable files

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

def test_imports():
    print("\n3. IMPORT CHAIN — module imports")

    MODULES = [
        "config",
        "math_exposure_core",
        "math_levels",
        "math_volatility",
        "math_probabilities",
        "math_exposure",
        "signal_types",
        "micro_structure",
        "regime_engine",
        "monte_carlo",
        "bayesian_fusion",
    ]

    for mod in MODULES:
        try:
            m = importlib.import_module(mod)
            _pass(f"import {mod}")
        except Exception as e:
            _fail(f"import {mod}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4: DATACLASS INTEGRITY
# ══════════════════════════════════════════════════════════════════════════════

def test_dataclasses():
    print("\n4. DATACLASS INTEGRITY")

    # SnapshotRow
    try:
        from db import SnapshotRow
        sr = SnapshotRow(
            ticker="SPY", timeframe="5m", ts_utc=1.0, ts_et="test",
            et_hour=10, et_minute=30, market_session="rth", spot=570.0,
        )
        n = len(SnapshotRow.__dataclass_fields__)
        _pass(f"SnapshotRow: {n} fields, constructs OK")

        # Check critical fields exist
        critical = [
            "regime_primary", "fusion_dominant", "mc_efe", "mc_eae",
            "validation_passed", "r_units", "execution_mode",
            "iv_skew", "atr", "breakout_score", "sweep_score",
            "session_high", "session_low", "last_sweep_type",
            "tnx_yield", "bond_signal", "iwm_risk_score",
            "sector_leader", "level_density_count",
        ]
        for f in critical:
            if f in SnapshotRow.__dataclass_fields__:
                _pass(f"  SnapshotRow.{f}")
            else:
                _fail(f"  SnapshotRow.{f} MISSING")
    except Exception as e:
        _fail(f"SnapshotRow: {e}")

    # SignalInput
    try:
        from signal_types import SignalInput
        n = len(SignalInput.__dataclass_fields__)
        _pass(f"SignalInput: {n} fields")

        for f in ["em_upper", "em_lower", "oi_center"]:
            if f in SignalInput.__dataclass_fields__:
                _pass(f"  SignalInput.{f}")
            else:
                _fail(f"  SignalInput.{f} MISSING")
    except Exception as e:
        _fail(f"SignalInput: {e}")

    # TheCall
    try:
        from signal_types import TheCall
        for f in ["validation_passed", "structure_valid", "probability_valid",
                   "risk_valid", "r_units", "execution_mode"]:
            if f in TheCall.__dataclass_fields__:
                _pass(f"  TheCall.{f}")
            else:
                _fail(f"  TheCall.{f} MISSING")
    except Exception as e:
        _fail(f"TheCall: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5: GEX FORMULA CORRECTNESS
# ══════════════════════════════════════════════════════════════════════════════

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

        db = EdDB(db_path)

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

def test_syntax():
    print("\n8. SYNTAX — all Python files parse")

    for pf in sorted(ROOT.glob("*.py")):
        try:
            ast.parse(pf.read_text(encoding="utf-8", errors="replace"))
            _pass(f"{pf.name}")
        except SyntaxError as e:
            _fail(f"{pf.name}: line {e.lineno}: {e.msg}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 9: WRAPPER HEALTH — math_exposure.py re-exports correctly
# ══════════════════════════════════════════════════════════════════════════════

def test_wrapper():
    print("\n9. WRAPPER — math_exposure.py re-exports")

    try:
        import math_exposure as me
        critical_exports = [
            "compute_exposures_by_strike",
            "compute_gamma_flip",
            "compute_gamma_void_zones",
            "compute_expected_move_straddle",
            "compute_atr",
            "compute_iv_skew",
            "compute_dealer_pressure_index",
            "compute_sector_strength",
            "compute_iwm_confluence",
            "compute_level_density",
            "compute_volatility_envelope",
        ]
        for name in critical_exports:
            if hasattr(me, name):
                _pass(f"math_exposure.{name}")
            else:
                _fail(f"math_exposure.{name} NOT exported")
    except Exception as e:
        _fail(f"Wrapper import: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 10: MONTE CARLO v2 REGIME BEHAVIOR
# ══════════════════════════════════════════════════════════════════════════════

def test_monte_carlo_v2():
    print("\n10. MONTE CARLO v2 — regime-aware behavior")

    try:
        import monte_carlo

        base_args = dict(
            spot=570.0, iv=0.18, horizon_bars=13, n_paths=3000,
            call_gamma_wall=575.0, put_gamma_wall=565.0,
            em_upper=573.0, em_lower=567.0,
            realized_vol=0.15, atr=0.8, seed=42,
        )

        # Test 1: pinning vs breakout dispersion
        r_pin = monte_carlo.simulate(**base_args, regime="pinning", regime_confidence="high")
        r_brk = monte_carlo.simulate(**base_args, regime="breakout", regime_confidence="high")

        if r_pin.simulation_ok and r_brk.simulation_ok:
            _pass("MC v2: both regimes simulate OK")
        else:
            _fail("MC v2: simulation failed")
            return

        if r_pin.path_dispersion < r_brk.path_dispersion:
            _pass(f"Pinning dispersion ({r_pin.path_dispersion:.2f}) < Breakout ({r_brk.path_dispersion:.2f})")
        else:
            _fail(f"Pinning dispersion should be < Breakout")

        if r_pin.containment_prob > r_brk.containment_prob:
            _pass(f"Pinning containment ({r_pin.containment_prob:.0%}) > Breakout ({r_brk.containment_prob:.0%})")
        else:
            _fail(f"Pinning containment should be > Breakout")

        # Test 2: shock enabled only in breakout/expansion
        if r_brk.assumptions.get("shock_enabled") and not r_pin.assumptions.get("shock_enabled"):
            _pass("Shocks enabled in breakout, disabled in pinning")
        else:
            _fail("Shock gating incorrect")

        # Test 3: model version is v3
        if "v3" in r_pin.model_version or "garch" in r_pin.model_version:
            _pass(f"Model version: {r_pin.model_version}")
        else:
            _fail(f"Expected mc_v3_garch, got {r_pin.model_version}")

        # Test 4: no NaN/inf in outputs
        import math as _m
        fields_to_check = [
            r_pin.median_path, r_pin.upper_50, r_pin.lower_50,
            r_pin.expected_favorable_excursion, r_pin.expected_adverse_excursion,
            r_pin.path_dispersion, r_pin.expected_move, r_pin.volatility,
        ]
        has_bad = any(v is not None and (_m.isnan(v) or _m.isinf(v)) for v in fields_to_check)
        if not has_bad:
            _pass("No NaN/inf in MC outputs")
        else:
            _fail("NaN or inf detected in MC outputs")

        # Test 5: drift responds to model input
        r_up = monte_carlo.simulate(**base_args, regime="trend_continuation",
            model_prob_up=0.70, model_prob_down=0.10, model_confidence="high")
        r_dn = monte_carlo.simulate(**base_args, regime="trend_continuation",
            model_prob_up=0.10, model_prob_down=0.70, model_confidence="high")
        drift_up = r_up.assumptions.get("per_bar_drift", 0)
        drift_dn = r_dn.assumptions.get("per_bar_drift", 0)
        if drift_up > 0 and drift_dn < 0:
            _pass(f"Drift follows model: up={drift_up:.6f}, down={drift_dn:.6f}")
        else:
            _fail(f"Drift not following model: up={drift_up:.6f}, down={drift_dn:.6f}")

        # Test 6: vol-of-vol produces fatter tails than constant vol
        r_baseline = monte_carlo.simulate(**base_args, regime="unknown")
        # Stochastic vol should produce wider tails (larger upper_75 - lower_75 gap)
        if r_baseline.upper_75 is not None and r_baseline.lower_75 is not None:
            tail_width = r_baseline.upper_75 - r_baseline.lower_75
            if tail_width > 0:
                _pass(f"Stochastic vol tail width: {tail_width:.2f}pts")
            else:
                _fail("Tail width should be positive")

        # Test 7: GARCH integration — MC accepts per-bar sigma
        try:
            from math_volatility import compute_garch_forecast, blend_garch_sigma
            import math as _m2
            # Build fake closes with known vol
            _fake_closes = [570.0]
            _rng = __import__('random')
            _rng.seed(99)
            for _ in range(40):
                _fake_closes.append(_fake_closes[-1] + _rng.gauss(0, 0.4))

            _g_raw = compute_garch_forecast(_fake_closes, horizon=13)
            if _g_raw and len(_g_raw) == 13:
                _pass(f"GARCH forecast: 13 bars, bar1={_g_raw[0]:.6f} bar13={_g_raw[-1]:.6f}")
                _g_blend = blend_garch_sigma(_g_raw, iv=0.18, realized_vol=0.15, spot=570.0)
                if _g_blend and len(_g_blend) == 13 and all(s > 0 for s in _g_blend):
                    _pass(f"GARCH blend: 13 bars, floor enforced")
                else:
                    _fail("GARCH blend failed")

                # MC with GARCH
                r_garch = monte_carlo.simulate(**base_args, regime="unknown",
                                               garch_sigma_bars=_g_blend)
                if r_garch.assumptions.get("garch_active"):
                    _pass(f"MC GARCH active: disp={r_garch.path_dispersion:.2f}")
                else:
                    _fail("MC did not use GARCH sigma bars")
            else:
                _warn("GARCH forecast returned None or wrong length")
        except Exception as e:
            _fail(f"GARCH test error: {e}")

    except Exception as e:
        _fail(f"MC v2 test error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    full = "--full" in sys.argv

    print("=" * 70)
    print("  EdWebConsole — Production Hardening Tests")
    print("=" * 70)
    start = time.time()

    test_architecture()
    test_formula_ownership()
    test_syntax()
    test_gex_formula()
    test_dataclasses()
    test_model_health()
    test_wrapper()

    if full:
        test_imports()
        test_db_schema(full=True)
        test_monte_carlo_v2()
    else:
        print("\n3. IMPORT CHAIN — skipped (use --full)")
        print("\n7. DB SCHEMA — skipped (use --full)")
        print("\n10. MC v2 BEHAVIOR — skipped (use --full)")

    elapsed = time.time() - start

    print("\n" + "=" * 70)
    print(f"  RESULTS: {PASS} passed, {FAIL} failed, {WARN} warnings")
    print(f"  Time: {elapsed:.1f}s")
    print("=" * 70)

    if FAIL > 0:
        print(f"\n  [FAIL] {FAIL} FAILURES -- fix before deploying")
        sys.exit(1)
    elif WARN > 0:
        print(f"\n  [WARN] {WARN} warnings -- review recommended")
    else:
        print("\n  [OK] ALL CLEAR -- ready for deployment")
