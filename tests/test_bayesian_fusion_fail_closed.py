"""I-01: fuse() outer boundary returns unavailable FusionPayload without fabricated numerics."""
from __future__ import annotations

from types import SimpleNamespace

import bayesian_fusion as bf
from bayesian_fusion import fuse


def test_fuse_exception_returns_fail_closed_payload(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("fusion test failure")

    monkeypatch.setattr(bf, "_fuse_impl", _boom)
    regime = SimpleNamespace(primary="pinning", confidence="medium")
    rules = SimpleNamespace(signal="wait", conviction="medium")
    unavailable = SimpleNamespace(available=False)
    mc = SimpleNamespace(available=False)
    result = fuse(regime, unavailable, unavailable, unavailable, mc, rules)
    assert result.available is False
    assert result.fusion_confidence_score is None
    assert result.dominant_probability is None
    assert "Fusion error" in (result.fusion_summary or "")
