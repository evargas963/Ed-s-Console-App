"""Phase 1a governance consolidation guards."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Pin excerpt hashes only (not full AGENTS.md body).
BANNED_TOOLS_HASH = "37f3366b8388286a3287ca5fac07cf944f7274c0bcabd8b564a5d08690538fea"
NO_PERMISSION_ASKS_HASH = "714265531ba2ffd5ca14d3823bd79ee0874972b1c0efd2c89103b92a10b49715"


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


def test_agents_rule_compliance_zero_drift_section():
    agents = _read("AGENTS.md")
    assert "Rule compliance" in agents
    assert "zero drift" in agents.lower()
    assert "check_fix_everything_we_touch" in agents
    assert "by design" in agents


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


def test_agents_mandatory_enforcement_registry() -> None:
    agents = _read("AGENTS.md")
    assert "Mandatory enforcement registry" in agents
    assert "check_institutional_contract()" in agents
    assert "Cards lit + no false STALE pill" in agents
    assert "check_governance_binding_contract()" in agents
    assert "check_institutional_signoff_contract()" in agents


def test_governance_binding_contract() -> None:
    from tools.check_fix_everything_we_touch import check_governance_binding_contract

    errors = check_governance_binding_contract()
    assert errors == [], f"governance binding contract: {errors}"
    agents = _read("AGENTS.md")
    assert "Governance document hierarchy" in agents
    assert "INSTITUTIONAL_STANDARD_V3.md" in agents
    active = _read("ACTIVE_PROGRAM.md")
    assert "Governance document hierarchy" in active
    eng = _read("governance/ENGINEERING_GATEKEEPING_POLICY.md")
    assert "Binding authority:" in eng


def test_institutional_signoff_contract() -> None:
    from tools.check_fix_everything_we_touch import check_institutional_signoff_contract

    errors = check_institutional_signoff_contract()
    assert errors == [], f"institutional sign-off contract: {errors}"
    agents = _read("AGENTS.md")
    assert "Institutional sign-off contract — uniform Cursor + Claude" in agents
    assert "Tier 0" in agents
    assert "--upfront-gate" in agents
    assert "Tier A" in agents
    assert "Canonical sign-off block" in agents
    assert "AUDIT_LADDER:" in agents
    assert "catalog_slots" in agents
    assert "runnable_scored" in agents
    cursor = _read(".cursor/rules/00-always.mdc")
    assert "Tier 0" in cursor
    assert "Tier A" in cursor
    assert "Institutional sign-off contract" in cursor
    enforce = _read("tools/enforce_all_rules.py")
    assert "Tier A" in enforce
    assert "--upfront-gate" in enforce
    hardening = _read(".github/workflows/hardening.yml")
    assert "enforce_all_rules.py --enforce-static" in hardening


def test_upfront_mechanical_gate_stamp(monkeypatch, tmp_path) -> None:
    import json
    from datetime import datetime, timedelta, timezone

    from tools.check_fix_everything_we_touch import (
        UPFRONT_GATE_MAX_AGE_SEC,
        check_upfront_mechanical_gate_stamp,
        _upfront_gate_lock_set_sha256,
    )
    import tools.check_fix_everything_we_touch as gate_mod

    stamp_path = tmp_path / "upfront_mechanical_gate.json"
    monkeypatch.setattr(gate_mod, "UPFRONT_GATE_STAMP_PATH", stamp_path)
    monkeypatch.setattr(gate_mod, "_git_head_sha", lambda: "deadbeef" * 5)

    assert check_upfront_mechanical_gate_stamp(staged={"tests/test_foo.py"}) == []

    missing = check_upfront_mechanical_gate_stamp(staged={"signals.py"})
    assert missing and "missing stamp" in missing[0]

    fresh = {
        "schema_version": 1,
        "git_sha": "deadbeef" * 5,
        "utc_ts": datetime.now(timezone.utc).isoformat(),
        "exit_code": 0,
        "command": "--upfront-gate",
        "lock_set_sha256": _upfront_gate_lock_set_sha256(),
        "static_error_count": 0,
    }
    stamp_path.write_text(json.dumps(fresh), encoding="utf-8")
    assert check_upfront_mechanical_gate_stamp(staged={"signals.py"}) == []

    stale = dict(fresh)
    stale["utc_ts"] = (
        datetime.now(timezone.utc) - timedelta(seconds=UPFRONT_GATE_MAX_AGE_SEC + 60)
    ).isoformat()
    stamp_path.write_text(json.dumps(stale), encoding="utf-8")
    stale_errs = check_upfront_mechanical_gate_stamp(staged={"signals.py"})
    assert stale_errs and "stamp age" in stale_errs[0]

    wrong_head = dict(fresh)
    wrong_head["git_sha"] = "cafebabe" * 5
    stamp_path.write_text(json.dumps(wrong_head), encoding="utf-8")
    head_errs = check_upfront_mechanical_gate_stamp(staged={"signals.py"})
    assert head_errs and "git_sha" in head_errs[0]

    assert check_upfront_mechanical_gate_stamp(staged={"tools/check_fix_everything_we_touch.py"}) == []


def test_tier1_engineering_standard() -> None:
    from tools.check_fix_everything_we_touch import (
        TIER1_PRINCIPLE_IDS,
        check_tier1_engineering_standard,
    )

    errors = check_tier1_engineering_standard()
    assert errors == [], f"Tier-1 engineering standard: {errors}"
    agents = _read("AGENTS.md")
    assert "Quality Standard vs Product law" in agents
    assert len(TIER1_PRINCIPLE_IDS) == 24
    for pid in TIER1_PRINCIPLE_IDS:
        assert f"**{pid}**" in agents


def test_v3_invariant_mechanical_registry() -> None:
    from tools.check_fix_everything_we_touch import (
        V3_INVARIANT_MECHANICAL_LOCKS,
        check_v3_invariant_mechanical_registry,
    )

    assert len(V3_INVARIANT_MECHANICAL_LOCKS) == 20
    errors = check_v3_invariant_mechanical_registry()
    assert errors == [], f"V3 invariant mechanical registry: {errors}"
    agents = _read("AGENTS.md")
    assert "V3 invariant mechanical registry" in agents
    for inv_id in V3_INVARIANT_MECHANICAL_LOCKS:
        assert f"**{inv_id}**" in agents


def test_governance_archive_batch2_contract() -> None:
    from tools.check_fix_everything_we_touch import check_governance_archive_batch2_contract

    errors = check_governance_archive_batch2_contract()
    assert errors == [], f"governance archive batch 2: {errors}"
    queue = _read("governance/REPO_CLEANUP_QUEUE.md")
    assert "batch 2 complete" in queue.lower()


def test_ablation_denominator_vocabulary() -> None:
    from tools.check_fix_everything_we_touch import check_ablation_denominator_vocabulary

    errors = check_ablation_denominator_vocabulary()
    assert errors == [], f"ablation denominator vocabulary: {errors}"


def test_agents_meet_or_exceed_closure_cycle() -> None:
    agents = _read("AGENTS.md")
    assert "Meet-or-Exceed Closure Cycle" in agents
    assert "VERDICT: MET" in agents
    assert "check_meet_or_exceed_signoff()" in agents
    assert "GET /api/build" in agents
    assert "Scope — universal, not gated" in agents
    assert "full repo" in agents
    assert "one cycle, one verdict vocabulary" in agents


def test_agents_objective_code_audit_closure() -> None:
    agents = _read("AGENTS.md")
    assert "Objective → Code → Audit closure" in agents
    assert "run_objective_code_audit" in agents
    assert "run_repo_wide_static_audit" in agents
    assert "run_situational_runtime_audits" in agents
    assert "--objective-audit" in agents
    assert "--full-runtime" in agents
    assert "AUDIT: CLEAN" in agents
    assert "Scope — universal, full repo" in agents
    assert "where the situation fits" in agents
    assert "audit_ablation_placement_validity" in agents


def test_agents_always_on_institutional_binding() -> None:
    """Institutional gate is always on — operator must not re-prompt each turn."""
    agents = _read("AGENTS.md")
    assert "Always-on institutional binding" in agents
    assert "no operator activation phrase" in agents
    assert "Design brief" in agents and "build" in agents
    assert "CURSOR-UI-AUTHORIZED" in agents
    assert "static/index.html" in agents


def test_server_logging_visual_severity_marker_warning_plus_only() -> None:
    """server.py installs a Formatter that prepends a bracket-tag for WARNING+ so
    operator-actionable events stand out in the dense INFO/DEBUG console stream.
    DEBUG/INFO get no marker (steady-state stays quiet)."""
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
