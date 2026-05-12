"""Prior scoreboard Δ must use last committed JSON, not stale working-tree rebuilds."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.schwab_v4_scoreboard import (
    ROOT,
    build_scoreboard,
    load_prior_scoreboard_from_git,
    _prior_counts_from_doc,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _minimal_d17(unreviewed: int, replaced: int) -> dict:
    return {
        "scanner_version": "3.0.0",
        "register_path": str(Path("/tmp/register.csv")),
        "replaced_count": replaced,
        "governed_exception_with_oxx_count": 0,
        "bare_governed_exception_count": 0,
        "no_schwab_equivalent_count": 0,
        "not_market_data_count": 0,
        "unreviewed_count": unreviewed,
        "v4_a_violations": [],
        "closure_admissible": False,
    }


def test_load_prior_scoreboard_from_git_reads_head_not_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    art = repo / "governance" / "artifacts"
    art.mkdir(parents=True)
    out = art / "schwab_v4_scoreboard.json"
    committed = {"d17": {"unreviewed_count": 82402, "replaced_count": 0}, "scoreboard": {}}
    out.write_text(json.dumps(committed), encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "governance/artifacts/schwab_v4_scoreboard.json")
    _git(repo, "commit", "-m", "baseline scoreboard")
    out.write_text(
        json.dumps({"d17": {"unreviewed_count": 82390, "replaced_count": 12}, "scoreboard": {}}),
        encoding="utf-8",
    )

    doc, sha, src = load_prior_scoreboard_from_git(repo, out)
    assert src == "git_head"
    assert sha is not None and len(sha) == 40
    assert doc is not None
    u, r = _prior_counts_from_doc(doc)
    assert u == 82402
    assert r == 0


@patch("tools.schwab_v4_scoreboard._count_perf_proofs", return_value=(4, []))
@patch("tools.schwab_v4_scoreboard.compute_full_metrics")
def test_build_scoreboard_delta_uses_git_head_after_double_local_rebuild(
    mock_metrics: object,
    _mock_p: object,
    tmp_path: Path,
) -> None:
    """Working-tree scoreboard already shows current counts; Δ must still use HEAD."""
    repo = tmp_path / "repo"
    art = repo / "governance" / "artifacts"
    art.mkdir(parents=True)
    out = art / "schwab_v4_scoreboard.json"
    committed = {
        "d17": {"unreviewed_count": 82402, "replaced_count": 0},
        "scoreboard": {"replaced_count_d17": 0},
    }
    out.write_text(json.dumps(committed), encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "governance/artifacts/schwab_v4_scoreboard.json")
    _git(repo, "commit", "-m", "baseline")

    mock_metrics.return_value = _minimal_d17(82390, 12)
    reg = tmp_path / "register.csv"
    reg.write_text("register_id,disposition\n", encoding="utf-8")
    op = tmp_path / "op.md"
    op.write_text("# op\n", encoding="utf-8")
    perf = tmp_path / "perf"
    perf.mkdir()

    out.write_text(
        json.dumps({"d17": {"unreviewed_count": 82390, "replaced_count": 12}, "scoreboard": {}}),
        encoding="utf-8",
    )

    doc = build_scoreboard(
        register=reg,
        operator_register=op,
        perf_dir=perf,
        out_path=out,
        use_register_meta=False,
        update_perf_index=False,
        repo_root=repo,
        prior_from_git=True,
    )
    sb = doc["scoreboard"]
    assert sb["prior_scoreboard_source"] == "git_head"
    assert sb["prior_unreviewed_count"] == 82402
    assert sb["unreviewed_count"] == 82390
    assert sb["delta_unreviewed_count"] == -12
    assert sb["prior_git_ref"] is not None and len(sb["prior_git_ref"]) == 40
    assert sb["prior_replaced_count_d17"] == 0
    assert sb["delta_replaced_count_d17"] == 12


@patch("tools.schwab_v4_scoreboard._count_perf_proofs", return_value=(4, []))
@patch("tools.schwab_v4_scoreboard.compute_full_metrics")
def test_build_scoreboard_prior_from_working_tree_when_prior_from_git_false(
    mock_metrics: object,
    _mock_p: object,
    tmp_path: Path,
) -> None:
    """prior_from_git=False skips git; prior comes from on-disk scoreboard (legacy)."""
    repo = tmp_path / "repo"
    art = repo / "governance" / "artifacts"
    art.mkdir(parents=True)
    out = art / "schwab_v4_scoreboard.json"
    committed = {
        "d17": {"unreviewed_count": 82402, "replaced_count": 0},
        "scoreboard": {"replaced_count_d17": 0},
    }
    out.write_text(json.dumps(committed), encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "add", "governance/artifacts/schwab_v4_scoreboard.json")
    _git(repo, "commit", "-m", "baseline")

    mock_metrics.return_value = _minimal_d17(82390, 12)
    reg = tmp_path / "register.csv"
    reg.write_text("register_id,disposition\n", encoding="utf-8")
    op = tmp_path / "op.md"
    op.write_text("# op\n", encoding="utf-8")
    perf = tmp_path / "perf"
    perf.mkdir()

    out.write_text(
        json.dumps({"d17": {"unreviewed_count": 82390, "replaced_count": 12}, "scoreboard": {}}),
        encoding="utf-8",
    )

    doc = build_scoreboard(
        register=reg,
        operator_register=op,
        perf_dir=perf,
        out_path=out,
        use_register_meta=False,
        update_perf_index=False,
        repo_root=repo,
        prior_from_git=False,
    )
    sb = doc["scoreboard"]
    assert sb["prior_scoreboard_source"] == "working_tree"
    assert sb["prior_git_ref"] is None
    assert sb["prior_unreviewed_count"] == 82390
    assert sb["delta_unreviewed_count"] == 0


def test_load_prior_relative_path_must_be_under_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "test")
    out = tmp_path / "outside.json"
    out.write_text("{}", encoding="utf-8")
    doc, sha, src = load_prior_scoreboard_from_git(repo, out)
    assert doc is None and sha is None and src == "none"


@pytest.mark.skipif(
    not (ROOT / ".git").is_dir(),
    reason="EdWebConsole checkout has no .git (sparse/snapshot)",
)
def test_real_repo_git_show_head_scoreboard_parses() -> None:
    out = ROOT / "governance" / "artifacts" / "schwab_v4_scoreboard.json"
    doc, sha, src = load_prior_scoreboard_from_git(ROOT, out)
    if src != "git_head":
        pytest.skip("scoreboard not in last commit")
    assert doc is not None and sha is not None
    u, _r = _prior_counts_from_doc(doc)
    assert u is not None
