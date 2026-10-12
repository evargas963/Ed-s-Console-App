"""The console's build identity route."""

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
