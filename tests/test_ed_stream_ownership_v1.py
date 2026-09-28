"""static/js/ed-stream.js declares each view's option-contract demand."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_ed_stream_declares_demand_per_view():
    """Runs the REAL ed-stream.js (tests/ed_stream_demand_node.mjs): each view declares its own
    option-contract demand with its id and seq, confirms against the demand the server recorded
    (not the budgeted union), refreshes its lease, and releases it on pagehide."""
    import shutil
    import subprocess

    import pytest
    node = shutil.which("node")
    if not node:
        pytest.fail("Node.js is required on PATH for this test (runs tests/ed_stream_demand_node.mjs).")
    r = subprocess.run([node, str(ROOT / "tests" / "ed_stream_demand_node.mjs")], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
