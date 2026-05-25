"""Phase 1a governance consolidation guards."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Pin excerpt hashes only (not full AGENTS.md body).
BANNED_TOOLS_HASH = "0de266bec3a17c77af3180fa8fbdb10d03fa075cd6a34be01e306dc5761c1194"
NO_PERMISSION_ASKS_HASH = "1a1f2968debddd443f24595e4c4d4384585bde65c26a8e7a89e124a254a28d3f"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}.*?(?=^## |\Z)", text, re.M | re.S)
    assert m, f"missing section {heading!r}"
    return m.group(0).strip()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_agents_md_exists():
    assert (ROOT / "AGENTS.md").is_file()


def test_active_program_exists():
    assert (ROOT / "ACTIVE_PROGRAM.md").is_file()


def test_mdc_always_apply():
    mdc = _read(".cursor/rules/00-always.mdc")
    assert "alwaysApply: true" in mdc


def test_mdc_pointers_match_canonical_files():
    mdc = _read(".cursor/rules/00-always.mdc")
    for name in ("ACTIVE_PROGRAM.md", "AGENTS.md", "CLAUDE.md"):
        assert name in mdc
    assert "ACTIVE_PROGRAM.md" in _read("AGENTS.md")
    assert "AGENTS.md" in _read("ACTIVE_PROGRAM.md")


def test_agents_banned_tools_excerpt_hash():
    agents = _read("AGENTS.md")
    excerpt = _section(agents, "Banned tools")
    assert _sha(excerpt) == BANNED_TOOLS_HASH


def test_agents_no_permission_asks_excerpt_hash():
    agents = _read("AGENTS.md")
    excerpt = _section(agents, "No permission asks")
    assert _sha(excerpt) == NO_PERMISSION_ASKS_HASH


def test_agent_self_governance_no_grep_references():
    text = _read("docs/governance/AGENT_SELF_GOVERNANCE.md").lower()
    for banned in ("grep", "ripgrep", " re-grep", "re-greps"):
        assert banned not in text, f"AGENT_SELF_GOVERNANCE still references {banned!r}"


def test_memory_archive_has_all_source_files():
    archive = ROOT / "governance/archive/2026-Q2/memory_archive"
    assert archive.is_dir()
    archived = {p.name for p in archive.glob("*.md") if p.name != "README.md"}
    # Phase 0 classification counted 34 non-MEMORY.md memory files
    assert len(archived) == 34
    for name in (
        "feedback_no_grep_tool.md",
        "feedback_no_permission_asks.md",
        "feedback_fiduciary_duty.md",
        "project_gate_b_state_2026_05_21.md",
    ):
        assert name in archived
    assert (ROOT / "MEMORY.md").is_file()
    body = (ROOT / "MEMORY.md").read_text(encoding="utf-8")
    assert "AGENTS.md" in body and "OPERATOR-ONLY" in body


SCOPE_HEADER_RE = re.compile(
    r"\*\*(?:Classification|Scope|Historical|SUPERSEDED)",
    re.I,
)


def _iter_repo_md() -> list[Path]:
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "backups"}
    out: list[Path] = []
    for path in ROOT.rglob("*.md"):
        rel = path.relative_to(ROOT)
        if any(part in skip for part in rel.parts):
            continue
        if ".claude" in rel.parts and "worktrees" in rel.parts:
            continue
        out.append(path)
    return out


def test_phase2_md_classification_spreadsheet():
    csv_path = ROOT / "governance/consolidation/phase2/md_classification.csv"
    assert csv_path.is_file(), "run tools/build_phase2_md_classification.py"
    import csv

    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 250
    categories = {r["category"] for r in rows}
    for cat in (
        "Active Rule Source",
        "Policy Specification",
        "Historical Record",
        "Operational Ledger",
        "Operator Runbook",
    ):
        assert cat in categories


def test_phase2_all_md_have_scope_headers():
    missing: list[str] = []
    for path in _iter_repo_md():
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:15])
        if not SCOPE_HEADER_RE.search(head):
            missing.append(path.relative_to(ROOT).as_posix())
    assert not missing, f"missing scope headers: {missing[:20]}"


def test_phase3_cleanup_artifacts():
    phase3 = ROOT / "governance/consolidation/phase3"
    for name in (
        "baseline_delta.json",
        "duplicate_md_report.json",
        "protected_py_audit.json",
        "worktree_cleanup_notes.md",
        "phase3_execution_log.json",
    ):
        assert (phase3 / name).is_file(), f"missing {name}; run tools/execute_phase3_cleanup.py"


def test_phase3e_worktrees_pruned():
    log = json.loads(
        (ROOT / "governance/consolidation/phase3/phase3_execution_log.json").read_text(
            encoding="utf-8"
        )
    )
    wt = log["3e_worktrees"]
    assert wt["prune_executed"] is True
    assert wt["bytes_after"] == 0


def test_phase3b_root_audit_archives():
    archive = ROOT / "governance/archive/2026-Q2/root_audits"
    for name in (
        "FUSION_MC_AUDIT.md",
        "SNAPSHOT_DATA_AUDIT.md",
    ):
        assert (archive / name).is_file()
    stub = (ROOT / "FUSION_MC_AUDIT.md").read_text(encoding="utf-8")
    assert "Archived Phase 3b" in stub and "root_audits" in stub


def test_phase4_pre_commit_config():
    assert (ROOT / ".pre-commit-config.yaml").is_file()
    assert (ROOT / "tools/check_no_grep_subprocess.py").is_file()


def test_pytest_ci_workflow_exists():
    wf = ROOT / ".github/workflows/pytest.yml"
    assert wf.is_file(), "PYTEST-TO-CI requires .github/workflows/pytest.yml"
    body = wf.read_text(encoding="utf-8")
    assert "npm run test:all" in body


def test_mdc_is_pointers_only_no_duplicate_bans():
    mdc = _read(".cursor/rules/00-always.mdc")
    assert "Do not duplicate AGENTS rules here" in mdc
    assert "Never use grep" not in mdc
    assert "Want me to" not in mdc


def test_agents_closure_and_no_new_files_sections():
    agents = _read("AGENTS.md")
    assert "Closure definition + no-deferral" in agents
    assert "No new files when an existing one will do" in agents
    assert "REAL-GATE taxonomy" in agents
    assert "5-artifact" in agents or "ALL of the following land in the same commit" in agents
    assert "historical only" in agents.lower() or "AGENTS.md wins" in agents


def test_agents_mutual_gatekeeping_section():
    agents = _read("AGENTS.md")
    assert "Active agent posture + mutual gatekeeping" in agents
    assert "Passive relay" in agents
    assert "Gatekeeper pending" in agents
    assert "Memo-only commits that document fixable code debt are rejection-grade" in agents
    assert 'id="active-agent-posture"' in agents


def test_agents_file_delete_gatekeeper_section():
    agents = _read("AGENTS.md")
    excerpt = _section(agents, "File delete gatekeeper")
    assert "gatekeeper and own catch-net" in excerpt
    assert "Enumeration first, verdict second" in excerpt
    assert "Publish an in-chat referrer table" in excerpt
    assert "Delete = multi-file cone closure" in excerpt
    assert "Subagent/explore summaries are leads, not verdicts" in excerpt
    assert 'id="file-delete-gatekeeper"' in agents
    assert "Banned without referrer table" in excerpt


def test_cursor_v4_brief_fix_as_we_find_overrides_gatekeeper_wait():
    brief = _read("governance/CURSOR_V4_AGENT_BRIEF.md")
    assert "Class A" in brief and "Class B" in brief
    assert "fix-as-we-find" in brief
    assert "execute relay handoffs blind" in brief.lower() or "relay handoffs blind" in brief


def test_no_deferral_artifacts_sprawl_file_absent():
    assert not (ROOT / "tests/test_no_deferral_artifacts.py").is_file()


def test_build_config_fail_closed_without_secrets(monkeypatch, tmp_path: Path) -> None:
    import pytest as pt

    monkeypatch.delenv("SCHWAB_API_KEY", raising=False)
    monkeypatch.delenv("SCHWAB_APP_SECRET", raising=False)
    monkeypatch.setattr("config._load_dotenv_if_present", lambda: None)
    from config import build_config

    with pt.raises(RuntimeError, match="SCHWAB_API_KEY"):
        build_config(str(tmp_path))


def test_build_config_reads_env_secrets(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SCHWAB_API_KEY", "test-key")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "test-secret")
    from config import build_config

    cfg = build_config(str(tmp_path))
    assert cfg.api_key == "test-key"
    assert cfg.app_secret == "test-secret"


def test_config_py_has_no_hardcoded_api_secrets() -> None:
    text = (ROOT / "config.py").read_text(encoding="utf-8")
    assert "SCHWAB_API_KEY =" not in text
    assert "SCHWAB_APP_SECRET =" not in text
    assert "A8y3Yf4jkAbJfavtb76VNbYimkSEk082" not in text


def test_agents_code_first_no_governance_only_section() -> None:
    agents = _read("AGENTS.md")
    assert "Code-first / no governance-only turn" in agents
    assert "governance-only lane" in agents
    assert "bookkeeping" in agents
    active = _read("ACTIVE_PROGRAM.md")
    assert "code-first" in active.lower()


def test_server_logging_visual_severity_marker_warning_plus_only() -> None:
    """server.py installs a Formatter that prepends a bracket-tag for WARNING+ so
    operator-actionable events stand out in the dense INFO/DEBUG console stream.
    DEBUG/INFO get no marker (steady-state stays quiet)."""
    import importlib.util
    import logging

    # Import the Formatter directly without booting server.py (which imports
    # the world). Use the class definition via inline reconstruction — assert
    # source-level presence + behavioral semantics on a synthetic instance.
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "class _LevelMarkerFormatter(logging.Formatter):" in src, "marker formatter missing"
    assert "_install_visual_severity_markers" in src, "install helper missing"
    assert "isatty" in src, "TTY detection missing (ANSI must not be emitted into log-capture files)"
    # Both ANSI + plain marker tables present (so file capture stays clean)
    assert "_ANSI_BY_LEVEL" in src
    assert "_PLAIN_BY_LEVEL" in src
    # All three operator-actionable levels covered
    for lvl in ("WARNING", "ERROR", "CRITICAL"):
        assert f"logging.{lvl}" in src, f"{lvl} level marker missing"

    # Behavioral check: instantiate the formatter (re-import the class via exec
    # of the source slice) and verify the level marker decision.
    import re as _re
    cls_match = _re.search(
        r"class _LevelMarkerFormatter.*?(?=\n(?:def |class |\n\Z))",
        src,
        _re.DOTALL,
    )
    assert cls_match is not None, "could not isolate formatter class source"
    ns: dict = {"logging": logging}
    exec(cls_match.group(0), ns)
    Formatter = ns["_LevelMarkerFormatter"]

    # Plain mode (no TTY) — used in file capture / CI logs
    f_plain = Formatter("%(levelname)s:%(name)s:%(message)s", use_ansi=False)
    rec_warn = logging.LogRecord("ed_server", logging.WARNING, "x.py", 1, "test", None, None)
    rec_info = logging.LogRecord("ed_server", logging.INFO, "x.py", 1, "test", None, None)
    rec_err = logging.LogRecord("ed_server", logging.ERROR, "x.py", 1, "test", None, None)
    out_warn = f_plain.format(rec_warn)
    out_info = f_plain.format(rec_info)
    out_err = f_plain.format(rec_err)
    assert out_warn.startswith("[WARN] "), f"warning marker missing in plain mode: {out_warn!r}"
    assert out_err.startswith("[ERR ] "), f"error marker missing in plain mode: {out_err!r}"
    assert not (out_info.startswith("[WARN]") or out_info.startswith("[ERR")), (
        f"INFO must NOT carry a level marker (steady-state stays quiet): {out_info!r}"
    )

    # ANSI mode (TTY) — used when operator watches uvicorn live
    f_ansi = Formatter("%(levelname)s:%(name)s:%(message)s", use_ansi=True)
    out_warn_ansi = f_ansi.format(rec_warn)
    assert "\033[33m[WARN]\033[0m " in out_warn_ansi, (
        f"ANSI yellow marker missing for WARNING: {out_warn_ansi!r}"
    )
    out_info_ansi = f_ansi.format(rec_info)
    assert "\033[" not in out_info_ansi, f"INFO must not emit ANSI escapes: {out_info_ansi!r}"
