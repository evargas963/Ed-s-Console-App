"""PHASE 4 — negative/positive controls for single-stream-authority, one test per
operator-lettered requirement, so the evidence packet has a direct 1:1 pointer.

Each test below is a thin, explicitly-labeled wrapper over mechanisms proven in
tests/test_single_stream_authority_v1.py, tests/test_simple_daemon_v1.py, and
tests/test_daemon_plane_feed_v1.py — this file exists for TRACEABILITY (which test
proves which lettered requirement), not to duplicate their assertions.
"""

from __future__ import annotations

import ast
import inspect

import app.options.order_flow.streaming as ofs

#: TEST_SYSTEM_REHAB_V2: requirement-letter A was a fresh run_census() call asserting
#: the EXACT same fact (census["VIOLATION"] == []) as
#: test_single_stream_authority_v1.py::test_current_tree_has_exactly_one_production_owner
#: already proves — a real, expensive (~15-20s) duplicate whole-tree census, not a
#: distinct check. Requirement A's traceability now lives in that test's own name/
#: docstring instead of a second executable census.


def test_B_server_startup_path_has_no_streamclient_constructor():
    """B. direct server startup path attempts StreamClient -> BLOCK / constructor
    unreachable under canonical architecture. Structural, not behavioral: the import
    does not exist, so there is no code path to reach."""
    src = inspect.getsource(ofs)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "schwab.streaming"


def test_C_mutation_alternate_factory_is_caught():
    """C. alternate helper/factory creates Schwab StreamClient -> BLOCK.
    See test_single_stream_authority_v1.py::test_mutation_reintroducing_a_second_
    production_streamclient_fails_the_gate for the full mutation proof; re-asserted here
    under its operator letter for direct traceability."""
    from tools import check_single_stream_authority as gate

    def fake_find(path):
        if path.name == "some_new_helper.py":
            return [1]
        return []

    orig_find = gate.find_stream_client_constructions
    orig_tracked = gate._tracked_python
    gate.find_stream_client_constructions = fake_find
    gate._tracked_python = lambda: ["some_new_helper.py"]
    try:
        census = gate.run_census()
        assert census["VIOLATION"] == ["some_new_helper.py:1"]
    finally:
        gate.find_stream_client_constructions = orig_find
        gate._tracked_python = orig_tracked


#: TEST_SYSTEM_REHAB_V2: requirement letters D and E were callable()/iscoroutinefunction()
#: existence checks — existence is not runtime correctness. Both docstrings named the
#: real behavioral proof already covering them (verified present, not just claimed):
#: test_simple_daemon_v1.py::test_one_daemon_at_a_time_and_a_dead_owners_lock_is_reclaimed (D)
#: and ::test_a_dying_connection_is_replaced_and_everything_wanted_is_resubscribed (E).


def test_G_live_plane_consumes_transported_observations_no_schwab_socket():
    """G. server/live plane continues consuming transported observations -> PASS
    without opening Schwab socket. See test_daemon_plane_feed_v1.py for the full
    hydration proof (L1 + book rows replay into app.options.order_flow.state/live_market_plane)."""
    src = inspect.getsource(ofs)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Import)
                   and any(a.name.split(".")[0] == "schwab" for a in node.names))


def test_mutation_control_the_gate_actually_discriminates():
    """The decisive mission requirement: deliberately reintroduce a second production
    StreamClient path and prove the gate/test fails. Full proof in
    test_single_stream_authority_v1.py::
    test_mutation_reintroducing_a_second_production_streamclient_fails_the_gate and
    ::test_mutation_two_production_owners_also_fails. Re-invoked here directly."""
    from tools import check_single_stream_authority as gate

    orig = gate.run_census
    gate.run_census = lambda: {
        "PRODUCTION_OWNER": ["tools/run_stream_capture.py:555"],
        "TEST_ONLY": [],
        "VIOLATION": ["app/options/order_flow/streaming.py:999"],
    }
    try:
        assert gate.main() == 1
    finally:
        gate.run_census = orig
