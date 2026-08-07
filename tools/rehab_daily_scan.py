"""Daily repo rehab scan (RC-218) — READ-ONLY recommendations.

Appends ranked findings to reports/rehab_queue.jsonl and writes reports/rehab_latest.md.
Does NOT edit product code, commit, or restart servers.

Usage:
  .venv/Scripts/python.exe tools/rehab_daily_scan.py
  .venv/Scripts/python.exe tools/rehab_daily_scan.py --json-only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QUEUE_PATH = REPO / "reports" / "rehab_queue.jsonl"
LATEST_MD = REPO / "reports" / "rehab_latest.md"
LATEST_JSON = REPO / "reports" / "rehab_latest.json"


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _run(argv: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(
            argv,
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
        return p.returncode, out.strip()
    except Exception as exc:  # noqa: BLE001 — scan must not die
        return 99, f"{type(exc).__name__}: {exc}"


def _git(*args: str) -> str:
    code, out = _run(["git", *args], timeout=60)
    return out if code == 0 else ""


def _measure() -> dict:
    py = REPO / ".venv" / "Scripts" / "python.exe"
    exe = str(py) if py.is_file() else sys.executable
    code, out = _run([exe, "tools/operating_process_lock.py", "--measure"], timeout=180)
    try:
        return json.loads(out) if out else {"error": "empty measure", "exit": code}
    except json.JSONDecodeError:
        return {"error": "measure_not_json", "exit": code, "raw": out[:2000]}


#: RC-250: how stale the advisory report may be before the scan calls it out. The daily job
#: refreshes it every run, so anything older than ~2 days means the schedule itself stopped.
ADVISORY_REPORT_REL = "reports/advisory_debt_latest.json"
ADVISORY_STALE_SEC = 48 * 3600.0


def _run_advisory_debt() -> dict:
    """RC-250: actually RUN the advisory checks P1 moved off the blocking commit path.

    RC-246 took 7 ADVISORY checks out of pre-commit (145s/commit faster) on the PM's explicit
    condition that they still surface daily. That condition was written into the row and the
    commit message but never wired: nothing invoked `--advisory`, so the only reason the report
    existed was a hand-typed one-shot. A capability without a caller is indistinguishable from
    a feature, from the inside — this is the caller.

    Read-only with respect to product code: the gate's advisory mode prints and returns 0, and
    this scan is recommendation-only by design.
    """
    py = REPO / ".venv" / "Scripts" / "python.exe"
    exe = str(py) if py.is_file() else sys.executable
    code, out = _run(
        [exe, "-m", "tools.check_institutional_correctness", "--advisory"], timeout=1800
    )
    report = REPO / ADVISORY_REPORT_REL
    info: dict = {"exit": code, "report": ADVISORY_REPORT_REL, "ran": True}
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
        info["total_advisory_violations"] = data.get("total_advisory_violations")
        info["checks"] = data.get("checks")
        info["measured_at_utc"] = data.get("measured_at_utc")
        # RC-251: hotspots are the WHERE. Omitting them here silently emptied the TQM queue —
        # the report had them, the reader dropped them, and triage produced zero items while
        # every count looked healthy. Caught by RUNNING the loop, not by reading it.
        info["hotspots"] = data.get("hotspots") or {}
    except (OSError, ValueError, json.JSONDecodeError) as e:
        info["error"] = f"{type(e).__name__}: {e}"
    if out:
        info["tail"] = out.strip().splitlines()[-1][:200]
    return info


def _advisory_findings(adv: dict) -> list[dict]:
    """A silent advisory run is the failure this row exists for — say so out loud."""
    import time as _time

    out: list[dict] = []
    if adv.get("error") or adv.get("total_advisory_violations") is None:
        out.append({
            "id": "rehab.advisory_report_missing",
            "severity": "P1",
            "facet": "governance_visibility",
            "summary": f"advisory debt report unreadable after run: {adv.get('error') or 'no total'}",
            "recommendation": (
                "P1 (RC-246) moved 7 advisory checks off pre-commit ONLY because this report "
                "keeps them visible. If it cannot be produced, that trade is void — fix the "
                "runner or put the checks back in the blocking path."
            ),
            "evidence": adv,
        })
        return out
    ts = adv.get("measured_at_utc")
    if isinstance(ts, (int, float)) and (_time.time() - float(ts)) > ADVISORY_STALE_SEC:
        out.append({
            "id": "rehab.advisory_report_stale",
            "severity": "P1",
            "facet": "governance_visibility",
            "summary": f"advisory debt report is older than {int(ADVISORY_STALE_SEC/3600)}h",
            "recommendation": "The scheduled rehab job is not firing — check the Task Scheduler entry.",
            "evidence": {"measured_at_utc": ts},
        })
    return out


#: RC-251: the TRIAGE artifact. Five is the cap because a queue longer than a session's
#: attention is a dump wearing a queue's clothes — the failure this row exists for.
TQM_QUEUE_REL = "reports/tqm_queue_latest.json"
TQM_MAX_ITEMS = 5

#: RC-255: module-level and therefore REDIRECTABLE, like QUEUE_PATH / LATEST_MD / LATEST_JSON.
#: This used to be built as `REPO / TQM_QUEUE_REL` inside the writer, which left it the one
#: artifact a test could not monkeypatch — so the two tests that drive main() wrote the real
#: tracked file and shipped a fixture (advisory_total 1, top_items []) into a commit.
TQM_QUEUE_PATH = REPO / TQM_QUEUE_REL


def _guard_repo_artifact(path: Path) -> None:
    """RC-255: a test may never write a TRACKED artifact — fail closed, not silently.

    Redirecting paths in tests is goodwill, and goodwill fails: forgetting is invisible,
    because the suite asserts what main() RETURNS and never what it TOUCHED. Under pytest a
    write aimed at the real reports/ tree is a defect in the test, so it raises there and
    stays inert in a real scheduled run.
    """
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        path.resolve().relative_to((REPO / "reports").resolve())
    except ValueError:
        return
    raise RuntimeError(
        f"RC-255: test tried to write the TRACKED artifact {path} — redirect it "
        f"(monkeypatch the module-level path) instead of mutating repo state"
    )

#: What a "smallest safe change" means per advisory check, and what would DISPROVE the item
#: being worth doing. Kill criteria are first-class: an item nobody can refuse is not triage.
_TQM_PLAYBOOK: dict[str, dict[str, str]] = {
    "ruff_quality": {
        "severity": "P2",
        "suggested_smallest_change": "ruff --fix on THIS FILE only, then run the file's own test module; commit the autofix alone",
        "kill_criteria": "kill if the file has no test module, or if --fix touches money-path semantics (greeks, levels, decisions) rather than style",
    },
    "mypy_types": {
        "severity": "P2",
        "suggested_smallest_change": "annotate the single function the error names; do not restructure call sites",
        "kill_criteria": "kill if the annotation forces a runtime change, or if the error is in a vendored/legacy tree scheduled for deletion",
    },
    "function_length": {
        "severity": "P3",
        "suggested_smallest_change": "extract ONE cohesive block into a named helper, with a behavioural test pinning before==after on real inputs",
        "kill_criteria": "kill if no behavioural test can be written for the extracted block — RC-19 split five circular imports to save seven lines; length is never worth a correctness risk",
    },
    "function_complexity": {
        "severity": "P3",
        "suggested_smallest_change": "collapse one guard ladder into an early-return, behaviour identical, test first",
        "kill_criteria": "kill if the complexity encodes real market branching (session states, tier fallbacks) — that is domain truth, not debt",
    },
    "file_length": {
        "severity": "P3",
        "suggested_smallest_change": "move one already-cohesive group to a sibling module; imports only, no logic edits",
        "kill_criteria": "kill unless the move is import-only; RC e52b5701 made SHAPE metrics track-but-never-block precisely because splitting to hit a number is the anti-pattern",
    },
    "orphan_dict_keys": {
        "severity": "P2",
        "suggested_smallest_change": "delete the key at its producer AND prove no consumer reads it (grep the payload name end-to-end)",
        "kill_criteria": "kill if any UI/API surface still reads the key — an orphan by static scan may be a live field via dynamic access",
    },
    "debt_ratchet": {
        "severity": "P1",
        "suggested_smallest_change": "read the ratchet delta and revert whichever change raised it, or record why the rise is correct",
        "kill_criteria": "kill if the rise is a deliberate, reviewed addition already justified in an RC row",
    },
}


def _load_prior_advisory_total() -> int | None:
    """Previous run's total, for the RE-MEASURE stage. Without a baseline no action can be
    shown to have helped, which is how quality work becomes unfalsifiable."""
    try:
        prior = json.loads(TQM_QUEUE_PATH.read_text(encoding="utf-8"))
        val = prior.get("advisory_total")
        return int(val) if isinstance(val, (int, float)) else None
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return None


def _build_tqm_queue(adv: dict) -> dict:
    """RC-251: turn a 3,349-line tally into at most five things worth doing next.

    Ranking is by (check severity, then hotspot density) — a file with 40 findings of one rule
    is one bounded change; 40 files with one finding each is a sweep, and sweeps are banned.
    """
    prior_total = _load_prior_advisory_total()
    total = adv.get("total_advisory_violations")
    hotspots: dict = adv.get("hotspots") or {}
    sev_rank = {"P1": 0, "P2": 1, "P3": 2}

    candidates: list[dict] = []
    for check, per_file in hotspots.items():
        play = _TQM_PLAYBOOK.get(check, {
            "severity": "P3",
            "suggested_smallest_change": "inspect the top file and make the narrowest change that clears it",
            "kill_criteria": "kill if the change cannot be covered by an existing or new test",
        })
        for path, count in list(per_file.items())[:3]:
            candidates.append({
                "id": f"tqm.{check}.{path.replace('/', '.')}",
                "check": check,
                "path": path,
                "count": count,
                "severity": play["severity"],
                "kill_criteria": play["kill_criteria"],
                "suggested_smallest_change": play["suggested_smallest_change"],
                "why_now": f"{count} {check} finding(s) concentrated in one file — a bounded change, not a sweep",
            })
    candidates.sort(key=lambda c: (sev_rank.get(c["severity"], 9), -int(c["count"])))
    top = candidates[:TQM_MAX_ITEMS]

    return {
        "generated_at_utc": datetime.now(timezone.utc).timestamp(),
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "advisory_total": total,
        "prior_total": prior_total,
        "delta": (total - prior_total) if isinstance(total, int) and isinstance(prior_total, int) else None,
        "checks": adv.get("checks") or {},
        "top_items": top,
        "cap": TQM_MAX_ITEMS,
        "note": (
            "TRIAGE stage of the TQM loop. Work ONLY these items. Mass-rewriting the advisory "
            "backlog is banned: every change needs a reproduce command and a test."
        ),
    }


def _write_tqm_queue(queue: dict) -> Path:
    out = TQM_QUEUE_PATH
    _guard_repo_artifact(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def _porcelain_stats() -> dict:
    raw = _git("status", "--porcelain")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    staged = sum(1 for ln in lines if ln[0] not in (" ", "?"))
    untracked = sum(1 for ln in lines if ln.startswith("??"))
    modified = sum(1 for ln in lines if "M" in ln[:2] or ln[1] == "M")
    return {
        "porcelain_lines": len(lines),
        "staged_ish": staged,
        "untracked": untracked,
        "modified_ish": modified,
    }


def _head() -> str:
    return _git("rev-parse", "--short", "HEAD").strip() or "UNKNOWN"


def _product_findings() -> list[dict]:
    """Product defects, from the scanners that read the running system (RC-271).

    Every finding this scan could previously emit was about PROCESS --
    dirty_tree_sprawl, index_wt_drift, pm_not_cursor, staged_only_checks. Ten
    ids, all governance. Meanwhile direct measurement of the product found 850
    multi-producer fields with 12 disagreeing, a function at cyclomatic
    complexity 608 against a review threshold of 15, coverage unmeasured across
    544 test files, and p95 latency of 1560ms against a 200ms budget. The
    nightly report the operator asked for reported none of it.

    These call the existing scanners rather than reimplementing them, so there
    is one queue and one report and no second surface to drift.
    """
    out: list[dict] = []
    py = str(REPO / ".venv" / "Scripts" / "python.exe")
    if not os.path.exists(py):
        py = sys.executable

    # --- one faucet per field: does the product contradict itself? ---------
    code, text = _run([py, "tools/check_one_faucet_live.py", "--skip-if-down"],
                      timeout=180)
    hit = re.search(r"DISAGREEING\s*:\s*(\d+)", text or "")
    if hit and int(hit.group(1)) > 0:
        fields = re.findall(r"FAIL\s+(\S+)\s+\[", text)
        out.append({
            "id": "rehab.product.faucets_disagree",
            "severity": "P0",
            "facet": "one_faucet",
            "summary": f"{hit.group(1)} field(s) disagree across endpoints "
                       f"right now: {', '.join(fields[:6])}",
            "recommendation": "Two screens can show contradictory numbers with "
                              "nothing to detect it. One producer per field "
                              "(RC-262).",
            "evidence": {"fields": fields[:20]},
        })

    # --- database health against published standards -----------------------
    code, text = _run([py, "tools/check_db_health.py"], timeout=300)
    if code == 1:
        fails = re.findall(r"\[FAIL\] ([^\n]+)", text or "")
        out.append({
            "id": "rehab.product.db_health",
            "severity": "P1",
            "facet": "data_quality",
            "summary": f"{len(fails)} database health rule(s) failing",
            "recommendation": "DAMA dimensions and OHLC invariants; see "
                              "tools/check_db_health.py for the cited source.",
            "evidence": {"failing": fails[:12]},
        })

    # --- duplication register ----------------------------------------------
    code, text = _run([py, "tools/duplication_audit.py"], timeout=600)
    hit = re.search(r"TOTAL\s+(\d+)", text or "")
    if hit and int(hit.group(1)) > 0:
        rows = re.findall(r"!(\S+)\s+(\d+)\s", text or "")
        out.append({
            "id": "rehab.product.duplication",
            "severity": "P1",
            "facet": "multi_faucet",
            "summary": f"{hit.group(1)} duplications across "
                       f"{len(rows)} class(es)",
            "recommendation": "One implementation of everything. Run "
                              "tools/duplication_audit.py for the register.",
            "evidence": {"by_class": dict(rows)},
        })

    # --- complexity outliers, threshold from the published standard ---------
    try:
        import ast

        DECISION = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
                    ast.With, ast.AsyncWith, ast.Assert, ast.BoolOp, ast.IfExp,
                    ast.comprehension)
        worst: list[tuple[int, str, int, str]] = []
        skip = {".venv", "node_modules", "__pycache__", "site-packages",
                "backups", "scratchpad", "tests"}
        for path in REPO.rglob("*.py"):
            if any(part in skip for part in path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                cc = 1 + sum(1 for n in ast.walk(node) if isinstance(n, DECISION))
                if cc > 15:            # codeant: flag above 15
                    worst.append((cc, _display_path(path), node.lineno, node.name))
        if worst:
            worst.sort(reverse=True)
            top = [f"CC {c} {p}:{ln} {n}()" for c, p, ln, n in worst[:5]]
            out.append({
                "id": "rehab.product.complexity",
                "severity": "P1" if worst[0][0] > 100 else "P2",
                "facet": "codebase_quality",
                "summary": f"{len(worst)} function(s) above the CC>15 review "
                           f"threshold; worst is {worst[0][0]}",
                "recommendation": "Median CC under 10, flag above 15 "
                                  "(codeant seven axes). The worst outliers "
                                  "carry the risk, not the median.",
                "evidence": {"worst": top},
            })
    except Exception as exc:            # noqa: BLE001 — scan must not die
        out.append({
            "id": "rehab.product.complexity_unmeasured",
            "severity": "P2",
            "facet": "codebase_quality",
            "summary": f"complexity scan failed: {type(exc).__name__}",
            "recommendation": "Fix the scanner; an unmeasured axis reads as clean.",
            "evidence": {},
        })

    # --- coverage: unmeasured is not the same as good ----------------------
    has_cov = (REPO / ".coverage").exists() or any(
        REPO.rglob("coverage*.xml"))
    if not has_cov:
        out.append({
            "id": "rehab.product.coverage_unmeasured",
            "severity": "P1",
            "facet": "codebase_quality",
            "summary": "no coverage artefact: test coverage is unmeasured",
            "recommendation": "544 test files prove tests EXIST, not that they "
                              "cover anything. Target >=80% on core modules.",
            "evidence": {},
        })
    return out


def _collect_findings(measure: dict, status: dict) -> list[dict]:
    findings: list[dict] = _product_findings()
    now = datetime.now(timezone.utc).isoformat()

    live = measure.get("live_collect_disk_only")
    if live:
        findings.append(
            {
                "id": "rehab.live_disk_only",
                "severity": "P0",
                "facet": "collect_runtime",
                "summary": str(live),
                "recommendation": "Operator restart :8000 when ready; until then status is DISK_ONLY_UNTIL_RESTART.",
                "evidence": {"live_collect_disk_only": live},
            }
        )

    mismatches = measure.get("index_worktree_mismatches") or []
    if mismatches:
        findings.append(
            {
                "id": "rehab.index_wt_drift",
                "severity": "P0",
                "facet": "worktree_integrity",
                "summary": f"{len(mismatches)} enforcement path(s) index≠WT",
                "recommendation": "Reconcile WT from index (or re-stage intentional WT) before any green claim or commit.",
                "evidence": {"paths": mismatches[:40]},
            }
        )

    staged_checks = measure.get("staged_checks_not_on_head") or []
    if staged_checks:
        findings.append(
            {
                "id": "rehab.staged_only_checks",
                "severity": "P1",
                "facet": "governance_head_lag",
                "summary": f"{len(staged_checks)} ENFORCED check(s) staged but not on HEAD",
                "recommendation": "Operator GO + coherent iceberg commit, or unstage intentionally. AGENTS claims must not outrun HEAD.",
                "evidence": {"checks": staged_checks[:40]},
            }
        )

    faucet = REPO / "governance" / "level_faucets.json"
    if not faucet.is_file():
        findings.append(
            {
                "id": "rehab.level_faucets_missing",
                "severity": "P1",
                "facet": "multi_faucet",
                "summary": "governance/level_faucets.json missing on disk",
                "recommendation": "Restore registry; domain faucet lock gates nothing without it.",
                "evidence": {},
            }
        )
    else:
        in_index = bool(_git("ls-files", "governance/level_faucets.json").strip())
        if not in_index:
            findings.append(
                {
                    "id": "rehab.level_faucets_untracked",
                    "severity": "P1",
                    "facet": "multi_faucet",
                    "summary": "level_faucets.json on disk but not in git index/HEAD",
                    "recommendation": "Stage/commit with domain faucet checker so RC-212 class cannot CLOSED-ahead-of-HEAD.",
                    "evidence": {},
                }
            )

    if status.get("porcelain_lines", 0) >= 100:
        findings.append(
            {
                "id": "rehab.dirty_tree_sprawl",
                "severity": "P2",
                "facet": "worktree_hygiene",
                "summary": f"Dirty tree sprawl: {status.get('porcelain_lines')} porcelain lines",
                "recommendation": "PM: sequence landings; avoid multi-mission dirt; path-limited commits only.",
                "evidence": status,
            }
        )

    sole = REPO / "governance" / "sole_writer.json"
    if sole.is_file():
        try:
            sw = json.loads(sole.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            sw = {}
        if str(sw.get("pm", "")).lower() != "cursor":
            findings.append(
                {
                    "id": "rehab.pm_not_cursor",
                    "severity": "P1",
                    "facet": "process",
                    "summary": "sole_writer.pm is not 'cursor'",
                    "recommendation": "Set governance/sole_writer.json pm=cursor (RC-218).",
                    "evidence": {"pm": sw.get("pm")},
                }
            )

    # Code-health BLOCKING (best-effort; may be slow)
    py = REPO / ".venv" / "Scripts" / "python.exe"
    exe = str(py) if py.is_file() else sys.executable
    panel = REPO / "tools" / "code_health_panel.py"
    if panel.is_file():
        code, out = _run([exe, str(panel), "--check"], timeout=300)
        if code != 0:
            findings.append(
                {
                    "id": "rehab.code_health_blocking",
                    "severity": "P1",
                    "facet": "static_quality",
                    "summary": "code_health_panel --check non-zero (BLOCKING defects or unmeasurable)",
                    "recommendation": "Run /code-health quality circle; drive BLOCKING to 0.",
                    "evidence": {"exit": code, "tail": out[-1500:]},
                }
            )

    for f in findings:
        f["scanned_at_utc"] = now
        f["head"] = _head()
    return findings


def _write_outputs(findings: list[dict], measure: dict, status: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "scanned_at_utc": now,
        "head": _head(),
        "finding_count": len(findings),
        "findings": findings,
        "measure": measure,
        "status": status,
        "pm": "cursor",
        "mode": "recommend_only",
    }
    for _artifact in (QUEUE_PATH, LATEST_JSON, LATEST_MD):
        _guard_repo_artifact(_artifact)
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"scanned_at_utc": now, "head": payload["head"], "findings": findings}) + "\n")
    LATEST_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# Rehab latest — {now}",
        "",
        f"**HEAD:** `{payload['head']}` · **PM:** Cursor · **Mode:** recommend only (no auto-edit)",
        "",
        f"Findings: **{len(findings)}**",
        "",
        "| Sev | ID | Facet | Summary | Recommendation |",
        "|-----|----|-------|---------|----------------|",
    ]
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    for f in sorted(findings, key=lambda x: order.get(str(x.get("severity")), 9)):
        lines.append(
            f"| {f.get('severity')} | `{f.get('id')}` | {f.get('facet')} | "
            f"{str(f.get('summary', '')).replace('|', '/')} | "
            f"{str(f.get('recommendation', '')).replace('|', '/')} |"
        )
    if not findings:
        lines.append("| — | — | — | No findings this scan | Keep PM cadence |")

    # RC-251: the report a human or agent acts from. Totals answer "how much", hotspots answer
    # "where", delta answers "is it getting better", and the TQM queue answers "what next" —
    # a report missing any of those is a dump, and dumps are what this loop replaced.
    adv = (measure or {}).get("advisory_debt") or {}
    tqm = (measure or {}).get("tqm_queue") or {}
    if adv or tqm:
        total = adv.get("total_advisory_violations")
        prior = tqm.get("prior_total")
        delta = tqm.get("delta")
        arrow = "—" if delta is None else ("▲ +%d" % delta if delta > 0 else ("▼ %d" % delta if delta < 0 else "= 0"))
        lines.extend([
            "",
            "## Advisory debt (P1/RC-246 moved these off the blocking commit path)",
            "",
            f"**Total: {total}** · prior: {prior if prior is not None else '—'} · delta: {arrow}",
            "",
            "| Check | Count |",
            "|---|---:|",
        ])
        for name, count in sorted((adv.get("checks") or {}).items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{name}` | {count} |")

        hotspots = adv.get("hotspots") or {}
        if hotspots:
            lines.extend(["", "### Top hotspots (file · rule · count)", "",
                          "| File | Check | Count |", "|---|---|---:|"])
            flat = [(p, c, n) for c, per in hotspots.items() for p, n in list(per.items())[:3]]
            for path, check, n in sorted(flat, key=lambda t: -t[2])[:10]:
                lines.append(f"| `{path}` | {check} | {n} |")

        items = tqm.get("top_items") or []
        lines.extend([
            "",
            f"## TQM queue — next ACT cycle (max {tqm.get('cap', TQM_MAX_ITEMS)})",
            "",
            "Work ONLY these. Mass-rewriting the backlog is banned: every change needs a "
            "reproduce command and a test, and each item below carries the criteria that "
            "would KILL it as not-worth-doing.",
            "",
        ])
        if not items:
            lines.append("_No actionable hotspots this run._")
        for i, it in enumerate(items, 1):
            lines.extend([
                f"**{i}. [{it.get('severity')}] `{it.get('check')}` → `{it.get('path')}` "
                f"({it.get('count')} finding(s))**",
                "",
                f"- why now: {it.get('why_now')}",
                f"- smallest safe change: {it.get('suggested_smallest_change')}",
                f"- kill criteria: {it.get('kill_criteria')}",
                "",
            ])
        lines.extend([
            f"Machine-readable queue: `{TQM_QUEUE_REL}` · tally: `reports/advisory_debt_latest.json`",
            "",
            "RE-MEASURE after acting: re-run this scan and confirm the delta moved. "
            "A win claimed in chat is not a win.",
        ])

    lines.extend(
        [
            "",
            "## Operator next",
            "",
            "1. PM (Cursor) triages this table.",
            "2. Operator green-lights one mission.",
            "3. Sole writer executes; Cursor audits.",
            "",
            f"Queue log: `{_display_path(QUEUE_PATH)}`",
            "",
        ]
    )
    LATEST_MD.write_text("\n".join(lines), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument(
        "--skip-advisory",
        action="store_true",
        help="skip the advisory-debt run (RC-250: the run is ON by default because P1 moved "
             "those checks off pre-commit only on condition they surface here)",
    )
    args = ap.parse_args(argv)
    measure = _measure()
    status = _porcelain_stats()
    findings = _collect_findings(measure, status)
    # RC-250: the caller P1 promised and never wired. Advisory checks cannot block a commit;
    # this is the path that keeps them VISIBLE, which is the whole basis of that trade.
    tqm_queue: dict | None = None
    if not args.skip_advisory:
        advisory = _run_advisory_debt()
        # RC-251: TRIAGE must be built from the SAME run that measured, and the prior total
        # must be read BEFORE the new queue overwrites it, or the delta compares a file to
        # itself and every day reports "no change".
        tqm_queue = _build_tqm_queue(advisory)
        _write_tqm_queue(tqm_queue)
        measure["advisory_debt"] = advisory
        measure["tqm_queue"] = tqm_queue
        findings.extend(_advisory_findings(advisory))
    payload = _write_outputs(findings, measure, status)
    def _safe_print(msg: str) -> None:
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", "replace").decode("ascii"))

    if args.json_only:
        _safe_print(json.dumps(payload, indent=2))
    else:
        _safe_print(f"rehab_daily_scan: {len(findings)} finding(s) -> {LATEST_MD}")
        for f in findings:
            _safe_print(f"  [{f.get('severity')}] {f.get('id')}: {f.get('summary')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
