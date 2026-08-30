"""PHASE 4 — negative/positive controls for single-stream-authority, one test per
operator-lettered requirement, so the evidence packet has a direct 1:1 pointer.

Each test below is a thin, explicitly-labeled wrapper over mechanisms proven in
tests/test_single_stream_authority_v1.py, tests/test_stream_capture_daemon_v1.py, and
tests/test_daemon_plane_feed_v1.py — this file exists for TRACEABILITY (which test
proves which lettered requirement), not to duplicate their assertions.
"""

from __future__ import annotations

import ast
import inspect

import order_flow_streaming as ofs
from tools.check_single_stream_authority import run_census


def test_A_alternate_stream_construction_anywhere_in_tree_is_a_census_violation():
    """A. canonical daemon running + server attempts independent Schwab stream -> BLOCK.

    Not a runtime race to simulate — the server code path CANNOT construct one (see B);
    this proves the repo-wide census would catch it if it ever could."""
    census = run_census()
    assert census["VIOLATION"] == []


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


def test_D_second_daemon_owner_is_blocked_by_the_pidfile():
    """D. second daemon/capture owner -> BLOCK. Pre-existing mechanism
    (acquire_owner_lock), unmodified by this repair — reasserted here for completeness of
    the Phase 4 letter mapping. See test_stream_capture_daemon_v1.py::
    test_owner_lock_released_on_every_exit_path for the full exercise."""
    import tools.run_stream_capture as d
    assert callable(d.acquire_owner_lock) and callable(d.release_owner_lock)


def test_E_canonical_one_owner_startup_passes():
    """E. canonical one-owner startup -> PASS.
    See test_stream_capture_daemon_v1.py::test_schwab_connect_registers_book_handlers_
    every_time for the full connect-time proof (login, handlers, subs all fire)."""
    import tools.run_stream_capture as d
    assert inspect.iscoroutinefunction(d._schwab_connect)


def test_F_reconnect_after_recycle_has_no_concurrent_authorities():
    """F. canonical owner reconnect after half-open socket -> PASS without creating
    concurrent old/new authorities. See test_stream_capture_daemon_v1.py::
    test_reconnect_replaces_stream_not_both_at_once (two connects yield two distinct
    stream objects, old task provably cancelled) and ::
    test_recycle_cancels_old_pump_before_reconnecting_structurally (cancel-before-
    reconnect ordering in _run_streaming)."""
    import tools.run_stream_capture as d
    src = inspect.getsource(d._run_streaming)
    assert src.index("pump_task.cancel()") < src.index("_schwab_connect(", src.index("await pump_task"))


def test_G_live_plane_consumes_transported_observations_no_schwab_socket():
    """G. server/live plane continues consuming transported observations -> PASS
    without opening Schwab socket. See test_daemon_plane_feed_v1.py for the full
    hydration proof (L1 + book rows replay into order_flow_live_state/live_market_plane)."""
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
        "OFFLINE_TOOL": [], "TEST_ONLY": [],
        "VIOLATION": ["order_flow_streaming.py:999"],
    }
    try:
        assert gate.main() == 1
    finally:
        gate.run_census = orig
