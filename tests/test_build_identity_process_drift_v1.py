"""BUILD_IDENTITY_PROCESS_DRIFT_V1 — immutable process-start identity tests.

Proves the root-cause fix: /api/build's process identity is captured once at
module import and cannot drift when repository HEAD moves afterwards; the
request-time repository read feeds only the separately named
repository_state_now diagnostic (and the legacy top-level git_sha
compatibility field, which stays dynamic by existing contract —
tests/test_batch2_analytics_bg_fail_counter.py::test asserts a monkeypatched
_repo_git_head_sha flows through git_sha per request).
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server as srv  # noqa: E402

SHA_A_MSG = "identity commit A"
SHA_B_MSG = "identity commit B"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=30.0
    )
    return (proc.stdout or "").strip()


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    """Isolated temp git repo at commit A — never the primary working repo."""
    repo = tmp_path / "identrepo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@test.local")
    _git(repo, "config", "user.name", "identity-test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "a.txt").write_text("A\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", SHA_A_MSG, "--no-verify")
    return repo, _git(repo, "rev-parse", "HEAD")


def _advance_repo(repo: Path) -> str:
    (repo / "b.txt").write_text("B\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", SHA_B_MSG, "--no-verify")
    return _git(repo, "rev-parse", "HEAD")


def _capture_at(monkeypatch, repo: Path):
    monkeypatch.setattr(srv, "APP_DIR", str(repo))
    return srv._capture_process_identity()


# ── T1 + runtime drift: startup SHA A immutable while repo moves to SHA B ────


def test_t1_startup_sha_immutable_across_repo_drift(tmp_path, monkeypatch):
    repo, sha_a = _make_repo(tmp_path)
    ident = _capture_at(monkeypatch, repo)
    assert ident.startup_git_sha == sha_a
    assert ident.startup_git_available is True
    assert ident.identity_source == "git_startup_capture"

    sha_b = _advance_repo(repo)
    assert sha_b != sha_a

    monkeypatch.setattr(srv, "PROCESS_IDENTITY_V1", ident)
    with TestClient(srv.app) as client:
        body = client.get("/api/build").json()
    assert body["process_identity"]["startup_git_sha"] == sha_a
    assert body["repository_state_now"]["repo_head_now"] == sha_b
    # BUILD_IDENTITY semantics (operator-approved 2026-07-10): git_sha IS the
    # startup process identity; drift is reported explicitly instead.
    assert body["git_sha"] == sha_a
    assert body["code_drift"]["repo_moved_past_process"] is True


# ── T2: repeated calls never recapture/replace process identity ──────────────


def test_t2_no_request_time_replacement(tmp_path, monkeypatch):
    repo, sha_a = _make_repo(tmp_path)
    ident = _capture_at(monkeypatch, repo)
    monkeypatch.setattr(srv, "PROCESS_IDENTITY_V1", ident)

    heads = iter(["b" * 40, "c" * 40, "d" * 40])
    monkeypatch.setattr(srv, "_repo_git_head_sha", lambda: next(heads))

    bodies = []
    with TestClient(srv.app) as client:
        for _ in range(3):
            bodies.append(client.get("/api/build").json())
    pi_serialized = {json.dumps(b["process_identity"], sort_keys=True) for b in bodies}
    assert len(pi_serialized) == 1  # byte-stable immutable block
    assert [b["repository_state_now"]["repo_head_now"] for b in bodies] == [
        "b" * 40, "c" * 40, "d" * 40,
    ]


# ── T3/T4: dirty and clean tree truthfulness ─────────────────────────────────


def test_t3_dirty_tree_startup_truthful(tmp_path, monkeypatch):
    repo, sha_a = _make_repo(tmp_path)
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")  # untracked counts as dirty
    ident = _capture_at(monkeypatch, repo)
    assert ident.startup_git_sha == sha_a
    assert ident.startup_git_dirty is True


def test_t4_clean_tree_startup_truthful(tmp_path, monkeypatch):
    repo, sha_a = _make_repo(tmp_path)
    ident = _capture_at(monkeypatch, repo)
    assert ident.startup_git_sha == sha_a
    assert ident.startup_git_dirty is False


# ── T5: git executable unavailable — no fabricated SHA ───────────────────────


def test_t5_git_unavailable_truthful(monkeypatch):
    def _no_git(cmd, **kwargs):
        raise FileNotFoundError("git not on PATH")

    monkeypatch.setattr(subprocess, "run", _no_git)
    ident = srv._capture_process_identity()
    assert ident.startup_git_available is False
    assert ident.startup_git_sha is None
    assert ident.startup_git_sha_short is None
    assert ident.startup_git_dirty is None
    assert ident.identity_capture_error == "git_executable_unavailable"
    assert ident.identity_source in ("release_object_package", "unavailable")
    monkeypatch.setattr(srv, "PROCESS_IDENTITY_V1", ident)
    with TestClient(srv.app) as client:
        r = client.get("/api/build")
    assert r.status_code == 200
    assert r.json()["process_identity"]["startup_git_sha"] is None


# ── T6: git command failure — operational, sanitized, no fabricated identity ─


def test_t6_git_failure_fails_honestly(monkeypatch):
    def _boom(cmd, **kwargs):
        raise subprocess.CalledProcessError(
            128, cmd, output="fatal: secret path C:/private/creds leaked"
        )

    monkeypatch.setattr(subprocess, "run", _boom)
    ident = srv._capture_process_identity()
    assert ident.startup_git_sha is None
    assert ident.identity_capture_error == "git_command_failed"
    # sanitized fixed classification only — never raw subprocess output
    assert "secret" not in json.dumps(dataclasses.asdict(ident))
    assert "fatal" not in json.dumps(dataclasses.asdict(ident))
    monkeypatch.setattr(srv, "PROCESS_IDENTITY_V1", ident)
    with TestClient(srv.app) as client:
        assert client.get("/api/build").status_code == 200


def test_t6b_unknown_dirty_state_is_not_clean(tmp_path, monkeypatch):
    """rev-parse succeeds but status fails -> dirty=None (unknown), never False."""
    repo, sha_a = _make_repo(tmp_path)
    real_run = subprocess.run

    def _status_fails(cmd, **kwargs):
        if "status" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(srv, "APP_DIR", str(repo))
    monkeypatch.setattr(subprocess, "run", _status_fails)
    ident = srv._capture_process_identity()
    assert ident.startup_git_sha == sha_a
    assert ident.startup_git_dirty is None
    assert ident.identity_capture_error == "git_dirty_state_unavailable"


# ── T7: SHA validation and short-SHA derivation ──────────────────────────────


def test_t7_sha_validation_and_short_derivation(tmp_path, monkeypatch):
    repo, sha_a = _make_repo(tmp_path)
    ident = _capture_at(monkeypatch, repo)
    assert ident.startup_git_sha == sha_a and len(sha_a) == 40
    assert ident.startup_git_sha_short == sha_a[:12]  # derived, no second rev-parse

    class _Fake:
        stdout = "not-a-sha\n"
        stderr = ""

    calls = []
    real_run = subprocess.run

    def _malformed(cmd, **kwargs):
        calls.append(list(cmd))
        if "rev-parse" in cmd:
            return _Fake()
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", _malformed)
    bad = srv._capture_process_identity()
    assert bad.startup_git_sha is None
    assert bad.identity_capture_error == "git_output_not_a_sha"
    rev_parse_calls = [c for c in calls if "rev-parse" in c]
    assert len(rev_parse_calls) == 1  # short SHA never triggers a second git call


# ── T8/T9: PID and timestamp stability ───────────────────────────────────────


def test_t8_t9_pid_and_timestamps_stable(tmp_path, monkeypatch):
    repo, _sha_a = _make_repo(tmp_path)
    ident = _capture_at(monkeypatch, repo)
    assert ident.process_id == os.getpid()
    assert ident.startup_identity_captured_at_utc > 0
    monkeypatch.setattr(srv, "PROCESS_IDENTITY_V1", ident)
    with TestClient(srv.app) as client:
        b1 = client.get("/api/build").json()["process_identity"]
        b2 = client.get("/api/build").json()["process_identity"]
    assert b1["process_id"] == b2["process_id"] == os.getpid()
    assert b1["startup_identity_captured_at_utc"] == b2["startup_identity_captured_at_utc"]
    assert b1["process_started_at_utc"] == b2["process_started_at_utc"]


# ── T10: legacy response-contract compatibility ──────────────────────────────


def test_t10_response_contract_compatibility():
    with TestClient(srv.app) as client:
        body = client.get("/api/build").json()
    for legacy_key in (
        "git_sha", "contract", "release_id",
        "ui_maximize_sla_ms", "ui_maximize_panel_warm_tickers",
    ):
        assert legacy_key in body, f"legacy /api/build key missing: {legacy_key}"
    assert body["contract"] == "meet_or_exceed_v1"
    pi = body["process_identity"]
    assert set(pi) == {
        "schema_version", "startup_git_sha", "startup_git_sha_short",
        "startup_git_dirty", "startup_git_available",
        "startup_identity_captured_at_utc", "process_started_at_utc",
        "process_id", "package_build_id", "identity_source",
        "identity_capture_error",
    }
    assert pi["schema_version"] == "1"
    assert set(body["repository_state_now"]) == {"repo_head_now"}


# ── T11: mechanical immutability ─────────────────────────────────────────────


def test_t11_identity_object_immutable():
    ident = srv.PROCESS_IDENTITY_V1
    with pytest.raises(dataclasses.FrozenInstanceError):
        ident.startup_git_sha = "f" * 40  # type: ignore[misc]
    with TestClient(srv.app) as client:
        body = client.get("/api/build").json()
    body["process_identity"]["startup_git_sha"] = "tampered"
    with TestClient(srv.app) as client:
        again = client.get("/api/build").json()
    assert again["process_identity"]["startup_git_sha"] != "tampered"


# ── T12: no hidden git read populates process identity at request time ───────


def test_t12_request_git_reads_feed_diagnostics_only(monkeypatch):
    head_calls = {"n": 0}

    def _counting_head():
        head_calls["n"] += 1
        return "e" * 40

    def _capture_must_not_run():
        raise AssertionError("request handling must never recapture process identity")

    monkeypatch.setattr(srv, "_repo_git_head_sha", _counting_head)
    monkeypatch.setattr(srv, "_capture_process_identity", _capture_must_not_run)
    before = json.dumps(dataclasses.asdict(srv.PROCESS_IDENTITY_V1), sort_keys=True)
    with TestClient(srv.app) as client:
        for _ in range(3):
            body = client.get("/api/build").json()
            assert body["repository_state_now"]["repo_head_now"] == "e" * 40
    after = json.dumps(dataclasses.asdict(srv.PROCESS_IDENTITY_V1), sort_keys=True)
    assert before == after
    assert head_calls["n"] == 3  # one dynamic read per request, diagnostics only


# ── T13 (fresh process at SHA B) + dependency safety ─────────────────────────


def test_t13_fresh_capture_at_sha_b_reports_sha_b(tmp_path, monkeypatch):
    repo, sha_a = _make_repo(tmp_path)
    ident_a = _capture_at(monkeypatch, repo)
    sha_b = _advance_repo(repo)
    ident_b = srv._capture_process_identity()  # fresh capture = fresh process semantics
    assert ident_a.startup_git_sha == sha_a
    assert ident_b.startup_git_sha == sha_b
    assert ident_b.startup_identity_captured_at_utc >= ident_a.startup_identity_captured_at_utc


def test_t14_operational_without_psutil(monkeypatch, tmp_path):
    """Optional process-metadata support absent -> started_at None, capture OK."""
    repo, sha_a = _make_repo(tmp_path)
    monkeypatch.setattr(srv, "APP_DIR", str(repo))
    monkeypatch.setitem(sys.modules, "psutil", None)  # import psutil -> None -> attr error path
    ident = srv._capture_process_identity()
    assert ident.startup_git_sha == sha_a
    assert ident.process_started_at_utc is None
    assert ident.process_id == os.getpid()
