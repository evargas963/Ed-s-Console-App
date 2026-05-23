"""Phase 1a governance consolidation guards."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

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


def test_phase_1b_stub_agent_self_governance_grep_phrases():
    """Enabled in Phase 1b."""
    pass


def test_phase_1c_stub_memory_archive_copies():
    """Enabled in Phase 1c."""
    pass
