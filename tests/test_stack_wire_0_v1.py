"""STACK-WIRE-0 — Phase 0 ingest map + diag housekeeping guards."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "governance" / "STACK_WIRING_INTEGRITY_MAP.md"
SERVER_PY = ROOT / "server.py"

_INGESTED_FINDS = frozenset(
    n for n in range(1, 20) if n not in (10, 16)
)


def _map_text() -> str:
    return MAP_PATH.read_text(encoding="utf-8", errors="replace")


def test_stack_wiring_integrity_map_exists_with_schema_and_anchors():
    assert MAP_PATH.is_file()
    text = _map_text()
    assert "surface | field | producer | transport | client_clock | stale_rule | test | open_items_id" in text
    for anchor in (
        "Decision Command rail",
        "Card cluster",
        "Quote header",
        "Diagnostic surfaces",
    ):
        assert anchor in text


def test_stack_wiring_integrity_map_ingests_all_17_findings():
    text = _map_text()
    found = set(int(m.group(1)) for m in re.finditer(r"FIND-SERVERPY-(\d+)", text))
    assert found == set(_INGESTED_FINDS)
    for n in _INGESTED_FINDS:
        assert text.count(f"FIND-SERVERPY-{n}") >= 1


def test_server_py_diag_markers_renamed_post_ed_db_hoist():
    import server

    src = inspect.getsource(server._fetch_state)
    assert '_diag_step("pre_db_counts", ticker)' in src
    assert '_diag_done("db_counts", ticker)' in src
    assert '_diag_step("pre_get_db", ticker)' not in src
    assert '_diag_done("get_db", ticker)' not in src
