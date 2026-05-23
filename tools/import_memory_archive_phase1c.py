"""Phase 1c: import Claude memory files into repo archive with trigger rewrites."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_SRC = Path.home() / ".claude/projects/C--Users-evarg-Documents-Trading-EdWebConsole/memory"
ARCHIVE = ROOT / "governance/archive/2026-Q2/memory_archive"

REWRITES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"rules #1-#27", re.I), "AGENT_SELF_GOVERNANCE alternation, sign-off, and verification topics"),
    (re.compile(r"\brule #25\b", re.I), "money-path module roster (AGENTS.md)"),
    (re.compile(r"\brule #26\b", re.I), "N-site parity regression tests"),
    (re.compile(r"\brule #22\b", re.I), "independent full-Read verification"),
    (re.compile(r"\brule #23\b", re.I), "retract sign-off on re-verification gaps"),
    (re.compile(r"\brule #18\b", re.I), "Slice tag in commit body"),
    (re.compile(r"\brule #17\b", re.I), "adjacent findings in producer/consumer cone"),
    (re.compile(r"\brule #20\b", re.I), "cross-module dict wire contracts"),
    (re.compile(r"#23\b"), "retract sign-off on re-verification gaps"),
    (re.compile(r"#22\b"), "independent full-Read verification"),
]


def rewrite_triggers(text: str) -> str:
    out = text
    for pat, repl in REWRITES:
        out = pat.sub(repl, out)
    return out


def main() -> None:
    if not MEMORY_SRC.is_dir():
        raise SystemExit(f"memory source missing: {MEMORY_SRC}")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    count = 0
    for src in sorted(MEMORY_SRC.glob("*.md")):
        if src.name == "MEMORY.md":
            continue
        dest = ARCHIVE / src.name
        body = src.read_text(encoding="utf-8")
        dest.write_text(rewrite_triggers(body), encoding="utf-8")
        count += 1
    print(f"archived {count} files to {ARCHIVE}")


if __name__ == "__main__":
    main()
