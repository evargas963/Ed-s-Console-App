"""The console's build identity route, and the launcher's port guard."""

from __future__ import annotations

from pathlib import Path


















def test_api_build_exposes_git_sha():
    """git_sha is the process's startup identity; the checkout's HEAD now is served apart, under
    repository_state_now.repo_head_now (read here from the checkout with git)."""
    import subprocess

    import server as srv

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(srv.__file__).resolve().parent,
                          capture_output=True, text=True, check=True).stdout.strip()
    body = srv.api_build()
    assert body["git_sha"] == body["process_identity"]["startup_git_sha"]
    assert body["repository_state_now"]["repo_head_now"] == head
    assert body["git_sha_semantics"] == "startup_process_identity"
    assert body["contract"] == "meet_or_exceed_v1"




def test_the_port_guard_refuses_an_occupied_port_and_passes_a_free_one():
    """The launcher's port guard, run as a subprocess against a bound port (an occupant that is
    not an Ed Console server -> exit 1, refuse) and a free port (-> exit 0, proceed)."""
    import socket
    import subprocess
    import sys

    root = Path(__file__).resolve().parent.parent
    guard = str(root / "launcher_port_guard.py")
    venv_py = sys.executable  # virtualenv-parity gate guarantees this is the repo .venv python

    busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    busy_port = busy.getsockname()[1]
    try:
        occ = subprocess.run([venv_py, guard, str(busy_port)], capture_output=True, text=True)
    finally:
        busy.close()
    assert occ.returncode == 1, (
        f"launcher_port_guard must report an unrecognized occupant as exit 1: {occ.stdout}"
    )

    free = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    free.bind(("127.0.0.1", 0))
    free_port = free.getsockname()[1]
    free.close()
    fr = subprocess.run([venv_py, guard, str(free_port)], capture_output=True, text=True)
    assert fr.returncode == 0, f"launcher_port_guard must report a free port as exit 0: {fr.stdout}"
