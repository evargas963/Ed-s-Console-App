"""Tests for source-control hygiene checker."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_source_control_hygiene import (  # noqa: E402
    check_gitignore_markers,
    check_source_control_hygiene,
    classify_untracked_path,
    forbidden_untracked_paths,
)


def test_gitignore_has_required_markers():
    errs = check_gitignore_markers()
    assert errs == [], errs


def test_source_control_hygiene_passes_on_current_repo():
    errs = check_source_control_hygiene()
    assert errs == [], errs


def test_audit_artifact_present_and_valid():
    path = REPO / "governance/artifacts/SOURCE_CONTROL_HYGIENE_AUDIT.json"
    assert path.is_file()
    audit = json.loads(path.read_text(encoding="utf-8"))
    assert audit["schema_version"] == 1
    assert len(audit["classifications"]) >= 10


@pytest.mark.parametrize(
    "rel,expected",
    [
        ("_schwab_auth_url.txt", "local_secret_or_auth"),
        ("backups/db/20260611_ed_console.db", "database_backup"),
        ("logs/survivor_retrain_gate.err", "generated_runtime_artifact"),
        ("models/active/GOOG/xgb_GOOG_1c.pkl", "model_binary_output"),
        ("feature_analysis.xlsx", "analysis_output"),
        ("timing_probe.py", "scratch_probe"),
        ("timing_probe3.py", "scratch_probe"),
        ("reports/daily_scoreboard/latest.json", "local_report"),
    ],
)
def test_classify_forbidden_runtime_paths(rel: str, expected: str):
    assert classify_untracked_path(rel) == expected


def test_classify_allows_source_paths():
    assert classify_untracked_path("market_state.py") is None
    assert classify_untracked_path("tools/check_source_control_hygiene.py") is None
    assert classify_untracked_path("governance/artifacts/persistence_consumer_map.json") is None


def test_forbidden_untracked_detects_auth_file(monkeypatch):
    monkeypatch.setattr(
        "tools.check_source_control_hygiene._git_untracked_paths",
        lambda repo=None: ["_schwab_auth_url.txt", "market_state.py"],
    )
    hits = forbidden_untracked_paths()
    assert ("_schwab_auth_url.txt", "local_secret_or_auth") in hits


def test_check_fails_when_forbidden_untracked_present(monkeypatch):
    monkeypatch.setattr(
        "tools.check_source_control_hygiene._git_untracked_paths",
        lambda repo=None: ["calibration/trading_data.db"],
    )
    errs = check_source_control_hygiene()
    assert any("calibration/trading_data.db" in e for e in errs)
