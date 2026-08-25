# institutional-synthetic-ok: crafted hook transcripts prove the RC-87 guard blocks and permits correctly.
"""RC-87 proof-only guard — audit round 2 (2026-08-25) hardenings.

WHAT WAS MEASURED (executed PoCs, guard-machinery audit): a hard verdict PASSED on the mere
presence of a backticked command STRING that never ran; one hedged aside anywhere in the
message disabled the whole guard; only the final assistant record was judged, so a verdict
hid behind a bland 'Done.' tail; the memory lexicon missed ordinary paraphrases; the
verdict regex was case-inconsistent. Every test here drives the REAL guard (function or
subprocess) against crafted transcripts mirroring the live record shape.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tools.proof_only_guard as G  # noqa: E402


def _rec(role: str, *blocks: dict) -> str:
    return json.dumps({"type": role, "message": {"role": role, "content": list(blocks)}})


def _text(t: str) -> dict:
    return {"type": "text", "text": t}


def _bash(cmd: str, tid: str = "tu_1") -> dict:
    return {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}


def _result(tid: str = "tu_1", is_error: bool = False) -> dict:
    return {"type": "tool_result", "tool_use_id": tid, "is_error": is_error,
            "content": [{"type": "text", "text": "output"}]}


def _write_transcript(tmp_path: Path, *lines: str) -> str:
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def _run_main(transcript_path: str | None, stop_hook_active: bool = False):
    payload: dict = {}
    if transcript_path is not None:
        payload["transcript_path"] = transcript_path
    if stop_hook_active:
        payload["stop_hook_active"] = True
    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "proof_only_guard.py")],
        input=json.dumps(payload), capture_output=True, text=True)
    return proc.returncode, proc.stderr or ""


VERDICT_WITH_FAKE_CMD = (
    "CONFIRMED: the abstain gate holds fleet-wide. I verified with "
    "`python tools/terrain_backtest_report_v1.py --full`.")


def test_fake_backticked_command_is_not_proof(tmp_path):
    """The founding gap: proof-shaped prose passed. A cited command must have RUN."""
    tp = _write_transcript(
        tmp_path,
        _rec("user", _text("did the gate hold?")),
        _rec("assistant", _text(VERDICT_WITH_FAKE_CMD)))
    rc, err = _run_main(tp)
    assert rc == 2 and "no same-turn proof" in err, err


def test_the_same_citation_with_the_command_run_successfully_passes(tmp_path):
    tp = _write_transcript(
        tmp_path,
        _rec("user", _text("did the gate hold?")),
        _rec("assistant",
             _bash("python tools/terrain_backtest_report_v1.py --full"),
             _text(VERDICT_WITH_FAKE_CMD)),
        _rec("user", _result("tu_1", is_error=False)))
    rc, err = _run_main(tp)
    assert rc == 0, err


def test_a_command_that_FAILED_is_not_proof(tmp_path):
    """RESULT, NOT ISSUANCE (operator, 2026-08-25): issuing `pytest` that then errored
    cannot ground a verdict — the tool_result carries is_error=true."""
    tp = _write_transcript(
        tmp_path,
        _rec("user", _text("did the gate hold?")),
        _rec("assistant",
             _bash("python tools/terrain_backtest_report_v1.py --full"),
             _text(VERDICT_WITH_FAKE_CMD)),
        _rec("user", _result("tu_1", is_error=True)))
    rc, err = _run_main(tp)
    assert rc == 2 and "no same-turn proof" in err, err


def test_a_command_with_no_result_record_is_not_proof(tmp_path):
    """An interrupted call (tool_use with no tool_result) proves nothing ran to completion."""
    tp = _write_transcript(
        tmp_path,
        _rec("user", _text("did the gate hold?")),
        _rec("assistant",
             _bash("python tools/terrain_backtest_report_v1.py --full"),
             _text(VERDICT_WITH_FAKE_CMD)))
    rc, err = _run_main(tp)
    assert rc == 2, err


def test_verdict_judged_on_whole_turn_not_last_record(tmp_path):
    """A bland tail record must not hide the verdict from the guard."""
    tp = _write_transcript(
        tmp_path,
        _rec("user", _text("status?")),
        _rec("assistant", _text("CONFIRMED: the abstain gate holds fleet-wide.")),
        _rec("assistant", _text("Done. The files are updated.")))
    rc, err = _run_main(tp)
    assert rc == 2 and "CONFIRMED" in err, err


def test_backticked_path_alone_is_not_proof(tmp_path):
    tp = _write_transcript(
        tmp_path,
        _rec("user", _text("status?")),
        _rec("assistant", _text(
            "CONFIRMED. See `tools/terrain_backtest_report_v1.py` for the logic.")))
    rc, err = _run_main(tp)
    assert rc == 2, err


def test_unrelated_hedge_does_not_disable_guard():
    """One hedged aside used to switch off BOTH the memory rule and the verdict rule.
    The correction exemption is neighbourhood-scoped (±200 chars), so the hedge here sits
    beyond that window — a distant aside must not exempt the citation."""
    filler = ("The collector loop, the terrain cache, the chart painters and the decision "
              "gate were all reviewed in this pass; the serving path stayed abstain "
              "throughout and the fleet metas were untouched by the change. " * 2)
    text = ("CONFIRMED: the abstain gate holds fleet-wide. Per my memory, the encode "
            "path was already fixed too. " + filler +
            "(Unrelated: the old charm claim remains unproven.)")
    bad = G.violations(text, executed=[])
    assert any("memory cited" in b for b in bad), bad
    assert any("CONFIRMED" in b for b in bad), bad


def test_adjacent_correction_still_exempts_the_memory_citation():
    text = "Per my memory GEX-R1 was retired — but that is unproven; I retract it."
    assert not any("memory cited" in b for b in G.violations(text, executed=[]))


def test_correction_class_verdict_still_rides_a_correction():
    text = "Correction: the earlier claim is DISPROVEN — retracting it now."
    assert G.violations(text, executed=[]) == []


def test_memory_paraphrases_caught():
    for phrasing in (
            "MEMORY.md records GEX-R1 as retired-by-measurement",
            "The earlier audit showed the signal is dead",
            "As established in RC-87, this holds",
            "You'll recall the flip is quasi-static",
            "that lane is known-dead from the July study",
            "My memory file notes the collector was fixed"):
        assert any("memory cited" in b for b in G.violations(phrasing, executed=[])), phrasing
    assert not any("memory cited" in b for b in G.violations(
        "I will now establish this by measurement", executed=[]))


def test_phrase_verdicts_case_insensitive_single_words_stay_caps():
    assert G.violations("Does not replicate on clean inputs.", executed=[])
    # ACCEPT A2 pinned: a lowercase single-word verdict is out of scope by design.
    assert G.violations("the hypothesis is confirmed and the old signal retired",
                        executed=[]) == []


def test_past_tense_rc_claim_needs_row():
    bad = G.violations("opened RC-99999 and fixed it same turn", executed=[])
    assert any("RC-99999" in b for b in bad), bad


def test_missing_transcript_path_fails_closed(tmp_path):
    rc, err = _run_main(None)
    assert rc == 2 and "transcript_path" in err, err
    rc, _ = _run_main(None, stop_hook_active=True)
    assert rc == 0


def test_turn_slice_reads_only_this_turn(tmp_path):
    """Commands from PRIOR turns must not satisfy this turn's citation."""
    tp = _write_transcript(
        tmp_path,
        _rec("user", _text("first ask")),
        _rec("assistant", _bash("python tools/terrain_backtest_report_v1.py --full"),
             _text("ran it.")),
        _rec("user", _text("second ask — did the gate hold?")),
        _rec("assistant", _text(VERDICT_WITH_FAKE_CMD)))
    text, executed = G.turn_slice(tp)
    assert executed == []
    assert "CONFIRMED" in (text or "")
