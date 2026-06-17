"""REPO_SWEEP error-propagation baseline guards (bare except + silent pass)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path


_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__", "tests"}
)

# Repo-wide silent ``except Exception: pass`` after sweep #3 (production tree).
_BASELINE_SILENT_EXCEPTION_PASS = 0

_BARE_EXCEPT = re.compile(r"^\s*except\s*:\s*", re.MULTILINE)
_SILENT_PASS = re.compile(
    r"except\s+Exception\s*:\s*(?:\n\s*)+pass\s*(?:\n|$)",
    re.MULTILINE,
)

# Decision pipeline modules: zero tolerance for ``except Exception: pass`` (rule #25).
_CRITICAL_SILENT_PASS_FILES = frozenset(
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
        "server.py",
        "ml_scheduler.py",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iter_production_py(root: Path):
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield path, rel


def _scan_patterns() -> tuple[list[str], list[str], dict[str, int]]:
    root = _repo_root()
    bare: list[str] = []
    silent: list[str] = []
    per_file: dict[str, int] = {}
    for path, rel in _iter_production_py(root):
        src = path.read_text(encoding="utf-8")
        rel_s = str(rel).replace("\\", "/")
        for m in _BARE_EXCEPT.finditer(src):
            line = src[: m.start()].count("\n") + 1
            bare.append(f"{rel_s}:{line}")
        for m in _SILENT_PASS.finditer(src):
            line = src[: m.start()].count("\n") + 1
            silent.append(f"{rel_s}:{line}")
            per_file[rel_s] = per_file.get(rel_s, 0) + 1
    return bare, silent, per_file


def test_no_bare_except_in_production_tree():
    bare, _, _ = _scan_patterns()
    assert not bare, f"bare except: clauses remain: {bare}"


def test_no_silent_exception_pass_in_production_tree():
    _, silent, per_file = _scan_patterns()
    assert len(silent) == _BASELINE_SILENT_EXCEPTION_PASS, (
        f"silent except Exception: pass count {len(silent)} != baseline {_BASELINE_SILENT_EXCEPTION_PASS}; "
        f"hits: {silent[:30]}; per_file={per_file}"
    )


def test_critical_paths_have_no_silent_exception_pass():
    _, silent, _ = _scan_patterns()
    critical_hits = [s for s in silent if s.split(":")[0] in _CRITICAL_SILENT_PASS_FILES]
    assert not critical_hits, critical_hits


def test_error_propagation_audit_artifact_exists():
    audit = _repo_root() / "governance" / "audits" / "repo_sweep_error_propagation_v1_20260520.json"
    assert audit.is_file(), "governance audit artifact missing"


def test_audit_json_class_c_fixed_count_matches_array():
    audit_path = _repo_root() / "governance" / "audits" / "repo_sweep_error_propagation_v1_20260520.json"
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    entries = payload.get("class_c_fixed") or []
    summary = payload.get("summary") or {}
    count = summary.get("class_c_fixed_count")
    assert count == len(entries), (
        f"summary.class_c_fixed_count={count} != len(class_c_fixed)={len(entries)}"
    )


def test_error_propagation_audit_v2_artifact_exists():
    audit = _repo_root() / "governance" / "audits" / "repo_sweep_error_propagation_v2_20260518.json"
    assert audit.is_file(), "governance sweep #2 audit artifact missing"


def test_audit_v2_json_class_c_fixed_count_matches_array():
    audit_path = _repo_root() / "governance" / "audits" / "repo_sweep_error_propagation_v2_20260518.json"
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    entries = payload.get("class_c_fixed") or []
    summary = payload.get("summary") or {}
    count = summary.get("class_c_fixed_count")
    assert count == len(entries), (
        f"v2 summary.class_c_fixed_count={count} != len(class_c_fixed)={len(entries)}"
    )
    assert summary.get("silent_exception_pass_after") == 27


def test_error_propagation_audit_v3_artifact_exists():
    audit = _repo_root() / "governance" / "audits" / "repo_sweep_error_propagation_v3_20260520.json"
    assert audit.is_file(), "governance sweep #3 audit artifact missing"


def test_audit_v3_json_class_c_fixed_count_matches_array():
    audit_path = _repo_root() / "governance" / "audits" / "repo_sweep_error_propagation_v3_20260520.json"
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    entries = payload.get("class_c_fixed") or []
    summary = payload.get("summary") or {}
    count = summary.get("class_c_fixed_count")
    assert count == len(entries) == 27
    assert summary.get("silent_exception_pass_after") == _BASELINE_SILENT_EXCEPTION_PASS


def test_ml_predict_arch_state_probe_exception_falls_through_not_nameerror(
    tmp_path, monkeypatch, caplog
):
    """SWEEP-EP-28: arch_state probe must log via module ``logger``, not undefined ``log``."""
    import ml_predict as mp

    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "0")
    models = tmp_path / "models"
    models.mkdir()
    arch = models / "arch_state.json"
    arch.write_text("{not-json", encoding="utf-8")
    ticker = "EP28"
    hz = mp.get_ml_infer_horizon_slug()
    parallel = models / "parallel" / ticker
    parallel.mkdir(parents=True)
    (parallel / f"xgb_{ticker}_{hz}.pkl").write_bytes(b"\x00")

    monkeypatch.setattr(mp, "MODEL_DIR", models)
    monkeypatch.setattr(mp, "ARCH_STATE_PATH", arch)

    caplog.set_level(logging.DEBUG, logger=mp.logger.name)
    result = mp._model_dir_for_ticker(ticker)

    assert result == parallel
    assert "active model dir probe" in caplog.text


def test_normalized_training_sync_debounce_cancel_falls_through_not_nameerror(
    tmp_path, caplog
):
    """Gap-audit regression (parent fix @ 61b60f1): the debounce-timer cancel exception
    handler must log via the module ``_log``, not an undefined ``log`` (sweep3 generator
    blindly emitted ``log.debug`` for every site).
    """
    import normalized_training_sync as nts

    class _FakeTimer:
        def cancel(self):
            raise RuntimeError("forced cancel failure for regression test")

    # Seed the global debounce slot so schedule_debounced_normalized_refresh
    # exercises the cancel() exception branch.
    prior = nts._debounce_timer
    nts._debounce_timer = _FakeTimer()  # type: ignore[assignment]
    try:
        caplog.set_level(logging.DEBUG, logger=nts._log.name)
        # delay_s large so the new timer never fires during the test
        nts.schedule_debounced_normalized_refresh(tmp_path / "no_such.db", delay_s=3600.0)
        assert "debounce timer cancel" in caplog.text
    finally:
        # Cancel the new real timer scheduled by the call above
        t = nts._debounce_timer
        if t is not None and not isinstance(t, _FakeTimer):
            try:
                t.cancel()
            except Exception:
                pass
        nts._debounce_timer = prior
