"""execution_identity_v1 — immutable per-decision execution identity (ML-PIPE).

PER_ROW_HISTORICAL_MODEL_ARTIFACT_IDENTITY_V1. Single owner of:

  * the canonical execution ENVELOPE (deterministic JSON, content-addressed by
    SHA-256) committing to every materially active component of one production
    decision cycle: release/git/config identity, routing (requested vs bundle
    ticker, guest anchor), per-horizon bundle+artifact identity, calibration
    identity (or explicit absence reason), full-stack pins, runtime class and
    degradation state;
  * the insert-only ``model_execution_identities`` table (UPDATE/DELETE refused
    by triggers — envelopes are immutable after insertion);
  * the ``decision_persistence_ledger`` — the atomicity authority: one row per
    decision_id binding it to EXACTLY ONE execution identity and recording
    which dependent surfaces (decision record / snapshot / calibration) were
    expected and which landed.  Dependent tables carry
    (decision_id, execution_identity_sha256) enforced by triggers against the
    ledger, so related rows can never persist with different, missing, or
    inconsistent identities.  Partial persistence is therefore EXPLICIT
    (ledger status != COMPLETE) and mechanically detectable — never presented
    as complete, never silently inconsistent;
  * the governed content-addressed artifact store (CAS) under
    ``models/_artifact_cas`` — bytes verified before archival, addressed by
    SHA-256, written atomically, collision-refusing, retrieval-verified;
    garbage collection is refused unless a full reference scan proves no
    persisted execution identity references the artifact;
  * the replay resolver — resolves a persisted row to its immutable envelope
    and EXACT archived bytes; it never reads models/active (current/latest)
    and fails closed when any required component is missing.

Design note (differs from the audit's single-physical-transaction proposal):
the three dependent writers own separate SQLite connections with independent
busy-retry semantics against a multi-GB WAL capture database.  Forcing one
shared transaction would serialize the capture loop and rewrite all three
lifecycles.  The identity-anchor + ledger + trigger design proves the same
institutional outcomes: no dependent row without an identity, no two rows of
one decision with different identities, no hidden partial commit.

Legacy policy: historical rows keep NULL identity forever.  Classification is
evidence-only (PROVEN / PARTIALLY_RECOVERABLE / UNRECOVERABLE_LEGACY /
NOT_APPLICABLE); nothing is backfilled, guessed, or timestamp-matched.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Optional



ENVELOPE_SCHEMA_VERSION = "1"


# Row-level classification for persisted surfaces (snapshots).
ROW_CLASS_MODEL_DERIVED = "MODEL_DERIVED"
ROW_CLASS_NOT_APPLICABLE = "NOT_APPLICABLE"  # quote-only / non-model rows





class ExecutionIdentityError(ValueError):
    """Fail-closed execution-identity violation with a stable reason code."""

    REASONS = (
        "ENVELOPE_MALFORMED",
        "ENVELOPE_NONCANONICAL",
        "ENVELOPE_HASH_MISMATCH",
        "ENVELOPE_IMMUTABLE",
        "IDENTITY_MISSING",
        "IDENTITY_MISMATCH",
        "IDENTITY_CLASS_INVALID",
        "LEDGER_MISSING",
        "LEDGER_CONFLICT",
        "ARTIFACT_SOURCE_MISSING",
        "ARTIFACT_SOURCE_HASH_MISMATCH",
        "ARTIFACT_CAS_COLLISION",
        "ARTIFACT_CAS_MISSING",
        "ARTIFACT_CAS_CORRUPT",
        "ARTIFACT_REFERENCED",
        "REPLAY_CURRENT_POINTER_FORBIDDEN",
        "REPLAY_COMPONENT_UNRESOLVED",
        "LEGACY_ROW_NO_IDENTITY",
        "QUOTE_ONLY_NOT_MODEL_DERIVED",
        "WRITE_WITHOUT_IDENTITY",
    )

    def __init__(self, reason: str, detail: str):
        if reason not in self.REASONS:
            raise ValueError(f"unknown execution identity reason: {reason!r}")
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


# ══════════════════════════════════════════════════════════════════════════════
# Canonical envelope
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_ENVELOPE_KEYS: tuple[str, ...] = (
    "envelope_schema_version",
    "release",        # release_id, git_sha, config_hash, build_generation
    "routing",        # requested_ticker, bundle_ticker, guest_anchor, horizons
    "bundles",        # per-horizon: manifest sha, per-role artifact sha map, lineage, integrity class
    "calibration",    # per-horizon run/lineage ids, or {"attached": false, "reason": ...}
    "stack_pins",     # feature/preprocessing/label/fusion/regime/mc/rules/ablation identities
    "runtime",        # runtime_class, degradation, tradeable policy result, fail-closed reasons
    "executed_at_utc",
)


def canonical_envelope_json(envelope: dict[str, Any]) -> str:
    """Deterministic canonical serialization (sorted keys, compact, ASCII).

    Refuses NaN/Infinity (non-interoperable JSON) and non-dict envelopes.
    """
    if not isinstance(envelope, dict):
        raise ExecutionIdentityError("ENVELOPE_MALFORMED", "envelope must be a dict")
    missing = [k for k in REQUIRED_ENVELOPE_KEYS if k not in envelope]
    if missing:
        raise ExecutionIdentityError(
            "ENVELOPE_MALFORMED", f"missing required envelope keys: {missing}"
        )
    if envelope.get("envelope_schema_version") != ENVELOPE_SCHEMA_VERSION:
        raise ExecutionIdentityError(
            "ENVELOPE_MALFORMED",
            f"envelope_schema_version must be {ENVELOPE_SCHEMA_VERSION!r}",
        )
    try:
        return json.dumps(
            envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionIdentityError(
            "ENVELOPE_NONCANONICAL", f"envelope not canonically serializable: {exc}"
        ) from exc


def execution_identity_sha256(envelope: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_envelope_json(envelope).encode("ascii")).hexdigest()






# ══════════════════════════════════════════════════════════════════════════════
# Schema (insert-only identity table + persistence ledger + linkage triggers)
# ══════════════════════════════════════════════════════════════════════════════

EXECUTION_IDENTITY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS model_execution_identities (
    execution_identity_sha256 TEXT PRIMARY KEY,
    envelope_schema_version   TEXT NOT NULL,
    envelope_json             TEXT NOT NULL,
    created_at_utc            REAL NOT NULL,
    release_id                TEXT NOT NULL,
    git_sha                   TEXT NOT NULL,
    config_hash               TEXT NOT NULL,
    requested_ticker          TEXT NOT NULL,
    bundle_ticker             TEXT NOT NULL,
    runtime_class             TEXT NOT NULL,
    identity_class            TEXT NOT NULL
        CHECK (identity_class IN ('FULL_STACK_PINNED','DEGRADED_PINNED','FAIL_CLOSED_PINNED'))
);

CREATE TABLE IF NOT EXISTS decision_persistence_ledger (
    decision_id               TEXT PRIMARY KEY,
    execution_identity_sha256 TEXT NOT NULL
        REFERENCES model_execution_identities(execution_identity_sha256),
    expected_surfaces         TEXT NOT NULL,   -- canonical json list
    landed_surfaces           TEXT NOT NULL,   -- canonical json list
    status                    TEXT NOT NULL
        CHECK (status IN ('OPEN','COMPLETE','INCOMPLETE')),
    created_at_utc            REAL NOT NULL,
    updated_at_utc            REAL NOT NULL
);

-- Immutability: execution identities are insert-only forever.
CREATE TRIGGER IF NOT EXISTS trg_exec_identity_no_update
BEFORE UPDATE ON model_execution_identities
BEGIN
    SELECT RAISE(ABORT, 'ENVELOPE_IMMUTABLE: model_execution_identities is insert-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_exec_identity_no_delete
BEFORE DELETE ON model_execution_identities
BEGIN
    SELECT RAISE(ABORT, 'ENVELOPE_IMMUTABLE: model_execution_identities is insert-only');
END;
"""

# Dependent-table linkage triggers.  {table} carries decision_id +
# execution_identity_sha256 columns (added by additive migration).  Rules:
#   * an identity, when present, must EXIST in model_execution_identities;
#   * a (decision_id, identity) pair must match the ledger binding exactly —
#     two surfaces of one decision can never carry different identities;
#   * an identity without a decision_id (or vice versa) is refused.
_LINKAGE_TRIGGER_TEMPLATE = """
CREATE TRIGGER IF NOT EXISTS trg_{table}_exec_identity_link
BEFORE INSERT ON {table}
WHEN NEW.execution_identity_sha256 IS NOT NULL OR NEW.decision_id IS NOT NULL
BEGIN
    SELECT CASE
        WHEN NEW.execution_identity_sha256 IS NULL OR NEW.decision_id IS NULL THEN
            RAISE(ABORT, 'IDENTITY_MISMATCH: decision_id and execution_identity_sha256 must be set together')
        WHEN NOT EXISTS (
            SELECT 1 FROM model_execution_identities
            WHERE execution_identity_sha256 = NEW.execution_identity_sha256
        ) THEN
            RAISE(ABORT, 'IDENTITY_MISSING: execution identity not registered')
        WHEN NOT EXISTS (
            SELECT 1 FROM decision_persistence_ledger
            WHERE decision_id = NEW.decision_id
              AND execution_identity_sha256 = NEW.execution_identity_sha256
        ) THEN
            RAISE(ABORT, 'LEDGER_CONFLICT: decision_id is not bound to this execution identity')
    END;
END;
"""

LINKED_TABLES: tuple[str, ...] = (
    "snapshots",
    "production_decision_records",
    "calibration_decision_log",
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def ensure_execution_identity_schema(conn: sqlite3.Connection) -> None:
    """Idempotent, ADDITIVE migration: identity tables, dependent-table columns,
    and linkage triggers.  Never drops, rewrites, or mutates existing rows —
    legacy rows keep NULL identity forever."""
    conn.executescript(EXECUTION_IDENTITY_SCHEMA_SQL)
    for table in LINKED_TABLES:
        if not _table_exists(conn, table):
            continue
        cols = _columns(conn, table)
        if "decision_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN decision_id TEXT")
        if "execution_identity_sha256" not in cols:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN execution_identity_sha256 TEXT"
            )
        if table == "snapshots" and "execution_identity_class" not in cols:
            # MODEL_DERIVED vs NOT_APPLICABLE (quote-only) — explicit, never inferred
            conn.execute(
                "ALTER TABLE snapshots ADD COLUMN execution_identity_class TEXT"
            )
        conn.executescript(_LINKAGE_TRIGGER_TEMPLATE.format(table=table))
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
# Identity + ledger persistence (the atomic anchor)
# ══════════════════════════════════════════════════════════════════════════════









# ══════════════════════════════════════════════════════════════════════════════
# Content-addressed artifact store (CAS)
# ══════════════════════════════════════════════════════════════════════════════















# ══════════════════════════════════════════════════════════════════════════════
# Replay resolver (current-pointer-free by construction)
# ══════════════════════════════════════════════════════════════════════════════







# ══════════════════════════════════════════════════════════════════════════════
# Write-path guard (fail-closed for model-derived production writes)
# ══════════════════════════════════════════════════════════════════════════════

def require_identity_for_model_derived_write(
    *,
    is_model_derived: bool,
    decision_id: Optional[str],
    execution_identity_sha256: Optional[str],
    surface: str,
) -> str:
    """Single fail-closed policy for every production writer.

    Returns the row classification (MODEL_DERIVED / NOT_APPLICABLE); raises on
    a model-derived write missing its identity — never silently NULL."""
    if not is_model_derived:
        if execution_identity_sha256 or decision_id:
            raise ExecutionIdentityError(
                "QUOTE_ONLY_NOT_MODEL_DERIVED",
                f"{surface}: quote-only/non-model row must not carry an execution identity",
            )
        return ROW_CLASS_NOT_APPLICABLE
    if not decision_id or not execution_identity_sha256:
        raise ExecutionIdentityError(
            "WRITE_WITHOUT_IDENTITY",
            f"{surface}: model-derived production write requires decision_id + execution_identity_sha256",
        )
    return ROW_CLASS_MODEL_DERIVED


# ══════════════════════════════════════════════════════════════════════════════
# Live-cycle anchor (server persist tail)
# ══════════════════════════════════════════════════════════════════════════════

