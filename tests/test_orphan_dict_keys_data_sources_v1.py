"""RC-384 — the orphan-key check must search everywhere this repo can legitimately write.

check_no_orphan_dict_keys proves a NEGATIVE ("nothing writes this key") from a Python-only
AST walk. This repo also writes keys in COMMITTED data files that Python reads by name, so
three keys in active_bundle_contract — legacy_allowance, expires_at_utc, strict_default,
all written in config/ML_ITEM4_MIGRATION_POLICY.json — were reported as silent-None
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








def test_the_check_did_not_go_blind_a_genuine_orphan_is_still_reported(tmp_path, monkeypatch):
    """The load-bearing negative control: widening the SEARCH must not widen the EXEMPTIONS.

    Driven on a CONSTRUCTED population, not on a count of the live tree's orphans: the
    `len(violations) > 100` pin this replaced measured the tree's history, not the check's
    sight — it failed on 2026-09-10 when unrelated deletions left exactly 100 (RC-549)."""
    prod = tmp_path / "prod"
    prod.mkdir()
    writer, reader = prod / "writer.py", prod / "reader.py"
    writer.write_text('def produce():\n    return {"zz_written_key": 1}\n', encoding="utf-8")
    reader.write_text(
        'def consume(d):\n    return d.get("zz_written_key"), d.get("zz_orphan_key"), d.get("strict_default")\n',
        encoding="utf-8")
    monkeypatch.setattr(GATE, "_production_py_files", lambda: [reader, writer])
    reported = {v.msg.split("key '", 1)[1].split("'", 1)[0] for v in GATE.check_no_orphan_dict_keys()}
    assert "zz_orphan_key" in reported, "a key nothing writes went unreported — the check is blind"
    assert "zz_written_key" not in reported, "a key the population writes was reported — a false positive"
    assert "strict_default" in reported, (
        "a policy-file key excuses a read ONLY in its named reader; in an unlisted reader it is still an orphan")




def test_a_key_in_an_unlisted_committed_json_is_still_reported(tmp_path, monkeypatch):
    """Proves the harvest is bounded by the allowlist rather than by 'is it JSON'."""
    harvested = GATE._committed_data_file_keys()
    # A key that exists in committed JSON elsewhere in the tree (the ablation registry)
    # but is NOT in an allowlisted source must not be harvested.
    assert "catalog_tier" not in harvested, (
        "a key from an unlisted committed JSON leaked into the write set — the allowlist "
        "is not bounding the harvest")












