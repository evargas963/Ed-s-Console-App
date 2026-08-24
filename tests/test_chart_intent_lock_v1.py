# institutional-synthetic-ok: these tests INJECT Chart-intent / next-RTH violations to prove
# the RC-163 lock BLOCKS — that is their entire purpose.
"""RC-163: Chart-intent soft-out + next-RTH Monday-proof lies — fire and quiet controls."""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.chart_intent_lock as L  # noqa: E402
import tools.check_institutional_correctness as C  # noqa: E402
import tools.pretooluse_guard as PG  # noqa: E402

ET = ZoneInfo("America/New_York")
# Thursday evening after RTH close → next RTH is Friday (not Monday).
_THU_AFTER_CLOSE = datetime(2026, 7, 30, 22, 0, tzinfo=ET)
# Monday morning before open → Monday proof is honest.
_MON_BEFORE_OPEN = datetime(2026, 8, 3, 8, 0, tzinfo=ET)


def test_chart_intent_and_next_rth_is_enforced():
    assert ("chart_intent_and_next_rth", True) in [(n, e) for n, _f, e in C.CHECKS]


def test_collect_done_with_chart_oos_blocks_and_partial_allows():
    bad = (
        "Collect slice ACCEPT / CLOSED / Done. "
        "OUT-OF-SCOPE: Chart render / yellow bars / GEX bars — not this turn."
    )
    assert L.chart_intent_soft_out_violation(bad), (
        "Collect Done + Chart OUT-OF-SCOPE was not flagged — lock inert"
    )

    good = (
        "STATUS PARTIAL. Collect bank landed; open Chart residual CHART_CONSUMER / P0 "
        "until yellow and GEX bars paint from the accrual consumer."
    )
    assert L.chart_intent_soft_out_violation(good) is None, (
        "PARTIAL + CHART_CONSUMER residual was wrongly blocked"
    )

    waived = (
        "# chart-intent-ok: operator waiver — Collect-only audit, Chart tracked in RC-162. "
        "Collect slice ACCEPT. OUT-OF-SCOPE: Chart render this turn."
    )
    assert L.chart_intent_soft_out_violation(waived) is None, (
        "chart-intent-ok waiver was wrongly blocked"
    )


def test_banking_as_chart_done_blocks_without_consumer():
    bad = (
        "Chart mandate COMPLETE: accrual banking Done / CLOSED — yellow and gamma "
        "accumulate-and-render satisfied by the bank alone."
    )
    assert L.chart_intent_soft_out_violation(bad), (
        "banking-as-Chart-Done without consumer was not flagged"
    )

    good = (
        "Chart mandate path proven: latest_accrual_rows consumer feeds /api/terrain/strikes; "
        "accrual banking COMPLETE and Chart consumer proven."
    )
    assert L.chart_intent_soft_out_violation(good) is None


def test_monday_proof_blocks_when_next_rth_is_friday():
    bad = "Forward residual: Monday live proof of option_chain_accrual on the next session."
    reason = L.next_rth_monday_lie_violation(bad, as_of=_THU_AFTER_CLOSE)
    assert reason, "Monday proof when next RTH is Friday was not flagged"
    assert "2026-07-31" in reason and "Friday" in reason

    # Historical gate filename alone is not a Monday-proof phrase.
    hist = "See reports/gex_r1_monday_collector_gate.md for the 2026-07-20 ops note."
    assert L.next_rth_monday_lie_violation(hist, as_of=_THU_AFTER_CLOSE) is None

    ok_escape = (
        "# next-rth-ok: 2026-07-31 Friday computed via is_trading_day_et. "
        "Legacy note mentioned Monday proof only as the old label."
    )
    assert L.next_rth_monday_lie_violation(ok_escape, as_of=_THU_AFTER_CLOSE) is None

    honest_monday = "Monday proof of accrual when next RTH is Monday."
    assert L.next_rth_monday_lie_violation(honest_monday, as_of=_MON_BEFORE_OPEN) is None

    friday_ok = (
        "NEXT_RTH_PROOF on 2026-07-31 Friday (verified is_trading_day_et; not Monday)."
    )
    assert L.next_rth_monday_lie_violation(friday_ok, as_of=_THU_AFTER_CLOSE) is None


def test_next_rth_et_date_friday_after_thursday_close():
    d = L.next_rth_et_date(_THU_AFTER_CLOSE)
    assert d.isoformat() == "2026-07-31"
    assert d.strftime("%A") == "Friday"


def test_check_chart_intent_and_next_rth_screams_on_staged_added(tmp_path, monkeypatch):
    """Full check path: staged ADDED residual prose must produce >=1 violation."""
    reports = tmp_path / "reports"
    reports.mkdir()
    target = reports / "zz_chart_intent_bad.md"
    target.write_text(
        "Collect slice Done / ACCEPT.\n"
        "OUT-OF-SCOPE: Chart paint / yellow bars.\n"
        "Monday proof tomorrow.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(C, "REPO", tmp_path)

    # SIMPLICITY REHAB 2026-08-24 (T2-5): reports/** is UNGATED now; the gated surface
    # this control drives is an explicit handoff file, where the claims actually land.
    def fake_git(args: list[str]) -> list[str] | None:
        if args[:3] == ["diff", "--cached", "--name-only"]:
            return ["zz_chart_intent_handoff.md"]
        if args[:3] == ["diff", "--cached", "-U0"]:
            return [
                "+++ b/zz_chart_intent_handoff.md",
                "+Collect slice Done / ACCEPT.",
                "+OUT-OF-SCOPE: Chart paint / yellow bars.",
                "+Monday proof tomorrow.",
            ]
        return []

    monkeypatch.setattr(C, "_git_output_lines", fake_git)
    # Pin calendar so Monday-proof fires (Thursday after close → Friday next RTH).
    monkeypatch.setattr(
        L,
        "next_rth_et_date",
        lambda as_of=None: __import__("datetime").date(2026, 7, 31),
    )
    bad = C.check_chart_intent_and_next_rth()
    assert bad, f"staged Chart-intent / Monday-proof residual was not blocked: {bad}"
    msgs = " ".join(v.msg for v in bad)
    assert "Chart-intent" in msgs or "Banking" in msgs or "Monday" in msgs or "next RTH" in msgs


def test_pretooluse_blocks_chart_intent_and_monday_proof_write(monkeypatch):
    monkeypatch.setenv("ED_PRETOOLUSE_GUARD", "on")

    def run(content: str) -> tuple[int, str]:
        # T2-5: reports/** is ungated; a prompt-named file at a gated location drives it.
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(ROOT / "zz_chart_intent_prompt.md"),
                "content": content,
            },
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        err = io.StringIO()
        monkeypatch.setattr(sys, "stderr", err)
        code = PG.main()
        return code, err.getvalue()

    # Pin next RTH away from Monday inside the lock module used by the guard.
    monkeypatch.setattr(
        L,
        "next_rth_et_date",
        lambda as_of=None: __import__("datetime").date(2026, 7, 31),
    )

    code, err = run(
        "Collect slice ACCEPT. OUT-OF-SCOPE: Chart render / GEX bars. Monday live proof."
    )
    assert code == 2, f"Chart-intent/Monday residual Write not blocked (exit={code}, err={err!r})"
    assert "RC-163" in err

    code, err = run(
        "STATUS PARTIAL with open CHART_CONSUMER residual. "
        "NEXT_RTH_PROOF on 2026-07-31 Friday (is_trading_day_et)."
    )
    assert code == 0, f"honest PARTIAL residual was wrongly blocked: {err!r}"
