"""SINGLE-STREAM-AUTHORITY — PASS/FAIL/mutation controls for the census gate.

tools/check_single_stream_authority.py is the mutation-testable proof that
order_flow_streaming.py's retired second Schwab socket stays retired. These tests prove
the gate actually DISCRIMINATES: it passes on the real (repaired) tree, and it FAILS when
a second production StreamClient constructor is reintroduced — not merely that it prints
something.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tools.check_single_stream_authority import (
    OFFLINE_TOOLS,
    PRODUCTION_OWNER,
    classify,
    find_stream_client_constructions,
    run_census,
)


def test_current_tree_has_exactly_one_production_owner():
    """PHASE 1 acceptance: PRODUCTION_SCHWAB_STREAMCLIENT_CONSTRUCTORS = exactly 1."""
    census = run_census()
    assert census["PRODUCTION_OWNER"] == [f"{PRODUCTION_OWNER}:555"] or \
        len(census["PRODUCTION_OWNER"]) == 1, census["PRODUCTION_OWNER"]
    assert census["VIOLATION"] == [], census["VIOLATION"]


def test_offline_tool_is_classified_not_counted_as_a_violation():
    census = run_census()
    assert any(site.startswith(tuple(OFFLINE_TOOLS)) for site in census["OFFLINE_TOOL"])


def test_classify_production_owner_and_default_violation():
    assert classify(PRODUCTION_OWNER) == "PRODUCTION_OWNER"
    assert classify("schwab_full_field_inventory.py") == "OFFLINE_TOOL"
    assert classify("tests/test_whatever.py") == "TEST_ONLY"
    assert classify("some_new_module.py") == "VIOLATION"


def test_prose_mentioning_streamclient_is_not_a_false_positive(tmp_path):
    """A docstring that explains this repair (order_flow_streaming.py's own module
    docstring names schwab.streaming.StreamClient in prose) must not be counted — the
    gate traces actual `Call` nodes through actual `import` statements, not text."""
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
        if path.name == "order_flow_streaming.py":
            # Simulate the exact regression this gate exists to catch: the retired
            # socket reappearing in the file it was removed from.
            return [999]
        return real_find(path)

    real_find = gate.find_stream_client_constructions
    monkeypatch.setattr(gate, "find_stream_client_constructions", fake_find)
    try:
        census = gate.run_census()
        assert "order_flow_streaming.py:999" in census["VIOLATION"]
        assert gate.main() == 1, "the gate must exit non-zero when a violation is reintroduced"
    finally:
        pass   # monkeypatch fixture would undo automatically; explicit for clarity


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
