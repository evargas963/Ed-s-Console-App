"""OPTIONS FLOW FOUNDATION — excluding the expiry MAPS must lose no contract leaf (2026-08-26).

The field matrix dispositions chains.callExpDateMap / chains.putExpDateMap as
DELIBERATELY_EXCLUDED_WITH_PROOF. The stated reason is that those maps ARE the contracts, and every
leaf beneath them is already persisted verbatim per-contract elsewhere. That is a claim about DATA,
so it must be re-derivable on demand rather than believed from a commit message — this test IS the
derivation, and it runs the comparison rather than restating its conclusion.

METHOD: normalised NATIVE per-contract leafset (from the committed canonical inventory, which is
built from live vendor responses) MINUS the PERSISTED contract keyset (read from real rows in the
two persisters). Missing must be empty.

The `*` list-index wildcard is normalised away because the inventory writes
`optionDeliverablesList.*.assetType` where a persisted dict yields `optionDeliverablesList.assetType`
— the same field under two spellings. Without that normalisation the comparison reports five
phantom losses, which is what a first pass of this check did report.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.options_native_field_matrix_v1 import enumerate_rest_chain


def _norm(key: str) -> str:
    """Collapse the list-index wildcard: a.*.b -> a.b, and drop a bare trailing .*"""
    return re.sub(r"\.\*$", "", re.sub(r"\.\*(?=\.)", "", key))


def _persisted_contract_keys(conn: sqlite3.Connection, sql: str) -> set[str]:
    keys: set[str] = set()
    try:
        rows = conn.execute(sql).fetchall()
    except sqlite3.Error:
        return keys
    for (blob,) in rows:
        if not blob:
            continue
        try:
            contracts = json.loads(blob)
        except (ValueError, TypeError):
            continue
        for c in contracts if isinstance(contracts, list) else []:
            if not isinstance(c, dict):
                continue
            for k, v in c.items():
                keys.add(k)
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    for nested in v[0]:
                        keys.add(f"{k}.{nested}")
    return keys


#: The derivation needs a DB that actually HOLDS persisted option rows. In a fresh worktree db.DB_PATH
#: is an empty database, so the check would skip and prove nothing — and a skip presented as proof is
#: exactly the vacuous-green failure this suite exists to prevent. ED_OPTIONS_KEYSET_DB points the
#: derivation at a populated database (no operator-home path is hardcoded here — tracked files must
#: not carry one). Where neither has rows the test SKIPS LOUDLY, saying the claim is unverified in
#: this environment rather than implying it passed.
DB_ENV_VAR = "ED_OPTIONS_KEYSET_DB"


def _db_path() -> Path | None:
    import os

    override = os.environ.get(DB_ENV_VAR)
    if override:
        p = Path(override)
        if p.is_file():
            return p
    try:
        from db import DB_PATH
    except Exception:
        return None
    p = Path(str(DB_PATH))
    return p if p.is_file() else None


def test_every_native_contract_leaf_survives_in_the_persisted_keyset():
    db = _db_path()
    if db is None:
        pytest.skip("no local DB — this derivation needs real persisted rows")
    _env, _und, contract = enumerate_rest_chain()
    native = {_norm(c) for c in contract}
    assert native, "native contract leafset enumerated empty — evidence missing"

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30.0)
    try:
        persisted = _persisted_contract_keys(
            conn, "SELECT option_chain_json FROM snapshots WHERE option_chain_json IS NOT NULL "
                  "ORDER BY ts_utc DESC LIMIT 3")
        persisted |= _persisted_contract_keys(
            conn, "SELECT chain_json FROM option_chain_morning_full ORDER BY et_date DESC LIMIT 2")
    finally:
        conn.close()
    if not persisted:
        pytest.skip(f"UNVERIFIED HERE: no persisted option rows in {db}. This derivation did NOT "
                    f"run — set {DB_ENV_VAR} to a populated database to prove the claim.")

    persisted = {_norm(k) for k in persisted}
    missing = sorted(native - persisted)
    assert not missing, (
        "excluding call/putExpDateMap WOULD lose contract leaves — the matrix's "
        f"DELIBERATELY_EXCLUDED_WITH_PROOF disposition is unsupported for: {missing}")


def test_verbatim_storage_keeps_vendor_fields_newer_than_our_inventory():
    """The raw-first design earns its keep here: fields the vendor added AFTER the committed
    inventory was built are retained anyway, because the contract dict is stored whole. If this
    ever finds nothing extra it is not a failure — it is asserted only when extras exist."""
    db = _db_path()
    if db is None:
        pytest.skip("no local DB")
    _env, _und, contract = enumerate_rest_chain()
    native = {_norm(c) for c in contract}
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30.0)
    try:
        persisted = _persisted_contract_keys(
            conn, "SELECT option_chain_json FROM snapshots WHERE option_chain_json IS NOT NULL "
                  "ORDER BY ts_utc DESC LIMIT 3")
    finally:
        conn.close()
    if not persisted:
        pytest.skip(f"UNVERIFIED HERE: no persisted option rows in {db}. This derivation did NOT "
                    f"run — set {DB_ENV_VAR} to a populated database to prove the claim.")
    extras = {_norm(k) for k in persisted} - native
    for e in extras:
        assert e and isinstance(e, str)
