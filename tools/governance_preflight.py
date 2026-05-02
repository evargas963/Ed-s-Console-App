#!/usr/bin/env python3
"""
Governance mechanical preflight — governance/**/*.md only.

Hard fails: encoding/mojibake (R1), merge-gate template leakage (R2),
merge gate Run history Commit/PR for runs on or after 2026-05-02 (R3).

Semantic alignment: warnings only (R4). See governance/OPERATOR_PREFLIGHT.md.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Repository root = parent of tools/
REPO_ROOT = Path(__file__).resolve().parent.parent
GOVERNANCE = REPO_ROOT / "governance"
MERGE_GATE_NAME = "GOVERNANCE_MERGE_GATE.md"
MERGE_GATE_PATH = GOVERNANCE / MERGE_GATE_NAME

# R1 — UTF-8 strict + common mojibake (UTF-8 misread as Latin-1/Windows-1252).
# Do not match lone U+00A7 (§); these are multi-byte mojibake *sequences* as str literals.
MOJIBAKE_MARKERS = (
    "ΓÇ",
    "┬",
    "Ã",
    "Â§",  # mojibake for §, not the single character §
    "â€",
    "â€™",
)

# R2 — only GOVERNANCE_MERGE_GATE.md (high-confidence template / instruction leakage).
MERGE_GATE_FAIL_SUBSTRINGS = (
    "replace this",
    "after `git commit`",
    "after git commit",
    "placeholder",
    "commit_sha",
    "<sha",
    "todo: fill",
    "fill in this",
)

R3_CUTOFF = "2026-05-02"
COMMIT_PR_RE = re.compile(r"^[0-9a-f]{40}$")
HEADING_DATE_RE = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\b")
RUN_HISTORY_START = re.compile(r"^##\s+Run history\b", re.IGNORECASE)
LEVEL2_HEADING_RE = re.compile(r"^##\s+")
OPERATOR_SIG_DATE_RE = re.compile(
    r"\*\*Operator signature:\*\*\s*\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
REGISTER_DOC_DATE_RE = re.compile(
    r"\*\*Document date:\*\*\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
REGISTER_APPROVAL_RE = re.compile(
    r"\*\*Approval effective:\*\*\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
PHASE_VERSION_LOCKED_RE = re.compile(
    r"\*\*Version:\*\*\s*([\d.]+)\s+LOCKED",
    re.IGNORECASE,
)


def fail(msg: str) -> None:
    print(msg, file=sys.stderr)


def warn(msg: str) -> None:
    print(msg, file=sys.stderr)


def info(msg: str) -> None:
    print(msg, file=sys.stderr)


def read_text_strict(path: Path) -> tuple[list[str] | None, str | None]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return None, "UTF-8 BOM present (reject for consistency)"
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as e:
        return None, f"UTF-8 strict decode failed: {e}"
    lines = text.splitlines()
    return lines, None


def check_r1_encoding(path: Path, lines: list[str]) -> list[tuple[int, str]]:
    findings: list[tuple[int, str]] = []
    joined = "\n".join(lines)
    for marker in MOJIBAKE_MARKERS:
        if marker in joined:
            # Attribute to first line containing marker
            for i, line in enumerate(lines, start=1):
                if marker in line:
                    findings.append((i, f"R1_ENCODING:mojibake_marker:{marker!r}"))
                    break
    return findings


def check_r2_merge_gate_placeholders(path: Path, lines: list[str]) -> list[tuple[int, str]]:
    if path.name != MERGE_GATE_NAME:
        return []
    findings: list[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        lower = line.lower()
        for sub in MERGE_GATE_FAIL_SUBSTRINGS:
            if sub in lower:
                findings.append((i, f"R2_MERGE_GATE:{sub!r}"))
                break  # one rule hit per line is enough
    return findings


def _normalize_table_key(cell: str) -> str:
    return re.sub(r"\*+", "", cell).strip()


def check_r3_merge_gate_commit_pr(lines: list[str]) -> tuple[list[tuple[int, str]], list[str]]:
    failures: list[tuple[int, str]] = []
    warnings: list[str] = []
    if not MERGE_GATE_PATH.exists():
        return failures, warnings

    def sha_exists(sha: str) -> tuple[bool, str | None]:
        git_dir = REPO_ROOT / ".git"
        if not git_dir.exists():
            return True, None  # skip — not a failure
        try:
            r = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", f"{sha}^{{commit}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode != 0:
                return False, (r.stderr or r.stdout or "").strip()
            return True, None
        except (OSError, subprocess.SubprocessError) as e:
            warnings.append(f"R3_MERGE_GATE:git_rev_parse_error:{e}")
            return True, None

    in_run_history = False
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if RUN_HISTORY_START.match(stripped):
            in_run_history = True
            i += 1
            continue
        if in_run_history and LEVEL2_HEADING_RE.match(stripped) and not stripped.startswith("###"):
            break
        if in_run_history:
            m = HEADING_DATE_RE.match(stripped)
            if m:
                sec_date = m.group(1)
                block_start = i  # 0-based index of ### line
                j = i + 1
                while j < len(lines):
                    nxt = lines[j].strip()
                    if nxt.startswith("###"):
                        break
                    if LEVEL2_HEADING_RE.match(nxt) and not nxt.startswith("###"):
                        break
                    j += 1
                if sec_date >= R3_CUTOFF:
                    block_lines = lines[block_start:j]
                    commit_pr = None
                    commit_line: int | None = None
                    run_date_val = None
                    for idx, raw in enumerate(block_lines):
                        if not raw.strip().startswith("|"):
                            continue
                        parts = [p.strip() for p in raw.split("|")]
                        parts = [p for p in parts if p != ""]
                        if len(parts) < 2:
                            continue
                        key = _normalize_table_key(parts[0])
                        val = (
                            parts[1]
                            if len(parts) == 2
                            else "|".join(parts[1:]).strip()
                        )
                        if key == "Commit / PR":
                            commit_pr = val.strip().strip("`")
                            commit_line = block_start + idx + 1  # 1-based file line
                        if key == "Run date":
                            run_date_val = val.strip()

                    if commit_pr is None:
                        failures.append(
                            (
                                block_start + 1,
                                f"R3_MERGE_GATE:missing_Commit/PR:section_date={sec_date}",
                            )
                        )
                    elif not COMMIT_PR_RE.match(commit_pr):
                        failures.append(
                            (
                                commit_line or (block_start + 1),
                                f"R3_MERGE_GATE:Commit/PR_not_40_hex_lowercase:{commit_pr!r}",
                            )
                        )
                    else:
                        ok, err = sha_exists(commit_pr)
                        if not ok:
                            failures.append(
                                (
                                    commit_line or (block_start + 1),
                                    f"R3_MERGE_GATE:git_object_missing:{commit_pr!r}:{err}",
                                )
                            )

                    if run_date_val and run_date_val != sec_date:
                        warnings.append(
                            "R4_MERGE_GATE:Run_date_"
                            f"{run_date_val!r}_differs_from_heading_{sec_date!r}"
                        )
                i = j
                continue
        i += 1

    return failures, warnings


def check_r4_semantic_hints(paths: list[Path]) -> list[str]:
    warnings: list[str] = []
    by_name = {p.name: p for p in paths}

    reg = by_name.get("OPERATOR_DECISION_REGISTER.md")
    if reg and reg.exists():
        text = reg.read_text(encoding="utf-8")
        dm = REGISTER_DOC_DATE_RE.search(text)
        am = REGISTER_APPROVAL_RE.search(text)
        if dm and am and dm.group(1) != am.group(1):
            warnings.append(
                f"R4_REGISTER:document_date_{dm.group(1)!r}_!=_approval_effective_{am.group(1)!r}:{reg}"
            )

    mg = by_name.get(MERGE_GATE_NAME)
    if mg and mg.exists():
        text = mg.read_text(encoding="utf-8")
        lines = text.splitlines()
        sig_m = OPERATOR_SIG_DATE_RE.search(text)
        sig_date = sig_m.group(1) if sig_m else None
        heading_dates: list[str] = []
        in_rh = False
        for line in lines:
            if RUN_HISTORY_START.match(line.strip()):
                in_rh = True
                continue
            if in_rh and LEVEL2_HEADING_RE.match(line.strip()) and not line.strip().startswith(
                "###"
            ):
                break
            if in_rh:
                m = HEADING_DATE_RE.match(line.strip())
                if m:
                    heading_dates.append(m.group(1))
        if sig_date and heading_dates:
            last_heading = max(heading_dates)
            if last_heading != sig_date:
                warnings.append(
                    f"R4_MERGE_GATE:last_Run_history_heading_{last_heading!r}_!=_operator_signature_date_{sig_date!r}"
                )

    plan = by_name.get("PHASE_PLAN_INFRASTRUCTURE.md")
    if plan and plan.exists():
        text = plan.read_text(encoding="utf-8")
        vm = PHASE_VERSION_LOCKED_RE.search(text)
        if vm:
            ver = vm.group(1)
            if "### Changelog" in text:
                tail = text.split("### Changelog", 1)[1]
                # stop at next --- line that starts doc end or ## 18
                if ver not in tail[:8000]:
                    warnings.append(
                        f"R4_PHASE_PLAN:Version_{ver!r}_LOCKED_but_changelog_heuristic_missing_version_token"
                    )
            # §18 table Version cell vs header
            m18 = re.search(
                r"\|\s*\*\*Version\*\*\s*\|\s*\*\*([\d.]+)\s+LOCKED\*\*",
                text,
                re.IGNORECASE,
            )
            if m18:
                v18 = m18.group(1)
                if v18 != ver:
                    warnings.append(
                        f"R4_PHASE_PLAN:header_Version_{ver!r}_!=_§18_table_Version_{v18!r}"
                    )

    return warnings


def collect_md_paths(explicit: list[str] | None) -> list[Path]:
    gov_resolved = GOVERNANCE.resolve()
    if explicit:
        out = []
        for s in explicit:
            p = (REPO_ROOT / s).resolve() if not Path(s).is_absolute() else Path(s)
            try:
                p.relative_to(gov_resolved)
            except ValueError:
                fail(f"[FAIL]::{Path(s)}:R0_PATH:path_must_be_under_governance/")
                sys.exit(1)
            if p.suffix.lower() != ".md":
                fail(f"[FAIL]::{p}:R0_PATH:not_markdown")
                sys.exit(1)
            if not p.is_file():
                fail(f"[FAIL]::{p}:R0_PATH:missing_file")
                sys.exit(1)
            out.append(p)
        return sorted(set(out))
    return sorted(GOVERNANCE.rglob("*.md"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Governance mechanical preflight")
    parser.add_argument(
        "--paths",
        nargs="+",
        help="Limit scan to these paths (must be under governance/, .md only)",
    )
    args = parser.parse_args()

    paths = collect_md_paths(args.paths)
    fail_count = 0
    warn_count = 0

    merge_gate_lines: list[str] | None = None

    for path in paths:
        rel = path.relative_to(REPO_ROOT)
        lines, err = read_text_strict(path)
        if err:
            fail(f"[FAIL]{rel}:1:R1_ENCODING:{err}")
            fail_count += 1
            continue
        assert lines is not None

        if path.name == MERGE_GATE_NAME:
            merge_gate_lines = lines

        for line_no, rule in check_r1_encoding(path, lines):
            fail(f"[FAIL]{rel}:{line_no}:{rule}")
            fail_count += 1

        for line_no, rule in check_r2_merge_gate_placeholders(path, lines):
            fail(f"[FAIL]{rel}:{line_no}:{rule}")
            fail_count += 1

    if merge_gate_lines is not None:
        r3_fails, r3_warns = check_r3_merge_gate_commit_pr(merge_gate_lines)
        for line_no, rule in r3_fails:
            fail(f"[FAIL]{MERGE_GATE_NAME}:{line_no}:{rule}")
            fail_count += 1
        for w in r3_warns:
            warn(f"[WARN]::{w}")
            warn_count += 1
    elif any(p.name == MERGE_GATE_NAME for p in paths):
        pass
    else:
        info("[INFO]::R3_MERGE_GATE:skipped_merge_gate_not_in_scan_set")

    for w in check_r4_semantic_hints(paths):
        warn(f"[WARN]::{w}")
        warn_count += 1

    info(f"[INFO]::summary:FAIL={fail_count} WARN={warn_count}")
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
