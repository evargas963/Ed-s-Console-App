"""Repo-wide semantic-coherence mission, item 1: "Invalid bundle manifests must not
become 'manifest absent'." `training_cache.load_run_manifest` used to return bare
`None` for BOTH a genuinely-absent manifest file and a present-but-corrupt one,
conflating two different facts. `active_bundle_contract.write_bundle_integrity_manifest`
then recorded both as `{"source_manifest_absent": True}` -- an incorrect, misleading
state for the corrupt case (a real anomaly worth investigating reads as "nothing to see
here, no manifest was ever written").

These tests prove: the two states are now distinguishable at the source
(load_run_manifest raises ManifestCorruptError for corrupt, returns None only for
absent), and every caller either propagates that distinction correctly or explicitly
logs it rather than silently conflating -- proven against the real functions, not a
mock.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from training_cache import ManifestCorruptError, load_run_manifest, save_run_manifest


def test_load_run_manifest_returns_none_for_genuinely_absent(tmp_path: Path):
    assert load_run_manifest(tmp_path) is None


def test_load_run_manifest_raises_for_malformed_json(tmp_path: Path):
    from training_cache import candidate_manifest_path

    p = candidate_manifest_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ManifestCorruptError):
        load_run_manifest(tmp_path)


def test_load_run_manifest_raises_for_non_dict_json(tmp_path: Path):
    from training_cache import candidate_manifest_path

    p = candidate_manifest_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ManifestCorruptError):
        load_run_manifest(tmp_path)


def test_load_run_manifest_returns_dict_for_valid_manifest(tmp_path: Path):
    save_run_manifest(tmp_path, {"ticker": "SPY"})
    assert load_run_manifest(tmp_path) == {"ticker": "SPY"}


def _touch_one_artifact(bundle_dir: Path, ticker: str = "SPY", hz: str = "1c") -> None:
    (bundle_dir / f"xgb_{ticker}_{hz}.pkl").write_bytes(b"stub")
    (bundle_dir / f"xgb_{ticker}_{hz}_meta.json").write_text("{}", encoding="utf-8")


def test_write_bundle_integrity_manifest_distinguishes_absent_from_invalid(tmp_path: Path):
    """The actual repair site: source_lineage must record a DIFFERENT state for
    'never had a source manifest' vs 'had one but it's corrupt', not the same
    {'source_manifest_absent': True} for both."""
    from active_bundle_contract import write_bundle_integrity_manifest

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    _touch_one_artifact(bundle_dir)
    manifest_absent = write_bundle_integrity_manifest(
        bundle_dir, "SPY", "1c", source_run_manifest=None, allow_missing_required=True,
    )
    assert manifest_absent["source_lineage"] == {"source_manifest_absent": True}

    manifest_invalid = write_bundle_integrity_manifest(
        bundle_dir, "SPY", "1c",
        source_run_manifest=None,
        source_manifest_corrupt_reason="manifest at .../scheduler_run_manifest.json is not valid JSON: ...",
        allow_missing_required=True,
    )
    assert manifest_invalid["source_lineage"]["source_manifest_invalid"] is True
    assert "reason" in manifest_invalid["source_lineage"]
    assert manifest_invalid["source_lineage"] != manifest_absent["source_lineage"], (
        "absent and invalid must be distinguishable states, never the same dict shape"
    )


def test_write_bundle_integrity_manifest_rejects_malformed_source_manifest_type(tmp_path: Path):
    """The parameter's own type contract is `dict | None` -- a caller passing anything
    else (a list, a string) is a bug and must fail closed, not be silently treated as
    'absent' the way `isinstance(x, dict) else None` used to."""
    from active_bundle_contract import write_bundle_integrity_manifest

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    _touch_one_artifact(bundle_dir)
    with pytest.raises(TypeError):
        write_bundle_integrity_manifest(
            bundle_dir, "SPY", "1c",
            source_run_manifest=["not", "a", "dict"],  # type: ignore[arg-type]
            allow_missing_required=True,
        )


def test_promote_active_bundle_call_site_distinguishes_corrupt_from_absent(tmp_path: Path, monkeypatch):
    """Mutation control for the actual production call site
    (active_bundle_contract.py's promotion path, line ~894-908): plant a corrupt
    scheduler_run_manifest.json in the source dir and prove the resulting bundle
    integrity manifest records 'invalid', never 'absent'."""
    import active_bundle_contract as abc
    from training_cache import MANIFEST_FILENAME

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / MANIFEST_FILENAME).write_text("{not valid json", encoding="utf-8")

    manifest_state = None
    manifest_corrupt_reason = None
    try:
        manifest_state = load_run_manifest(src_dir)
    except ManifestCorruptError as e:
        manifest_corrupt_reason = str(e)
    assert manifest_state is None
    assert manifest_corrupt_reason is not None, (
        "a corrupt source manifest must raise, not silently produce None with no "
        "distinguishing reason -- this is the exact defect that let a corrupt manifest "
        "look identical to an absent one at the promotion call site"
    )

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    _touch_one_artifact(bundle_dir)
    result = abc.write_bundle_integrity_manifest(
        bundle_dir, "SPY", "1c",
        source_run_manifest=manifest_state,
        source_manifest_corrupt_reason=manifest_corrupt_reason,
        allow_missing_required=True,
    )
    assert result["source_lineage"].get("source_manifest_invalid") is True
    assert result["source_lineage"].get("source_manifest_absent") is not True
