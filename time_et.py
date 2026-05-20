"""US/Eastern wall-clock authority (DST-aware). Single source for production ET."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    """Timezone-aware US/Eastern now."""
    return datetime.now(ET)
