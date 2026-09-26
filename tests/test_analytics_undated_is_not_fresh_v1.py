"""RC-282 — an analytics bundle nobody can date is not a fresh bundle.

WHAT CURSOR MEASURED (adversarial audit of 20800292..bd9a9604). An entry carrying
`ms_dict` but neither `generated_at` nor `ts` produced:

    {'analytics_generated_at': None, 'analytics_age_sec': 0.0,
     'analytics_stale': False, 'analytics_refresh_due': False}

`_analytics_generated_ts` returned 0.0 for an undated entry and
`_attach_analytics_freshness_contract` computed `age = ... if gen_ts > 0 else 0.0`, so an
undatable bundle was published to the operator's card as brand new AND not due for refresh.

THE PART THAT MAKES IT A ROOT, NOT A TYPO. The SAME helper is read at the stale-serve
marker as `max(0.0, now - _analytics_generated_ts(entry))`, which for the same entry is
~1.8e9 seconds and correctly marks it stale. One sentinel, two callers, opposite verdicts
about the identical cache entry — and neither call site looks wrong in isolation, which is
why the disagreement survived. This is RC-274's root ("absence is re-decided at every
read") reaching a third surface: the earlier rows removed fabricated zeros from storage and
render paths but left the SENTINEL, which is the mechanism that permits the re-decision.

These tests pin both surfaces to the same answer.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import server as srv  # noqa: E402

KEY = ("ZZAN", "2026-08-07")


def _freshness(entry: dict | None) -> dict:
    md: dict = {}
    srv._attach_analytics_freshness_contract(
        md, data_cache_key=KEY, entry=entry, now=time.time(),
        sse_live=False, inflight_key=KEY)
    return md


# ───────────────────────────────────────────── the helper stops lying by sentinel ────





# ─────────────────────────────────────── the operator-facing card: Cursor's probe ────











# ────────────────────────────────────── the two call sites must not disagree again ────

def test_no_caller_treats_a_missing_timestamp_as_epoch_zero():
    """The disagreement was invisible because both readings were plausible arithmetic."""
    import inspect

    src = inspect.getsource(srv)
    assert "now - _analytics_generated_ts(" not in src, (
        "a call site does arithmetic directly on the reader again; if it returns None that "
        "raises, and if it ever returns 0.0 again this silently reads as 1970")
    assert "if gen_ts > 0" not in src, (
        "a call site tests the timestamp numerically instead of for absence")
