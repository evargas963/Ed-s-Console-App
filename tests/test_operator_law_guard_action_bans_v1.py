# institutional-synthetic-ok: these tests INJECT banned shell / edit spellings to prove the
# action bans BLOCK and the sanctioned forms flow — that is their entire purpose.
"""Action-ban negative controls for tools/operator_law_guard.py and two gate seams.

BEDROCK PR B (2026-09-06): these controls lived in tests/test_ui_mockup_lock_v1.py because
the RC-189 mockup-registry rule was one of the actions banned there. The registry, its lock
and that rule are retired (governance/retired_checks.md, ui_mockup_approval); the general
bans they sat beside are unchanged and moved here verbatim: lock-disable env spellings
(RC-186/RC-189 GUN 2), constructed -c / PowerShell write targets (RC-189 v2), the
ledger-status honesty clause, the domain-faucet registry seam (RC-212), the Edit-tool hook
wiring (RC-205) and the UTF-8 git reader (RC-187).
"""
from __future__ import annotations

import json
from pathlib import Path


def test_guard_git_reads_utf8_governance_content_without_locale_decode_errors():
    """RC-187 lock: the guard's `_git` must decode git output as UTF-8, not the locale
    codepage. Before the pin, `git show HEAD:governance/root_cause_log.md` threw
    UnicodeDecodeError in the capture reader thread on cp1252 hosts and silently degraded
    the RC-66 check to never-block. Drives the REAL callee against the REAL log."""
    from tools.pretooluse_guard import _git
    out = _git(["show", "HEAD:governance/root_cause_log.md"])
    assert out is not None and "| RC-" in out


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
