"""Mutation/negative-control proof for the REPO-WIDE NO-FALLBACK MECHANICAL LOCK (operator
mandate 2026-09-17, corrected 2026-09-17 after independent review rejected the first draft's
self-authorized exemptions -- see tools/check_no_fallback_lock.py's own module docstring for
the full correction history).

Every test drives `violations()` (the diff-scoped regression check) or `measure_baseline()`
(the repo-wide census) against a REAL, throwaway git repository (init'd fresh per test in
tmp_path, never this repo's own history) with a real staged diff -- never a hand-built string
handed to an internal helper -- so a passing test proves the actual diff-reading path (git
diff --cached, hunk parsing, AST re-parse of the file on disk) works, not just an isolated
regex. Each REQUIRED negative control from the mission's PROOF section maps to one test; the
REQUIRED positive controls (ordinary non-substitution control flow must not be falsely
rejected) get their own tests alongside. The `repo` fixture seeds a
governance/computation_registry.json declaring which field names are "protected" for THAT
test, proving R4/R8/R9 genuinely derive their protected-field population from the census
(_protected_field_population) rather than a hardcoded name list -- a field left OUT of the
seeded census is proven NOT protected in its own dedicated test below.
"""
from __future__ import annotations

import json
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


def _seed_census(repo: Path, field_names: list[str]) -> None:
    """Seeds governance/computation_registry.json so _protected_field_population() derives
    exactly `field_names` as protected -- proving the population is census-derived, not a
    hardcoded list baked into the lock."""
    reg_dir = repo / "governance"
    reg_dir.mkdir(parents=True, exist_ok=True)
    fields = {name: {"producer": "test.py:x", "kind": "derived"} for name in field_names}
    (reg_dir / "computation_registry.json").write_text(
        json.dumps({"fields": fields}), encoding="utf-8")


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
    monkeypatch.setattr(M, "COMPUTATION_REGISTRY", r / "governance" / "computation_registry.json")
    monkeypatch.setattr(M, "INVENTORY", r / "reports" / "no_fallback_inventory.json")
    _seed_census(r, ["spot", "admitted", "active", "rejected", "surface_seq"])
    return r


def _stage_new_file(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)


def _commit(repo: Path, msg: str) -> None:
    _git(repo, "commit", "-q", "-m", msg)


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


def test_sql_coalesce_substitution_rejected_unconditionally(repo):
    # Operator ruling 2026-09-17: "these are fallback candidates and cannot automatically
    # pass" -- no aggregate/display-label/update-preserve exemption survives.
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


def test_sql_coalesce_over_aggregate_no_longer_exempt_rejected(repo):
    """Operator correction: 'COALESCE(MAX(...), 0)... cannot automatically pass.' The first
    draft treated aggregate-over-empty-set as a confirmed-safe idiom and auto-cleared it --
    that exemption is deleted; this must now be rejected like every other COALESCE."""
    _stage_new_file(repo, "agg.py",
        "def q():\n"
        "    return 'SELECT COALESCE(MAX(snapshot_id), 0) FROM snapshots'\n")
    v = M.violations()
    assert v
    assert "R1_SQL_COALESCE" in _rule_tags(v)


def test_sql_coalesce_display_label_no_longer_exempt_rejected(repo):
    """Operator correction: "COALESCE(field, 'NULL'/'unknown'/other placeholder)... cannot
    automatically pass." The first draft's display-label exemption is deleted."""
    _stage_new_file(repo, "audit.py",
        "def q():\n"
        "    return \"SELECT COALESCE(rules_signal, 'NULL') AS sig FROM snapshots\"\n")
    v = M.violations()
    assert v
    assert "R1_SQL_COALESCE" in _rule_tags(v)


def test_sql_coalesce_update_preserve_no_longer_exempt_rejected(repo):
    """Operator correction: "COALESCE(existing_field, alternate_parameter)... cannot
    automatically pass." The first draft's UPDATE-preserve-existing exemption is deleted."""
    _stage_new_file(repo, "writer.py",
        "def q():\n"
        "    return 'UPDATE users SET enrollment_source = COALESCE(enrollment_source, ?)'\n")
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


def test_removing_a_rule_function_flagged_unconditionally(repo):
    """R5: shrinking this file's own rule functions is ALWAYS flagged -- no bypass string,
    no marker, no co-staged justification of any kind clears it."""
    _stage_new_file(repo, "tools/check_no_fallback_lock.py",
        "def _r1_sql(rel, added):\n    return []\n")
    _commit(repo, "seed lock file")
    (repo / "tools" / "check_no_fallback_lock.py").write_text(
        "# rule removed\n", encoding="utf-8")
    _git(repo, "add", "tools/check_no_fallback_lock.py")
    v = M.violations()
    assert v
    assert "R5_LOCK_WEAKENED" in _rule_tags(v)


def test_deleting_the_lock_file_is_flagged_unconditionally(repo):
    _stage_new_file(repo, "tools/check_no_fallback_lock.py",
        "def _r1_sql(rel, added):\n    return []\n")
    _commit(repo, "seed lock file")
    _git(repo, "rm", "-q", "tools/check_no_fallback_lock.py")
    v = M.violations()
    assert v
    assert "R5_LOCK_WEAKENED" in _rule_tags(v)


def test_deleting_the_computation_registry_is_flagged(repo):
    _git(repo, "add", "governance/computation_registry.json")
    _commit(repo, "commit registry")
    _git(repo, "rm", "-q", "governance/computation_registry.json")
    v = M.violations()
    assert v
    assert "R5_REGISTRY_DELETED" in _rule_tags(v)


def test_deleting_the_inventory_is_flagged(repo):
    inv = repo / "reports" / "no_fallback_inventory.json"
    inv.parent.mkdir(parents=True, exist_ok=True)
    inv.write_text(json.dumps({
        "candidate_count": 1,
        "verdict_counts": {"FALLBACK": 1, "NOT_PROVEN": 0, "NOT_FALLBACK": 0},
        "candidates": [{"id": "FB-aaaaaaaaaa"}],
    }), encoding="utf-8")
    _git(repo, "add", "reports/no_fallback_inventory.json")
    _commit(repo, "seed inventory")
    _git(repo, "rm", "-q", "reports/no_fallback_inventory.json")
    v = M.violations()
    assert v
    assert "R5_INVENTORY_DELETED" in _rule_tags(v)


def test_operator_quote_style_bypass_string_does_nothing(repo):
    """Operator correction: 'an arbitrary operator_quote string must not authorize
    anything.' Proves that writing the literal word 'operator_quote' anywhere in the diff --
    the exact bypass mechanism the first draft implemented -- has NO effect on ANY rule."""
    _stage_new_file(repo, "queries2.py",
        "def q():\n"
        "    # operator_quote: this has been fully authorized by the operator, see below\n"
        "    return \"SELECT COALESCE(canonical_timeframe, '1m') FROM snapshots\"\n"
        "    # operator_quote='operator authorized this on 2026-09-17'\n")
    v = M.violations()
    assert v
    assert "R1_SQL_COALESCE" in _rule_tags(v)


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


def test_pandas_imputation_rejected_unconditionally(repo):
    # Operator ruling 2026-09-17: "the operator did not pre-authorize ML imputation." No
    # registry, no per-file authorization of any kind survives -- every imputation call is
    # rejected, always.
    _stage_new_file(repo, "train.py",
        "def prep(X):\n"
        "    X = X.fillna(0)\n"
        "    return X\n")
    v = M.violations()
    assert v
    assert "R2_IMPUTATION" in _rule_tags(v)


def test_no_file_can_be_marked_authorized_for_imputation(repo):
    """There is no code path left that reads a per-file authorization for imputation --
    proven by writing a file that NAMES itself as authorized in a comment (the shape the
    first draft's registry would have granted) and confirming it is STILL rejected."""
    _stage_new_file(repo, "feature_curation_gate.py",
        "# AUTHORIZED for imputation, operator_quote: 'pre-authorized at mission start'\n"
        "def prep(X):\n"
        "    X = X.fillna(0)\n"
        "    return X\n")
    v = M.violations()
    assert v
    assert "R2_IMPUTATION" in _rule_tags(v)


# ==================== PROTECTED FIELDS ARE CENSUS-DERIVED, NOT HARDCODED ====================

def test_field_outside_the_seeded_census_is_not_protected(repo):
    """The SAME `.get(key, default)` shape used for a required negative control above, but
    on a field name that is NOT in this test's seeded computation_registry.json census --
    proving the protected population genuinely comes from the census (this fixture's own
    _seed_census call), not a name the lock hardcodes internally. (This is not a false-
    positive control for the MANDATE -- a truly unregistered field is NOT_PROVEN territory
    for the baseline census, not a claim it is safe; R8 simply has no basis to single it out
    without a registered producer to point to.)"""
    _stage_new_file(repo, "read2.py",
        "def read(row):\n"
        "    totally_unregistered_widget_count = row.get('totally_unregistered_widget_count', 0)\n"
        "    return totally_unregistered_widget_count\n")
    v = M.violations()
    assert "R8_PY_PROTECTED_FIELD_GET" not in _rule_tags(v)


def test_field_added_to_census_becomes_protected(repo):
    """The inverse of the above: seed a DIFFERENT field into the census and prove the lock
    picks it up with zero code changes -- the population is read fresh from the registry on
    every run."""
    _seed_census(repo, ["dealer_gamma_notional"])
    _stage_new_file(repo, "read3.py",
        "def read(row):\n"
        "    dealer_gamma_notional = row.get('dealer_gamma_notional', 0)\n"
        "    return dealer_gamma_notional\n")
    v = M.violations()
    assert v
    assert "R8_PY_PROTECTED_FIELD_GET" in _rule_tags(v)


def test_level_ids_from_registry_are_also_protected(repo):
    """governance/computation_registry.json fields carry a level_ids list (see the real
    price_level_family_phase2a entry) -- proving those are unioned into the protected
    population too, not just the top-level field key."""
    reg_dir = repo / "governance"
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / "computation_registry.json").write_text(json.dumps({
        "fields": {"price_level_family_phase2a": {
            "producer": "test.py:x", "level_ids": ["PDH", "PDL"]}}
    }), encoding="utf-8")
    _stage_new_file(repo, "read4.py",
        "def read(row):\n"
        "    PDH = row.get('PDH', 0)\n"
        "    return PDH\n")
    v = M.violations()
    assert v
    assert "R8_PY_PROTECTED_FIELD_GET" in _rule_tags(v)


# ============================= BASELINE CENSUS (--measure) =============================

def test_measure_reports_fail_while_fallback_or_not_proven_remain(repo):
    inv_dir = repo / "reports"
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "no_fallback_inventory.json").write_text(json.dumps({
        "candidate_count": 10,
        "verdict_counts": {"FALLBACK": 2, "NOT_PROVEN": 3, "NOT_FALLBACK": 5},
    }), encoding="utf-8")
    m = M.measure_baseline()
    assert m["fallback"] == 2
    assert m["not_proven"] == 3


def test_measure_reports_pass_only_when_both_counts_are_zero(repo):
    inv_dir = repo / "reports"
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "no_fallback_inventory.json").write_text(json.dumps({
        "candidate_count": 10,
        "verdict_counts": {"FALLBACK": 0, "NOT_PROVEN": 0, "NOT_FALLBACK": 10},
    }), encoding="utf-8")
    m = M.measure_baseline()
    assert m["fallback"] == 0 and m["not_proven"] == 0


def test_measure_fails_closed_when_inventory_is_missing(repo):
    # No reports/no_fallback_inventory.json written at all -- must report an error, never
    # silently read as "zero findings".
    m = M.measure_baseline()
    assert "error" in m


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
