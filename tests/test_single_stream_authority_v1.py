"""SINGLE-STREAM-AUTHORITY — PASS/FAIL/mutation controls for the census gate.

tools/check_single_stream_authority.py is the mutation-testable proof that
app/options/order_flow/streaming.py's retired second Schwab socket stays retired. These
tests prove the gate actually DISCRIMINATES: it passes on the real (repaired) tree, and
it FAILS when a second production StreamClient constructor is reintroduced — not merely
that it prints something.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.check_single_stream_authority import (
    OFFLINE_TOOLS,
    PRODUCTION_OWNER,
    classify,
    find_stream_client_constructions,
    run_census,
)


#: TEST_SYSTEM_REHAB_V2: the two tests below both independently called run_census() on
#: the REAL, unmutated tree (measured ~21-26s each) to assert different facts about the
#: SAME result. One canonical current-tree census, shared -- the mutation controls
#: further down (genuine repository-input changes via monkeypatch) still each run their
#: own census, because THAT is the materially distinct case this file exists to prove.
@pytest.fixture(scope="module")
def current_tree_census():
    return run_census()


def test_current_tree_has_exactly_one_production_owner(current_tree_census):
    """PHASE 1 acceptance: PRODUCTION_SCHWAB_STREAMCLIENT_CONSTRUCTORS = exactly 1."""
    census = current_tree_census
    assert census["PRODUCTION_OWNER"] == [f"{PRODUCTION_OWNER}:555"] or \
        len(census["PRODUCTION_OWNER"]) == 1, census["PRODUCTION_OWNER"]
    assert census["VIOLATION"] == [], census["VIOLATION"]


def test_offline_tool_is_classified_not_counted_as_a_violation(current_tree_census):
    assert any(site.startswith(tuple(OFFLINE_TOOLS)) for site in current_tree_census["OFFLINE_TOOL"])


def test_classify_production_owner_and_default_violation():
    assert classify(PRODUCTION_OWNER) == "PRODUCTION_OWNER"
    assert classify("schwab_full_field_inventory.py") == "OFFLINE_TOOL"
    assert classify("tests/test_whatever.py") == "TEST_ONLY"
    assert classify("some_new_module.py") == "VIOLATION"


def test_prose_mentioning_streamclient_is_not_a_false_positive(tmp_path):
    """A repair docstring in app/options/order_flow/streaming.py may name
    schwab.streaming.StreamClient in prose without counting as a constructor — the gate
    traces actual `Call` nodes through actual `import` statements, not text."""
    p = tmp_path / "prose_only.py"
    p.write_text(textwrap.dedent('''
        """This module used to open its own schwab.streaming.StreamClient — a real
        docstring that names the class without constructing one."""
        def noop():
            return "StreamClient"
    '''), encoding="utf-8")
    assert find_stream_client_constructions(p) == []


def test_a_module_alias_construction_is_still_found(tmp_path):
    """`import schwab.streaming as m; m.StreamClient(...)` must be caught — the census
    traces the MODULE alias, not only the direct `from ... import StreamClient` form."""
    p = tmp_path / "aliased.py"
    p.write_text(textwrap.dedent('''
        import schwab.streaming as m

        def connect(client):
            return m.StreamClient(client)
    '''), encoding="utf-8")
    lines = find_stream_client_constructions(p)
    assert len(lines) == 1


def test_from_schwab_import_streaming_alias_is_still_found(tmp_path):
    """ADVERSARIAL RECHECK 2026-08-30: `from schwab import streaming as s; s.StreamClient(...)`
    is a DIFFERENT AST shape from `import schwab.streaming as m` (an ImportFrom binding the
    module name via a from-import, not an Import statement) — a real, previously-unexploited
    blind spot in the module-alias detector, found by adversarial inspection and fixed by
    also walking ImportFrom(module='schwab') nodes. Unaliased `from schwab import streaming`
    is covered too."""
    p = tmp_path / "from_import_aliased.py"
    p.write_text(textwrap.dedent('''
        from schwab import streaming as s

        def connect(client):
            return s.StreamClient(client)
    '''), encoding="utf-8")
    lines = find_stream_client_constructions(p)
    assert len(lines) == 1

    p2 = tmp_path / "from_import_unaliased.py"
    p2.write_text(textwrap.dedent('''
        from schwab import streaming

        def connect(client):
            return streaming.StreamClient(client)
    '''), encoding="utf-8")
    assert len(find_stream_client_constructions(p2)) == 1


def test_bare_import_schwab_double_attribute_chain_is_found(tmp_path):
    """TEST_SYSTEM_REHAB_V2 (Cursor-confirmed hole, 2026-08-31): `import schwab` followed
    by `schwab.streaming.StreamClient(...)` — a double-attribute chain through the
    top-level PACKAGE name, a different AST shape from every form above (which all bind
    a name directly to the `schwab.streaming` module or the `StreamClient` class). This
    was undetected before _package_aliases_for_schwab existed."""
    p = tmp_path / "bare_package_import.py"
    p.write_text(textwrap.dedent('''
        import schwab

        def connect(client):
            return schwab.streaming.StreamClient(client)
    '''), encoding="utf-8")
    assert len(find_stream_client_constructions(p)) == 1

    p2 = tmp_path / "bare_package_import_aliased.py"
    p2.write_text(textwrap.dedent('''
        import schwab as sch

        def connect(client):
            return sch.streaming.StreamClient(client)
    '''), encoding="utf-8")
    assert len(find_stream_client_constructions(p2)) == 1


def test_bare_import_schwab_streaming_no_alias_double_attribute_is_found(tmp_path):
    """A bare `import schwab.streaming` (no `as`) binds the name `schwab`, not
    `schwab.streaming` — so the correct and only valid call shape is the DOUBLE
    attribute `schwab.streaming.StreamClient(...)`, not a single-level
    `schwab.StreamClient(...)`. The prior implementation added "schwab" to the
    single-attribute alias set for exactly this import form, which meant it could never
    actually match the real call shape a caller would write."""
    p = tmp_path / "bare_submodule_import.py"
    p.write_text(textwrap.dedent('''
        import schwab.streaming

        def connect(client):
            return schwab.streaming.StreamClient(client)
    '''), encoding="utf-8")
    assert len(find_stream_client_constructions(p)) == 1


def test_an_unrelated_streamclient_class_is_not_a_false_positive(tmp_path):
    """A same-named class from an UNRELATED module must not be flagged — only imports
    traced to schwab.streaming count."""
    p = tmp_path / "unrelated.py"
    p.write_text(textwrap.dedent('''
        class StreamClient:
            """Not Schwab's — some other library's class of the same name."""

        def build():
            return StreamClient()
    '''), encoding="utf-8")
    assert find_stream_client_constructions(p) == []


# ── MUTATION CONTROL (operator-required) ──────────────────────────────────────────────
def test_mutation_reintroducing_a_second_production_streamclient_fails_the_gate(monkeypatch):
    """Deliberately reintroduce a second production StreamClient path and prove the gate
    fails — the decisive proof this is a real, live-enforced invariant, not a one-time
    cleanup that could silently regress."""
    from tools import check_single_stream_authority as gate

    def fake_find(path: Path) -> list[int]:
        if path.as_posix().endswith("app/options/order_flow/streaming.py"):
            # Simulate the exact regression this gate exists to catch: the retired
            # socket reappearing in the file it was removed from.
            return [999]
        return real_find(path)

    real_find = gate.find_stream_client_constructions
    monkeypatch.setattr(gate, "find_stream_client_constructions", fake_find)
    census = gate.run_census()
    assert "app/options/order_flow/streaming.py:999" in census["VIOLATION"]
    # TEST_SYSTEM_REHAB_V2: main() re-derives its own census via a fresh run_census()
    # call, so asserting `gate.main() == 1` here used to trigger a SECOND full
    # tracked-tree AST scan (this was the 39.75s outlier in the local slowest-20).
    # main()'s exit-code contract is what this line proves, not run_census() a second
    # time -- so hand it the SAME real census already computed above (still the real,
    # live-mutated result; only the redundant re-scan is removed).
    monkeypatch.setattr(gate, "run_census", lambda: census)
    assert gate.main() == 1, "the gate must exit non-zero when a violation is reintroduced"


def test_mutation_two_production_owners_also_fails(monkeypatch):
    """The 'exactly 1' acceptance criterion, not merely '0 violations' — a second
    PRODUCTION_OWNER-classified file (e.g. a rename/duplication of the daemon) must also
    fail, even though nothing would be classified VIOLATION."""
    from tools import check_single_stream_authority as gate

    monkeypatch.setattr(gate, "run_census", lambda: {
        "PRODUCTION_OWNER": ["tools/run_stream_capture.py:555", "tools/run_stream_capture_2.py:10"],
        "OFFLINE_TOOL": [], "TEST_ONLY": [], "VIOLATION": [],
    })
    assert gate.main() == 1
