"""P3-1b: governed executor required for active/ writes."""
from __future__ import annotations

import pytest

from arch_competition.exceptions import ManualGovernanceError
from arch_competition.promotion_execution import (
    assert_active_writes_use_governed_executor,
    governed_active_write_scope,
)


def test_governed_executor_required_for_active_writes():
    with pytest.raises(ManualGovernanceError):
        assert_active_writes_use_governed_executor("test")
    with governed_active_write_scope("test"):
        assert_active_writes_use_governed_executor("test")


