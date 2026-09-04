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
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from app.domain.instrument_identity import ticker_storage_key

log = logging.getLogger(__name__)

ENVELOPE_SCHEMA_VERSION = "1"
REPO_ROOT = Path(__file__).resolve().parent
CAS_ROOT = REPO_ROOT / "models" / "_artifact_cas"

IDENTITY_CLASS_FULL = "FULL_STACK_PINNED"
IDENTITY_CLASS_DEGRADED = "DEGRADED_PINNED"
IDENTITY_CLASS_FAIL_CLOSED = "FAIL_CLOSED_PINNED"
IDENTITY_CLASSES = (IDENTITY_CLASS_FULL, IDENTITY_CLASS_DEGRADED, IDENTITY_CLASS_FAIL_CLOSED)

# Row-level classification for persisted surfaces (snapshots).
ROW_CLASS_MODEL_DERIVED = "MODEL_DERIVED"
ROW_CLASS_NOT_APPLICABLE = "NOT_APPLICABLE"  # quote-only / non-model rows

# Historical (pre-schema) row classification — evidence-only, never backfilled.
LEGACY_PROVEN = "PROVEN"
LEGACY_PARTIALLY_RECOVERABLE = "PARTIALLY_RECOVERABLE"
LEGACY_UNRECOVERABLE = "UNRECOVERABLE_LEGACY"
LEGACY_NOT_APPLICABLE = "NOT_APPLICABLE"

LEDGER_OPEN = "OPEN"
LEDGER_COMPLETE = "COMPLETE"
LEDGER_INCOMPLETE = "INCOMPLETE"  # terminal: a required surface never landed

_SHA256_HEX = frozenset("0123456789abcdef")


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


def build_execution_envelope(
    *,
    release: dict[str, Any],
    requested_ticker: str,
    bundle_ticker: str,
    guest_anchor: bool,
    guest_anchor_ticker: Optional[str],
    horizons_attempted: list[str],
    bundles_by_horizon: dict[str, dict[str, Any]],
    calibration_by_horizon: dict[str, dict[str, Any]] | None,
    calibration_logging_enabled: bool,
    stack_pins: dict[str, Any],
    runtime_class: str,
    degradation: dict[str, Any] | None,
    tradeable_policy: dict[str, Any] | None,
    executed_at_utc: float,
) -> dict[str, Any]:
    """Assemble the canonical envelope from the ACTUAL execution surfaces.

    ``bundles_by_horizon`` entries come from the Item-4 verification provenance
    registry + bundle integrity manifests (per-role sha256 map, manifest sha,
    integrity class, lineage).  Calibration absence is explicit, never silent.
    """
    calibration: dict[str, Any]
    if calibration_by_horizon:
        calibration = {"attached": True, "by_horizon": calibration_by_horizon,
                       "logging_enabled": bool(calibration_logging_enabled)}
    else:
        calibration = {
            "attached": False,
            "logging_enabled": bool(calibration_logging_enabled),
            "reason": ("calibration logging disabled" if not calibration_logging_enabled
                       else "no calibration artifacts attached for this execution"),
        }
    envelope = {
        "envelope_schema_version": ENVELOPE_SCHEMA_VERSION,
        "release": {
            "release_id": release.get("release_id"),
            "git_sha": release.get("git_sha"),
            "config_hash": release.get("config_hash"),
            "build_generation": release.get("build_generation"),
        },
        "routing": {
            # requested_ticker = REQUEST ECHO (what was asked for); explicitly NOT the canonical
            # routing identity and never substituted for it (RC-345/F25).
            "requested_ticker": str(requested_ticker).strip().upper(),
            # bundle_ticker / guest_anchor_ticker = CANONICAL instrument used for bundle/model/
            # storage/routing → the one storage-key authority.
            "bundle_ticker": ticker_storage_key(bundle_ticker),
            "guest_anchor": bool(guest_anchor),
            "guest_anchor_ticker": (ticker_storage_key(guest_anchor_ticker)
                                     if guest_anchor_ticker else None),
            "horizons_attempted": sorted(horizons_attempted),
            "horizons_executed": sorted(bundles_by_horizon),
        },
        "bundles": bundles_by_horizon,
        "calibration": calibration,
        "stack_pins": stack_pins,
        "runtime": {
            "runtime_class": runtime_class,
            "degradation": degradation or {"degraded": False},
            "tradeable_policy": tradeable_policy or {"evaluated": False},
        },
        "executed_at_utc": float(executed_at_utc),
    }
    # canonicalization check happens here so a malformed envelope never
    # reaches the insert path
    canonical_envelope_json(envelope)
    return envelope


def identity_class_for_envelope(envelope: dict[str, Any]) -> str:
    runtime = envelope.get("runtime") or {}
    degradation = runtime.get("degradation") or {}
    rc = str(runtime.get("runtime_class") or "")
    if "FAIL_CLOSED" in rc:
        return IDENTITY_CLASS_FAIL_CLOSED
    if degradation.get("degraded"):
        return IDENTITY_CLASS_DEGRADED
    return IDENTITY_CLASS_FULL


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

def _canon_list(items: list[str]) -> str:
    return json.dumps(sorted(set(items)), separators=(",", ":"))


def insert_execution_identity(
    conn: sqlite3.Connection,
    envelope: dict[str, Any],
    *,
    decision_id: str,
    expected_surfaces: list[str],
) -> str:
    """Atomically persist the identity anchor: envelope row + ledger binding.

    Concurrent identical inserts deduplicate safely (same sha, byte-identical
    envelope); a same-sha different-envelope collision is refused.  Returns the
    execution_identity_sha256.
    """
    payload = canonical_envelope_json(envelope)
    sha = hashlib.sha256(payload.encode("ascii")).hexdigest()
    identity_class = identity_class_for_envelope(envelope)
    rel = envelope["release"]
    routing = envelope["routing"]
    now = time.time()
    with conn:  # one physical transaction: identity + ledger anchor
        # Concurrency-safe dedupe: ON CONFLICT DO NOTHING then verify the
        # surviving row byte-matches — two racing identical inserts both
        # succeed; a same-address different-bytes registration is refused.
        conn.execute(
            """INSERT INTO model_execution_identities (
                   execution_identity_sha256, envelope_schema_version, envelope_json,
                   created_at_utc, release_id, git_sha, config_hash,
                   requested_ticker, bundle_ticker, runtime_class, identity_class
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(execution_identity_sha256) DO NOTHING""",
            (
                sha, ENVELOPE_SCHEMA_VERSION, payload, now,
                str(rel.get("release_id") or ""), str(rel.get("git_sha") or ""),
                str(rel.get("config_hash") or ""),
                routing["requested_ticker"], routing["bundle_ticker"],
                str((envelope.get("runtime") or {}).get("runtime_class") or ""),
                identity_class,
            ),
        )
        existing = conn.execute(
            "SELECT envelope_json FROM model_execution_identities WHERE execution_identity_sha256=?",
            (sha,),
        ).fetchone()
        if existing is None or existing[0] != payload:
            raise ExecutionIdentityError(
                "ENVELOPE_HASH_MISMATCH",
                f"identity {sha[:16]} already registered with DIFFERENT envelope bytes",
            )
        conn.execute(
            """INSERT INTO decision_persistence_ledger (
                   decision_id, execution_identity_sha256, expected_surfaces,
                   landed_surfaces, status, created_at_utc, updated_at_utc
               ) VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(decision_id) DO NOTHING""",
            (decision_id, sha, _canon_list(expected_surfaces), "[]",
             LEDGER_OPEN, now, now),
        )
        led = conn.execute(
            "SELECT execution_identity_sha256 FROM decision_persistence_ledger WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        if led is None or led[0] != sha:
            raise ExecutionIdentityError(
                "LEDGER_CONFLICT",
                f"decision {decision_id} already bound to a different execution identity",
            )
    return sha


def mark_surface_landed(conn: sqlite3.Connection, decision_id: str, surface: str) -> str:
    """Record one dependent surface as persisted; returns resulting ledger status."""
    row = conn.execute(
        "SELECT expected_surfaces, landed_surfaces FROM decision_persistence_ledger WHERE decision_id=?",
        (decision_id,),
    ).fetchone()
    if row is None:
        raise ExecutionIdentityError("LEDGER_MISSING", f"no ledger for decision {decision_id}")
    expected = set(json.loads(row[0]))
    landed = set(json.loads(row[1])) | {surface}
    status = LEDGER_COMPLETE if expected <= landed else LEDGER_OPEN
    with conn:
        conn.execute(
            "UPDATE decision_persistence_ledger SET landed_surfaces=?, status=?, updated_at_utc=? WHERE decision_id=?",
            (_canon_list(sorted(landed)), status, time.time(), decision_id),
        )
    return status


def ledger_consistency_scan(conn: sqlite3.Connection, *, stale_after_s: float = 900.0) -> dict[str, Any]:
    """Mechanical partial-persistence detector: OPEN ledgers older than the
    threshold are explicitly INCOMPLETE (terminal, non-tradeable, audit-visible)."""
    now = time.time()
    incomplete = []
    for did, exp, landed, updated in conn.execute(
        "SELECT decision_id, expected_surfaces, landed_surfaces, updated_at_utc "
        "FROM decision_persistence_ledger WHERE status='OPEN'"
    ).fetchall():
        if now - float(updated) >= stale_after_s:
            missing = sorted(set(json.loads(exp)) - set(json.loads(landed)))
            incomplete.append({"decision_id": did, "missing_surfaces": missing})
            with conn:
                conn.execute(
                    "UPDATE decision_persistence_ledger SET status='INCOMPLETE', updated_at_utc=? WHERE decision_id=?",
                    (now, did),
                )
    complete = conn.execute(
        "SELECT COUNT(*) FROM decision_persistence_ledger WHERE status='COMPLETE'"
    ).fetchone()[0]
    return {"incomplete_marked": incomplete, "complete_count": int(complete)}


# ══════════════════════════════════════════════════════════════════════════════
# Content-addressed artifact store (CAS)
# ══════════════════════════════════════════════════════════════════════════════

def _cas_path(sha: str, cas_root: Path | None = None) -> Path:
    s = str(sha).lower()
    if len(s) != 64 or not set(s) <= _SHA256_HEX:
        raise ExecutionIdentityError("ARTIFACT_CAS_MISSING", f"invalid sha256 address {sha!r}")
    root = Path(cas_root) if cas_root else CAS_ROOT
    return root / s[:2] / s


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_artifact(source: Path, expected_sha256: str, *, cas_root: Path | None = None) -> Path:
    """Verify-then-archive one artifact into the CAS (atomic; collision-refusing)."""
    src = Path(source)
    if not src.is_file():
        raise ExecutionIdentityError("ARTIFACT_SOURCE_MISSING", str(src))
    actual = _sha256_file(src)
    if actual != str(expected_sha256).lower():
        raise ExecutionIdentityError(
            "ARTIFACT_SOURCE_HASH_MISMATCH",
            f"{src}: expected {expected_sha256} actual {actual}",
        )
    dest = _cas_path(actual, cas_root)
    if dest.is_file():
        if _sha256_file(dest) != actual:
            raise ExecutionIdentityError(
                "ARTIFACT_CAS_COLLISION",
                f"CAS address {actual[:16]} holds DIFFERENT bytes — refusing overwrite",
            )
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(src.read_bytes())
    if _sha256_file(tmp) != actual:
        tmp.unlink(missing_ok=True)
        raise ExecutionIdentityError("ARTIFACT_CAS_CORRUPT", f"atomic write verify failed for {actual[:16]}")
    os.replace(tmp, dest)
    return dest


def retrieve_artifact(sha256: str, *, cas_root: Path | None = None) -> Path:
    """Resolve archived bytes by hash; verifies bytes on retrieval; fails closed."""
    dest = _cas_path(sha256, cas_root)
    if not dest.is_file():
        raise ExecutionIdentityError(
            "ARTIFACT_CAS_MISSING",
            f"{sha256[:16]}… not in the archive — replay MUST NOT fall back to models/active",
        )
    if _sha256_file(dest) != str(sha256).lower():
        raise ExecutionIdentityError("ARTIFACT_CAS_CORRUPT", f"CAS bytes for {sha256[:16]} fail hash verification")
    return dest


def envelope_artifact_shas(envelope: dict[str, Any]) -> set[str]:
    """Every artifact sha256 the envelope references (bundle manifests + roles)."""
    shas: set[str] = set()
    for hz_entry in (envelope.get("bundles") or {}).values():
        m = hz_entry.get("manifest_sha256")
        if isinstance(m, str) and len(m) == 64:
            shas.add(m.lower())
        for role_sha in (hz_entry.get("artifacts") or {}).values():
            if isinstance(role_sha, str) and len(role_sha) == 64:
                shas.add(role_sha.lower())
    return shas


def archive_envelope_artifacts(
    envelope: dict[str, Any],
    source_paths_by_sha: dict[str, Path],
    *,
    cas_root: Path | None = None,
) -> list[str]:
    """Archive EVERY artifact referenced by the envelope; refuse when a source
    is unavailable — an identity must never persist with unretained bytes."""
    archived = []
    for sha in sorted(envelope_artifact_shas(envelope)):
        dest = _cas_path(sha, cas_root)
        if dest.is_file():
            continue
        src = source_paths_by_sha.get(sha)
        if src is None:
            raise ExecutionIdentityError(
                "ARTIFACT_SOURCE_MISSING",
                f"no source bytes offered for referenced artifact {sha[:16]}…",
            )
        archive_artifact(Path(src), sha, cas_root=cas_root)
        archived.append(sha)
    return archived


def gc_check_artifact(conn: sqlite3.Connection, sha256: str) -> None:
    """Garbage collection guard: refuse removal while ANY persisted execution
    identity references the artifact (full reference scan, no cached counts)."""
    needle = str(sha256).lower()
    for (payload,) in conn.execute("SELECT envelope_json FROM model_execution_identities"):
        if needle in payload:
            raise ExecutionIdentityError(
                "ARTIFACT_REFERENCED",
                f"artifact {needle[:16]}… is referenced by a persisted execution identity",
            )


# ══════════════════════════════════════════════════════════════════════════════
# Replay resolver (current-pointer-free by construction)
# ══════════════════════════════════════════════════════════════════════════════

REPLAY_PROOF_LEVELS = (
    "ARTIFACT_BYTE_IDENTITY",       # proven here when all bytes resolve+verify
    "CONFIGURATION_IDENTITY",       # proven here (envelope pins)
    "EXECUTABLE_REPLAY_AVAILABILITY",  # NOT claimed by this resolver
    "ENVIRONMENT_IDENTITY",         # NOT claimed
    "STOCHASTIC_SEED_IDENTITY",     # NOT claimed
    "OUTPUT_EQUIVALENCE",           # NOT claimed
)


def resolve_execution_for_replay(
    conn: sqlite3.Connection,
    *,
    decision_id: str | None = None,
    execution_identity_sha256: str | None = None,
    cas_root: Path | None = None,
) -> dict[str, Any]:
    """row → identity → envelope → EXACT archived bytes.  Never touches
    models/active; fails closed on any unresolved component."""
    sha = execution_identity_sha256
    if sha is None:
        if not decision_id:
            raise ExecutionIdentityError("REPLAY_COMPONENT_UNRESOLVED", "no decision_id or identity given")
        row = conn.execute(
            "SELECT execution_identity_sha256 FROM decision_persistence_ledger WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise ExecutionIdentityError(
                "LEGACY_ROW_NO_IDENTITY",
                f"decision {decision_id} has no execution identity — UNRECOVERABLE_LEGACY; model replay refused",
            )
        sha = row[0]
    rec = conn.execute(
        "SELECT envelope_json FROM model_execution_identities WHERE execution_identity_sha256=?",
        (sha,),
    ).fetchone()
    if rec is None:
        raise ExecutionIdentityError("IDENTITY_MISSING", f"identity {str(sha)[:16]}… not registered")
    payload = rec[0]
    if hashlib.sha256(payload.encode("ascii")).hexdigest() != str(sha).lower():
        raise ExecutionIdentityError("ENVELOPE_HASH_MISMATCH", "stored envelope bytes fail content address")
    envelope = json.loads(payload)
    artifact_paths: dict[str, str] = {}
    for art_sha in sorted(envelope_artifact_shas(envelope)):
        artifact_paths[art_sha] = str(retrieve_artifact(art_sha, cas_root=cas_root))
    return {
        "execution_identity_sha256": str(sha).lower(),
        "envelope": envelope,
        "artifact_paths": artifact_paths,
        "proof_levels": {
            "ARTIFACT_BYTE_IDENTITY": "PROVEN",
            "CONFIGURATION_IDENTITY": "PROVEN",
            "EXECUTABLE_REPLAY_AVAILABILITY": "NOT_PROVEN",
            "ENVIRONMENT_IDENTITY": "NOT_PROVEN",
            "STOCHASTIC_SEED_IDENTITY": "NOT_PROVEN",
            "OUTPUT_EQUIVALENCE": "NOT_PROVEN",
        },
    }


def classify_historical_row(
    conn: sqlite3.Connection,
    *,
    decision_id: str | None,
    execution_identity_sha256: str | None,
    is_model_derived: bool,
) -> str:
    """Evidence-only historical classification.  NEVER writes anything."""
    if not is_model_derived:
        return LEGACY_NOT_APPLICABLE
    if execution_identity_sha256:
        rec = conn.execute(
            "SELECT 1 FROM model_execution_identities WHERE execution_identity_sha256=?",
            (execution_identity_sha256,),
        ).fetchone()
        return LEGACY_PROVEN if rec else LEGACY_UNRECOVERABLE
    if decision_id:
        # a decision record may pin release/git identity without artifact bytes
        return LEGACY_PARTIALLY_RECOVERABLE
    return LEGACY_UNRECOVERABLE


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

def anchor_production_execution(
    *,
    requested_ticker: str,
    serving_provenance: dict[str, Any] | None,
    calibration_info: dict[str, Any] | None,
    db_conn: sqlite3.Connection,
    decision_id: str,
    executed_at_utc: float,
    expected_surfaces: list[str],
    cas_root: Path | None = None,
) -> str:
    """Create the identity anchor for one live decision cycle BEFORE any
    model-derived persistence.  Assembles the envelope from the ACTUAL
    execution surfaces (release object, Item-4 verification provenance
    registry, serving provenance, calibration attach identity), archives every
    referenced artifact byte into the CAS, and registers identity + ledger.

    Raises ExecutionIdentityError on any unresolvable component — the caller
    must then REFUSE the model-derived write (fail closed), never persist a
    model-derived row without identity.
    """
    from release_object import get_current_release, validate_release_for_emission

    release = get_current_release(required=False)
    ok, reason = validate_release_for_emission(release)
    if not ok or not isinstance(release, dict):
        raise ExecutionIdentityError(
            "WRITE_WITHOUT_IDENTITY", f"release unavailable for identity anchor: {reason}"
        )

    prov = serving_provenance or {}
    # RC-345/F25: bundle_ticker is canonical routing identity — even when it falls back to the
    # request echo, it resolves through the one storage-key authority (echo never leaks raw).
    bundle_ticker = ticker_storage_key(prov.get("bundle_ticker") or requested_ticker)
    runtime_class = str(prov.get("runtime_class") or "UNKNOWN")

    import ml_predict as mp
    from ml_horizon import ML_HORIZON_SLUGS

    bundles: dict[str, dict[str, Any]] = {}
    sources: dict[str, Path] = {}
    for hz in ML_HORIZON_SLUGS:
        roles = mp.get_artifact_verification_provenance(bundle_ticker, hz)
        verified = {r: p for r, p in roles.items() if p.get("verified")}
        if not verified:
            continue
        artifacts: dict[str, str] = {}
        manifest_sha = None
        bundle_dir = None
        for role, rp in sorted(verified.items()):
            sha = str(rp.get("actual_sha256") or "").lower()
            if len(sha) != 64:
                raise ExecutionIdentityError(
                    "WRITE_WITHOUT_IDENTITY",
                    f"verified role {role} for {bundle_ticker}/{hz} lacks an artifact sha256",
                )
            artifacts[role] = sha
            ap = rp.get("artifact_path")
            if ap:
                sources[sha] = Path(ap)
            m_sha = str(rp.get("manifest_sha256") or "").lower()
            if len(m_sha) == 64:
                manifest_sha = m_sha
                mpth = rp.get("manifest_path")
                if mpth:
                    sources[m_sha] = Path(mpth)
            bundle_dir = bundle_dir or rp.get("bundle_dir") or str(Path(str(ap)).parent if ap else "")
        bundles[hz] = {
            "bundle_dir_identity": str(bundle_dir or ""),
            "manifest_sha256": manifest_sha,
            "artifacts": artifacts,
            "source_lineage": {
                "trained_at": next((v.get("trained_at") for v in verified.values()
                                     if v.get("trained_at")), None),
                "scheduler_cache_key": next((v.get("scheduler_cache_key") for v in verified.values()
                                              if v.get("scheduler_cache_key")), None),
            },
            "integrity_class": "VERIFIED_AGAINST_BUNDLE_MANIFEST",
            "serving_complete": bool(prov.get("bundle_complete")),
        }

    from calibration.writer import calibration_logging_enabled

    cal_enabled = calibration_logging_enabled()
    cal_by_hz = None
    if isinstance(calibration_info, dict) and calibration_info:
        cal_by_hz = calibration_info

    # fail-loud pins: a missing contract constant is an ImportError, never a
    # silently-None envelope field
    from model_contract import (
        CONTRACT_FIELDS,
        CURRENT_FEATURE_SCHEMA_VERSION,
        CURRENT_LABEL_CONFIG_VERSION,
        CURRENT_PREPROCESSING_VERSION,
    )

    stack_pins = {
        "feature_schema_version": CURRENT_FEATURE_SCHEMA_VERSION,
        "preprocessing_version": CURRENT_PREPROCESSING_VERSION,
        "label_config_version": CURRENT_LABEL_CONFIG_VERSION,
        "contract_fields": sorted(CONTRACT_FIELDS),
        "env_controlled_behavior": {
            k: os.environ.get(k)
            for k in (
                "ED_APPLY_ABLATION_SURVIVORS", "ED_ARTIFACT_INTEGRITY_STRICT",
                "ED_CALIBRATION_LOG", "ED_XGB_STRICT_ACTIVE_ONLY",
                "ED_ARTIFACT_REVERIFY_TTL_SECONDS",
            )
            if os.environ.get(k) is not None
        },
    }

    degraded_reasons = []
    if prov.get("relaxation_active"):
        degraded_reasons.append("relaxation_active")
    if prov.get("fail_closed_reason"):
        degraded_reasons.append(str(prov.get("fail_closed_reason")))
    envelope = build_execution_envelope(
        release=release,
        requested_ticker=requested_ticker,
        bundle_ticker=bundle_ticker,
        guest_anchor=bool(prov.get("guest_anchor")),
        guest_anchor_ticker=prov.get("guest_anchor_ticker"),
        horizons_attempted=list(ML_HORIZON_SLUGS),
        bundles_by_horizon=bundles,
        calibration_by_horizon=cal_by_hz,
        calibration_logging_enabled=cal_enabled,
        stack_pins=stack_pins,
        runtime_class=runtime_class,
        degradation=({"degraded": True, "reasons": degraded_reasons}
                     if degraded_reasons else None),
        tradeable_policy={"evaluated": True,
                          "model_load_status": prov.get("model_load_status")},
        executed_at_utc=executed_at_utc,
    )
    archive_envelope_artifacts(envelope, sources, cas_root=cas_root)
    return insert_execution_identity(
        db_conn, envelope, decision_id=decision_id, expected_surfaces=expected_surfaces
    )
