"""RC-384 — the orphan-key check must search everywhere this repo can legitimately write.

check_no_orphan_dict_keys proves a NEGATIVE ("nothing writes this key") from a Python-only
AST walk. This repo also writes keys in COMMITTED data files that Python reads by name, so
three keys in active_bundle_contract — legacy_allowance, expires_at_utc, strict_default,
all written in governance/ML_ITEM4_MIGRATION_POLICY.json — were reported as silent-None
candidates although the repo writes every one of them.

The danger in fixing this is obvious and is what these tests pin down: it would be easy to
"fix" the count by globbing every .json in the tree, which would absorb reports/, fixtures
and vendor captures, invent a writer for almost any string, and blind the check to the real
RC-15/RC-20 bugs it exists to find. So the allowlist is explicit, and the controls below
prove the check can still SEE — a key nobody writes is still reported, and a key living in
an unlisted committed JSON is still reported.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

TURN_AUDIT_OWNS = ["tools/check_institutional_correctness.py"]


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "cic_rc384", REPO / "tools" / "check_institutional_correctness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load_gate()

POLICY_KEYS = ("legacy_allowance", "expires_at_utc", "strict_default")

#: TEST_SYSTEM_REHAB_V2: the pure-read tests below now consume the SAME session-scoped
#: `live_orphans` fixture (tests/conftest.py) test_money_path_orphan_keys_v1.py uses --
#: both files independently sweeping the whole production tree via check_no_orphan_dict_keys()
#: was genuine duplicate cost (measured ~26-37s each). `GATE` (this file's isolated
#: `_load_gate()` module copy) stays: test_a_missing_or_malformed_source_contributes_nothing
#: monkeypatches GATE._DATA_FILE_KEY_SOURCES, and that mutation must never leak into the
#: normally-imported module every other test file shares -- an isolated copy is the
#: correct, minimal way to get that, not redundant computation.


def test_the_policy_file_actually_contains_the_keys_we_claim():
    """Ground the whole row in the artifact, not in the checker's opinion of it."""
    policy = json.loads(
        (REPO / "governance" / "ML_ITEM4_MIGRATION_POLICY.json").read_text(encoding="utf-8"))
    assert "legacy_allowance" in policy
    assert "strict_default" in policy
    assert "expires_at_utc" in policy["legacy_allowance"], "nested keys must be harvested too"


def test_keys_written_in_the_allowlisted_policy_are_harvested():
    harvested = GATE._committed_data_file_keys()
    for key in POLICY_KEYS:
        assert key in harvested, f"{key} is written in the policy file but was not harvested"


def test_the_three_policy_reads_are_no_longer_reported(live_orphans):
    reported = {
        str(v.path).replace("\\", "/") for v in live_orphans
    }
    assert not any(p.endswith("active_bundle_contract.py") for p in reported), (
        "the policy-backed reads are still flagged as orphans")


def test_the_check_did_not_go_blind_a_genuine_orphan_is_still_reported(live_orphans):
    """The load-bearing negative control: widening the SEARCH must not widen the EXEMPTIONS."""
    violations = live_orphans
    assert len(violations) > 100, (
        f"only {len(violations)} orphans reported — the check has been blinded, not fixed")


def test_the_allowlist_is_explicit_not_a_glob():
    """A blanket scan would invent a writer for almost any string. Keep it named."""
    sources = GATE._DATA_FILE_KEY_SOURCES
    assert len(sources) <= 5, f"allowlist is growing into a glob: {sources}"
    for rel, loader in sources:
        assert (REPO / rel).is_file(), f"allowlisted source does not exist: {rel}"
        assert loader, f"{rel} must name the loader that reads it"
        assert (REPO / loader).is_file(), f"named reader does not exist: {loader}"
        assert not any(ch in rel for ch in "*?["), f"glob pattern in allowlist: {rel}"
        assert not any(ch in loader for ch in "*?["), f"glob pattern in reader: {loader}"


def test_a_key_in_an_unlisted_committed_json_is_still_reported(tmp_path, monkeypatch):
    """Proves the harvest is bounded by the allowlist rather than by 'is it JSON'."""
    harvested = GATE._committed_data_file_keys()
    # A key that exists in committed JSON elsewhere in the tree (the ablation registry)
    # but is NOT in an allowlisted source must not be harvested.
    assert "catalog_tier" not in harvested, (
        "a key from an unlisted committed JSON leaked into the write set — the allowlist "
        "is not bounding the harvest")


def test_generic_keys_in_the_policy_file_are_not_global_writes():
    """The pre-scope harvest dumped dir/enabled/note into the global write set.
    Those names exist in the policy file; they must not count as written everywhere."""
    harvested = GATE._committed_data_file_keys()
    for generic in ("dir", "note", "rule", "FORBIDDEN", "reverify_ttl_seconds_default"):
        assert generic not in harvested, (
            f"{generic!r} was harvested from the policy file as a global write — "
            f"the glob failure at file scope (RC-384 Cursor audit)")


def test_data_file_credit_is_scoped_to_the_named_reader():
    """A policy key excuses a read in active_bundle_contract.py only, not elsewhere."""
    policy = GATE._data_file_keys_for("active_bundle_contract.py")
    calendar = GATE._data_file_keys_for("v2_decision/a2_session_calendar.py")
    other = GATE._data_file_keys_for("news_sentiment.py")
    assert "strict_default" in policy
    assert "strict_default" not in calendar
    assert "strict_default" not in other
    assert "valid_through_date" in calendar
    assert "valid_through_date" not in policy
    assert other == set()


def test_calendar_reads_are_no_longer_reported(live_orphans):
    reported = {
        str(v.path).replace("\\", "/") for v in live_orphans
    }
    assert not any(p.endswith("a2_session_calendar.py") for p in reported), (
        "the calendar-backed reads are still flagged as orphans")


def test_micro_5m_headline_is_a_stale_name_not_a_missing_producer(live_orphans):
    """The 5-minute micro signal ships as rules_headline (headline_5m -> RulesCard.headline)."""
    rules = (REPO / "rules_engine.py").read_text(encoding="utf-8")
    assert "headline=micro.headline_5m" in rules
    adapter = (REPO / "v2_decision" / "module_a_adapter.py").read_text(encoding="utf-8")
    html = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    assert 'ms.get("micro_5m_headline")' not in adapter
    assert "d.micro_5m_headline" not in html
    reported_keys = []
    for v in live_orphans:
        if "key '" in v.msg:
            reported_keys.append(v.msg.split("key '", 1)[1].split("'", 1)[0])
    assert "micro_5m_headline" not in reported_keys


def test_two_never_written_fallback_spellings_are_gone(live_orphans):
    """Same proof as lstm_1c_sha256: git log -S '\"key\":' empty, so the OR was dead."""
    src = (REPO / "v2_decision" / "a2_option_expression.py").read_text(encoding="utf-8")
    assert 'ms_dict.get("minutes_to_close")' not in src
    assert 'ms_dict.get("timestamp_ms")' not in src
    reported_keys = []
    for v in live_orphans:
        if "key '" in v.msg:
            reported_keys.append(v.msg.split("key '", 1)[1].split("'", 1)[0])
    assert "minutes_to_close" not in reported_keys
    assert "timestamp_ms" not in reported_keys


def test_a_missing_or_malformed_source_contributes_nothing(monkeypatch, tmp_path):
    """Absence must never widen what counts as written."""
    monkeypatch.setattr(
        GATE, "_DATA_FILE_KEY_SOURCES",
        (("governance/DOES_NOT_EXIST.json", "nobody.py"),
         ("governance/ML_ITEM4_MIGRATION_POLICY.json", "active_bundle_contract.py")),
    )
    harvested = GATE._committed_data_file_keys()
    assert "strict_default" in harvested, "the valid source must still be harvested"
    assert harvested, "a missing source must not empty the harvest"
