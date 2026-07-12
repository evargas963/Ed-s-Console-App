"""ML-PIPE Item 4 — fleet migration + strict enforcement adversarial suite.

Synthetic tmp fleets only; expected hashes recomputed independently via hashlib.
Covers: evidence classes, classification, plan mapping, dry-run purity, governed
re-promotion, manifest reconstruction, unproven replacement with rollback backup,
quarantine, fleet verification recompute, policy-based strict default (no legacy
reopen after expiry), TTL rehash closing the size+mtime_ns mutation gap, and
ticker/horizon universality by construction.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import time
from pathlib import Path

import pytest

import active_bundle_contract as abc_mod
from active_bundle_contract import (
    bundle_integrity_manifest_path,
    bundle_role_filenames,
    load_bundle_integrity_manifest,
    write_bundle_integrity_manifest,
)
from tools.ml_item4_fleet_migration import (
    ACTION_NONE,
    ACTION_QUARANTINE,
    ACTION_RECONSTRUCT_MANIFEST,
    ACTION_REPROMOTE,
    ACTION_REPROMOTE_REPLACING_UNPROVEN,
    CLASS_ALREADY_VERIFIED,
    CLASS_RECONSTRUCTABLE,
    CLASS_REPROMOTABLE,
    CLASS_RETRAIN,
    CLASS_UNPROVEN,
    QUARANTINE_DIRNAME,
    build_fleet_inventory,
    execute_migration,
    file_evidence,
    plan_migration,
    verify_fleet,
)

pytestmark = pytest.mark.usefixtures("_permissive_policy")


@pytest.fixture()
def _permissive_policy(tmp_path, monkeypatch):
    """Tests control strictness explicitly; default here = legacy allowance open."""
    pol = tmp_path / "policy_open.json"
    pol.write_text(json.dumps({
        "schema_version": 1,
        "strict_default": False,
        "legacy_allowance": {"enabled": True, "expires_at_utc": "299-01-01T00:00:00+00:00"},
    }), encoding="utf-8")
    monkeypatch.setattr(abc_mod, "MIGRATION_POLICY_PATH", pol)
    monkeypatch.delenv(abc_mod.ARTIFACT_INTEGRITY_STRICT_ENV, raising=False)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _mk_bundle(models_dir: Path, root: str, t: str, hz: str, seed: bytes = b"") -> Path:
    bd = models_dir / root / t
    bd.mkdir(parents=True, exist_ok=True)
    for role, name in bundle_role_filenames(t, hz).items():
        if name.endswith(".json"):
            (bd / name).write_text(json.dumps({"role": role, "t": t, "hz": hz}), encoding="utf-8")
        else:
            with (bd / name).open("wb") as fh:
                pickle.dump({"role": role, "t": t, "hz": hz, "seed": seed.decode("latin1")}, fh)
    return bd


def _mk_candidate(models_dir: Path, src_root: str, t: str, hz: str, from_bundle: Path | None = None,
                  run_manifest: bool = True) -> Path:
    d = models_dir / src_root / t
    d.mkdir(parents=True, exist_ok=True)
    if from_bundle is not None:
        for f in from_bundle.iterdir():
            if f.is_file() and f.name != "bundle_integrity_manifest.json":
                (d / f.name).write_bytes(f.read_bytes())
    if run_manifest:
        (d / "scheduler_run_manifest.json").write_text(json.dumps({
            "schema_version": 1, "trained_at": "2026-07-01T00:00:00Z",
            "data_end": "2026-06-30", "scheduler_cache_key": "k1",
        }), encoding="utf-8")
    return d


# ── evidence classes ─────────────────────────────────────────────────────────


def test_file_evidence_candidate_git_eol_none(tmp_path):
    f = tmp_path / "xgb_ZZT_1c.pkl"
    f.write_bytes(b"artifact-bytes")
    # CANDIDATE
    idx = {hashlib.sha256(b"artifact-bytes").hexdigest(): ["parallel/ZZT/xgb_ZZT_1c.pkl"]}
    ev = file_evidence(f, "models/active/ZZT/xgb_ZZT_1c.pkl", idx, {})
    assert ev["evidence"] == "CANDIDATE" and ev["source"].startswith("parallel/")
    # GIT exact
    raw = f.read_bytes()
    oid = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    ev2 = file_evidence(f, "k", {}, {"k": oid})
    assert ev2["evidence"] == "GIT" and ev2["source"] == f"git:{oid}"
    # GIT_EOL (CRLF on disk, LF in git)
    g = tmp_path / "m_meta.json"
    g.write_bytes(b'{"a": 1}\r\n')
    lf = b'{"a": 1}\n'
    oid_lf = hashlib.sha1(f"blob {len(lf)}\0".encode() + lf).hexdigest()
    ev3 = file_evidence(g, "k2", {}, {"k2": oid_lf})
    assert ev3["evidence"] == "GIT_EOL"
    # NONE — availability alone is never evidence
    ev4 = file_evidence(f, "unknown", {}, {})
    assert ev4["evidence"] == "NONE" and ev4["source"] is None


# ── classification + plan ────────────────────────────────────────────────────


@pytest.mark.parametrize("root,hz", [("active", "1c"), ("active_5c", "5c"),
                                     ("active_15c", "15c"), ("active_60c", "60c")])
def test_classification_matrix_all_horizons(tmp_path, root, hz):
    """One synthetic fleet per horizon root: repromotable / reconstructable /
    unproven-with-candidate / retrain-required / already-verified."""
    models = tmp_path / "models"
    # REPROMOTABLE: active == candidate bytes + run manifest
    a1 = _mk_bundle(models, root, "AAA", hz, seed=b"1")
    _mk_candidate(models, "parallel", "AAA", hz, from_bundle=a1)
    # UNPROVEN w/ candidate: active bytes differ from candidate, no other source
    a2 = _mk_bundle(models, root, "BBB", hz, seed=b"2")
    _mk_candidate(models, "parallel", "BBB", hz, from_bundle=a2)
    with (a2 / f"lstm_BBB_{hz}.pt").open("wb") as fh:
        pickle.dump({"drifted": True}, fh)
    # RETRAIN: unproven bytes, no candidate at all
    _mk_bundle(models, root, "CCC", hz, seed=b"3")
    # ALREADY_VERIFIED: stamped manifest
    a4 = _mk_bundle(models, root, "DDD", hz, seed=b"4")
    write_bundle_integrity_manifest(a4, "DDD", hz)
    inv = build_fleet_inventory(models, repo_root=tmp_path)
    cls = {k: v["classification"] for k, v in inv["bundles"].items()}
    assert cls[f"AAA:{hz}"] == CLASS_REPROMOTABLE
    assert cls[f"BBB:{hz}"] == CLASS_UNPROVEN
    assert cls[f"CCC:{hz}"] == CLASS_RETRAIN
    assert cls[f"DDD:{hz}"] == CLASS_ALREADY_VERIFIED

    plan = plan_migration(inv)
    act = {k: v["action"] for k, v in plan["actions"].items()}
    assert act[f"AAA:{hz}"] == ACTION_REPROMOTE
    assert act[f"BBB:{hz}"] == ACTION_REPROMOTE_REPLACING_UNPROVEN
    assert act[f"CCC:{hz}"] == ACTION_QUARANTINE
    assert act[f"DDD:{hz}"] == ACTION_NONE


def test_unknown_provenance_never_silently_recoverable(tmp_path):
    """A bundle with even one NONE-evidence file is never classified proven."""
    models = tmp_path / "models"
    bd = _mk_bundle(models, "active", "ZZZ", "1c")
    cand = _mk_candidate(models, "parallel", "ZZZ", "1c", from_bundle=bd)
    # one active file drifts from candidate
    (bd / "xgb_ZZZ_1c_meta.json").write_text("{\"tampered\": true}", encoding="utf-8")
    inv = build_fleet_inventory(models, repo_root=tmp_path)
    assert inv["bundles"]["ZZZ:1c"]["classification"] == CLASS_UNPROVEN
    # remove the candidate's run manifest -> not even repromotable, still never proven
    (cand / "scheduler_run_manifest.json").unlink()
    inv2 = build_fleet_inventory(models, repo_root=tmp_path)
    assert inv2["bundles"]["ZZZ:1c"]["classification"] in (CLASS_RETRAIN, CLASS_UNPROVEN)
    assert inv2["bundles"]["ZZZ:1c"]["classification"] != CLASS_RECONSTRUCTABLE


def test_dry_run_makes_no_filesystem_changes(tmp_path):
    models = tmp_path / "models"
    bd = _mk_bundle(models, "active", "DRY", "1c")
    _mk_candidate(models, "parallel", "DRY", "1c", from_bundle=bd)
    before = {p: _sha(p) for p in bd.iterdir()}
    inv = build_fleet_inventory(models, repo_root=tmp_path)
    plan = plan_migration(inv)
    execution = execute_migration(inv, plan, models, apply=False)
    assert execution["applied"] is False
    assert {p: _sha(p) for p in bd.iterdir()} == before
    assert not bundle_integrity_manifest_path(bd).is_file()
    assert not (models / QUARANTINE_DIRNAME).exists()


# ── execution paths ──────────────────────────────────────────────────────────


def test_repromote_stamps_manifest_with_promotion_provenance(tmp_path):
    models = tmp_path / "models"
    bd = _mk_bundle(models, "active", "RPA", "1c", seed=b"rp")
    cand = _mk_candidate(models, "parallel", "RPA", "1c", from_bundle=bd)
    inv = build_fleet_inventory(models, repo_root=tmp_path)
    plan = plan_migration(inv)
    execution = execute_migration(inv, plan, models, apply=True)
    rec = execution["results"]["RPA:1c"]
    assert rec["applied"] is True and rec["errors"] == []
    mf = load_bundle_integrity_manifest(bd)
    assert mf is not None
    assert mf["provenance"]["method"] == "REPROMOTED_FROM_GOVERNED_CANDIDATE"
    assert mf["provenance"]["candidate_dir"] == str(cand)
    assert mf["provenance"]["replaced_unproven_bytes"] is False
    assert mf["source_lineage"].get("trained_at") == "2026-07-01T00:00:00Z"
    # independent hash check of every stamped entry
    for name, entry in mf["artifacts"].items():
        assert entry["sha256"] == _sha(bd / name), name
    # byte identity with candidate preserved (serving unchanged)
    for role, name in bundle_role_filenames("RPA", "1c").items():
        assert _sha(bd / name) == _sha(cand / name)


def test_reconstruct_manifest_records_independent_evidence(tmp_path):
    models = tmp_path / "models"
    bd = _mk_bundle(models, "active", "RCA", "1c", seed=b"rc")
    # candidate copies WITHOUT run manifest in two different roots -> RECONSTRUCTABLE
    _mk_candidate(models, "parallel", "RCA", "1c", from_bundle=bd, run_manifest=False)
    inv = build_fleet_inventory(models, repo_root=tmp_path)
    assert inv["bundles"]["RCA:1c"]["classification"] == CLASS_RECONSTRUCTABLE
    plan = plan_migration(inv)
    assert plan["actions"]["RCA:1c"]["action"] == ACTION_RECONSTRUCT_MANIFEST
    execution = execute_migration(inv, plan, models, apply=True)
    assert execution["results"]["RCA:1c"]["errors"] == []
    mf = load_bundle_integrity_manifest(bd)
    assert mf["provenance"]["method"] == "RECONSTRUCTED_FROM_INDEPENDENT_EVIDENCE"
    # every present file's evidence is recorded and none is NONE
    ev = mf["provenance"]["evidence"]
    assert ev and all(v["evidence"] != "NONE" for v in ev.values())
    # reconstructed manifests are distinguishable from promoted ones
    assert mf["provenance"]["method"] != "REPROMOTED_FROM_GOVERNED_CANDIDATE"


def test_incomplete_bundle_reconstruction_pins_present_stays_fail_closed(tmp_path):
    """A 6-file restore-era bundle: present files get pinned (verify_fleet ok),
    the missing file keeps the bundle NON-servable via the completeness contract."""
    from active_bundle_contract import check_active_bundle_complete

    models = tmp_path / "models"
    bd = _mk_bundle(models, "active", "INC", "1c", seed=b"inc")
    _mk_candidate(models, "parallel", "INC", "1c", from_bundle=bd, run_manifest=False)
    (bd / "meta_INC_1c.pkl").unlink()  # incomplete: meta_stack gone everywhere active
    inv = build_fleet_inventory(models, repo_root=tmp_path)
    assert inv["bundles"]["INC:1c"]["classification"] == CLASS_RECONSTRUCTABLE
    plan = plan_migration(inv)
    execution = execute_migration(inv, plan, models, apply=True)
    assert execution["results"]["INC:1c"]["errors"] == []
    mf = load_bundle_integrity_manifest(bd)
    assert mf["missing_required_artifacts"] == ["meta_INC_1c.pkl"]
    assert "meta_INC_1c.pkl" not in mf["artifacts"]
    # fleet verification: present bytes pinned and green
    assert verify_fleet(models)["ok"] is True
    # serving completeness: still fail-closed on the missing artifact
    res = check_active_bundle_complete("INC", "1c", bundle_dir=bd, models_dir=models)
    assert res["compliant"] is False
    assert "meta_INC_1c.pkl missing" in json.dumps(res["artifacts"])


def test_unproven_replacement_backs_up_bytes_first(tmp_path):
    models = tmp_path / "models"
    bd = _mk_bundle(models, "active", "UPR", "1c", seed=b"orig")
    cand = _mk_candidate(models, "parallel", "UPR", "1c", from_bundle=bd)
    drifted = bd / "lstm_UPR_1c.pt"
    with drifted.open("wb") as fh:
        pickle.dump({"unproven": "bytes"}, fh)
    unproven_sha = _sha(drifted)
    inv = build_fleet_inventory(models, repo_root=tmp_path)
    assert inv["bundles"]["UPR:1c"]["classification"] == CLASS_UNPROVEN
    plan = plan_migration(inv)
    execution = execute_migration(inv, plan, models, apply=True)
    rec = execution["results"]["UPR:1c"]
    assert rec["applied"] is True and rec["errors"] == []
    # rollback backup preserves the REPLACED (unproven) bytes
    backup = Path(rec["backup"])
    assert _sha(backup / "lstm_UPR_1c.pt") == unproven_sha
    # active now serves the proven candidate bytes
    assert _sha(bd / "lstm_UPR_1c.pt") == _sha(cand / "lstm_UPR_1c.pt")
    assert _sha(bd / "lstm_UPR_1c.pt") != unproven_sha
    mf = load_bundle_integrity_manifest(bd)
    assert mf["provenance"]["replaced_unproven_bytes"] is True
    assert mf["provenance"]["rollback_backup"] == rec["backup"]


def test_quarantine_removes_serving_and_preserves_evidence(tmp_path):
    models = tmp_path / "models"
    bd = _mk_bundle(models, "active", "QQZ", "1c", seed=b"q")
    orig = {f.name: _sha(f) for f in bd.iterdir()}
    inv = build_fleet_inventory(models, repo_root=tmp_path)
    assert inv["bundles"]["QQZ:1c"]["classification"] == CLASS_RETRAIN
    plan = plan_migration(inv)
    assert plan["actions"]["QQZ:1c"]["action"] == ACTION_QUARANTINE
    execution = execute_migration(inv, plan, models, apply=True)
    rec = execution["results"]["QQZ:1c"]
    assert rec["applied"] is True
    assert not bd.exists(), "quarantined bundle must leave the serving tree"
    backup = Path(rec["backup"])
    assert {f.name: _sha(f) for f in backup.iterdir()} == orig
    # rollback path: restoring the backup returns the bundle byte-identically
    bd.mkdir(parents=True)
    for f in backup.iterdir():
        (bd / f.name).write_bytes(f.read_bytes())
    assert {f.name: _sha(f) for f in bd.iterdir()} == orig


# ── fleet verification (recompute, no stored counters) ──────────────────────


def test_verify_fleet_recomputes_from_filesystem(tmp_path):
    models = tmp_path / "models"
    good = _mk_bundle(models, "active", "GVA", "1c", seed=b"g")
    write_bundle_integrity_manifest(good, "GVA", "1c")
    legacy = _mk_bundle(models, "active_5c", "LVB", "5c", seed=b"l")
    fleet = verify_fleet(models)
    assert fleet["total_active_bundles"] == 2
    assert fleet["verified"] == 1
    assert fleet["legacy_unmanifested"] == ["LVB:5c"]
    assert fleet["ok"] is False
    # a manually-copied manifest-less bundle is DETECTED (ungoverned active
    # creation cannot hide from the recompute)
    write_bundle_integrity_manifest(legacy, "LVB", "5c")
    assert verify_fleet(models)["ok"] is True
    # post-stamp mutation flips the fleet red
    (good / "xgb_GVA_1c.pkl").write_bytes(b"tampered")
    fleet3 = verify_fleet(models)
    assert fleet3["ok"] is False and "GVA:1c" in fleet3["failed"]


# ── strict policy: repository-side default, no legacy reopen ────────────────


def _write_policy(tmp_path, **over):
    doc = {
        "schema_version": 1,
        "strict_default": True,
        "legacy_allowance": {"enabled": False, "expires_at_utc": "2026-07-12T00:00:00+00:00"},
    }
    doc.update(over)
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_strict_default_comes_from_committed_policy(tmp_path, monkeypatch):
    monkeypatch.delenv(abc_mod.ARTIFACT_INTEGRITY_STRICT_ENV, raising=False)
    monkeypatch.setattr(abc_mod, "MIGRATION_POLICY_PATH", _write_policy(tmp_path))
    assert abc_mod.artifact_integrity_strict_absence() is True
    monkeypatch.setattr(
        abc_mod, "MIGRATION_POLICY_PATH",
        _write_policy(tmp_path, strict_default=False,
                      legacy_allowance={"enabled": True,
                                        "expires_at_utc": "299-01-01T00:00:00+00:00"}),
    )
    assert abc_mod.artifact_integrity_strict_absence() is False


def test_missing_or_malformed_policy_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv(abc_mod.ARTIFACT_INTEGRITY_STRICT_ENV, raising=False)
    monkeypatch.setattr(abc_mod, "MIGRATION_POLICY_PATH", tmp_path / "absent.json")
    assert abc_mod.artifact_integrity_strict_absence() is True
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(abc_mod, "MIGRATION_POLICY_PATH", bad)
    assert abc_mod.artifact_integrity_strict_absence() is True


def test_env_cannot_reopen_legacy_after_allowance_expired(tmp_path, monkeypatch):
    """No indefinite grandfathering: env=0 is dead once the allowance is closed."""
    monkeypatch.setenv(abc_mod.ARTIFACT_INTEGRITY_STRICT_ENV, "0")
    # allowance disabled -> env=0 refused
    monkeypatch.setattr(abc_mod, "MIGRATION_POLICY_PATH", _write_policy(tmp_path))
    assert abc_mod.artifact_integrity_strict_absence() is True
    # allowance enabled but EXPIRED -> env=0 refused
    monkeypatch.setattr(
        abc_mod, "MIGRATION_POLICY_PATH",
        _write_policy(tmp_path, legacy_allowance={"enabled": True,
                                                  "expires_at_utc": "2026-01-01T00:00:00+00:00"}),
    )
    assert abc_mod.artifact_integrity_strict_absence() is True
    # allowance open -> env=0 honored (temporary, bounded)
    monkeypatch.setattr(
        abc_mod, "MIGRATION_POLICY_PATH",
        _write_policy(tmp_path, legacy_allowance={"enabled": True,
                                                  "expires_at_utc": "2099-01-01T00:00:00+00:00"}),
    )
    assert abc_mod.artifact_integrity_strict_absence() is False
    # hard lever always wins
    monkeypatch.setenv(abc_mod.ARTIFACT_INTEGRITY_STRICT_ENV, "1")
    assert abc_mod.artifact_integrity_strict_absence() is True


def test_committed_policy_is_strict_and_allowance_closed():
    """The COMMITTED repo policy (not a fixture) must be strict with the legacy
    allowance disabled/expired — recurrence lock against silent reopening."""
    doc = json.loads(
        (Path(__file__).resolve().parent.parent / "governance" / "ML_ITEM4_MIGRATION_POLICY.json")
        .read_text(encoding="utf-8")
    )
    assert doc["strict_default"] is True
    assert doc["legacy_allowance"]["enabled"] is False
    assert doc["fleet_completion_threshold"] == 1.0


# ── TTL rehash: size+mtime_ns-preserving mutation is bounded by the TTL ─────


def test_ttl_expiry_forces_full_rehash_detecting_stat_invisible_mutation(tmp_path, monkeypatch):
    import ml_predict as mp

    t, hz = "ZZTTL"[:5], "1c"
    bd = tmp_path / "active" / t
    bd.mkdir(parents=True)
    name = f"xgb_{t}_{hz}.pkl"
    for role, fname in bundle_role_filenames(t, hz).items():
        if fname.endswith(".json"):
            (bd / fname).write_text("{}", encoding="utf-8")
        else:
            with (bd / fname).open("wb") as fh:
                pickle.dump({"r": role}, fh)
    write_bundle_integrity_manifest(bd, t, hz)
    prov = mp._verify_governed_artifact(bd, t, hz, "xgb", name)
    assert prov is not None and prov["verified"] is True
    rk = mp._model_registry_key(t, hz)

    # mutation preserving BOTH size and mtime_ns (stat-invisible)
    p = bd / name
    st = p.stat()
    raw = bytearray(p.read_bytes())
    raw[-1] ^= 0x01
    p.write_bytes(bytes(raw))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert p.stat().st_size == st.st_size and p.stat().st_mtime_ns == st.st_mtime_ns

    # within TTL: stat guard alone cannot see it (the honest limit, now bounded)
    assert mp._artifact_registry_entry_stale(rk) is False
    # after TTL expiry: entry evicts and the full re-hash fails closed
    key = f"{rk}|xgb"
    mp._artifact_verification_registry[key]["verified_at_epoch"] = time.time() - 10_000
    assert mp._artifact_registry_entry_stale(rk) is True
    prov2 = mp._verify_governed_artifact(bd, t, hz, "xgb", name)
    assert prov2 is None  # ARTIFACT_HASH_MISMATCH fail-closed
    reg = mp.get_artifact_verification_provenance(t, hz)
    assert reg["xgb"]["reason_code"] == "ARTIFACT_HASH_MISMATCH"
    mp.invalidate_model_registry_key(rk)


def test_ttl_configurable_and_default_bounded(monkeypatch):
    import ml_predict as mp

    monkeypatch.delenv(mp.ARTIFACT_REVERIFY_TTL_ENV, raising=False)
    assert mp._artifact_reverify_ttl_seconds() == 900.0
    monkeypatch.setenv(mp.ARTIFACT_REVERIFY_TTL_ENV, "60")
    assert mp._artifact_reverify_ttl_seconds() == 60.0
    monkeypatch.setenv(mp.ARTIFACT_REVERIFY_TTL_ENV, "0")  # nonsense -> default
    assert mp._artifact_reverify_ttl_seconds() == 900.0
    monkeypatch.setenv(mp.ARTIFACT_REVERIFY_TTL_ENV, "junk")
    assert mp._artifact_reverify_ttl_seconds() == 900.0


# ── serving continuity: unavailable bundle fails closed, no substitution ────


def test_quarantined_bundle_fails_closed_not_substituted(tmp_path, monkeypatch):
    import ml_predict as mp

    models = tmp_path / "models"
    bd = _mk_bundle(models, "active", "GONE", "1c")
    inv = build_fleet_inventory(models, repo_root=tmp_path)
    plan = plan_migration(inv)
    execute_migration(inv, plan, models, apply=True)  # RETRAIN -> quarantined
    assert not bd.exists()
    monkeypatch.setattr(mp, "MODEL_DIR", models)
    monkeypatch.delenv("ED_XGB_STRICT_ACTIVE_ONLY", raising=False)
    prov = mp.build_model_serving_provenance("GONE")
    assert prov["runtime_class"] == "STRICT_ACTIVE_FAIL_CLOSED"
    assert prov["model_load_status"] == "fail_closed"
    assert prov["bundle_ticker"] == "GONE"  # no cross-ticker substitution


def test_candidate_completeness_exempt_from_strict_absence(tmp_path, monkeypatch):
    """Strict default must not brick the promotion pipeline: candidates are
    checked WITHOUT the manifest-absence requirement (manifest arrives at the
    governed promotion stamp)."""
    from active_bundle_contract import check_candidate_bundle_complete

    monkeypatch.setattr(abc_mod, "MIGRATION_POLICY_PATH", _write_policy(tmp_path))
    monkeypatch.delenv(abc_mod.ARTIFACT_INTEGRITY_STRICT_ENV, raising=False)
    assert abc_mod.artifact_integrity_strict_absence() is True
    models = tmp_path / "models"
    cand = _mk_candidate(models, "parallel", "CND", "1c",
                         from_bundle=_mk_bundle(models, "staging", "CND", "1c"))
    res = check_candidate_bundle_complete("CND", "1c", cand)
    integrity_issues = [i for i in res["issues"] if "MANIFEST_MISSING" in i]
    assert integrity_issues == [], "candidate must not fail on manifest absence"
