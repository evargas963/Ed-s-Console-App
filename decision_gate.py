"""Decision-path admission gate (charter, AGENTS.md §Decision-path admission).

No component may influence TRADE — or any output that authorizes or shapes
exposure — unless ``governance/decision_path_admissions.json`` records it
ADMITTED with evidence (preregistration, OOS results, costs, baselines, scope,
leakage review) and an operator admission decision.

The registry starts empty. Fail-closed by construction: a missing, unreadable,
malformed, or schema-mismatched registry admits nothing, and every failure mode
carries a human-readable detail string so the WAIT shown to the operator says
exactly why. The single production consumer is ``call_engine.compute_call``,
which forces the final signal to ``wait`` when this module does not admit the
decision path.

Registry contract (schema_version 1):

    {
      "schema_version": 1,
      "admissions": [
        {
          "component": "the_call",
          "status": "ADMITTED",
          "evidence": {
            "preregistration": "<experiment registration ref>",
            "oos_results": "<out-of-sample results ref>",
            "costs": "<cost-aware evaluation ref>",
            "baselines": "<trivial-baseline comparison ref>",
            "scope": "<tickers/horizons/sessions covered>",
            "leakage_review": "<causal/leakage review ref>"
          },
          "operator_decision": {"date": "YYYY-MM-DD", "decided_by": "operator"}
        }
      ]
    }

Every evidence field must be a non-empty string; ``operator_decision`` must
carry non-empty ``date`` and ``decided_by``. Anything less is not an admission.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

# The component that authorizes directional exposure: the final Call.
DECISION_PATH_COMPONENT = "the_call"

REQUIRED_EVIDENCE_FIELDS = (
    "preregistration",
    "oos_results",
    "costs",
    "baselines",
    "scope",
    "leakage_review",
)
REQUIRED_OPERATOR_DECISION_FIELDS = ("date", "decided_by")

_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent / "governance" / "decision_path_admissions.json"

# Registry states (AdmissionVerdict.registry_state vocabulary).
STATE_ADMITTED = "admitted"
STATE_EMPTY = "empty"
STATE_MISSING = "missing"
STATE_INVALID = "invalid"
STATE_NOT_ADMITTED = "not_admitted"


@dataclass(frozen=True)
class AdmissionVerdict:
    admitted: bool
    registry_state: str  # admitted | empty | missing | invalid | not_admitted
    detail: str


def registry_path() -> Path:
    """Resolve the admissions registry path (env override for tests/ops)."""
    override = os.environ.get("ED_DECISION_ADMISSIONS_PATH")
    if override is not None and override.strip():
        return Path(override.strip())
    return _DEFAULT_REGISTRY_PATH


def _record_admits(record: object, component: str) -> tuple[bool, str]:
    """One registry record → (admits component, reason when it does not)."""
    if not isinstance(record, dict):
        return False, "record is not an object"
    if str(record.get("component") or "").strip() != component:
        return False, f"record is for component {record.get('component')!r}"
    if str(record.get("status") or "").strip() != "ADMITTED":
        return False, f"status is {record.get('status')!r}, not ADMITTED"
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        return False, "evidence block missing"
    missing = [
        f for f in REQUIRED_EVIDENCE_FIELDS
        if not (isinstance(evidence.get(f), str) and evidence.get(f).strip())
    ]
    if missing:
        return False, f"evidence incomplete: missing {', '.join(missing)}"
    decision = record.get("operator_decision")
    if not isinstance(decision, dict):
        return False, "operator_decision missing"
    missing_dec = [
        f for f in REQUIRED_OPERATOR_DECISION_FIELDS
        if not (isinstance(decision.get(f), str) and decision.get(f).strip())
    ]
    if missing_dec:
        return False, f"operator_decision incomplete: missing {', '.join(missing_dec)}"
    return True, ""


def evaluate_decision_path_admission(
    component: str = DECISION_PATH_COMPONENT,
    *,
    path: Path | None = None,
) -> AdmissionVerdict:
    """Is ``component`` ADMITTED to authorize exposure? Fail-closed on every error."""
    p = path if path is not None else registry_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return AdmissionVerdict(
            False, STATE_MISSING,
            f"admissions registry not found at {p.name} — nothing is admitted; system abstains (WAIT)",
        )
    except OSError as exc:
        return AdmissionVerdict(
            False, STATE_INVALID,
            f"admissions registry unreadable ({exc.__class__.__name__}) — nothing is admitted; system abstains (WAIT)",
        )
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        return AdmissionVerdict(
            False, STATE_INVALID,
            f"admissions registry is not valid JSON (line {exc.lineno}) — nothing is admitted; system abstains (WAIT)",
        )
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        return AdmissionVerdict(
            False, STATE_INVALID,
            f"admissions registry schema_version != {SCHEMA_VERSION} — nothing is admitted; system abstains (WAIT)",
        )
    admissions = doc.get("admissions")
    if not isinstance(admissions, list):
        return AdmissionVerdict(
            False, STATE_INVALID,
            "admissions registry 'admissions' is not a list — nothing is admitted; system abstains (WAIT)",
        )
    if not admissions:
        return AdmissionVerdict(
            False, STATE_EMPTY,
            "admissions registry is empty — no component has proven edge; system abstains (WAIT) by charter",
        )
    reasons: list[str] = []
    for record in admissions:
        ok, why = _record_admits(record, component)
        if ok:
            return AdmissionVerdict(
                True, STATE_ADMITTED,
                f"component {component!r} ADMITTED with complete evidence and operator decision",
            )
        reasons.append(why)
    return AdmissionVerdict(
        False, STATE_NOT_ADMITTED,
        f"no valid admission for component {component!r} ({'; '.join(reasons[:3])}) — system abstains (WAIT)",
    )
