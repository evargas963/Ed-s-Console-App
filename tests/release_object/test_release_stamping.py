"""I-25 — release object stamping."""
from __future__ import annotations

import pytest


def test_release_object_requires_git_sha(monkeypatch):
    monkeypatch.delenv("ED_BUILD_GENERATION", raising=False)
    import release_object as ro

    monkeypatch.setattr(ro, "_git_head_sha", lambda: None)
    with pytest.raises(ValueError, match="git_sha"):
        ro.build_release_object()


def test_release_object_fields(monkeypatch):
    monkeypatch.setenv("ED_BUILD_GENERATION", "abc123" * 5)
    from release_object import build_release_object, validate_release_for_emission

    rel = build_release_object()
    ok, reason = validate_release_for_emission(rel)
    assert ok, reason
    for key in (
        "release_id",
        "git_sha",
        "build_generation",
        "model_hashes",
        "config_hash",
        "migration_version",
        "created_at_utc",
    ):
        assert key in rel
    assert rel["release_id"].startswith("rel-")


