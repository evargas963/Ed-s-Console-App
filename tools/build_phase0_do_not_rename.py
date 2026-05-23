"""Phase 0: governance path anchor list for consolidation."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    anchors = {
        "CLAUDE.md",
        "tests/test_mega4_traceable_audit.py",
        "governance/mega4_traceable_inventory.py",
        "server.py",
        "governance/artifacts/schwab_v4_register_build_meta.json",
        "governance/artifacts/schwab_v4_scoreboard.json",
        "docs/governance/AGENT_SELF_GOVERNANCE.md",
        "docs/plans/GOVERNANCE_CONSOLIDATION_EXECUTION_PLAN.md",
        "OPEN_ITEMS.md",
        "tools/check_schwab_csv_first.py",
    }
    inv_text = (ROOT / "governance/mega4_traceable_inventory.py").read_text(encoding="utf-8")
    m = re.search(r"MEGA4_FILES = frozenset\(\s*\{([^}]+)\}", inv_text, re.S)
    if m:
        anchors.update(re.findall(r'"([^"]+)"', m.group(1)))

    patterns = [
        re.compile(r'["\'](governance/[^"\']+)["\']'),
        re.compile(r'["\'](docs/governance/[^"\']+)["\']'),
        re.compile(r'["\'](docs/plans/[^"\']+)["\']'),
        re.compile(r'["\'](CLAUDE\.md)["\']'),
        re.compile(r'["\'](OPEN_ITEMS\.md)["\']'),
    ]
    hardcoded: set[str] = set()
    scan_roots = [ROOT / "tests", ROOT / "tools", ROOT / "server.py", ROOT / ".github"]
    for sr in scan_roots:
        paths = [sr] if sr.is_file() else sr.rglob("*")
        for p in paths:
            if p.is_file() and p.suffix in {".py", ".yml", ".yaml", ".md"}:
                try:
                    body = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for pat in patterns:
                    hardcoded.update(pat.findall(body))

    out = {
        "anchor_set": sorted(anchors),
        "hardcoded_governance_paths_in_tests_tools_ci": sorted(hardcoded),
        "do_not_rename_without_ci_update": sorted(set(anchors) | hardcoded),
    }
    dest = ROOT / "governance/consolidation/phase0/do_not_rename_paths.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {dest} ({len(out['do_not_rename_without_ci_update'])} paths)")


if __name__ == "__main__":
    main()
