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
from pathlib import Path

import pytest


pytestmark = pytest.mark.usefixtures("_permissive_policy")




def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()




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


