"""arch_competition.audit fail-closed visibility (Finding KK)."""

from __future__ import annotations

import json
from pathlib import Path

from arch_competition.audit import build_audit_record, load_recent_audit_records


def test_load_recent_audit_records_logs_corrupt_line(tmp_path: Path, caplog):
    import logging

    good = build_audit_record(
        action="manual_promote_attempt",
        outcome="pending",
        operator_id="op",
        ticker="SPY",
        ml_horizon_suffix="1c",
        prior_active_architecture="parallel",
        target_architecture="cascade",
        new_active_architecture=None,
        evaluation_manifest_path="/e",
        promotion_decision_path="/p",
        checkpoint_id="ck",
    )
    log_path = tmp_path / "arch_competition" / "governance_audit.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        json.dumps(good) + "\n" + "{not valid json}\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        rows = load_recent_audit_records(tmp_path, limit=10)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "SPY"
    assert any("corrupted" in r.message.lower() for r in caplog.records)
