#!/usr/bin/env python3
"""
UNIVERSAL_TICKER_MECHANICAL_LOCK_V1.

Operator-approved lock (2026-07-07): base anchors (SPY/QQQ/IWM) are the
minimum live proof surface, never the universal proof boundary. Universal
closure of ticker-affecting work requires either a full configured/supported
ticker-universe matrix, or mechanical proof the changed code path is
ticker-agnostic by construction plus base anchors plus guest/enrolled fixture
proof. Representative-only proof is NOT_PROVEN. BASE_TICKER_ONLY_CLOSURE is
FORBIDDEN.

Three mechanical checks:

1. Production ticker-literal scan (AST): locked ticker literals may appear at
   module level (config lists / rosters / inventories) but not inside
   function bodies of production Python, unless allowlisted here with a
   rationale. Tests, tools, docs, governance inventories are exempt surfaces.

2. Universality packet checks (markdown): a packet that declares
   `UNIVERSALITY_CLASSIFICATION:` must use an allowed value; the
   UNIVERSAL_TICKER_AGNOSTIC_PROVEN value requires every required packet
   field and must not rest on base-anchor mentions alone; representative
   proof without downgrade language fails.

3. Parent-lane closure guard (markdown): the universal parent lanes may not
   be assigned a closed-class status in any tracked markdown without a
   fully-fielded UNIVERSAL_TICKER_AGNOSTIC_PROVEN packet in the same file.

Wired into `enforce_all_rules --objective-audit` (same pattern as
STACK_SCOPE_CLOSURE_GOVERNANCE_LOCK_V1 / check_lane_closure_scopes).

Schwab CSV authority checked: yes
CSV row(s): NO_SCHWAB_EQUIVALENT — governance universality accounting only;
  no market field read, derivation, emission, or actionability logic.
Derived-field disposition: none required.
All consumers checked: yes — read-only governance validation.
SCHWAB_CSV_CHECKED
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_ANCHOR_TICKERS: tuple[str, ...] = ("SPY", "QQQ", "IWM")

# Operator-required minimum literal set (UNIVERSAL_TICKER_MECHANICAL_LOCK_V1).
LOCKED_TICKER_LITERALS: frozenset[str] = frozenset(
    {
        "SPY", "QQQ", "IWM",
        "NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA", "GOOGL", "AVGO",
        "PLTR", "$SPX", "SPX", "CIFR", "MRVL",
    }
)

UNIVERSALITY_CLASSIFICATIONS: tuple[str, ...] = (
    "UNIVERSAL_TICKER_AGNOSTIC_PROVEN",
    "BASE_ANCHOR_EVIDENCED_ONLY",
    "SUPPORTED_UNIVERSE_PARTIAL",
    "REPRESENTATIVE_ONLY_NOT_PROVEN",
    "INSUFFICIENT_UNIVERSE_EVIDENCE",
)

# ── UNIVERSAL_SENTINEL_PROOF_LANGUAGE_LOCK_V1 (operator-approved 2026-07-08) ──
# SPY/QQQ/IWM are RTH sentinel anchors ONLY — live money-path observation under
# real market load, never the proof boundary. Sentinel/base-anchor/
# representative runtime evidence may NEVER be used as universal closure.
# Required lane ladder instead:
#   <LANE> = UNIVERSAL_BY_CONSTRUCTION_STATIC_PROVEN / REMOTE_CI_PROVEN /
#            RTH_SENTINEL_REPROOF_PENDING
#   ...after sentinel success...
#   <LANE> = ... / RTH_SENTINEL_OBSERVED / FULL_UNIVERSAL_RUNTIME_PROVEN_NOT_CLAIMED
# Prose phrases match case-insensitively; ALL-CAPS tokens match exactly.
FORBIDDEN_CLOSURE_PHRASES_PROSE: tuple[str, ...] = (
    "base-anchor runtime proven",
    "representative runtime proven",
    "SPY/QQQ/IWM proven therefore universal",
    "money-path proven therefore closed",
    "full runtime proven from sentinel-only observation",
)
FORBIDDEN_CLOSURE_TOKENS: tuple[str, ...] = (
    "BASE_ANCHOR_RUNTIME_PROVEN",
    "RUNTIME_PROVEN_BASE_ANCHOR",
    "REPRESENTATIVE_RUNTIME_PROVEN",
    "BASE_ANCHOR_PROVEN",
    "SPY_QQQ_IWM_PROVEN_THEREFORE_UNIVERSAL",
    "SENTINEL_PROVEN_THEREFORE_UNIVERSAL",
)
RTH_SENTINEL_LADDER: tuple[str, ...] = (
    "UNIVERSAL_BY_CONSTRUCTION_STATIC_PROVEN",
    "REMOTE_CI_PROVEN",
    "RTH_SENTINEL_REPROOF_PENDING",
    "RTH_SENTINEL_OBSERVED",
    "FULL_UNIVERSAL_RUNTIME_PROVEN_NOT_CLAIMED",
    "CARD_FIDELITY_OVERALL_NOT_PROVEN",
    "REAL_MONEY_READINESS_NOT_PROVEN",
)


def check_sentinel_closure_language(text: str, relpath: str) -> list[str]:
    """Reject sentinel/base-anchor/representative evidence used as closure."""
    errors: list[str] = []
    low = text.lower()
    for ph in FORBIDDEN_CLOSURE_PHRASES_PROSE:
        if ph.lower() in low:
            errors.append(
                f"{relpath}: forbidden sentinel-closure phrase {ph!r} — "
                f"SPY/QQQ/IWM are RTH sentinels, never the proof boundary; "
                f"use the RTH_SENTINEL ladder ({' / '.join(RTH_SENTINEL_LADDER[:3])} ...)"
            )
    for tok in FORBIDDEN_CLOSURE_TOKENS:
        if tok in text:
            errors.append(
                f"{relpath}: forbidden sentinel-closure token {tok!r} — "
                f"use RTH_SENTINEL_OBSERVED / FULL_UNIVERSAL_RUNTIME_PROVEN_NOT_CLAIMED"
            )
    return errors

# ── REPO_WIDE_UNIVERSALITY_HARDGATE_V1 (operator P0, 2026-07-07) ─────────────
# Universality is repo-wide, not ticker-only. Universal means: not one ticker,
# route, card, horizon, timeframe, session state, expiry/cache key, data
# source, DB table, model path, UI surface, happy-path fixture, or
# representative sample. A lane may close only if it proves universal behavior
# across the affected universe, or explicitly classifies itself as
# partial/subset/not-proven.
REPO_UNIVERSALITY_CLASSIFICATIONS: tuple[str, ...] = (
    "UNIVERSAL_BEHAVIOR_PROVEN",
    "UNIVERSAL_BY_CONSTRUCTION_WITH_MECHANICAL_LOCK",
    "SUBSET_EVIDENCED_ONLY",
    "REPRESENTATIVE_ONLY_NOT_PROVEN",
    "PARTIAL_UNIVERSE_PROVEN",
    "INSUFFICIENT_UNIVERSE_EVIDENCE",
    "EXCEPTION_APPROVED_WITH_SCOPE",
)

REPO_REQUIRED_PACKET_FIELDS: tuple[str, ...] = (
    "AFFECTED_UNIVERSE_ENUMERATED",
    "SUBSET_TESTED",
    "UNIVERSAL_CONSTRUCTION_PROOF",
    "MECHANICAL_LOCK_OR_TEST_PROOF",
    "EXCEPTIONS_AND_LIMITATIONS",
    "REPRESENTATIVE_ONLY_STATUS",
    "PARENT_LANE_CLOSURE_STATUS",
    "UNIVERSALITY_CLASSIFICATION",
)

# Universe dimensions a packet's AFFECTED_UNIVERSE_ENUMERATED should draw from
# (documentation vocabulary — the mechanical check enforces field presence).
UNIVERSE_DIMENSIONS: tuple[str, ...] = (
    "tickers",
    "routes/endpoints",
    "ui_cards/surfaces",
    "horizons",
    "timeframes",
    "session_states",
    "expiries/cache_keys",
    "data_sources",
    "db_tables/columns",
    "model_paths/horizons/features",
    "operator_trust_states",
    "failure_modes",
    "user_roles/modes",
)

# Repo classification values that assert universality and therefore demand the
# full repo-wide packet.
_REPO_PROVEN_CLASSIFICATIONS = (
    "UNIVERSAL_BEHAVIOR_PROVEN",
    "UNIVERSAL_BY_CONSTRUCTION_WITH_MECHANICAL_LOCK",
)

# Forbidden universal language when used as a claim: any of these tokens in a
# packet demands a repo-proven classification with every required field.
_UNIVERSAL_CLAIM_RE = re.compile(
    r"(?i)\buniversal(?:ly)?\s+(?:closure|closed|proven)\b"
    r"|=\s*UNIVERSAL_BEHAVIOR_PROVEN\b"
    r"|=\s*UNIVERSAL_BY_CONSTRUCTION_WITH_MECHANICAL_LOCK\b"
    r"|\b(?:route|card|horizon|session|timeframe)-universal\b"
    r"|\ball-session\s+closure\b"
    r"|\bdata-layer\s+closure\b"
    r"|\bmodel-stack\s+closure\b"
)

REQUIRED_PACKET_FIELDS: tuple[str, ...] = (
    "TICKER_UNIVERSE_ENUMERATED",
    "BASE_ANCHOR_MATRIX_SPY_QQQ_IWM",
    "SUPPORTED_UNIVERSE_MATRIX_OR_REASON_NOT_AVAILABLE",
    "GUEST_TICKER_PROOF",
    "TICKER_AGNOSTIC_CONSTRUCTION_PROOF",
    "TICKER_LITERAL_SEARCH_OUTPUT",
    "CONFIRMATION_NO_TICKER_SPECIAL_CASES",
    "UNIVERSALITY_CLASSIFICATION",
)

# Universal parent lanes: closed-class assignment is guarded everywhere.
GUARDED_PARENT_LANES: tuple[str, ...] = (
    "CARD_FIDELITY_OVERALL",
    "MODEL_REAL_MONEY_EDGE",
    "UNIVERSAL_RUNTIME_LIVE_PROOF",
    "REAL_MONEY_READINESS",
)

# Closed-class value tokens. NOT_PROVEN / NOT_CLOSED / NOT_APPROVED never match
# because the negative token is checked first.
_CLOSED_CLASS_RE = re.compile(
    r"(?P<lane>" + "|".join(GUARDED_PARENT_LANES) + r")\s*[=:]\s*(?P<value>[A-Z_]+)"
)
_NEGATIVE_VALUE_PREFIXES = ("NOT_", "PENDING", "QUEUED", "HOLD", "IN_PROGRESS")
_CLOSED_CLASS_VALUES = ("PROVEN", "CLOSED", "COMPLETE", "PASS", "APPROVED", "MET")

_CLASSIFICATION_RE = re.compile(
    r"UNIVERSALITY_CLASSIFICATION\s*[=:]?\s*`?(?P<value>[A-Z_]+)`?"
)

# Non-production surfaces for the literal scan: tests, tooling, governance
# inventories/registers, docs, research/scratch collateral, verification
# harnesses. Everything else tracked as *.py is production/runtime for this
# lock.
NON_PRODUCTION_PREFIXES: tuple[str, ...] = (
    "tests/",
    "tools/",
    "governance/",
    "docs/",
    "reports/",
    "research/",
    "arch_competition/",
    "v2_decision/research",
    "mocks/",
    "scratch",
    "verification/",
)

# Diagnostic / probe / validation CLI scripts (by basename pattern): operator
# entrypoints whose ticker literals are run arguments or probe examples, not
# decision logic. Production modules never match these prefixes.
DIAGNOSTIC_BASENAME_PREFIXES: tuple[str, ...] = (
    "verify_",
    "validate_",
    "check_",
    "audit_",
    "compare_",
    "probe_",
    "test_",
    "run_",
    "build_",
    "schwab_full_field_inventory",
)

# ── Allowlist: (relpath, function name, literal) -> rationale ────────────────
# Every row is a governed exception: a pre-existing in-function ticker literal
# verified by Read at lock time (2026-07-07). New rows require operator
# approval with rationale. Config lists at module level never need rows here
# (allowed by construction). Known granularity limit: the key is
# (file, function, literal), so a second occurrence of the same literal in the
# same function is accepted by the same row — new literals in other functions
# or new ticker symbols always fail.
TICKER_LITERAL_ALLOWLIST: dict[tuple[str, str, str], str] = {
    ("feature_contracts.py", "build_current_xgb_engineered_features", "SPY"): (
        "Synthetic single-row probe for feature-NAME enumeration (train/infer "
        "parity); the literal is a placeholder value, no decision output."
    ),
    ("governed_stack_contract.py", "resolve_guest_anchor_route", "SPY"): (
        "Guest→anchor routing authority: SPY IS the governed broad-market "
        "anchor target; routing to named anchors is this contract's purpose."
    ),
    ("governed_stack_contract.py", "resolve_guest_anchor_route", "IWM"): (
        "Guest→anchor routing authority: IWM IS the governed small-cap anchor "
        "target for Russell-2000 sample holdings."
    ),
    ("market_context.py", "fetch_market_context", "SPY"): (
        "Market-context definition: the index trio SPY/QQQ/IWM constitutes "
        "the cross-market context product surface, not per-ticker decisions."
    ),
    ("market_context.py", "fetch_market_context", "QQQ"): (
        "Market-context definition (see SPY row)."
    ),
    ("market_context.py", "fetch_market_context", "IWM"): (
        "Market-context definition (see SPY row)."
    ),
    ("market_context.py", "confluence_quote_rows_from_context", "SPY"): (
        "Persists the same context-trio quote rows fetch_market_context "
        "defines; context persistence, not decision logic."
    ),
    ("market_context.py", "confluence_quote_rows_from_context", "QQQ"): (
        "Context-trio persistence (see SPY row)."
    ),
    ("market_context.py", "confluence_quote_rows_from_context", "IWM"): (
        "Context-trio persistence (see SPY row)."
    ),
    ("ml_predict.py", "_apply_5c_xgb_plus_transformer_isotonic_calibration", "SPY"): (
        "GOVERNED PRE-EXISTING PRODUCT DECISION with a universality smell: "
        "SPY-only 5c isotonic runtime calibration (maps fit on SPY validation "
        "cohort). Flagged as a universality-review candidate — removal or "
        "per-ticker generalization is model work, not lock work."
    ),
    ("ml_train.py", "probe_training_feature_row", "SPY"): (
        "Synthetic single-row probe for tabular feature-name enumeration; "
        "placeholder value only."
    ),
    ("planes/l1_runtime.py", "input_fingerprint_materially_changed", "SPY"): (
        "Empty-ticker fallback default ((ticker or '').upper() or 'SPY'); no "
        "ticker-conditional branch — all tickers share the same engine."
    ),
    ("planes/l1_thresholds.py", "resolve_l1_materiality_engine", "SPY"): (
        "Empty-ticker fallback default (same pattern as l1_runtime row)."
    ),
    ("server.py", "_fetch_state", "SPY"): (
        "Context/diagnostic uses only, verified by Read 2026-07-07: index-trio "
        "sector-strength context group (~:5990), model-health dashboard "
        "preferred-ticker selection from arch_state keys (~:7400/:7404). No "
        "per-ticker decision branch."
    ),
    ("server.py", "_fetch_state", "QQQ"): (
        "Index-trio context group + dashboard ticker preference (see SPY row)."
    ),
    ("server.py", "_fetch_state", "IWM"): (
        "Index-trio context group + dashboard ticker preference (see SPY row)."
    ),
    ("server.py", "_fetch_state", "NVDA"): (
        "Snapshot persistence column mapping (nvda_chg_pct ← constituent map); "
        "schema-fixed context columns, not decision logic."
    ),
    # FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1 (2026-07-08): the snapshot persistence
    # block moved verbatim into the nested _post_publish_persistence_tail inside
    # _fetch_state. Same eight schema-fixed context-column literals, same
    # rationale; the scanner attributes nested-def constants to both the outer
    # and the nested FunctionDef, so both key shapes carry rows.
    ("server.py", "_post_publish_persistence_tail", "NVDA"): (
        "Relocated snapshot context-column mapping (see _fetch_state NVDA row)."
    ),
    ("server.py", "_post_publish_persistence_tail", "AAPL"): (
        "Relocated snapshot context-column mapping (see _fetch_state NVDA row)."
    ),
    ("server.py", "_post_publish_persistence_tail", "MSFT"): (
        "Relocated snapshot context-column mapping (see _fetch_state NVDA row)."
    ),
    ("server.py", "_post_publish_persistence_tail", "AMZN"): (
        "Relocated snapshot context-column mapping (see _fetch_state NVDA row)."
    ),
    ("server.py", "_post_publish_persistence_tail", "GOOGL"): (
        "Relocated snapshot context-column mapping (see _fetch_state NVDA row)."
    ),
    ("server.py", "_post_publish_persistence_tail", "AVGO"): (
        "Relocated snapshot context-column mapping (see _fetch_state NVDA row)."
    ),
    ("server.py", "_post_publish_persistence_tail", "META"): (
        "Relocated snapshot context-column mapping (see _fetch_state NVDA row)."
    ),
    ("server.py", "_post_publish_persistence_tail", "TSLA"): (
        "Relocated snapshot context-column mapping (see _fetch_state NVDA row)."
    ),
    ("server.py", "_fetch_state", "AAPL"): ("Snapshot context column mapping (see NVDA row)."),
    ("server.py", "_fetch_state", "MSFT"): ("Snapshot context column mapping (see NVDA row)."),
    ("server.py", "_fetch_state", "AMZN"): ("Snapshot context column mapping (see NVDA row)."),
    ("server.py", "_fetch_state", "GOOGL"): ("Snapshot context column mapping (see NVDA row)."),
    ("server.py", "_fetch_state", "AVGO"): ("Snapshot context column mapping (see NVDA row)."),
    ("server.py", "_fetch_state", "META"): ("Snapshot context column mapping (see NVDA row)."),
    ("server.py", "_fetch_state", "TSLA"): ("Snapshot context column mapping (see NVDA row)."),
    ("server.py", "_app_lifespan", "SPY"): (
        "Startup Schwab token validation probe quote — minimal-call symbol, "
        "result discarded beyond auth health."
    ),
    ("server.py", "get_l1_diagnostics", "SPY"): (
        "Diagnostics endpoint sample resolution (SPY vs synthetic penny "
        "fixture) illustrating the adaptive materiality engine; output only."
    ),
    ("similarity_feature_survivorship.py", "default_multi_anchor_set_v1", "SPY"): (
        "Research-anchor seed roster (config-in-function); anchors extend via "
        "extra_tickers parameter."
    ),
    ("similarity_feature_survivorship.py", "default_multi_anchor_set_v1", "QQQ"): (
        "Research-anchor seed roster (see SPY row)."
    ),
    ("similarity_feature_survivorship.py", "discover_tickers_for_survivorship", "SPY"): (
        "Excludes the wave-1 seed tickers from rediscovery; pairs with "
        "default_multi_anchor_set_v1 roster."
    ),
    ("similarity_feature_survivorship.py", "discover_tickers_for_survivorship", "QQQ"): (
        "Wave-1 seed exclusion (see SPY row)."
    ),
}


def _git_tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=str(root),
        check=True,
    ).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def is_production_python(relpath: str) -> bool:
    rp = relpath.replace("\\", "/")
    if not rp.endswith(".py"):
        return False
    if any(rp.startswith(p) for p in NON_PRODUCTION_PREFIXES):
        return False
    base = rp.rsplit("/", 1)[-1]
    return not any(base.startswith(p) for p in DIAGNOSTIC_BASENAME_PREFIXES)


def scan_python_source_for_ticker_literals(
    src: str,
    relpath: str,
    allowlist: Optional[dict[tuple[str, str, str], str]] = None,
) -> list[str]:
    """Locked ticker literals inside function bodies of production Python are
    violations unless allowlisted. Module-level literals (config) are allowed."""
    allow = TICKER_LITERAL_ALLOWLIST if allowlist is None else allowlist
    violations: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"{relpath}: unparseable python ({e})"]
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Signature default values are config defaults (endpoint Query
        # defaults, CLI probe defaults), not decision logic — exempt.
        default_consts: set[int] = set()
        for d in list(node.args.defaults) + [d for d in node.args.kw_defaults if d]:
            for sub in ast.walk(d):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    default_consts.add(id(sub))
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Constant) and isinstance(sub.value, str)):
                continue
            if id(sub) in default_consts:
                continue
            if sub.value not in LOCKED_TICKER_LITERALS:
                continue
            key = (relpath.replace("\\", "/"), node.name, sub.value)
            if key in allow:
                continue
            violations.append(
                f"{relpath}:{sub.lineno} ticker literal {sub.value!r} inside "
                f"function {node.name!r} (production logic must be "
                f"ticker-agnostic; config lists belong at module level; "
                f"allowlist requires operator rationale)"
            )
    return violations


def check_production_ticker_literals(root: Path = ROOT) -> list[str]:
    violations: list[str] = []
    for rel in _git_tracked_files(root):
        if not is_production_python(rel):
            continue
        p = root / rel
        if not p.is_file():
            continue
        violations += scan_python_source_for_ticker_literals(
            p.read_text(encoding="utf-8", errors="replace"), rel
        )
    return violations


def _mentioned_locked_tickers(text: str) -> set[str]:
    found = set()
    for t in LOCKED_TICKER_LITERALS:
        if re.search(r"(?<![A-Z$])" + re.escape(t) + r"(?![A-Z])", text):
            found.add(t)
    return found


def _has_full_ticker_packet(text: str, classification: Optional[str]) -> bool:
    return classification == "UNIVERSAL_TICKER_AGNOSTIC_PROVEN" and all(
        f in text for f in REQUIRED_PACKET_FIELDS
    )


def _has_full_repo_packet(text: str, classification: Optional[str]) -> bool:
    return classification in _REPO_PROVEN_CLASSIFICATIONS and all(
        f in text for f in REPO_REQUIRED_PACKET_FIELDS
    )


def check_packet_text(text: str, relpath: str) -> list[str]:
    """Universality packet rules (ticker contract + repo-wide hardgate)."""
    errors: list[str] = []
    errors += check_sentinel_closure_language(text, relpath)
    m = _CLASSIFICATION_RE.search(text)
    classification = m.group("value") if m else None
    allowed = set(UNIVERSALITY_CLASSIFICATIONS) | set(REPO_UNIVERSALITY_CLASSIFICATIONS)

    if classification is not None and classification not in allowed:
        errors.append(
            f"{relpath}: UNIVERSALITY_CLASSIFICATION {classification!r} not in "
            f"{sorted(allowed)}"
        )
        return errors

    if classification == "UNIVERSAL_TICKER_AGNOSTIC_PROVEN":
        missing = [f for f in REQUIRED_PACKET_FIELDS if f not in text]
        if missing:
            errors.append(
                f"{relpath}: UNIVERSAL_TICKER_AGNOSTIC_PROVEN requires every "
                f"packet field — missing {missing}"
            )
        mentioned = _mentioned_locked_tickers(text)
        if mentioned and mentioned <= set(BASE_ANCHOR_TICKERS):
            if "SUPPORTED_UNIVERSE_MATRIX_OR_REASON_NOT_AVAILABLE" not in text:
                errors.append(
                    f"{relpath}: universal claim rests on base anchors only "
                    f"({sorted(mentioned)}) with no supported-universe matrix "
                    f"or reason — BASE_TICKER_ONLY_CLOSURE is FORBIDDEN"
                )

    # REPO_WIDE_UNIVERSALITY_HARDGATE_V1: proven-universal classifications
    # demand the full repo packet; approved exceptions demand documented scope
    # plus explicit operator approval.
    if classification in _REPO_PROVEN_CLASSIFICATIONS:
        missing = [f for f in REPO_REQUIRED_PACKET_FIELDS if f not in text]
        if missing:
            errors.append(
                f"{relpath}: {classification} requires every repo-wide packet "
                f"field — missing {missing}"
            )
    if classification == "EXCEPTION_APPROVED_WITH_SCOPE":
        for req in ("EXCEPTIONS_AND_LIMITATIONS", "PARENT_LANE_CLOSURE_STATUS"):
            if req not in text:
                errors.append(
                    f"{relpath}: EXCEPTION_APPROVED_WITH_SCOPE requires {req}"
                )
        if not re.search(r"(?i)operator[-_ ]approved", text):
            errors.append(
                f"{relpath}: EXCEPTION_APPROVED_WITH_SCOPE requires explicit "
                f"operator approval language ('operator approved')"
            )

    # Forbidden universal language with subset evidence: any universal-claim
    # token demands a proven repo classification with every required field.
    for i, line in enumerate(text.splitlines(), 1):
        if _UNIVERSAL_CLAIM_RE.search(line):
            if not _has_full_repo_packet(text, classification):
                errors.append(
                    f"{relpath}:{i} universal claim {line.strip()[:80]!r} "
                    f"without a fully-fielded repo-universality packet "
                    f"(UNIVERSAL_BEHAVIOR_PROVEN or UNIVERSAL_BY_CONSTRUCTION_"
                    f"WITH_MECHANICAL_LOCK + all repo fields) — subset/"
                    f"representative evidence cannot make universal claims"
                )
            break

    # Representative-only proof must carry downgrade language.
    for i, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        if "representative" in low and ("proven" in low or "proof" in low):
            if "not_proven" not in low and "REPRESENTATIVE_ONLY_NOT_PROVEN" not in text:
                errors.append(
                    f"{relpath}:{i} representative proof without downgrade "
                    f"language (REPRESENTATIVE_ONLY_NOT_PROVEN required)"
                )

    # Guarded parent lanes: closed-class assignment demands a fully-fielded
    # universal packet (ticker or repo-wide contract) in the same document.
    for i, line in enumerate(text.splitlines(), 1):
        for lane_m in _CLOSED_CLASS_RE.finditer(line):
            value = lane_m.group("value")
            if value.startswith(_NEGATIVE_VALUE_PREFIXES):
                continue
            if not any(value.startswith(cv) for cv in _CLOSED_CLASS_VALUES):
                continue
            if not (
                _has_full_ticker_packet(text, classification)
                or _has_full_repo_packet(text, classification)
            ):
                errors.append(
                    f"{relpath}:{i} parent lane {lane_m.group('lane')} assigned "
                    f"closed-class value {value!r} without a fully-fielded "
                    f"universal packet — child/slice/base/partial evidence "
                    f"cannot close universal parents"
                )
    return errors


def check_universality_packets(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for rel in _git_tracked_files(root):
        rp = rel.replace("\\", "/")
        if not rp.endswith(".md"):
            continue
        if not (rp.startswith("reports/") or rp.startswith("governance/")):
            continue
        p = root / rel
        if not p.is_file():
            continue
        errors += check_packet_text(p.read_text(encoding="utf-8", errors="replace"), rel)
    return errors


def run_check(root: Path = ROOT) -> dict[str, Any]:
    errors = check_production_ticker_literals(root) + check_universality_packets(root)
    return {"ok": not errors, "errors": errors}


def main() -> int:
    result = run_check()
    if not result["ok"]:
        print("check_universal_ticker_lock: FAIL", file=sys.stderr)
        for e in result["errors"]:
            print(f"- {e}", file=sys.stderr)
        return 1
    print(
        "check_universal_ticker_lock: PASS "
        "(UNIVERSAL_TICKER_MECHANICAL_LOCK_V1 — no in-function ticker literals "
        "outside the governed allowlist; universality packets consistent; "
        "universal parent lanes not closed on base/partial evidence)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
