"""Negative controls for the mockup-before-code law (RC-186) — check `ui_mockup_approval`.

Each test drives the REAL callee (`tools.ui_mockup_lock.mockup_approval_violation`) against a
registry written to a temp repo root, so the controls are independent of the live registry's
current approval state (a live-registry assertion would flip the suite the day the operator
approves a variant — the RC-169 clock-dependence class through a registry door).
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.ui_mockup_lock import (
    ESCAPE_TOKEN,
    REGISTRY_REL,
    mockup_approval_violation,
    mockup_gated_entry,
)

# RC-368: declared direct owner — this suite drives stop_violations (RC-190) and the
# mockup-lock clauses that live in the guard.
TURN_AUDIT_OWNS = [
    "tools/operator_law_guard.py",
]


def _write_registry(root: Path, status: str, variant: str | None,
                    quote: str | None = "operator said: approved, variant v6") -> None:
    reg = root / REGISTRY_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({
        "surfaces": {
            "static/chart.html": {
                "status": status,
                "approved_variant": variant,
                "approved_on": "2026-08-02" if variant else None,
                "operator_quote": quote,
            },
        },
    }), encoding="utf-8")


def test_pending_surface_screams(tmp_path):
    """INJECTED VIOLATION: a design_pending surface must block — the check can fail."""
    _write_registry(tmp_path, "design_pending", None)
    reason = mockup_approval_violation("static/chart.html", "body { color: red }",
                                       repo=tmp_path)
    assert reason is not None and "RC-186" in reason


def test_approved_surface_flows_only_with_operator_grant(tmp_path, monkeypatch):
    """Cursor v2 compound seal: provenance fields alone (forgeable) must NOT unlock — the
    live operator grant is required beside them."""
    from tools.ui_mockup_lock import APPROVE_ENV
    _write_registry(tmp_path, "approved", "variant-b-proximity-pills")
    monkeypatch.delenv(APPROVE_ENV, raising=False)
    forged = mockup_approval_violation("static/chart.html", "body {}", repo=tmp_path)
    assert forged is not None and APPROVE_ENV in forged
    monkeypatch.setenv(APPROVE_ENV, "1")
    assert mockup_approval_violation("static/chart.html", "body {}", repo=tmp_path) is None


def test_approved_status_without_a_named_variant_still_blocks(tmp_path):
    """'approved' with no variant recorded is not an approval — it is a half-filled form."""
    _write_registry(tmp_path, "approved", None)
    assert mockup_approval_violation("static/chart.html", "x", repo=tmp_path) is not None


def test_bug_fix_escape_in_the_edited_text_flows(tmp_path):
    _write_registry(tmp_path, "design_pending", None)
    text = f"<!-- # {ESCAPE_TOKEN} RC-000 hotfix, not redesign -->\nbody {{}}"
    assert mockup_approval_violation("static/chart.html", text, repo=tmp_path) is None


def test_unlisted_surface_is_not_gated(tmp_path):
    _write_registry(tmp_path, "design_pending", None)
    assert mockup_approval_violation("static/index.html", "x", repo=tmp_path) is None


def test_operator_env_escape_does_not_flow(tmp_path, monkeypatch):
    _write_registry(tmp_path, "design_pending", None)
    monkeypatch.setenv("ED_UI_MOCKUP_LOCK", "off")
    assert mockup_approval_violation("static/chart.html", "x", repo=tmp_path)


def test_missing_registry_gates_nothing(tmp_path):
    """No registry = no surface ever placed under the law — silence, not a universal block."""
    assert mockup_approval_violation("static/chart.html", "x", repo=tmp_path) is None
    assert mockup_gated_entry("static/chart.html", repo=tmp_path) is None


def test_live_registry_gates_the_chart_surface():
    """The real registry must keep static/chart.html under the law until the operator approves
    a variant there (state read, not asserted: this checks the entry EXISTS, not its status)."""
    assert mockup_gated_entry("static/chart.html") is not None


def test_guard_git_reads_utf8_governance_content_without_locale_decode_errors():
    """RC-187 lock: the guard's `_git` must decode git output as UTF-8, not the locale
    codepage. Before the pin, `git show HEAD:governance/root_cause_log.md` threw
    UnicodeDecodeError in the capture reader thread on cp1252 hosts and silently degraded
    the RC-66 check to never-block. Drives the REAL callee against the REAL log."""
    from tools.pretooluse_guard import _git
    out = _git(["show", "HEAD:governance/root_cause_log.md"])
    assert out is not None and "| RC-" in out


def test_gun1_bare_status_flip_does_not_unlock_chart(tmp_path):
    """RC-189 GUN 1 (consumption side): approved WITHOUT operator_quote grants nothing —
    however the flip got written, the chart stays locked."""
    _write_registry(tmp_path, "approved", "v6-full-page", quote=None)
    assert mockup_approval_violation("static/chart.html", "body {}", repo=tmp_path) is not None


def test_gun1_registry_selfapprove_write_blocks(monkeypatch):
    """RC-189 GUN 1 (write side): recording an approval needs BOTH the operator grant env and
    the operator_quote in the same written text. Attack forms must BLOCK; the legitimate
    operator-provenance path must flow."""
    from tools.ui_mockup_lock import APPROVE_ENV, REGISTRY_REL, registry_mutation_violation
    monkeypatch.delenv(APPROVE_ENV, raising=False)
    flip = '"status": "approved"'
    assert registry_mutation_violation(REGISTRY_REL, flip) is not None
    flip_q = '"status": "approved", "operator_quote": "operator: approved v6"'
    r = registry_mutation_violation(REGISTRY_REL, flip_q)
    assert r is not None and "grant" in r
    monkeypatch.setenv(APPROVE_ENV, "1")
    assert registry_mutation_violation(REGISTRY_REL, flip) is not None
    assert registry_mutation_violation(REGISTRY_REL, flip_q) is None
    assert registry_mutation_violation(REGISTRY_REL, '"mockups_rendered": "2026-08-02"') is None


def test_gun1_grant_var_cannot_be_minted_into_settings():
    from tools.ui_mockup_lock import registry_mutation_violation
    r = registry_mutation_violation(".claude/settings.json",
                                    '"env": {"ED_UI_MOCKUP_APPROVE": "1"}')
    assert r is not None
    assert registry_mutation_violation(".claude/settings.json", '"model": "opus"') is None


def test_gun1_shell_channel_to_registry_or_grant_blocks():
    """RC-189 GUN 1: shell WRITE access to the registry or grant-var minting is refused
    on the RAW command — heredoc and -c payload writes were the dodge around the
    Edit/Write hook. SIMPLICITY REHAB 2026-08-24 (T2-7): the ban is WRITE-scoped — the
    fragment-only form blocked pure READS twice in one measured session (a json.load of
    the registry; a commit message naming the gate). Reads are legal; writes and
    grant-sets still block."""
    from tools.operator_law_guard import bash_violations
    assert any("RC-189" in v for v in bash_violations(
        "python -c \"open('governance/ui_mockup_approvals.json','w').write('x')\"", []))
    assert any("RC-189" in v for v in bash_violations(
        "$env:ED_UI_MOCKUP_APPROVE='1'; git commit", []))
    # READS of the registry are legal now — the risk this gun guards is the WRITE.
    assert not any("RC-189" in v for v in bash_violations(
        "cat governance/ui_mockup_approvals.json", []))
    assert not any("RC-189" in v for v in bash_violations("git status", []))


def test_gun3_bare_or_midword_escape_token_blocks(tmp_path):
    """RC-189 GUN 3: only the declaration form `# ui-mockup-ok: <reason>` unlocks."""
    _write_registry(tmp_path, "design_pending", None)
    for text in (f"{ESCAPE_TOKEN} smuggled", f"x{ESCAPE_TOKEN}x",
                 f"const s = 'zzz{ESCAPE_TOKEN}zzz';"):
        assert mockup_approval_violation("static/chart.html", text, repo=tmp_path) is not None, text
    assert mockup_approval_violation("static/chart.html",
                                     f"# {ESCAPE_TOKEN} real hotfix reason",
                                     repo=tmp_path) is None


def test_gun3_multiedit_escape_does_not_unlock_siblings(tmp_path):
    """RC-189 GUN 3: MultiEdit is judged PER EDIT — one declared waiver cannot carry its
    siblings through."""
    from tools.ui_mockup_lock import tool_input_texts
    _write_registry(tmp_path, "design_pending", None)
    tool_input = {"edits": [
        {"new_string": f"<!-- # {ESCAPE_TOKEN} hotfix -->"},
        {"new_string": "body { color: red }"},
    ]}
    texts = tool_input_texts(tool_input)
    assert len(texts) == 2
    verdicts = [mockup_approval_violation("static/chart.html", t, repo=tmp_path)
                for t in texts]
    assert verdicts[0] is None and verdicts[1] is not None


def test_path_alias_case_and_dot_segments_still_gate(tmp_path):
    """Cursor §E: `static/./chart.html` and case aliases must resolve to the gated entry."""
    from tools.ui_mockup_lock import mockup_gated_entry
    _write_registry(tmp_path, "design_pending", None)
    for alias in ("static/./chart.html", "STATIC\\Chart.HTML", "static//chart.html"):
        assert mockup_gated_entry(alias, repo=tmp_path) is not None, alias
        assert mockup_approval_violation(alias, "x", repo=tmp_path) is not None, alias


def test_v2_concat_shell_channel_blocks():
    """Cursor v2 GUN 1 residual: the exact concat one-liner must BLOCK, along with join-style
    fragments; the legitimate lock-module and test-file spellings stay clean."""
    from tools.operator_law_guard import bash_violations
    cursor_escape = "python -c \"p='gov'+'ernance/ui_mockup_'+'approvals.json'; open(p,'w').write('x')\""
    assert any("RC-189" in v for v in bash_violations(cursor_escape, []))
    assert any("RC-189" in v for v in bash_violations(
        "Copy-Item x (Join-Path governance ui_mockup_approvals.json)", []))
    assert not any("RC-189" in v for v in bash_violations(
        ".venv/Scripts/python.exe -m pytest tests/test_ui_mockup_lock_v1.py -q", []))
    assert not any("RC-189" in v for v in bash_violations(
        "python tools/ui_mockup_lock.py", []))


def test_v2_payload_and_ps_constructed_writes_block():
    """Cursor v2: -c payload writes to constructed / governance / production targets refuse;
    literal safe-data targets stay legal."""
    from tools.operator_law_guard import bash_violations
    blocked = (
        "python -c \"p='x'+'y.json'; open(p,'w').write('1')\"",
        "python -c \"open('.claude/zzz.json','w').write('1')\"",
        "python -c \"open('static/chart.html','w').write('1')\"",
        'Set-Content ("gov"+"ernance/x.json") 1',
        "Out-File -FilePath $(Resolve-Path x) -InputObject 1",
        "Copy-Item a.html static/b.html",
    )
    for cmd in blocked:
        assert any("RC-189 v2" in v or "RC-189" in v for v in bash_violations(cmd, [])), cmd
    legal = (
        "python -c \"open('reports/x.jsonl','a').write('1')\"",
        "python -c \"open('governance/root_cause_log.md','a').write('row')\"",
        "python -c \"print(open('db.py').read())\"",
    )
    for cmd in legal:
        assert not any("RC-189 v2" in v for v in bash_violations(cmd, [])), cmd


def test_v2_ledger_status_prose_honesty_clause():
    """Cursor v2: CLOSED prose against an OPEN status cell (and the mirror) must fire —
    drives the REAL rc_row_schema_violations logic on injected rows."""
    import tools.check_institutional_correctness as cic
    from tools.check_institutional_correctness import rc_row_schema_violations
    log = cic.REPO / "governance" / "root_cause_log.md"
    dishonest = "| RC-998 | OPEN | d | d | defect | whys | CLOSED same turn. |"
    mirrored = "| RC-997 | CLOSED | d | d | defect | whys | IN PROGRESS. |"
    honest = "| RC-996 | CLOSED | d | d | defect | whys | FIXED: everything. |"
    msgs = [str(v) for v in rc_row_schema_violations(
        "\n".join([dishonest, mirrored, honest]), log)]
    assert any("RC-998" in m for m in msgs) and any("RC-997" in m for m in msgs)
    assert not any("RC-996" in m for m in msgs)


def test_gun2_powershell_and_quoted_disable_forms_block():
    """RC-189 GUN 2: every Cursor escape form must match the skip-hooks ban; grant vars and
    non-disable values must not."""
    from tools.operator_law_guard import _SKIP_HOOKS
    for cmd in (
        'ED_UI_MOCKUP_LOCK="off" git commit',
        "ED_UI_MOCKUP_LOCK='off' pytest",
        "ED_UI_MOCKUP_LOCK = off",
        '$env:ED_UI_MOCKUP_LOCK="off"; git commit',
        "$Env:ED_STOP_GUARD='false'",
        "Set-Item env:ED_UI_MOCKUP_LOCK off",
        'Set-Item -Path env:ED_UI_MOCKUP_LOCK -Value "off"',
        "New-Item Env:\\ED_UI_MOCKUP_LOCK -Value off",
        "[Environment]::SetEnvironmentVariable('ED_UI_MOCKUP_LOCK','off')",
        "os.environ['ED_UI_MOCKUP_LOCK']='off'",
        '${env:ED_UI_MOCKUP_LOCK}="off"',
        "$ExecutionContext.SessionState.PSVariable.Set('ED_UI_MOCKUP_LOCK','off')",
        '$env:ED_UI_MOCKUP_LOCK=("o"+"ff")',
    ):
        assert _SKIP_HOOKS.search(cmd), cmd
    for cmd in (
        "ED_UI_GATE_LIVE=1 pytest",
        "ED_UI_MOCKUP_APPROVE=1 echo hi",
        "$env:ED_UI_MOCKUP_LOCK='on'",
        "ED_STOP_GUARD_TIMEOUT=0.5 run",
        "git commit -m 'normal'",
    ):
        assert _SKIP_HOOKS.search(cmd) is None, cmd


def test_lock_disable_env_is_a_blocked_action():
    """Self-audit finding 2026-08-02: operator_law_guard's skip-hooks ban enumerated only the
    four *_GUARD names, so ED_UI_MOCKUP_LOCK=off was silently agent-usable the day the lock
    shipped. Drives the REAL regex: every lock-disable env form must match; a benign env that
    merely contains GATE/LIVE must not."""
    from tools.operator_law_guard import _SKIP_HOOKS
    for cmd in ("ED_UI_MOCKUP_LOCK=off git commit", "ED_PRETOOLUSE_GUARD=off python x.py",
                "ED_STOP_GUARD=0 echo", "ED_PROOF_ONLY_GUARD=false echo",
                "ED_OPERATOR_LAW_GUARD=off echo"):
        assert _SKIP_HOOKS.search(cmd), cmd
    assert _SKIP_HOOKS.search("ED_UI_GATE_LIVE=1 pytest") is None
    assert _SKIP_HOOKS.search("git commit -m 'normal'") is None


def test_gate_screams_when_registry_is_unparseable(tmp_path, monkeypatch):
    """Clause 1 of check ui_mockup_approval: a deleted/corrupt registry must FAIL the gate,
    never silently gate nothing (self-audit finding 2026-08-02). SIMPLICITY REHAB note:
    this gate's retirement is proposed in the audited cut list (PR review covers static/);
    execution was classifier-denied 2026-08-24 — operator to run."""
    import tools.check_institutional_correctness as cic
    (tmp_path / "governance").mkdir()
    (tmp_path / REGISTRY_REL).write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(cic, "REPO", tmp_path)
    reasons = [str(v) for v in cic.check_ui_mockup_approval()]
    assert any("registry" in r and ("unparseable" in r or "missing" in r) for r in reasons)


def test_stop_still_blocks_edit_with_nothing_run():
    """SIMPLICITY REHAB 2026-08-24: the RC-190 same-turn turn_self_audit ledger clause is
    RETIRED (one obligation was enforced twice; commit + delta gate keep the roster).
    The SURVIVING Stop clause is pinned here: a production edit with NOTHING executed
    still blocks; running anything (tests/probe) clears exactly that block; and no
    retired RC-190 message resurfaces."""
    from tools.operator_law_guard import stop_violations
    nothing_run = [{"kind": "edit", "detail": "server.py"}]
    msgs = stop_violations(nothing_run)
    assert any("RAN WITHOUT ERROR" in m for m in msgs)
    cmd = ".venv/Scripts/python.exe -m pytest tests/x.py -q"
    verified = nothing_run + [{"kind": "bash", "detail": cmd}]
    # RESULT, NOT ISSUANCE (operator 2026-08-25): the seeded verification clears the block
    # only when it also ran WITHOUT ERROR (present in the successful-command set).
    assert stop_violations(verified, frozenset({cmd})) == []
    # Issued but not proven-successful (no transcript / errored) still blocks.
    assert stop_violations(verified, frozenset()) != []
    assert not any("RC-190" in m for m in stop_violations(nothing_run))


def test_turn_self_audit_blast_radius_and_suite_matching(tmp_path):
    """RC-190: the audit tool's matcher pairs changed modules with the attack suites that
    NAME them, and reports uncovered modules as findings rather than skipping them."""
    from tools.turn_self_audit import matching_attack_suites
    suites, uncovered = matching_attack_suites(["tools/ui_mockup_lock.py"])
    assert "tests/test_ui_mockup_lock_v1.py" in suites and not uncovered
    ghost = "zz_no_such_" + "module_zz"      # split so THIS file cannot satisfy the scan
    suites2, uncovered2 = matching_attack_suites([f"tools/{ghost}.py"])
    assert suites2 == [] and uncovered2 == [ghost]


def test_domain_faucet_lock_blocks_second_faucets():
    """RC-212 negative controls (operator: two faucets 'in any other way they can
    manifest' are strictly prohibited). Drives the REAL callee six ways."""
    from tools.check_institutional_correctness import domain_faucet_violations
    reg = (Path(__file__).resolve().parent.parent / "governance" /
           "level_faucets.json").read_text(encoding="utf-8")
    new_route = '@app.get("/api/levels-extra")\ndef f(): pass'
    # (a) unregistered level-domain producer -> scream
    assert domain_faucet_violations("server.py", new_route, reg)
    # (b) registered producer -> silent
    ok_route = '@app.get("/api/exposure/book")\ndef f(): pass'
    assert domain_faucet_violations("server.py", ok_route, reg) == []
    # (c) co-staged registry WITH operator_quote -> silent
    assert domain_faucet_violations(
        "server.py", new_route, reg,
        registry_staged_added='"operator_quote": "operator authorized the fifth"') == []
    # (d) inline d1-style greek outside math_levels -> scream
    greek = "d1 = (math.log(spot / strike) + 0.5 * s * s * t) / (s * math.sqrt(t))"
    assert domain_faucet_violations("terrain_engine.py", greek, reg)
    # (e) declared escape -> silent
    assert domain_faucet_violations(
        "terrain_engine.py", "# greek-faucet-ok: parity cross-check only\n" + greek,
        reg) == []
    # (f) corrupt registry -> scream (gates nothing silently)
    assert domain_faucet_violations("server.py", ok_route, "{broken")
    # math_levels itself is the faucet -> silent
    assert domain_faucet_violations("math_levels.py", greek, reg) == []


def test_operator_law_guard_wired_for_edit_tools():
    """RC-205: the Edit/Write branch of operator_law_guard was DEAD CODE because
    .claude/settings.json only routed Bash|PowerShell to it — the ledger never received
    'edit' entries and the RC-190/RC-203 Stop clauses were blind on edit-only turns
    (Cursor's lock research). This pins the wiring so it cannot silently unwire."""
    settings = json.loads((Path(__file__).resolve().parent.parent / ".claude" / "settings.json")
                          .read_text(encoding="utf-8"))
    edit_matchers = [m for m in settings["hooks"]["PreToolUse"]
                     if "Edit" in (m.get("matcher") or "")]
    assert edit_matchers, "no PreToolUse matcher covers Edit tools at all"
    cmds = "\n".join(h["command"] for m in edit_matchers for h in m["hooks"])
    assert "operator_law_guard" in cmds, (
        "operator_law_guard is not wired for Edit/Write — its ledger cannot see production "
        "edits and every edit-dependent Stop clause is blind (RC-205)")
    # BEDROCK 2026-09-06: pretooluse_guard is off the roster by design (its content gates and
    # the mutation-side latch are removed); an inert rostered guard is the E-05/E-07 class.
    assert "pretooluse_guard" not in cmds


def test_ship_confirmation_required_for_approved_surface_changes():
    """RC-194 negative control for clause 5 of check `ui_mockup_approval` (operator: "always
    confirm first with actual code before you ship"): an approved surface staged WITHOUT a
    ship-confirmation report screams; with a qualifying co-staged report it flows."""
    import tools.check_institutional_correctness as cic
    bare = cic.ship_confirmation_violations("static/chart.html", ["static/chart.html"])
    assert bare and "RENDERED-FRAME" in str(bare[0])
    conf = sorted((cic.REPO / "reports").glob("ship_confirmation_*.md"))
    assert conf, "no ship-confirmation report exists for the shipped v6 surface"
    ok = cic.ship_confirmation_violations(
        "static/chart.html",
        ["static/chart.html", f"reports/{conf[-1].name}"])
    assert ok == [], f"a qualifying confirmation did not satisfy clause 5: {ok}"
    assert cic.ship_confirmation_violations("tools/ui_mockup_lock.py", []) == []


