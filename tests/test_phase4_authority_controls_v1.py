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
#: test_stream_capture_daemon_v1.py::test_owner_lock_released_on_every_exit_path (D) and
#: ::test_schwab_connect_registers_book_handlers_every_time (E). Deleted; their
#: traceability now lives in those tests' own names/docstrings.


def test_F_reconnect_after_recycle_has_no_concurrent_authorities():
    """F. canonical owner reconnect after a half-open socket -> PASS without creating
    concurrent old/new authorities.

    STRENGTHENED. This used to index _run_streaming's SOURCE TEXT for "pump_task.cancel()"
    ahead of "_schwab_connect(". That pinned a spelling, not a behaviour: it broke as soon
    as the cancellation moved into a named helper, and it never covered the authority that
    actually outlived a generation — the poll/control tasks, which kept issuing vendor
    operations on a retired session after the replacement was already live.

    "No concurrent authorities" is now a proven RUNTIME property of the real recycle; the
    behavioural proofs live in test_stream_capture_daemon_v1.py::
    test_d1_a_stale_generation_tick_cannot_mutate_the_next_generation,
    ::test_1c_a_stale_book_poll_tick_cannot_mutate_after_a_recycle,
    ::test_recycle_retires_the_old_generation_before_the_replacement_is_built and
    ::test_d3d_at_most_one_live_logged_in_session_across_the_whole_lifecycle (which
    carries its own mutation control). What this test keeps is the structural guarantee
    those depend on: the recycle retires the whole generation BEFORE it reconnects, and
    the retirement actually awaits what it cancels."""
    import app.market_data.schwab.streaming.capture as d
    src = inspect.getsource(d._run_streaming)
    retire_at = src.index("_retire_stream_generation(")
    reconnect_at = src.index("_schwab_connect(", retire_at)
    assert retire_at < reconnect_at, (
        "the recycle must retire the whole old generation before building its replacement")
    # cancel() alone only SCHEDULES cancellation; until awaited, a tick suspended inside a
    # vendor operation can still resume and mutate the next generation's state.
    cancel_src = inspect.getsource(d._cancel_and_await)
    assert ".cancel()" in cancel_src and "await t" in cancel_src
    gen_src = inspect.getsource(d._retire_stream_generation)
    assert gen_src.index("control_tasks") < gen_src.index("(pump_task,)"), (
        "control tasks must be retired FIRST: they are the ones that can be suspended "
        "inside a vendor await and resume into the next generation's state")


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
        "VIOLATION": ["app/options/order_flow/streaming.py:999"],
    }
    try:
        assert gate.main() == 1
    finally:
        gate.run_census = orig
