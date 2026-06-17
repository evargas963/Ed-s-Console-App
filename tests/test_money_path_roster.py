"""AGENTS.md money-path roster file-exists guard (Phase 1b)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def money_path_modules_from_agents(text: str | None = None) -> list[str]:
    raw = text if text is not None else (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    m = re.search(
        r"## Money-path module roster.*?\n\n(.*?)(?=\n## |\Z)",
        raw,
        re.S,
    )
    assert m, "AGENTS.md missing Money-path module roster section"
    block = m.group(1)
    return re.findall(r"^- `([^`]+)`", block, re.M)


def test_money_path_roster_non_empty():
    modules = money_path_modules_from_agents()
    assert len(modules) == 11


def test_money_path_roster_files_exist():
    missing = [p for p in money_path_modules_from_agents() if not (ROOT / p).is_file()]
    assert missing == [], f"missing money-path modules: {missing}"
