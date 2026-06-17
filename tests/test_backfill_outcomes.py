"""backfill_outcomes CLI and import fail-closed."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from calibration.backfill_outcomes import main


def test_main_prints_json_stats(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "missing.db"
    with patch("calibration.backfill_outcomes.backfill", return_value={"candidates": 0, "updated": 0}):
        with patch(
            "calibration.backfill_outcomes.require_canonical_db_target",
        ), patch(
            "sys.argv",
            ["backfill_outcomes", "--db", str(db_path), "--allow-noncanonical-db"],
        ):
            # Touch file so main passes existence check
            db_path.write_text("", encoding="utf-8")
            rc = main()
    assert rc == 0
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed["candidates"] == 0
    assert parsed["updated"] == 0
