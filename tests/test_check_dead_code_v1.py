"""tools/check_dead_code.py on the repository's own code and history: dead code a change creates
is refused, in the file it touched or in one that lost its last user; vulture's false positives
are cleared by the check's rules, never by a list of names."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_dead_code as cdc  # noqa: E402

TOKEN_TIMING = [
    ("schwab_client.py", "seconds_to_expiry", "variable"), ("schwab_client.py", "is_expired", "variable"),
    ("schwab_client.py", "is_expiring_soon", "variable"), ("schwab_client.py", "seconds_to_expiry", "attribute"),
    ("schwab_client.py", "is_expired", "attribute"), ("schwab_client.py", "is_expiring_soon", "attribute")]


def test_the_change_that_deleted_the_last_reader_of_the_token_timing_is_refused():
    """941eef43 deleted server.py's startup log of the token timing, the only reader of three
    TokenInspectionResult fields; schwab_client.py, which still filled them, was not touched."""
    found = [f.key for f in cdc.new_findings(ROOT, "941eef43^", "941eef43")]
    assert [k for k in found if k[0] == "schwab_client.py"] == TOKEN_TIMING


def test_one_bar_history_left_no_dead_code_and_is_allowed():
    """d965484b (#459) deleted the console's bar writer and everything only it used."""
    assert cdc.new_findings(ROOT, "93fca283", "d965484b") == []


def test_on_main_at_26ddc457_the_rules_keep_only_code_nothing_uses():
    """vulture finds 73 names at 26ddc457. The rules clear the 57 a framework, a library or a
    serializer uses (FastAPI routes, pytest fixtures and hooks, BaseHTTPRequestHandler.do_GET,
    sqlite3's row_factory, schwab-py's label_message, the dataclass fields asdict writes, callback
    parameters) and keep these 16. write_flow_e2e_fixture is run by hand (`python -c`); no rule
    sees that."""
    found = [f.key for f in cdc.findings_at(ROOT, "26ddc457")]
    assert found == TOKEN_TIMING + [
        ("stream_spine.py", "rows_written", "attribute"), ("stream_spine.py", "rows_written", "attribute"),
        ("tests/test_eol_style_invariant_v1.py", "TURN_AUDIT_OWNS", "variable"),
        ("tests/test_eol_style_invariant_v1.py", "rc2", "variable"),
        ("tests/test_live_ui_daemon_to_browser_v1.py", "spy", "variable"),
        ("tests/test_live_ui_daemon_to_browser_v1.py", "aapl", "variable"),
        ("tests/test_options_order_flow_production_v1.py", "write_flow_e2e_fixture", "function"),
        ("tests/test_options_order_flow_semantics_v1.py", "_push_option_l1", "function"),
        ("tests/test_protected_paths_v1.py", "TURN_AUDIT_OWNS", "variable"),
        ("tools/operator_law_guard.py", "ledger", "variable")]
