"""GOV-GATE-PERF-V1 Phase 4 — adversarial proofs for the governance gate cache.

Every correctness property from the mission's required list is proven here:
identity completeness, invalidation on every dependency class, success-only
storage, interrupted/failed-run exclusion, corrupt-entry fail-closed, worktree
identity, and force-no-cache mode.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.governance_gate_cache import (
    GATE_CACHE_VERSION,
    build_key,
    cached_check,
    db_triple_identity,
    gate_cache_enabled,
)


@pytest.fixture()
def deps(tmp_path, monkeypatch):
    import tools.governance_gate_cache as gc

    monkeypatch.setattr(gc, "CACHE_DIR", tmp_path / "cache")
    # conftest force-disables the cache for the whole suite (tests must exercise
    # real compute); THIS suite tests the cache itself, so re-enable it here.
    monkeypatch.setenv("ED_GATE_CACHE_DISABLE", "")
    src = tmp_path / "checker.py"
    src.write_text("v1", encoding="utf-8")
    cfg = tmp_path / "manifest.json"
    cfg.write_text('{"a": 1}', encoding="utf-8")
    db = tmp_path / "store.db"
    db.write_text("dbdata", encoding="utf-8")
    return gc, src, cfg, db


def _key(src, cfg, db, **inv):
    k, parts = build_key(
        check_name="t",
        source_deps=[src, cfg],
        db_deps=[db],
        invocation=inv or {"mode": "m"},
    )
    return k, parts


def test_identical_inputs_produce_identical_key_and_cache_hit(deps):
    gc, src, cfg, db = deps
    k1, _ = _key(src, cfg, db)
    k2, _ = _key(src, cfg, db)
    assert k1 == k2
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return []

    common = dict(check_name="t", source_deps=[src, cfg], db_deps=[db], invocation={"mode": "m"})
    e1, p1 = cached_check(**common, compute=compute)
    e2, p2 = cached_check(**common, compute=compute)
    assert e1 == e2 == []
    assert calls["n"] == 1, "second identical run must be a cache hit"
    assert p1["cache"] == "miss" and p1["stored"] is True
    assert p2["cache"] == "hit" and "created_at" in p2


def test_checker_source_mutation_invalidates(deps):
    gc, src, cfg, db = deps
    k1, _ = _key(src, cfg, db)
    src.write_text("v2", encoding="utf-8")
    k2, _ = _key(src, cfg, db)
    assert k1 != k2


def test_governed_config_and_rule_manifest_mutation_invalidates(deps):
    gc, src, cfg, db = deps
    k1, _ = _key(src, cfg, db)
    cfg.write_text('{"a": 2}', encoding="utf-8")
    k2, _ = _key(src, cfg, db)
    assert k1 != k2


def test_db_wal_triple_mutation_invalidates(deps):
    gc, src, cfg, db = deps
    k1, _ = _key(src, cfg, db)
    wal = Path(str(db) + "-wal")
    wal.write_text("walwrite", encoding="utf-8")
    k2, _ = _key(src, cfg, db)
    assert k1 != k2, "a WAL write must invalidate (live-DB dependency)"
    assert len(db_triple_identity(db)) == 3


def test_invocation_argument_mutation_invalidates(deps):
    gc, src, cfg, db = deps
    k1, _ = _key(src, cfg, db, mode="a")
    k2, _ = _key(src, cfg, db, mode="b")
    assert k1 != k2


def test_env_and_python_and_worktree_participate_in_key(deps):
    gc, src, cfg, db = deps
    _, parts = _key(src, cfg, db)
    assert "python" in parts and parts["python"]
    assert "repo_root" in parts and parts["repo_root"]
    assert "env" in parts
    assert parts["cache_version"] == GATE_CACHE_VERSION


def test_staged_scope_mutation_invalidates_via_invocation(deps):
    gc, src, cfg, db = deps
    k1, _ = _key(src, cfg, db, staged="a.py")
    k2, _ = _key(src, cfg, db, staged="b.py")
    assert k1 != k2


def test_failed_run_is_never_cached(deps):
    gc, src, cfg, db = deps
    calls = {"n": 0}

    def failing():
        calls["n"] += 1
        return ["gate violation"]

    common = dict(check_name="t", source_deps=[src, cfg], db_deps=[db], invocation={"mode": "m"})
    e1, p1 = cached_check(**common, compute=failing)
    e2, p2 = cached_check(**common, compute=failing)
    assert e1 == e2 == ["gate violation"]
    assert calls["n"] == 2, "failures must recompute every time"
    assert p1["stored"] is False and p2["cache"] == "miss"
    assert not list((gc.CACHE_DIR).glob("*.json")) if gc.CACHE_DIR.exists() else True


def test_interrupted_run_is_never_cached(deps):
    gc, src, cfg, db = deps

    def interrupted():
        raise KeyboardInterrupt()

    common = dict(check_name="t", source_deps=[src, cfg], db_deps=[db], invocation={"mode": "m"})
    with pytest.raises(KeyboardInterrupt):
        cached_check(**common, compute=interrupted)
    calls = {"n": 0}

    def ok():
        calls["n"] += 1
        return []

    _, prov = cached_check(**common, compute=ok)
    assert prov["cache"] == "miss" and calls["n"] == 1


def test_corrupt_cache_entry_fails_closed(deps):
    gc, src, cfg, db = deps
    common = dict(check_name="t", source_deps=[src, cfg], db_deps=[db], invocation={"mode": "m"})
    calls = {"n": 0}

    def ok():
        calls["n"] += 1
        return []

    _, p1 = cached_check(**common, compute=ok)
    entry = gc.CACHE_DIR / p1["entry"]
    entry.write_text("{corrupt", encoding="utf-8")
    _, p2 = cached_check(**common, compute=ok)
    assert calls["n"] == 2
    assert p2["cache"] in ("corrupt_entry_recompute", "miss")
    _, p3 = cached_check(**common, compute=ok)
    assert p3["cache"] == "hit", "recompute must repair the corrupt entry"


def test_wrong_key_in_entry_fails_closed(deps):
    gc, src, cfg, db = deps
    common = dict(check_name="t", source_deps=[src, cfg], db_deps=[db], invocation={"mode": "m"})
    calls = {"n": 0}

    def ok():
        calls["n"] += 1
        return []

    _, p1 = cached_check(**common, compute=ok)
    entry = gc.CACHE_DIR / p1["entry"]
    doc = json.loads(entry.read_text(encoding="utf-8"))
    doc["key"] = "0" * 64  # different-worktree/foreign entry simulation
    entry.write_text(json.dumps(doc), encoding="utf-8")
    _, p2 = cached_check(**common, compute=ok)
    assert calls["n"] == 2, "an entry whose recorded key mismatches must never be reused"


def test_deleted_dependency_invalidates(deps):
    gc, src, cfg, db = deps
    k1, _ = _key(src, cfg, db)
    cfg.unlink()
    k2, parts = _key(src, cfg, db)
    assert k1 != k2
    assert any(str(v).startswith("ABSENT:") for v in parts["source_deps"].values())


def test_added_dependency_changes_key(deps):
    gc, src, cfg, db = deps
    k1, _ = build_key(check_name="t", source_deps=[src], db_deps=[db], invocation={"mode": "m"})
    extra = src.parent / "new_governed.py"
    extra.write_text("x", encoding="utf-8")
    k2, _ = build_key(
        check_name="t", source_deps=[src, extra], db_deps=[db], invocation={"mode": "m"}
    )
    assert k1 != k2


def test_force_no_cache_mode(deps, monkeypatch):
    gc, src, cfg, db = deps
    monkeypatch.setenv("ED_GATE_CACHE_DISABLE", "1")
    assert gate_cache_enabled() is False
    calls = {"n": 0}

    def ok():
        calls["n"] += 1
        return []

    common = dict(check_name="t", source_deps=[src, cfg], db_deps=[db], invocation={"mode": "m"})
    _, p1 = cached_check(**common, compute=ok)
    _, p2 = cached_check(**common, compute=ok)
    assert calls["n"] == 2 and p1["cache"] == p2["cache"] == "disabled"


def test_production_wiring_dependency_closure_locked():
    """The real subcheck's cache wiring must key on the known dependency closure
    (checker source, curation gate, lock index, contract, manifest, registry,
    the cache module itself, AGENTS.md, and the live DB triple)."""
    import inspect

    import tools.check_fix_everything_we_touch as m

    s = inspect.getsource(m.check_ablation_seven_model_four_horizon_grid)
    for needle in (
        "cached_check",
        "AGENTS.md",
        "feature_curation_gate.py",
        "ablation_static_lock_index.py",
        "build_feature_assignment_matrix_v2.py",
        "governance_gate_cache.py",
        "governed_stack_contract.py",
        "feature_ablation_manifest_leaf.json",
        "schwab_ablation_field_registry.json",
        "ed_console.db",
        "check_fix_everything_we_touch.py",
    ):
        assert needle in s, f"cache wiring missing dependency {needle}"
    assert "_check_ablation_seven_model_four_horizon_grid_impl" in s
