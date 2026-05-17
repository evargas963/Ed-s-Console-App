"""
Registered non-Schwab sources for chain-of-trust ALLOWLISTED rows.

Each entry requires: id, justification, owner_section, added_in_sha, category.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AllowlistCategory = Literal[
    "clock",
    "auth",
    "transport",
    "counter",
    "config",
    "filesystem",
    "env",
    "internal_state",
]

REQUIRED_CATEGORIES = frozenset(
    {
        "clock",
        "auth",
        "transport",
        "counter",
        "config",
        "filesystem",
        "env",
        "internal_state",
    }
)


@dataclass(frozen=True)
class AllowlistEntry:
    id: str
    justification: str
    owner_section: str
    added_in_sha: str
    category: AllowlistCategory


CHAIN_OF_TRUST_ALLOWLIST: tuple[AllowlistEntry, ...] = (
    AllowlistEntry(
        id="mega1_oauth_flow",
        justification="Interactive OAuth authorize/callback flow; no Schwab market field is produced.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="auth",
    ),
    AllowlistEntry(
        id="mega1_oauth_token_file",
        justification="Reads local token JSON metadata for refresh eligibility; not a quote/chain/pricehistory leaf.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="auth",
    ),
    AllowlistEntry(
        id="mega1_schwab_py_client",
        justification="Constructs schwab-py HTTP client object from token; wire calls happen in safe_get_* wrappers.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="transport",
    ),
    AllowlistEntry(
        id="mega1_transport_abstract",
        justification="Abstract bar-stream transport stubs with no Schwab wire read until implemented.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="transport",
    ),
    AllowlistEntry(
        id="mega1_transport_retry",
        justification="HTTP retry/backoff and token-refresh orchestration around Schwab safe_get_* calls.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="transport",
    ),
    AllowlistEntry(
        id="mega1_session_calendar",
        justification="ET session calendar window for polling; not published on Schwab quote/chain/pricehistory JSON.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="clock",
    ),
    AllowlistEntry(
        id="mega1_sqlite_internal",
        justification="SQLite snapshot persistence and normalization tables; stored rows are downstream of Schwab ingest.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="internal_state",
    ),
    AllowlistEntry(
        id="mega1_l1_sse_counters",
        justification="L1 SSE throttle counters, fingerprints, and queue bookkeeping; no market field derivation.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="counter",
    ),
    AllowlistEntry(
        id="mega1_env_config",
        justification="Environment variables and runtime config flags for server/live plane wiring.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="env",
    ),
    AllowlistEntry(
        id="mega1_filesystem",
        justification="Diagnostic directory creation and token path normalization on local disk.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="filesystem",
    ),
    AllowlistEntry(
        id="mega1_diagnostic_log",
        justification="Structured logging and diagnostic JSON writes without reading market fields.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="internal_state",
    ),
    AllowlistEntry(
        id="mega1_internal_helper",
        justification="Pure parse/format/control helper with no Schwab wire or persisted snapshot field output.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="internal_state",
    ),
    AllowlistEntry(
        id="mega1_replay_validation",
        justification="Replay-vs-live validation harness compares captured bundles; not a Schwab API producer.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="internal_state",
    ),
    AllowlistEntry(
        id="mega1_live_plane_state",
        justification="In-memory live plane connection state and diagnostics; not a Schwab dictionary leaf.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="internal_state",
    ),
    AllowlistEntry(
        id="mega1_thread_executor",
        justification="Thread-pool scheduling for async fetch work; carries no market field semantics.",
        owner_section="Mega1",
        added_in_sha="PENDING",
        category="internal_state",
    ),
)

ALLOWLIST_BY_ID: dict[str, AllowlistEntry] = {e.id: e for e in CHAIN_OF_TRUST_ALLOWLIST}
