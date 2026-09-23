"""RC-REHAB-3 — decision_record.py's JSON blob columns (release_json, market_inputs_json,
risk_state_json, model_outputs_json, fusion_json, overrides_json, staleness_json,
quarantine_json, reconstruction_json) are gzip-compressed via json_blob_codec. Proves the
compression is real, that get_production_decision_by_id reads both compressed and
pre-migration plain-JSON rows correctly, and that validation_summary (a mixed str/JSON
column, deliberately NOT compressed) is unaffected."""
from __future__ import annotations

import json
import sqlite3

from decision_record import (
    build_reconstruction_payload,
    ensure_production_decision_schema,
    get_production_decision_by_id,
    persist_production_decision,
)
from json_blob_codec import decode_json_blob, is_compressed_blob


def _release():
    return {"release_id": "rel-1", "git_sha": "a" * 40, "build_generation": 1}


def _ms_dict():
    return {
        "decision_id": "d-compress-1",
        "decision_generation_id": 1,
        "decision_timestamp_utc": 1000.0,
        "ticker": "SPY",
        "call_signal": "wait",
        "call_conviction": "low",
        "mhap_rows": [{"horizon": "1c", "signal": "wait"}],
        "fusion_by_horizon": {"1c": {"p_up": 0.33}},
        "validation_summary": "ok",
        "call": {"trade_valid": True, "risk_valid": True, "validation_summary": "ok"},
    }


def test_json_blob_columns_are_actually_compressed_on_disk(tmp_path):
    db_path = tmp_path / "dec.db"
    ms = _ms_dict()
    decision_id = persist_production_decision(ms, route="test", release=_release(), db_path=db_path)
    assert decision_id == "d-compress-1"

    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute(
            "SELECT release_json, market_inputs_json, risk_state_json, model_outputs_json, "
            "fusion_json, overrides_json, staleness_json, quarantine_json, reconstruction_json, "
            "validation_summary FROM production_decision_records WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
    finally:
        con.close()
    *blob_cols, validation_summary = row
    for value in blob_cols:
        assert is_compressed_blob(value), f"expected gzip bytes, got {type(value)}"
    # validation_summary is a plain string here (str branch), deliberately untouched.
    assert validation_summary == "ok"
    assert not is_compressed_blob(validation_summary)


def test_get_production_decision_by_id_reads_the_compressed_row_correctly(tmp_path):
    db_path = tmp_path / "dec.db"
    ms = _ms_dict()
    decision_id = persist_production_decision(ms, route="test", release=_release(), db_path=db_path)
    payload = get_production_decision_by_id(decision_id, db_path)
    assert payload is not None
    assert payload["decision_id"] == "d-compress-1"
    assert payload["ticker"] == "SPY"
    assert payload["model_outputs"] == [{"horizon": "1c", "signal": "wait"}]


def test_a_pre_migration_plain_json_row_still_reads_back_correctly(tmp_path):
    """A row written before this codec existed stored plain JSON TEXT in
    reconstruction_json -- get_production_decision_by_id must keep reading it."""
    db_path = tmp_path / "dec.db"
    con = sqlite3.connect(str(db_path))
    try:
        ensure_production_decision_schema(con)
        reconstruction = build_reconstruction_payload(_ms_dict(), route="legacy", release=_release())
        con.execute(
            "INSERT INTO production_decision_records "
            "(decision_id, decision_ts_utc, ticker, route, release_id, release_json, "
            " reconstruction_json, created_at_utc) VALUES (?,?,?,?,?,?,?,?)",
            ("d-legacy-1", 1000.0, "SPY", "legacy", "rel-1",
             json.dumps(_release()), json.dumps(reconstruction), 1000.0),
        )
        con.commit()
    finally:
        con.close()

    payload = get_production_decision_by_id("d-legacy-1", db_path)
    assert payload is not None
    assert payload == decode_json_blob(json.dumps(reconstruction))
