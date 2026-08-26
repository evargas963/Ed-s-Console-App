"""OPTIONS FLOW — replay must reconstruct what was KNOWABLE, not what we later learned.

THE MEASURED FACT UNDER TEST. LEVELONE_OPTIONS is a DELTA service and OPTIONS_BOOK is a FULL
REPLACEMENT service. Measured on the committed capture: L1 content entries carried 55, 23, 17,
17, 17 and 11 fields with only ten names common to all, while every BOOK frame carried exactly
BOOK_TIME/BIDS/ASKS.

Both halves of that matter and both are tested:
  * Folding L1 is REQUIRED. Reading a later 17-field frame as a snapshot would report GAMMA and
    OPEN_INTEREST as absent when they were simply unchanged.
  * Folding BOOK is FORBIDDEN. Merging book frames would splice price levels from different
    instants into a book that never existed.

Nothing here derives greeks or infers dealer ownership, aggressor side, or intent.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from calibration.options_stream_coverage import close_epochs, explain_absence, open_epochs  # noqa: E402
from calibration.options_stream_ingest import OptionsFrameIngest  # noqa: E402
from calibration.options_stream_replay import (  # noqa: E402
    book_state_as_of,
    level_one_state_as_of,
)

CAPTURE = REPO / "reports" / "of_capability_probe" / "options_20260820T1354Z" / "frames"
SYM = "SPY   260820C00767000"


def _frames(service: str) -> list[dict]:
    out = []
    for p in sorted(CAPTURE.glob(f"{service}_*_decoded.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def _ingest_at(db: str, service: str, frames: list[dict], base_ms: int,
               spacing_ms: int = 1000) -> list[int]:
    """Ingest real frames on a synthetic clock, returning each frame's timestamp.

    The capture's own stamps are all within a second of each other, which is useless for
    exercising as-of ordering, so frames are spaced deliberately. Payloads are untouched.
    """
    stamps = []
    ing = OptionsFrameIngest(db, max_queue=1000, batch_max=1000)
    ing.start()
    for i, fr in enumerate(frames):
        g = json.loads(json.dumps(fr))
        ts = base_ms + i * spacing_ms
        g["timestamp"] = ts
        for entry in (g.get("content") or []):
            if isinstance(entry, dict):
                entry["key"] = SYM
        ing.offer(service, g, received_ts_ms=ts + 5)
        stamps.append(ts)
    out = ing.stop(timeout=60.0)
    assert out["written"] == len(frames), out
    return stamps


def test_level_one_deltas_are_folded_so_unchanged_fields_do_not_vanish(tmp_path):
    """THE CORE CORRECTNESS PROPERTY of a sparse stream.

    Frame 1 carries 55 fields; later frames carry as few as 11. After folding, the state at the
    LAST instant must still know the fields only the FIRST frame ever sent.
    """
    db = str(tmp_path / "cap.db")
    frames = _frames("LEVELONE_OPTIONS")
    assert len(frames) >= 4, "capture missing"
    base = int(time.time() * 1000) - 600_000
    stamps = _ingest_at(db, "LEVELONE_OPTIONS", frames, base)
    open_epochs(db, [SYM], service="LEVELONE_OPTIONS", reason="test", at_ms=base - 1000)

    first_only = set(frames[0]["content"][0]) - set(frames[-1]["content"][0])
    assert first_only, "fixture no longer demonstrates sparsity — the premise must be re-derived"

    st = level_one_state_as_of(db, SYM, stamps[-1])
    assert st["coverage"] == "SUBSCRIBED"
    assert st["frames_folded"] == len(frames)
    missing = [f for f in first_only if f not in st["fields"]]
    assert not missing, (
        f"folding lost fields that only the first frame carried: {sorted(missing)[:8]} — a "
        f"later sparse frame was treated as a full snapshot")

    # And the age is reported honestly: a field the final frame did not carry must be dated to
    # the last frame that DID carry it — which is some earlier frame, not necessarily the first
    # (these fields can also appear in intermediate frames), and never the final one.
    for f in sorted(first_only):
        rec = st["fields"][f]
        assert rec["observed_ts_ms"] < stamps[-1], (
            f"{f} is absent from the final frame yet dated to it — a held value was silently "
            f"re-stamped as fresh")
        assert rec["observed_ts_ms"] in stamps, f"{f} dated to no real frame"
        assert rec["age_ms"] == stamps[-1] - rec["observed_ts_ms"], (
            f"{f} misreports its age; a delta stream is only honest if staleness is visible")
        assert rec["age_ms"] > 0


def test_replay_has_no_lookahead(tmp_path):
    """State at T must never contain a frame that arrived after T."""
    db = str(tmp_path / "cap.db")
    frames = _frames("LEVELONE_OPTIONS")
    base = int(time.time() * 1000) - 600_000
    stamps = _ingest_at(db, "LEVELONE_OPTIONS", frames, base)
    open_epochs(db, [SYM], service="LEVELONE_OPTIONS", reason="test", at_ms=base - 1000)

    early = level_one_state_as_of(db, SYM, stamps[1])
    late = level_one_state_as_of(db, SYM, stamps[-1])

    assert early["frames_folded"] == 2, "as-of state folded frames it could not have seen"
    assert late["frames_folded"] == len(frames)
    for rec in early["fields"].values():
        assert rec["observed_ts_ms"] <= stamps[1], "a future observation leaked into the past"
    # Reconstructing the same instant twice must be identical — replay is a pure function of
    # retained history, not of when the question is asked.
    again = level_one_state_as_of(db, SYM, stamps[1])
    assert again["fields"] == early["fields"]


def test_book_is_replaced_not_folded(tmp_path):
    """OPTIONS_BOOK frames must never be merged into a book that never existed."""
    db = str(tmp_path / "cap.db")
    frames = _frames("OPTIONS_BOOK")
    assert frames, "capture missing"
    base = int(time.time() * 1000) - 600_000
    stamps = _ingest_at(db, "OPTIONS_BOOK", frames, base)
    open_epochs(db, [SYM], service="OPTIONS_BOOK", reason="test", at_ms=base - 1000)

    st = book_state_as_of(db, SYM, stamps[-1])
    assert st["coverage"] == "SUBSCRIBED"
    assert st["observed_ts_ms"] == stamps[-1], "book must take the LATEST frame, not a merge"
    assert set(st["book"]) - {"key"} <= {"BOOK_TIME", "BIDS", "ASKS"}, (
        "book state carries fields no single frame had — frames were merged")

    mid = book_state_as_of(db, SYM, stamps[1])
    assert mid["observed_ts_ms"] == stamps[1], "as-of book picked the wrong frame"


def test_absence_says_WHY_not_merely_that_it_is_empty(tmp_path):
    """not-subscribed and subscribed-but-quiet must never look the same."""
    db = str(tmp_path / "cap.db")
    frames = _frames("LEVELONE_OPTIONS")
    base = int(time.time() * 1000) - 600_000
    stamps = _ingest_at(db, "LEVELONE_OPTIONS", frames, base)
    open_epochs(db, [SYM], service="LEVELONE_OPTIONS", reason="test", at_ms=base - 1000)
    close_epochs(db, [SYM], service="LEVELONE_OPTIONS", reason="test_end",
                 at_ms=stamps[-1] + 1000)

    before = level_one_state_as_of(db, SYM, base - 60_000)
    assert before["coverage"] == "NOT_SUBSCRIBED"
    assert not before["fields"], "state was reported outside the coverage epoch"

    after = explain_absence(db, SYM, stamps[-1] + 500_000)
    assert after["verdict"] == "NOT_SUBSCRIBED", after

    quiet = explain_absence(db, SYM, stamps[-1] + 500, window_ms=100)
    assert quiet["verdict"] in ("SUBSCRIBED_NO_UPDATE", "SUBSCRIBED_MAYBE_DROPPED"), quiet
    assert quiet["verdict"] != "NOT_SUBSCRIBED", (
        "a covered-but-quiet instant was reported as uncovered — that would turn our own "
        "coverage into a claim about the market")

    seen = explain_absence(db, SYM, stamps[-1], window_ms=5000)
    assert seen["verdict"] == "OBSERVED" and seen["frames"] >= 1


def test_folding_does_not_cross_a_subscription_gap(tmp_path):
    """A value must not be carried over a window in which we were not watching.

    Carrying a pre-gap GAMMA across an outage would assert we knew it had not changed, when in
    fact we could not have seen a change.
    """
    db = str(tmp_path / "cap.db")
    frames = _frames("LEVELONE_OPTIONS")
    base = int(time.time() * 1000) - 900_000
    stamps = _ingest_at(db, "LEVELONE_OPTIONS", frames, base)

    # Epoch A covers the early frames and then ENDS; epoch B starts later.
    open_epochs(db, [SYM], service="LEVELONE_OPTIONS", reason="A", at_ms=base - 1000)
    close_epochs(db, [SYM], service="LEVELONE_OPTIONS", reason="gap", at_ms=stamps[1] + 100)
    open_epochs(db, [SYM], service="LEVELONE_OPTIONS", reason="B", at_ms=stamps[-1] - 100)

    st = level_one_state_as_of(db, SYM, stamps[-1])
    assert st["coverage"] == "SUBSCRIBED"
    for rec in st["fields"].values():
        assert rec["observed_ts_ms"] >= stamps[-1] - 100, (
            "a value from before the subscription gap was folded forward — replay claimed "
            "knowledge it could not have had")
