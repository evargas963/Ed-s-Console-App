"""Phase 3a.1: promotion_decision_record must not use ambiguous 'winner' key."""

from pathlib import Path


def test_promotion_decision_record_uses_scheduler_log_loss_winner():
    text = Path("ml_scheduler.py").read_text(encoding="utf-8")
    start = text.index("promotion_decision_record = {")
    block = text[start : start + 900]
    assert '"winner"' not in block
    assert '"scheduler_log_loss_winner"' in block
