"""Mutation/negative-control proof for the REPO-WIDE NO-FALLBACK MECHANICAL LOCK (operator
mandate 2026-09-17, tools/check_no_fallback_lock.py).

Every test drives `violations()` against a REAL, throwaway git repository (init'd fresh per
test in tmp_path, never this repo's own history) with a real staged diff -- never a hand-
built string handed to an internal helper -- so a passing test proves the actual diff-
reading path (git diff --cached, hunk parsing, AST re-parse of the file on disk) works, not
just an isolated regex. Each REQUIRED negative control from the mission's PROOF section maps
to one test; the REQUIRED positive controls (ordinary non-substitution control flow must not
be falsely rejected) get their own tests alongside.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_no_fallback_lock as M  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "README.md").write_text("seed\n", encoding="utf-8")
    _git(r, "add", "README.md")
    _git(r, "commit", "-q", "-m", "seed")
    monkeypatch.setattr(M, "REPO", r)
    monkeypatch.setattr(M, "REGISTRY", r / "governance" / "no_fallback_registry.json")
    return r


def _stage_new_file(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)


def _rule_tags(findings: list[str]) -> set[str]:
    return {f.split("[", 1)[1].split("]", 1)[0] for f in findings if "[" in f}


# ============================= REQUIRED NEGATIVE CONTROLS =============================

def test_python_alternate_value_ladder_on_protected_field_rejected(repo):
    _stage_new_file(repo, "app.py",
        "def read(payload):\n"
        "    spot = payload.get('spot') or payload.get('last_close')\n"
        "    return spot\n")
    v = M.violations()
    assert v
    assert "R8_PY_PROTECTED_FIELD_OR" in _rule_tags(v)


def test_js_or_or_nullish_coalesce_substitution_rejected(repo):
    _stage_new_file(repo, "static/app.js",
        "function render(d) {\n"
        "  var spot = d.spot || d.lastClose;\n"
        "  return spot;\n"
        "}\n")
    v = M.violations()
    assert v
    assert "R4_JS_PROTECTED_FIELD" in _rule_tags(v)


def test_inline_html_script_fallback_rejected(repo):
    _stage_new_file(repo, "static/page.html",
        "<html><body><script>\n"
        "  var spot = window.state.spot ?? window.state.lastClose;\n"
        "</script></body></html>\n")
    v = M.violations()
    assert v
    assert "R4_JS_PROTECTED_FIELD" in _rule_tags(v)


def test_sql_coalesce_substitution_rejected(repo):
    _stage_new_file(repo, "queries.py",
        "def q():\n"
        "    return \"SELECT COALESCE(canonical_timeframe, '1m') FROM snapshots\"\n")
    v = M.violations()
    assert v
    assert "R1_SQL_COALESCE" in _rule_tags(v)


def test_sql_ifnull_substitution_rejected(repo):
    _stage_new_file(repo, "schema.sql",
        "SELECT IFNULL(enrollment_source, 'default_source') FROM users;\n")
    v = M.violations()
    assert v
    assert "R1_SQL_COALESCE" in _rule_tags(v)


def test_exception_driven_substitute_rejected(repo):
    _stage_new_file(repo, "loader.py",
        "def load(tk):\n"
        "    try:\n"
        "        tickers = fetch_all(tk)\n"
        "    except Exception:\n"
        "        tickers = []\n"
        "    return tickers\n")
    v = M.violations()
    assert v
    assert "R3_EXCEPT_SUBSTITUTE" in _rule_tags(v)


def test_cached_prior_value_carried_forward_as_current_rejected(repo):
    _stage_new_file(repo, "publish.py",
        "def publish(cached_admitted, new_generation):\n"
        "    admitted = cached_admitted\n"
        "    admitted_generation = new_generation\n"
        "    return admitted, admitted_generation\n")
    v = M.violations()
    assert v
    assert "R9_STALE_FRESH_BADGE" in _rule_tags(v)


def test_missing_numeric_value_converted_to_zero_rejected(repo):
    _stage_new_file(repo, "read.py",
        "def read(row):\n"
        "    active = row.get('active', 0)\n"
        "    return active\n")
    v = M.violations()
    assert v
    assert "R8_PY_PROTECTED_FIELD_GET" in _rule_tags(v)


def test_stale_value_assigned_a_fresh_timestamp_rejected(repo):
    # Same shape as the cached/prior-value test above -- R9 exists specifically to catch
    # "old data, new badge", the two required controls share one mechanism by design.
    _stage_new_file(repo, "publish2.py",
        "def publish(last_known_rejected, now_ts):\n"
        "    rejected = last_known_rejected\n"
        "    rejected_ts = now_ts\n"
        "    return rejected, rejected_ts\n")
    v = M.violations()
    assert v
    assert "R9_STALE_FRESH_BADGE" in _rule_tags(v)


def test_lock_registry_weakened_without_operator_quote_rejected(repo):
    reg_dir = repo / "governance"
    reg_dir.mkdir(parents=True, exist_ok=True)
    reg_path = reg_dir / "no_fallback_registry.json"
    reg_path.write_text(
        '{"ml_imputation_authorized_files": {"a.py": {"operator_quote": "seed"}}}\n',
        encoding="utf-8")
    _git(repo, "add", "governance/no_fallback_registry.json")
    _git(repo, "commit", "-q", "-m", "seed registry")
    # Now widen it (remove the sole authorized file) with NO operator_quote in the diff.
    reg_path.write_text('{"ml_imputation_authorized_files": {}}\n', encoding="utf-8")
    _git(repo, "add", "governance/no_fallback_registry.json")
    v = M.violations()
    assert v
    assert "R5_LOCK_WEAKENED" in _rule_tags(v)


def test_lock_registry_widened_with_operator_quote_passes(repo):
    reg_dir = repo / "governance"
    reg_dir.mkdir(parents=True, exist_ok=True)
    reg_path = reg_dir / "no_fallback_registry.json"
    reg_path.write_text('{"ml_imputation_authorized_files": {}}\n', encoding="utf-8")
    _git(repo, "add", "governance/no_fallback_registry.json")
    _git(repo, "commit", "-q", "-m", "seed registry")
    reg_path.write_text(
        '{"ml_imputation_authorized_files": {"a.py": {"operator_quote": '
        '"operator authorized this on 2026-09-17"}}}\n', encoding="utf-8")
    _git(repo, "add", "governance/no_fallback_registry.json")
    v = M.violations()
    assert "R5_LOCK_WEAKENED" not in _rule_tags(v)


def test_unscanned_executable_file_type_rejected(repo):
    _stage_new_file(repo, "scripts/deploy.sh", "#!/bin/sh\necho hi\n")
    v = M.violations()
    assert v
    assert "R6_UNKNOWN_SURFACE" in _rule_tags(v)


def test_parse_failure_rejected(repo):
    _stage_new_file(repo, "broken.py", "def f(:\n    pass\n")
    v = M.violations()
    assert v
    assert "R7_PARSE_FAILURE" in _rule_tags(v)


def test_unauthorized_pandas_imputation_rejected(repo):
    _stage_new_file(repo, "train.py",
        "def prep(X):\n"
        "    X = X.fillna(0)\n"
        "    return X\n")
    v = M.violations()
    assert v
    assert "R2_IMPUTATION" in _rule_tags(v)


def test_authorized_pandas_imputation_passes(repo):
    reg_dir = repo / "governance"
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / "no_fallback_registry.json").write_text(
        '{"ml_imputation_authorized_files": {"train.py": {"operator_quote": "authorized"}}}\n',
        encoding="utf-8")
    _stage_new_file(repo, "train.py",
        "def prep(X):\n"
        "    X = X.fillna(0)\n"
        "    return X\n")
    v = M.violations()
    assert "R2_IMPUTATION" not in _rule_tags(v)


# ============================= REQUIRED POSITIVE CONTROLS =============================

def test_explicit_unavailable_state_disclosure_passes(repo):
    _stage_new_file(repo, "state.py",
        "def compute(row):\n"
        "    try:\n"
        "        spot = resolve(row)\n"
        "    except Exception as e:\n"
        "        spot_error = str(e)\n"
        "        spot_status = 'unavailable'\n"
        "        return None\n"
        "    return spot\n")
    v = M.violations()
    assert v == []


def test_stale_flag_with_original_observation_identity_passes(repo):
    _stage_new_file(repo, "state2.py",
        "def compute(row):\n"
        "    spot_stale = True\n"
        "    spot_as_of_ts_utc = row['observed_ts_utc']\n"
        "    return spot_stale, spot_as_of_ts_utc\n")
    v = M.violations()
    assert v == []


def test_separately_named_alternative_semantic_never_populates_original_field(repo):
    # A NEW, distinctly-named field (spot_reference) beside `spot` -- never substituting
    # INTO `spot` itself -- must not trip the protected-field rules.
    _stage_new_file(repo, "levels.py",
        "def compute(row):\n"
        "    spot_reference = row.get('prior_close')\n"
        "    return spot_reference\n")
    v = M.violations()
    assert v == []


def test_ordinary_boolean_control_flow_not_falsely_rejected(repo):
    _stage_new_file(repo, "guard.py",
        "def ok(payload):\n"
        "    if payload.get('spot') or payload.get('quote_ahead'):\n"
        "        return True\n"
        "    return False\n")
    v = M.violations()
    assert v == []


def test_aggregate_over_empty_set_coalesce_not_falsely_rejected(repo):
    _stage_new_file(repo, "agg.py",
        "def q():\n"
        "    return 'SELECT COALESCE(MAX(snapshot_id), 0) FROM snapshots'\n")
    v = M.violations()
    assert v == []


def test_self_describing_display_label_coalesce_not_falsely_rejected(repo):
    _stage_new_file(repo, "audit.py",
        "def q():\n"
        "    return \"SELECT COALESCE(rules_signal, 'NULL') AS sig FROM snapshots\"\n")
    v = M.violations()
    assert v == []


def test_update_preserve_existing_coalesce_not_falsely_rejected(repo):
    _stage_new_file(repo, "writer.py",
        "def q():\n"
        "    return 'UPDATE users SET enrollment_source = COALESCE(enrollment_source, ?)'\n")
    v = M.violations()
    assert v == []


def test_except_handler_naming_the_failure_not_falsely_rejected(repo):
    _stage_new_file(repo, "loader2.py",
        "def load():\n"
        "    try:\n"
        "        return fetch()\n"
        "    except Exception as e:\n"
        "        fetch_error = str(e)\n"
        "        raise\n")
    v = M.violations()
    assert v == []


def test_declared_noop_extensions_not_falsely_rejected(repo):
    _stage_new_file(repo, "config.yaml", "key: value\n")
    v = M.violations()
    assert v == []
