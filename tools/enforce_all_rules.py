#!/usr/bin/env python3
"""Single shared rule-enforcement orchestrator — binds BOTH agents (Claude + Cursor), mirrored.

ONE source of truth for deterministic rule checks. Invoked by every gate so neither agent
gets a weaker check:
  * Claude Code `Stop` hook  -> `python tools/enforce_all_rules.py --stop-hook`
  * git pre-commit / CI      -> `python tools/check_fix_everything_we_touch.py` + hooks
  * Before sign-off          -> `python tools/enforce_all_rules.py --enforce-all` (exit 0 required)

Every AGENTS.md `[PROMOTED]` rule maps to mechanical lock(s) in
`tools/check_fix_everything_we_touch.py::_PROMOTED_AGENTS_RULE_LOCKS` — verified by
`check_promoted_agents_rules_mechanically_locked()`. Prose-only rules are rejection-grade.
"""
from __future__ import annotations

import argparse
import ast
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ── Banned CLOSERS / output phrases (deterministic subset; sources cited) ─────────────────
# Conservative set: phrases that are violations in an agent's OUTPUT in essentially all
# contexts. Each entry: (compiled regex, rule_id, source). Kept tight to avoid false positives;
# the broader judgment set is on the --checklist. Extend here as new deterministic rules land.
# ALWAYS banned in asserted output (no escape) — permission/menu, wait-posture, lie-verdict,
# excuse/partial-completion, third-state, meet-or-exceed sign-off vocab. High-confidence multi-word
# phrases only (single common words like "mostly"/"by design" are too false-positive-prone for a
# blanket block and stay commit-scoped / checklist).
_BANNED_OUTPUT = [
    (r"\bstanding by\b", "lie-no-standing-by-unfixed", "AGENTS.md §Do not lie"),
    (r"\bsay the word\b", "npa-banned-patterns", "AGENTS.md §No permission asks"),
    (r"\bif you want,? i can\b", "npa-banned-patterns", "AGENTS.md §No permission asks"),
    (r"\bcomplete \(not closed\)", "ncr-banned-third-state", "AGENTS.md §No carried residuals"),
    (r"\b(tracked|disclosed|bounded-design) residual\b", "ncr-banned-third-state", "AGENTS.md §No carried residuals"),
    (r"\bworks as (designed|intended)\b", "bp-excuse", "AGENTS.md §Banned phrases"),
    (r"\bgood enough for now\b", "moe-banned-signoff-vocab", "AGENTS.md §Meet-or-Exceed"),
    (r"\b(mostly|substantially) complete\b", "moe-banned-signoff-vocab", "AGENTS.md §Meet-or-Exceed"),
    (r"\bpartial(ly)? meets\b|\bmeets with gaps\b", "moe-banned-signoff-vocab", "AGENTS.md §Meet-or-Exceed"),
    (r"\b(minimal|small) patch\b", "bp-excuse", "AGENTS.md §Banned phrases (excuse)"),
    (r"\bpartial fix\b", "bp-excuse", "AGENTS.md §Banned phrases (excuse)"),
    (r"\bacceptable drift\b", "bp-excuse", "AGENTS.md §Banned phrases"),
    (r"\brules are guidance\b", "bp-excuse", "AGENTS.md §Banned phrases"),
    (r"\boperator will catch\b", "bp-excuse", "AGENTS.md §Banned phrases"),
    (r"\blooks clean\b", "lie-no-impression-verdict", "AGENTS.md §Do not lie (impression-verdict)"),
    (r"\bappears orphaned\b", "lie-no-impression-verdict", "AGENTS.md §Do not lie"),
    (r"\bshould be safe\b", "lie-no-impression-verdict", "AGENTS.md §Do not lie"),
    (r"\bper (subagent|cursor|the agent|peer) summary\b", "lie-no-per-summary", "AGENTS.md §Do not lie"),
    (r"\bzero references outside itself\b", "del-banned-without-table", "AGENTS.md §File delete gatekeeper"),
    (r"\bsafe single-slice delete\b", "del-banned-without-table", "AGENTS.md §File delete gatekeeper"),
    # NO ASSUMPTIONS — verify, never assume (operator binding, hard-enforced). Asserting an
    # assumption instead of a verified fact is rejection-grade. Discuss the rule itself only inside
    # code blocks / `inline code` / >-quotes (those are stripped before scanning).
    (r"\bassum(e|es|ed|ing|ption|ptions)\b", "no-assume-verify", "AGENTS.md §No assumptions — verify, never assume"),
    (r"\bpresum(e|es|ed|ing|ably)\b", "no-assume-verify", "AGENTS.md §No assumptions — verify, never assume"),
    (r"\b(i'?d guess|my guess|i guess|i'?m guessing)\b", "no-assume-verify", "AGENTS.md §No assumptions — verify, never assume"),
]

# Banned UNLESS a [REAL-GATE:<tag>] is present in the message — deferral/parking & scope-narrowing.
_BANNED_UNLESS_REALGATE = [
    (r"\bdeferr(ed|ing)\b", "cdef-no-pending-variants", "AGENTS.md §Closure + no-deferral"),
    (r"\bfollow-up (commit|slice)\b", "cdef-no-pending-variants", "AGENTS.md §Closure + no-deferral"),
    (r"\bnext slice will\b|\bnext commit will\b", "cdef-no-pending-variants", "AGENTS.md §Closure + no-deferral"),
    (r"\b(will|can) land " + r"later\b", "cdef-no-pending-variants", "AGENTS.md §Closure + no-deferral"),
    (r"\bbroader sweep deferred\b", "cdef-no-pending-variants", "AGENTS.md §Closure + no-deferral"),
    (r"\b(implementation|consumer|behavioral spec) pending\b", "cdef-no-pending-variants", "AGENTS.md §Closure + no-deferral"),
    (r"\bout of scope\b", "scope-narrowing", "AGENTS.md §Banned phrases (scope-narrowing)"),
    (r"\bfor this section only\b|\bscope of (the )?current section\b", "scope-narrowing", "AGENTS.md §Banned phrases"),
    (r"\bscanner capability\b|\bscanner doesn'?t walk\b", "scope-narrowing", "AGENTS.md §Banned phrases"),
    (r"\bbased on the files i'?ve reviewed\b", "scope-narrowing", "AGENTS.md §Banned phrases"),
    (r"\bthe section is closed\b|\bmega \w+ is done\b", "scope-narrowing", "AGENTS.md §Banned phrases"),
]
# End-of-message closers (flagged only when near the END of the message).
#  - permission/menu asks
#  - "announce-and-stop": naming a next action Claude can do NOW, then ending the turn. This is a
#    punt/wait-posture (no-announce-and-stop rule, 2026-06-05). Self-promises only ("I'll build/add/
#    wire/do … next", "next, let me …") — NOT operator/Cursor-directed handoffs ("run X", "push X").
_BANNED_CLOSERS = [
    (r"(want me to\b.*\?|should i\b.*\?)\s*$", "npa-banned-patterns / banned_end_of_turn_phrases", "AGENTS.md §No permission asks"),
    (r"\b(next|then)[, ].{0,40}\bi'?ll\b.{0,60}$", "no-announce-and-stop", "AGENTS.md §Fix-as-we-find / no-deferral"),
    (r"\bi'?ll\b.{0,60}\bnext\b[.! ]*$", "no-announce-and-stop", "AGENTS.md §Fix-as-we-find / no-deferral"),
    (r"\b(let me|i'?ll|i will)\b.{0,60}\b(build|add|wire|implement|write|do|fix|create)\b.{0,40}(next|after this|then)\b[.! ]*$", "no-announce-and-stop", "AGENTS.md §Fix-as-we-find / no-deferral"),
]


def _strip_quotes(text: str) -> str:
    """Remove fenced code blocks, inline `code spans`, and >-quoted lines so DISCUSSING a banned
    phrase (quoting it to explain) does not false-positive. Only asserted prose is scanned."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    kept = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    return "\n".join(kept)


def _scan_output(text: str) -> list[str]:
    stripped = _strip_quotes(text)
    low = stripped.lower()
    has_realgate = "[real-gate" in low
    hits: list[str] = []
    for pat, rid, src in _BANNED_OUTPUT:
        if re.search(pat, low):
            hits.append(f"BANNED OUTPUT: /{pat}/ ({rid}) — {src}")
    if not has_realgate:  # deferral/scope phrases are allowed only with an explicit [REAL-GATE:<tag>]
        for pat, rid, src in _BANNED_UNLESS_REALGATE:
            if re.search(pat, low):
                hits.append(f"BANNED (no [REAL-GATE]): /{pat}/ ({rid}) — {src}")
    tail = low.rstrip()[-400:]
    for pat, rid, src in _BANNED_CLOSERS:
        if re.search(pat, tail, re.MULTILINE):
            hits.append(f"BANNED CLOSER: /{pat}/ ({rid}) — {src}")
    # ACTION ban (not just the word): a strong verdict asserted with NO shown evidence anywhere in
    # the response is the assume-action — claiming a verified state without showing the verification.
    # "verify, never assume" => every verdict carries its command/Read output in-turn, or it's omitted.
    # (`text` is the original; a fenced ``` block = shown command/Read output. Quoted/inline uses of
    # the verdict words are already stripped from `low`, so only ASSERTED verdicts count.)
    if "```" not in text:
        vm = re.search(
            r"\b(verified|confirmed|passes|passed|all (?:green|clean)|no issues|ready to run"
            r"|it works|fully (?:done|fixed|closed)|is clean|is done|is fixed|checks out|holds up)\b",
            low,
        )
        if vm:
            hits.append(
                f"BANNED ACTION (no-assume-verify): verdict {vm.group(0)!r} asserted with NO shown "
                f"evidence (no command/Read output block in the response) — show the verification "
                f"that proves it, or omit the claim. AGENTS.md §No assumptions — verify, never assume"
            )
    return hits


def _run_deterministic_file_checks(paths: list[Path]) -> list[str]:
    """All repo-wide mechanical locks — same as pre-commit static audit."""
    findings: list[str] = []
    str_paths = [str(p) for p in paths if p.exists()]
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.check_fix_everything_we_touch import run_repo_wide_static_audit

    static_errs = run_repo_wide_static_audit(staged=set())
    if static_errs:
        findings.append(
            "run_repo_wide_static_audit (all AGENTS promoted mechanical locks):\n- "
            + "\n- ".join(static_errs)
        )
    checks = [
        (["python", "tools/check_no_grep_subprocess.py", *[p for p in str_paths if p.endswith(".py")]],
         "no_grep_subprocess (AGENTS.md §Banned tools)"),
        (["python", "tools/check_no_deferral_language.py", *str_paths],
         "no_deferral_language (AGENTS.md §Closure + no-deferral)"),
    ]
    for cmd, label in checks:
        if len(cmd) <= 2:
            continue
        try:
            r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                findings.append(f"{label}:\n{(r.stdout + r.stderr).strip()}")
        except Exception as e:  # pragma: no cover - defensive
            findings.append(f"{label}: check failed to run: {e}")
    return findings


def _session_edited_files(transcript_path: str) -> list[Path]:
    """Files THIS session actually edited (Edit/Write/NotebookEdit tool_use file_path args).
    This is the correct scope for fix-what-you-touch — NOT the whole working tree."""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: set[str] = set()
    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg = obj.get("message") if isinstance(obj, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Edit", "Write", "NotebookEdit"):
                fp = (b.get("input") or {}).get("file_path")
                if fp:
                    out.add(fp)
    res = []
    for p in out:
        fp = Path(p)
        if fp.exists() and fp.suffix in (".py", ".html", ".js", ".css", ".md", ".json", ".yaml", ".yml", ".csv"):
            res.append(fp)
    return res


def _last_assistant_text(transcript_path: str) -> str:
    """Extract the most recent assistant text message from a Claude Code transcript (JSONL)."""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg = obj.get("message") if isinstance(obj, dict) else None
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _stop_hook() -> int:
    """Claude Code Stop hook entrypoint. Reads hook JSON on stdin; blocks turn-end on violation."""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    violations: list[str] = []
    tp = payload.get("transcript_path")
    if tp:
        violations += _scan_output(_last_assistant_text(tp))
    violations += _run_deterministic_file_checks(_session_edited_files(tp) if tp else [])
    if violations:
        reason = (
            "enforce_all_rules: turn blocked — resolve before stopping:\n- "
            + "\n- ".join(violations)
            + "\n\nRun: python tools/enforce_all_rules.py --enforce-all (exit 0 required before sign-off)."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        return 0
    return 0


def _check_files(paths: list[str]) -> int:
    findings = _run_deterministic_file_checks([Path(p) for p in paths])
    if findings:
        print("enforce_all_rules: violations:\n- " + "\n- ".join(findings), file=sys.stderr)
        return 1
    print("enforce_all_rules: file checks PASS")
    return 0


_CHECKLIST = (
    "All AGENTS [PROMOTED] rules are mechanically locked — run before sign-off:\n"
    "  python tools/enforce_all_rules.py --enforce-all\n"
    "  python tools/enforce_all_rules.py --objective-audit\n"
    "Prose-only compliance is rejection-grade. Rule text: AGENTS.md / CLAUDE.md."
)


def _ast_callname(node: ast.Call):
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _ast_callsites(funcname: str) -> int:
    """MANDATORY AST audit (AGENTS.md §Audit method): exhaustively report EVERY call site of
    `funcname` across the repo with its binding — tuple-unpack arity, single-name bind (possible
    two-step unpack), or arg/index use. Line-break-agnostic; catches what regex/eyeballing miss.
    Use on any signature/arity change to verify caller compatibility with certainty."""
    rows: list[tuple[str, int, str]] = []
    for fp in glob.glob(str(REPO / "**" / "*.py"), recursive=True):
        if "__pycache__" in fp:
            continue
        try:
            tree = ast.parse(Path(fp).read_text(encoding="utf-8"))
        except Exception:
            continue
        rel = str(Path(fp).relative_to(REPO))
        assign_of: dict[int, ast.Assign] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for c in ast.walk(node.value):
                    if isinstance(c, ast.Call) and _ast_callname(c) == funcname:
                        assign_of[id(c)] = node
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _ast_callname(node) == funcname:
                a = assign_of.get(id(node))
                if a is None:
                    rows.append((rel, node.lineno, "expr/arg/index use (no unpack)"))
                    continue
                t = a.targets[0]
                if isinstance(t, ast.Tuple):
                    rows.append((rel, a.lineno, f"unpack n={len(t.elts)}"))
                elif isinstance(t, ast.Name):
                    rows.append((rel, a.lineno, f"single-name '{t.id}' (verify downstream unpack)"))
                else:
                    rows.append((rel, a.lineno, f"target {type(t).__name__}"))
    if not rows:
        print(f"ast-callsites: no call sites of {funcname!r} found")
        return 0
    arities = sorted({r[2] for r in rows if r[2].startswith("unpack")})
    print(f"ast-callsites: {funcname} — {len(rows)} site(s); distinct unpack arities: {arities or '(none)'}")
    for f, ln, kind in sorted(rows):
        print(f"  {f}:{ln}  {kind}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stop-hook", action="store_true", help="Claude Code Stop hook mode (stdin JSON)")
    ap.add_argument("--check-files", nargs="*", help="run deterministic checks on these paths")
    ap.add_argument(
        "--ablation-bias",
        action="store_true",
        help="run ZERO-BIAS ablation contract (AGENTS.md §Ablation contract / ZERO-BIAS)",
    )
    ap.add_argument(
        "--code-quality",
        action="store_true",
        help="run universal code quality audit (AGENTS.md § simplicity and institutional pride)",
    )
    ap.add_argument(
        "--objective-audit",
        action="store_true",
        help="run Objective→Code→Audit closure audit (AGENTS.md § mandatory turn protocol; full-repo static + situational runtime)",
    )
    ap.add_argument(
        "--full-runtime",
        action="store_true",
        help="with --objective-audit: run every situational runtime probe (not only staged-cone fits)",
    )
    ap.add_argument(
        "--enforce-static",
        action="store_true",
        help="run full repo static rule locks (mirrors pre-commit contract checks; AGENTS § Mandatory enforcement registry)",
    )
    ap.add_argument(
        "--enforce-all",
        action="store_true",
        help="run ALL mechanical rule locks (static + code-quality + external tools audit)",
    )
    ap.add_argument("--checklist", action="store_true", help="print enforcement command summary")
    ap.add_argument("--ast-callsites", metavar="FUNC", help="AST audit: every call site of FUNC + binding arity")
    args = ap.parse_args(argv)
    if args.ast_callsites:
        return _ast_callsites(args.ast_callsites)
    if args.enforce_all:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from tools.check_fix_everything_we_touch import (
            check_external_rule_tools_wired,
            run_repo_wide_static_audit,
            run_universal_code_quality_audit,
        )

        failures = 0
        static_errs = run_repo_wide_static_audit(staged=set())
        if static_errs:
            print(
                "enforce_all_rules --enforce-all: static FAIL\n- " + "\n- ".join(static_errs),
                file=sys.stderr,
            )
            failures += 1
        else:
            print("enforce_all_rules --enforce-all: static PASS (all promoted mechanical locks)")
        ext = check_external_rule_tools_wired()
        if ext:
            print(
                "enforce_all_rules --enforce-all: external tools FAIL\n- " + "\n- ".join(ext),
                file=sys.stderr,
            )
            failures += 1
        cq = run_universal_code_quality_audit()
        if not cq.get("ok"):
            print(
                "enforce_all_rules --enforce-all: code-quality FAIL\n- "
                + "\n- ".join(cq.get("errors") or []),
                file=sys.stderr,
            )
            failures += 1
        else:
            print("enforce_all_rules --enforce-all: code-quality PASS")
        return 1 if failures else 0
    if args.enforce_static:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from tools.check_fix_everything_we_touch import run_repo_wide_static_audit

        errs = run_repo_wide_static_audit(staged=set())
        if errs:
            print(
                "enforce_all_rules --enforce-static: FAIL\n- " + "\n- ".join(errs),
                file=sys.stderr,
            )
            return 1
        print(
            "enforce_all_rules --enforce-static: PASS "
            "(repo-wide static locks incl. fusion-only cards + mandatory registry)"
        )
        return 0
    if args.code_quality:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from tools.check_fix_everything_we_touch import run_universal_code_quality_audit

        result = run_universal_code_quality_audit()
        if not result.get("ok"):
            print(
                "enforce_all_rules --code-quality: FAIL\n- "
                + "\n- ".join(result.get("errors") or []),
                file=sys.stderr,
            )
            return 1
        warns = result.get("warnings") or []
        if warns:
            print(
                "enforce_all_rules --code-quality: PASS with warnings (review long functions):\n- "
                + "\n- ".join(warns),
                file=sys.stderr,
            )
        else:
            print(
                "enforce_all_rules --code-quality: PASS "
                "(universal simplicity + institutional pride; staged Python audited)"
            )
        return 0
    if args.objective_audit:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from tools.check_fix_everything_we_touch import _git_staged_paths, run_objective_code_audit

        staged = _git_staged_paths()
        result = run_objective_code_audit(
            staged=staged,
            runtime=True,
            full_runtime=bool(args.full_runtime),
        )
        if not result.get("ok"):
            print(
                "enforce_all_rules --objective-audit: FAIL (audit_status=DEFECTS)\n"
                + json.dumps(
                    {
                        "scope": result.get("scope"),
                        "static_errors": result.get("static_errors"),
                        "runtime_errors": result.get("runtime_errors"),
                        "applied_runtime_audits": result.get("applied_runtime_audits"),
                        "skipped_runtime_audits": result.get("skipped_runtime_audits"),
                        "situational_results": result.get("situational_results"),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1
        print(
            "enforce_all_rules --objective-audit: PASS (AUDIT: CLEAN — "
            "repo-wide static + situational runtime where cone fits; "
            f"applied={result.get('applied_runtime_audits')!r})"
        )
        return 0
    if args.ablation_bias:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from tools.check_fix_everything_we_touch import (
            check_ablation_full_stack_non_negotiable,
            check_ablation_seven_model_four_horizon_grid,
            check_feature_list_no_model_preassignment,
            check_no_ablation_gate_bypass_in_money_path,
            check_production_fusion_score_path_contract,
            check_zero_bias_ablation_contract,
            run_ablation_integrity_audit,
        )

        errs = (
            check_ablation_seven_model_four_horizon_grid()
            + check_ablation_full_stack_non_negotiable()
            + check_zero_bias_ablation_contract()
            + check_production_fusion_score_path_contract()
            + check_no_ablation_gate_bypass_in_money_path()
            + check_feature_list_no_model_preassignment()
        )
        if errs:
            print("enforce_all_rules --ablation-bias: FAIL\n- " + "\n- ".join(errs), file=sys.stderr)
            return 1
        audit = run_ablation_integrity_audit(runtime=True)
        if not audit.get("ok"):
            print(
                "enforce_all_rules --ablation-bias: runtime FAIL\n"
                + json.dumps(
                    {
                        "static_errors": audit.get("static_errors"),
                        "runtime_ok": audit.get("runtime_ok"),
                        "preflight_ready": (audit.get("preflight") or {}).get("ready"),
                        "preflight_issues": (audit.get("preflight") or {}).get("issues"),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1
        print(
            "enforce_all_rules --ablation-bias: PASS (2632-cell grid; no partial-ready; "
            "7-layer whole-stack preflight + placement validity green)"
        )
        return 0
    if args.stop_hook:
        return _stop_hook()
    if args.checklist:
        print(_CHECKLIST)
        return 0
    if args.check_files is not None:
        return _check_files(args.check_files)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
