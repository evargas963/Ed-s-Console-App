"""Chain-of-trust: consumer canonical fields must resolve to Schwab leaves or allowlisted sources."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.chain_of_trust_audit import (  # noqa: E402
    PRIORITY_FIELDS,
    TrustStatus,
    format_gap_report,
    resolve_field_for_consumer,
    run_chain_of_trust_audit,
    _inventory_index,
    build_producer_index,
    FieldRef,
)


def test_priority_canonical_fields_resolve():
    """Critical contamination-risk fields must close before full consumer sweep."""
    from governance.chain_of_trust_audit import FieldRef

    inv = _inventory_index(range(1, 17))
    producer_idx = build_producer_index(ROOT)
    failures: list[str] = []
    for carrier, name in PRIORITY_FIELDS:
        res = resolve_field_for_consumer(ROOT, inv, producer_idx, FieldRef(carrier, name))
        if res.status not in (TrustStatus.SCHWAB_LEAF, TrustStatus.ALLOWLISTED):
            failures.append(f"{carrier}.{name}: {res.detail}")
    assert failures == [], "priority field gaps:\n" + "\n".join(failures)


def test_chain_of_trust_closes_for_all_canonical_fields():
    """
    Full consumer read sweep (§4, §6, §7, §10, §11, §13, §14, §16) must resolve.

    Expected to fail until producer links are complete; failure message is the fix list.
  Run: python governance/chain_of_trust_audit.py
    """
    result = run_chain_of_trust_audit(ROOT)
    assert result.consumer_reads > 0
    assert result.priority_gaps == [], format_gap_report(result, limit=30)
    assert result.closes, format_gap_report(result, limit=40)
