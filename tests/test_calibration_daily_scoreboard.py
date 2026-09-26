"""Daily signal scoreboard: per-horizon fusion prediction vs attached outcome labels."""

from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo



ET = ZoneInfo("America/New_York")


# ── SCOREBOARD_TARGET_TRUTH_V1 (v4) — abstention, baselines, warnings ─────────


def test_invalid_threshold_classification_is_flat_and_disclosed():
    """Historical behavior preserved and DISCLOSED: classify_direction_pts turns a
    missing/non-positive threshold into 'flat'. The forward fail-closed change to
    the truth writer (no-label instead of flat) belongs to the target-redesign
    mission; until then the risk flag is the governed disclosure."""
    from math_probabilities import classify_direction_pts

    assert classify_direction_pts(5.0, None) == "flat"
    assert classify_direction_pts(5.0, 0.0) == "flat"
    assert classify_direction_pts(5.0, -1.0) == "flat"
    assert classify_direction_pts(5.0, 1.0) == "up"


# ── DEFECT-1: operator semantic safety (independent requirements) ─────────────
# These tests assert the REQUIRED CONCEPTS as independent strings — they do NOT
# import the production display-contract constants and echo them back.



# ── V2 (Cursor findings): eligible grid, governed unit, low-coverage safety ───


def test_lane_a_mutation_manifest_purity():
    """Package truth: the Lane-A manifest contains ONLY lane-A mutations with the
    required evidence fields; Lane-B mutations live in the quarantined artifact
    marked excluded from the Lane-A package."""
    root = Path(__file__).resolve().parent.parent
    m = json.loads((root / "reports/scoreboard_forensic/mutation_evidence_manifest.json").read_text(encoding="utf-8"))
    assert m["lane"] == "A"
    assert all(r["lane"] == "A" for r in m["mutations"])
    assert not any(r["id"] in ("M2", "M3") for r in m["mutations"])
    for r in m["mutations"]:
        for field in ("preimage_sha256", "unified_diff", "iteration_history"):
            assert field in r, f"{r['id']} missing {field}"
        # schema v5: per-run evidence blocks with matched canonical signatures.
        for run_key in ("run1", "run2"):
            run = r[run_key]
            for field in ("signature_digest", "structured_failures",
                          "restoration_hashes_match_preimages", "raw_evidence_files"):
                assert field in run, f"{r['id']}.{run_key} missing {field}"
        assert r["signature_match"] is True, f"{r['id']} signatures differ between runs"
    assert m["summary"]["statement"].startswith("LANE_A_MUTATIONS_DETECTED = ")
    assert m["summary"]["signature_matches"] == "27/27"
    for run_key in ("run1", "run2"):
        assert "lane-A composition" in m["restoration"][run_key]["suite_footprint"]
    # The Lane-B artifact is EXCLUDED from the Lane-A patch; when present in a
    # combined worktree it must be explicitly quarantined.
    lane_b = root / "reports/scoreboard_forensic/mutation_evidence_lane_b_uncommitted.json"
    if lane_b.is_file():
        b = json.loads(lane_b.read_text(encoding="utf-8"))
        assert b["lane"] == "B" and "QUARANTINED" in b["composition"]
        assert {r["id"] for r in b["mutations"]} == {"M2", "M3"}


def test_forensic_packet_lane_purity():
    """Package truth: the forensic packet machine-readably excludes Lane-B design
    from the Lane-A patch and never claims identity-first implementation for Lane A."""
    root = Path(__file__).resolve().parent.parent
    d = json.loads((root / "reports/scoreboard_forensic/july13_2026_target_truth_forensic.json").read_text(encoding="utf-8"))
    tags = d["lane_decomposition"]["section_tags"]
    assert tags["join_identity_forensic"]["included_in_lane_a_patch"] is False
    assert tags["join_identity_forensic"]["not_commit_evidence_for_lane_a"] is True
    fw = d["join_identity_forensic"]["verdicts"]["FORWARD_IDENTITY_FIRST_DESIGN"]
    assert fw.startswith("LANE_B_UNCOMMITTED_DESIGN")
    assert "LOCALLY_IMPLEMENTED" not in fw
    dumped = json.dumps(d)
    assert "correction_landed" not in dumped


def test_board_row_lane_language_purity():
    """Package truth: the board row states the Lane-A patch ships HEAD backfill
    behavior and carries no identity-first-implemented claim for Lane A."""
    board = Path(__file__).resolve().parent.parent.joinpath("OPEN_ITEMS.md").read_text(encoding="utf-8")
    row = next(l for l in board.splitlines() if "SCOREBOARD-TARGET-TRUTH " in l)
    assert "HEAD backfill behavior only" in row
    assert "FORWARD_IDENTITY_FIRST_DESIGN = LOCALLY_IMPLEMENTED" not in row
    assert "LOCALLY_PROVEN_PENDING_PR" not in row
    assert "NOT in the Lane-A patch" in row
    assert "LANE B COMMIT_READY = NO" in row
