"""Money-path roster file-exists guard (PROTECTS_RUNTIME_TRUTH).

The canonical money-path set is tools/check_market_correctness.MONEY_PATH_FILES —
the files the money-path static gate scans. This test asserts every module in that
roster is a real file ("the money-path modules exist"). It reads the roster from
that single source of truth instead of parsing an AGENTS.md section (removed when
AGENTS.md became the one-page charter under the ED CONSOLE SLIMMING directive).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_market_correctness import MONEY_PATH_FILES  # noqa: E402


def test_money_path_roster_non_empty() -> None:
    assert len(MONEY_PATH_FILES) >= 7


def test_money_path_roster_files_exist() -> None:
    missing = [p for p in MONEY_PATH_FILES if not (ROOT / p).is_file()]
    assert missing == [], f"missing money-path modules: {missing}"
