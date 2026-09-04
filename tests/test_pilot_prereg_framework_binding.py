"""Framework binding and prereg integrity hard-fail behavior."""

from __future__ import annotations

import pytest


def test_validate_framework_binding_version_mismatch_raises():
    from research.pilot_step3 import pilot_config

    prereg = pilot_config.load_prereg(validate=False)
    bad = {**prereg, "framework_doc_version": "0.0"}
    with pytest.raises(ValueError, match="framework_doc_version mismatch"):
        pilot_config.validate_framework_binding(bad)


def test_validate_framework_binding_id_mismatch_raises():
    from research.pilot_step3 import pilot_config

    prereg = pilot_config.load_prereg(validate=False)
    bad = {**prereg, "framework_doc_id": "wrong/path.md"}
    with pytest.raises(ValueError, match="framework_doc_id mismatch"):
        pilot_config.validate_framework_binding(bad)


def test_validate_prereg_hash_mismatch_raises():
    from research.pilot_step3 import pilot_config

    prereg = pilot_config.load_prereg(validate=False)
    bad = {**prereg, "content_hash": "0" * 64}
    with pytest.raises(ValueError, match="content_hash mismatch"):
        pilot_config.validate_prereg_hash(bad)


def test_load_prereg_validate_false_allows_stale_hash_for_fix_tooling():
    from research.pilot_step3 import pilot_config

    prereg = pilot_config.load_prereg(validate=False)
    stale = {**prereg, "content_hash": "0" * 64}
    assert stale["content_hash"] != pilot_config.prereg_content_hash(stale)
    with pytest.raises(ValueError, match="content_hash mismatch"):
        pilot_config.validate_prereg_hash(stale)


def test_generate_events_revalidates_frozen_prereg():
    """Defense-in-depth: frozen prereg_id path re-runs integrity before events."""
    from research.pilot_step3.event_generation import generate_events
    from research.pilot_step3 import pilot_config
    from research.pilot_step3.data_loader import Bar1m
    from datetime import datetime, timedelta

    from app.domain.time_et import ET as et  # noqa: F401
    prereg = pilot_config.load_prereg(validate=False)
    prereg = {**prereg, "framework_doc_version": "0.0", "content_hash": pilot_config.prereg_content_hash({**prereg, "framework_doc_version": "0.0"})}

    bars = []
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=et)
    for i in range(120):
        c = 100.0 + 0.01 * i
        ts = (t0 + timedelta(minutes=i)).timestamp()
        bars.append(Bar1m(ts, ts + 60.0, c, c + 0.2, c - 0.2, c, 1.0))

    with pytest.raises(ValueError, match="framework_doc_version mismatch"):
        generate_events(bars, prereg)
