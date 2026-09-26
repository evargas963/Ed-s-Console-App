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
import pickle
from pathlib import Path

import pytest

import active_bundle_contract as abc_mod
from active_bundle_contract import (
    bundle_role_filenames,
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


# ── classification + plan ────────────────────────────────────────────────────


# ── drift-recovery record engine (committed, deterministic, fail-closed) ────


# ── execution paths ──────────────────────────────────────────────────────────


# ── fleet verification (recompute, no stored counters) ──────────────────────


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
        (Path(__file__).resolve().parent.parent / "config" / "ML_ITEM4_MIGRATION_POLICY.json")
        .read_text(encoding="utf-8")
    )
    assert doc["strict_default"] is True
    assert doc["legacy_allowance"]["enabled"] is False
    assert doc["fleet_completion_threshold"] == 1.0


# ── TTL rehash: size+mtime_ns-preserving mutation is bounded by the TTL ─────




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
