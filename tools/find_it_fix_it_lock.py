"""FIND IT → FIX IT lock (RC-452 / RC-453 / RC-480).

ONE unresolved-work authority: ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md.
RC log is historical evidence only. It does not create, classify, promote, defer,
or close obligations, and it does not determine Stop eligibility.

Actionable obligation state is derived from the sole master (REQ comments +
checkbox STATUS=FAIL/NOT_PROVEN) plus second-list / unfinished-disposition
controls. RC CLASS:ACTIVE / CLASS:PASSIVE is not work-state.

Required transitions (mechanical) apply to sole-master REQ execution= and
checkbox STATUS=, not to RC CLASS: tokens:
  NEW MATERIAL DISCOVERY → ACTIVE on the sole master (not PASSIVE)
  PASSIVE + implicated by active mission → ACTIVE on the sole master
  ACTIVE → PASSIVE is illegal merely to permit Stop.

A syntactically valid but incomplete presented active view BLOCKS (omission
negative control). If governance/active_defects.json exists it is a derived
view only and must not act as a second authority.

Hard blockers require type evidence. Self-authored turn-budget / blast-radius
/ next-pass language is never a blocker.

Remediation requires more than an RC id + nonempty command string: the cited
command must name an existing path that exercises the defect's FIXED scope.

Called by check_find_it_fix_it (commit) and tools/stop_guard.py (Stop) — one
authority, cannot diverge.
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parent.parent
RC_LOG = REPO / "governance" / "root_cause_log.md"
PM_MISSION_PATH = REPO / "governance" / "pm_mission.json"
ACTIVE_DEFECTS_PATH = REPO / "governance" / "active_defects.json"
REQUIREMENT_TREE_PATH = REPO / "governance" / "requirement_tree.json"
SOLE_MASTER_REL = "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md"
SOLE_MASTER_PATH = REPO / SOLE_MASTER_REL

_UNRESOLVED_BOX = re.compile(r"(?m)^\s*[-*]\s+\[\s\]\s+")
_UNRESOLVED_MARK = re.compile("UNRESOLVED_WORK_ITEM" + r"\s*:", re.I)
# Vendor/generated only. Historical evidence prefixes are still searched; they
# may not host a live second queue (magic marker or ID/Status/Work table).
_SECOND_LIST_VENDOR_PREFIX = (
    "node_modules/",
    ".venv/",
    "__pycache__/",
)
# reports/ + tests/ may hold evidence or fixtures. docs/, .claude/, and .cursor/
# are scanned for live queues — historical-looking paths are not a hide.
_SECOND_LIST_HISTORICAL_PREFIX = (
    "reports/",
    "tests/",
    "governance/register_slices/",
    "governance/archive/",
    "governance/design_history/",
)
_SECOND_LIST_TEXT_EXT = frozenset({
    ".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml",
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".html", ".htm", ".css", ".scss", ".less",
    ".sql", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".cfg", ".ini", ".xml", ".csv", ".mdc", ".jsonl",
})
_QUEUE_TABLE_HEADER = re.compile(
    r"(?im)^\|\s*ID\s*\|\s*Status\s*\|\s*Work(?: item)?\s*\|"
)

PARENT_MISSION_TOKENS = (
    "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1",
    "FIND IT → FIX IT",
    "FIND IT -> FIX IT",
)

VALID_BLOCKER_TYPES = frozenset({
    "RTH_ONLY",
    "EXTERNAL_DATA_UNAVAILABLE",
    "DESTRUCTIVE_APPROVAL_REQUIRED",
    "ENVIRONMENT_BLOCKED",
})

BANNED_BLOCKER_PHRASES = (
    "turn budget",
    "remaining budget",
    "token budget",
    "too large",
    "large blast radius",
    "many files",
    "many models",
    "atomic migration",
    "too much work",
    "next pass",
    "next turn",
)

_RTH_PROBE_MARKERS = (
    "time_et",
    "is_rth",
    "is_trading_day",
    "rth_only",
    "09:30",
    "16:00",
)

_UNAVAILABLE_MARKERS = (
    "unavailable",
    "401",
    "403",
    "404",
    "timeout",
    "connection refused",
    "no such host",
    "dns",
    "errno",
    "econnrefused",
)

_UNIMPLEMENTED_MARKERS = (
    "not implemented",
    "unimplemented",
    "todo",
    "coming soon",
)

_MATERIAL_DECL = re.compile(
    r"(?:MATERIAL_DEFECT|DISCOVERED_DEFECT)\s*:\s*(RC-\d+|[A-Za-z][\w.-]{7,80})",
    re.I,
)
# Explicit unfinished dispositions (RC-468). Magic MATERIAL_DEFECT tokens are not
# required. An agent that writes these and then Stops is still under FIND IT → FIX IT.
_REMAINING_ACTIVE_HEADER = re.compile(
    r"REMAINING\s+ACTIVE(?:\s+PARENT)?\s+DEFECTS\b",
    re.I,
)
_QUEUED_DISPOSITION_LINE = re.compile(
    r"^(?P<line>[^\n]{0,240}(?:—\s*)?\bQUEUED\b(?:\s*—|\s*:|\s+\(|\s*$|\s+—)[^\n]*)$",
    re.I | re.M,
)
_NEXT_DISPOSITION_LINE = re.compile(
    r"^(?P<line>[^\n]{0,120}(?:^|[\s—\-•*])\bNEXT\s*[:—\-][^\n]*)$",
    re.I | re.M,
)
_QUEUED_FALSE_POSITIVE = re.compile(
    r"message queue|queuedMessage|queued messages|in the queue|queue length|job queue",
    re.I,
)
_NEXT_FALSE_POSITIVE = re.compile(
    r"NEXT_RTH|next RTH|next-rth|# next-rth-ok",
    re.I,
)
_LINE_HARD_BLOCKED = re.compile(
    r"HARD_BLOCKER\s*:|"
    r"\bENVIRONMENT_BLOCKED\b|"
    r"\bEXTERNAL_DATA_UNAVAILABLE\b|"
    r"\bDESTRUCTIVE_APPROVAL_REQUIRED\b|"
    r"(?<![A-Z_])RTH_ONLY(?![A-Z_])",
    re.I,
)
_NONE_REMAINING = re.compile(
    r"^(?:[-*•]|\d+\.)?\s*(?:none|n/a|no remaining|all remediated|no active)\b",
    re.I,
)
# RC-471: calling an ACTIVE FAIL/NOT_PROVEN parent "proof state" / "not queued"
# is not a legal Stop. Vocabulary cannot convert a fixable parent into a leftover.
_PROOF_STATE_LAUNDER = re.compile(
    r"proof[\s-]+state.{0,160}not.{0,80}queued"
    r"|not\s+a\s+queued\s+leftover"
    r"|proof\s+state,\s+not\s+queued",
    re.I | re.S,
)
_TURN_IMPLICATE_NEAR = re.compile(
    r"(?:implicat|remaining\s+active|QUEUED|KEEP FIXING|"
    r"still (?:open|broken|wrong|unfixed|active)|"
    r"must fix|discovered|this mission|ACTIVE (?:PARENT )?DEFECT)",
    re.I,
)
_PARENT_SCOPE = re.compile(
    r"\b(end-to-end|universal|parent|all models|all tickers|operable surface)\b",
    re.I,
)
_CHILD_TEST = re.compile(
    r"(spy|qqq|iwm|chunk\d|one_route|single_ticker)",
    re.I,
)

_SNAKE_ASSERTION = re.compile(r"^[a-z][a-z0-9_]{3,80}$")
_RC_ID = re.compile(r"^RC-\d+$")
_BACKTICK_CMD = re.compile(r"`([^`]+)`")
_HARD_BLOCKER_RE = re.compile(
    r"HARD_BLOCKER:\s*(?P<body>.+?)(?:\s{2,}|$)",
    re.I,
)
_CLASS_RE = re.compile(r"CLASS:(ACTIVE|PASSIVE|CLOSED)\b", re.I)
_PATH_TOKEN_RE = re.compile(
    r"(?:^|[\s`\"'(])((?:tools|tests|governance|static|features|planes|research|"
    r"calibration|v2_decision)/[\w./-]+\.[\w]+|[\w.-]+\.py)(?:$|[\s`\"')])"
)


def _load_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _parse_rc_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        rows.append({
            "id": cells[0],
            "status": cells[1].upper(),
            "opened": cells[2],
            "due": cells[3],
            "defect": cells[4],
            "why": cells[5],
            "fix": cells[6],
            "line": line,
        })
    return rows


def _row_text(row: dict[str, str]) -> str:
    return " ".join(row.get(k, "") for k in ("defect", "why", "fix", "line"))


def _declared_class(row: dict[str, str]) -> str | None:
    m = _CLASS_RE.search(_row_text(row))
    return m.group(1).upper() if m else None


def _paths_in_text(text: str) -> set[str]:
    return {m.group(1) for m in _PATH_TOKEN_RE.finditer(text or "")}


def _mission() -> dict:
    return _load_json(PM_MISSION_PATH)


def _dirty_paths(repo: Path | None = None) -> list[str]:
    try:
        from tools.writer_drift_lock import git_changed_paths
    except ImportError:
        from writer_drift_lock import git_changed_paths  # type: ignore
    return git_changed_paths(repo or REPO, staged_only=False)


_PROCESS_LOCK_DIRTY = (
    "tools/check_institutional_correctness.py",
    "tools/find_it_fix_it_lock.py",
    "tools/requirement_proof.py",
    "tools/writer_drift_lock.py",
    "tools/operating_process_lock.py",
    "tools/process_lock_guard.py",
    "tools/stop_guard.py",
    "tools/pretooluse_guard.py",
    "tools/rehab_daily_scan.py",
    "governance/root_cause_log.md",
    "governance/sole_writer.json",
    "governance/pm_mission.json",
    "governance/AGENT_OPERATING_PROCESS_V1.md",
    "governance/PM_MANDATE.md",
    "governance/REHAB_PROGRAM.md",
    "AGENTS.md",
    "CLAUDE.md",
)


def _material_dirty(dirty: Iterable[str]) -> set[str]:
    """Process-lock edits do not implicate the historical backlog (omission still binds)."""
    out: set[str] = set()
    for p in dirty:
        rel = p.replace("\\", "/").strip()
        if not rel:
            continue
        if rel in _PROCESS_LOCK_DIRTY:
            continue
        if rel.startswith("tests/test_") and (
            "lock" in rel or "writer_drift" in rel or "find_it_fix" in rel
        ):
            continue
        if rel.startswith(".cursor/") or rel.startswith(".claude/") or rel.startswith("governance/"):
            continue
        out.add(rel)
    return out


# Mega surfaces named in almost every historical display/collect row. Path-string
# coincidence on these files does not, by itself, activate the historical backlog
# (RC-466). Narrow module paths still activate PASSIVE → ACTIVE. Mission-tagged /
# opened-today / CLASS:ACTIVE rows still activate. A wide-surface row that the
# current turn explicitly implicates (RC id + implication language) also activates.
_WIDE_SURFACES_NO_AUTO_IMPLICATE = frozenset({
    "static/chart.html",
    "static/index.html",
    "server.py",
    "db.py",
})


def _assistant_scan_text(payload: dict | None) -> str:
    """Assistant-authored text only. User/operator packets must not self-trigger."""
    if not payload:
        return ""
    parts: list[str] = []
    for k in ("last_assistant_text", "assistant_text", "response_text"):
        v = payload.get(k)
        if v:
            parts.append(str(v))
    if parts:
        return "\n".join(parts)
    tp = payload.get("transcript_path")
    if not tp:
        return ""
    try:
        from tools.proof_only_guard import last_assistant_text
        t = last_assistant_text(str(tp))
    except Exception:
        return ""
    return t or ""


def _turn_implicates_row(row: dict[str, str], payload: dict | None) -> bool:
    """Current-turn discovery/implication of a specific RC — not path coincidence."""
    rid = (row.get("id") or "").strip()
    if not rid or not payload:
        return False
    text = _assistant_scan_text(payload)
    if not text or rid not in text:
        return False
    for m in re.finditer(re.escape(rid), text):
        window = text[max(0, m.start() - 120): m.end() + 160]
        if _TURN_IMPLICATE_NEAR.search(window):
            return True
    return False


def _path_implicated(row_paths: set[str], dirty: Iterable[str], scope: Iterable[str]) -> bool:
    """Narrow-module dirty-path match only. Wide-surface coincidence never implicates."""
    dirty_n = _material_dirty(dirty)
    if not dirty_n:
        return False
    for rp in row_paths:
        if rp in _WIDE_SURFACES_NO_AUTO_IMPLICATE:
            continue
        if rp in dirty_n:
            return True
        for d in dirty_n:
            if d in _WIDE_SURFACES_NO_AUTO_IMPLICATE:
                continue
            if d.startswith(rp.rstrip("/") + "/") or rp.startswith(d.rstrip("/") + "/"):
                return True
        # Scope overlap alone does not activate the backlog — only dirty product paths.
    return False


def classify_row(
    row: dict[str, str],
    *,
    today: str,
    mission: dict | None = None,
    dirty_paths: Iterable[str] | None = None,
    payload: dict | None = None,
) -> str:
    """Return CLOSED | ACTIVE | PASSIVE for one RC row."""
    status = (row.get("status") or "").upper()
    if status in ("CLOSED",):
        return "CLOSED"
    declared = _declared_class(row)
    if declared == "CLOSED" and status in ("CLOSED",):
        return "CLOSED"
    mission = mission if mission is not None else _mission()
    mid = str(mission.get("mission_id") or "")
    body = _row_text(row)
    dirty = list(dirty_paths) if dirty_paths is not None else _dirty_paths()
    scopes = mission.get("scope_paths") or []
    if not isinstance(scopes, list):
        scopes = []
    # Implication reads the DEFECT headline only — a 4k-char why/fix cell naming a file
    # as past evidence is not "materially implicated by the active change".
    headline = (row.get("defect") or "")[:320]
    implicated = _path_implicated(_paths_in_text(headline), dirty, scopes)
    opened_today = row.get("opened") == today
    mission_tagged = bool(mid) and mid in body
    parent_tagged = any(tok in body for tok in PARENT_MISSION_TOKENS)
    if opened_today or mission_tagged or parent_tagged or implicated or declared == "ACTIVE":
        return "ACTIVE"
    if _turn_implicates_row(row, payload):
        return "ACTIVE"
    if declared == "PASSIVE":
        return "PASSIVE"
    # Historical OPEN/PARTIAL with no implication — passive backlog, does not block.
    return "PASSIVE"


def derive_active_obligations(
    rc_text: str,
    *,
    today: str | None = None,
    mission: dict | None = None,
    dirty_paths: Iterable[str] | None = None,
    payload: dict | None = None,
) -> list[dict[str, str]]:
    """RC log has zero execution authority — never returns work-state rows."""
    return []


def illegal_passive_escape_offenders(
    rc_text: str,
    *,
    today: str | None = None,
    mission: dict | None = None,
    dirty_paths: Iterable[str] | None = None,
    payload: dict | None = None,
) -> list[tuple[str, str]]:
    """RC CLASS:PASSIVE is not work-state. Returns empty."""
    return []


def _parse_hard_blocker(fix: str) -> dict[str, str] | None:
    m = _HARD_BLOCKER_RE.search(fix or "")
    if not m:
        return None
    body = m.group("body").strip()
    if body.startswith("{"):
        try:
            doc = json.loads(body)
            return {str(k): str(v) if not isinstance(v, bool) else v for k, v in doc.items()} if isinstance(doc, dict) else None  # type: ignore[misc]
        except (ValueError, TypeError):
            return None
    fields: dict[str, Any] = {}
    for tok in body.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            fields[k.strip().lower()] = v.strip()
        elif tok.upper() in VALID_BLOCKER_TYPES:
            fields["type"] = tok.upper()
    return fields if fields.get("type") else None


def _banned_blocker_language(text: str) -> str | None:
    low = (text or "").lower()
    for phrase in BANNED_BLOCKER_PHRASES:
        if phrase in low:
            return phrase
    return None


def blocker_evidence_ok(blocker: dict, *, repo: Path | None = None) -> tuple[bool, str]:
    """Type-specific evidence. Self-authored assertions are never enough."""
    repo = repo or REPO
    if not isinstance(blocker, dict) or not blocker:
        return False, "missing HARD_BLOCKER fields"
    typ = str(blocker.get("type") or "").upper()
    if typ not in VALID_BLOCKER_TYPES:
        return False, f"type {typ!r} is not a valid hard blocker"
    blob = json.dumps(blocker, default=str)
    banned = _banned_blocker_language(blob)
    if banned:
        return False, f"{banned!r} is never a hard blocker"
    assertion = str(blocker.get("assertion") or "")
    if not _SNAKE_ASSERTION.fullmatch(assertion):
        return False, "assertion must be exact snake_case (not a subsystem label)"

    if typ == "RTH_ONLY":
        probe = str(blocker.get("probe") or "")
        probe_path = repo / probe
        if not probe or not probe_path.is_file():
            return False, "RTH_ONLY requires an existing probe file path"
        try:
            probe_text = probe_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False, "RTH_ONLY probe file unreadable"
        if assertion not in probe_text:
            return False, "RTH_ONLY probe is not designed to test the named assertion"
        low_probe = probe_text.lower()
        if not any(m.lower() in low_probe for m in _RTH_PROBE_MARKERS):
            return False, (
                "RTH_ONLY probe must actually measure session hours "
                "(time_et / is_rth / is_trading_day) — an arbitrary existing file is not a probe"
            )
        complete = str(blocker.get("non_rth_complete") or blocker.get("non_rth_remediation_complete") or "").lower()
        if complete not in ("1", "true", "yes"):
            return False, "RTH_ONLY requires non_rth_complete=true (deterministic work finished)"
        if not str(blocker.get("rth_observation") or "").strip():
            return False, "RTH_ONLY requires rth_observation naming the remaining live observation"
        return True, "ok"

    if typ == "EXTERNAL_DATA_UNAVAILABLE":
        cap = str(blocker.get("capability") or "").strip()
        src = str(blocker.get("source") or "").strip()
        ev = str(blocker.get("unavailability_evidence") or "").strip()
        if not cap or not src:
            return False, "EXTERNAL_DATA_UNAVAILABLE requires capability= and source="
        ev_path = repo / ev if ev and not ev.startswith("observed:") else None
        ev_text = ""
        if ev_path is not None:
            if not ev_path.is_file():
                return False, "unavailability_evidence path does not exist"
            ev_text = ev_path.read_text(encoding="utf-8", errors="replace")
            if cap not in ev_text and src not in ev_text:
                return False, "evidence file does not name the capability/source"
        elif ev.startswith("observed:"):
            ev_text = ev
        else:
            return False, (
                "EXTERNAL_DATA_UNAVAILABLE requires unavailability_evidence as an existing "
                "path or observed:<machine-failure> — absence from current implementation "
                "is not unavailability"
            )
        low_ev = ev_text.lower()
        if any(m in low_ev for m in _UNIMPLEMENTED_MARKERS) and not any(
            m in low_ev for m in _UNAVAILABLE_MARKERS
        ):
            return False, (
                "EXTERNAL_DATA_UNAVAILABLE evidence shows unimplemented/TODO, not a "
                "genuinely unavailable source"
            )
        if not any(m in low_ev for m in _UNAVAILABLE_MARKERS):
            return False, (
                "EXTERNAL_DATA_UNAVAILABLE requires machine evidence the source is "
                "unavailable (timeout/401/404/connection refused/DNS), not a missing feature"
            )
        return True, "ok"

    if typ == "DESTRUCTIVE_APPROVAL_REQUIRED":
        op = str(blocker.get("operation") or "")
        obj = str(blocker.get("object") or blocker.get("target") or "")
        blob = f"{op} {obj}"
        if not re.search(r"\b(delete|truncate|drop|unlink|rmtree|destroy)\b", blob, re.I):
            return False, "must identify the exact destructive operation"
        if not obj.strip():
            return False, "must name the exact object/data affected"
        if not re.search(r"data/|backups/|models/|ed_console\.db", blob, re.I):
            return False, "destructive operation must name a protected data/models/backups target"
        return True, "ok"

    if typ == "ENVIRONMENT_BLOCKED":
        err = str(blocker.get("observed_error") or "").strip()
        cmd = str(blocker.get("command") or "").strip()
        if not err or not cmd:
            return False, "ENVIRONMENT_BLOCKED requires observed_error= and command="
        banned = _banned_blocker_language(err + " " + cmd)
        if banned:
            return False, f"{banned!r} is never an environment failure"
        if not re.search(
            r"(Error|Exception|E_|exit [1-9]|errno|ConnectionRefused|FileNotFound|OSError|CalledProcessError|ModuleNotFoundError)",
            err,
        ):
            return False, "observed_error must be an observable machine/environment failure"
        return True, "ok"

    return False, "unknown blocker type"


def _remaining_active_items(text: str) -> list[str]:
    items: list[str] = []
    for m in _REMAINING_ACTIVE_HEADER.finditer(text):
        rest = text[m.end():]
        cut = re.search(
            r"\n(?:[A-Z][A-Z0-9 /_\-]{8,}(?:\n|$)|#{1,3}\s|\n---)",
            rest,
        )
        section = rest[:cut.start()] if cut else rest
        for raw in section.splitlines():
            line = raw.strip()
            if not line or re.fullmatch(r"[-*=_]+", line):
                continue
            if _NONE_REMAINING.match(line):
                continue
            items.append(line)
    return items


def _requirement_items(payload: dict | None) -> list[dict[str, Any]]:
    """Requirement rows. Tests may inject payload['_requirement_tree']."""
    raw: Any = None
    if payload and isinstance(payload.get("_requirement_tree"), dict):
        raw = payload["_requirement_tree"]
    else:
        try:
            from tools.requirement_proof import parse_master
            raw = parse_master()
        except Exception:
            try:
                raw = json.loads(REQUIREMENT_TREE_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                return []
    if not isinstance(raw, dict):
        return []
    items = raw.get("items") or raw.get("requirements")
    if not isinstance(items, list):
        return []
    return [i for i in items if isinstance(i, dict) and i.get("id")]


def _is_text_like_work_file(rel_n: str) -> bool:
    suf = Path(rel_n).suffix.lower()
    if suf in _SECOND_LIST_TEXT_EXT:
        return True
    return Path(rel_n).name.lower() in {"makefile", "dockerfile", "gemfile", "procfile"}


def _has_second_queue_table(text: str) -> bool:
    """Operator NOW / standing-queue ID/Status/Work table, with or without a magic marker."""
    if not _QUEUE_TABLE_HEADER.search(text):
        return False
    for ln in text.splitlines():
        stripped = ln.strip()
        if _QUEUE_TABLE_HEADER.match(stripped):
            continue
        if re.match(r"^\|\s*:?-{2,}", stripped):
            continue
        if re.match(r"^\|\s*[A-Za-z0-9][A-Za-z0-9._-]*\s*\|", stripped):
            return True
    return False


def second_work_list_violations(
    payload: dict | None = None,
    *,
    repo: Path | None = None,
) -> list[tuple[str, str]]:
    """Unresolved work outside the sole master BLOCKs (one-list law)."""
    if payload and payload.get("_skip_second_work_list"):
        return []
    if payload and "_requirement_tree" in payload and not payload.get("_check_second_list"):
        return []
    repo = repo or REPO
    master_rel = SOLE_MASTER_REL
    if not (repo / master_rel).is_file():
        return [("(sole_master)", "sole master checklist missing — one-list law fail-closed")]
    try:
        listed = subprocess.check_output(
            ["git", "ls-files"],
            cwd=str(repo),
            text=True,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return [("(sole_master)", "git ls-files failed — cannot prove one-list completeness")]
    out: list[tuple[str, str]] = []
    for rel in listed:
        rel_n = rel.replace("\\", "/")
        if rel_n == master_rel:
            continue
        if any(rel_n.startswith(p) for p in _SECOND_LIST_VENDOR_PREFIX):
            continue
        if not _is_text_like_work_file(rel_n):
            continue
        path = repo / rel_n
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _UNRESOLVED_MARK.search(text):
            out.append((rel_n, "UNRESOLVED_WORK_ITEM outside the sole master — one-list law"))
            continue
        if _has_second_queue_table(text):
            out.append((
                rel_n,
                "ID/Status/Work queue table outside the sole master — one-list law",
            ))
            continue
        historical = any(rel_n.startswith(p) for p in _SECOND_LIST_HISTORICAL_PREFIX)
        if historical:
            continue
        if _UNRESOLVED_BOX.search(text):
            out.append((rel_n, "unchecked work box outside the sole master — one-list law"))
    return out


_TODO_LINE = re.compile(r"(?i)\b(TODO|FIXME)\b")
_JSON_UNRESOLVED_STATE = re.compile(
    r'(?i)"(status|state|disposition)"\s*:\s*"(OPEN|QUEUED|NEXT|UNRESOLVED)"'
)
_RC_OPEN_ROW = re.compile(r"(?im)^\|\s*RC-\d+\s*\|\s*OPEN\s*\|")
_WORK_LANG_NO_TODO = re.compile(
    r"(?i)(still remains to (?:be )?(?:fixed|proven)|what remains to fix|"
    r"this obligation is unfinished)"
)


def collect_outside_master_debt_candidates(
    repo: Path | None = None,
) -> list[dict[str, str]]:
    """Scanner for omitted debt outside the sole master. Zero work authority.

    Detects queue marks, TODO/FIXME comments, JSON unresolved state, open-defect
    records, frontend TODOs, and differently worded obligations with no TODO token.
    Used for one-list completeness / negative controls — not a second board.
    """
    repo = repo or REPO
    master_rel = SOLE_MASTER_REL
    try:
        listed = subprocess.check_output(
            ["git", "ls-files"],
            cwd=str(repo),
            text=True,
        ).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return []
    found: list[dict[str, str]] = []
    for rel in listed:
        rel_n = rel.replace("\\", "/")
        if rel_n == master_rel:
            continue
        if any(rel_n.startswith(p) for p in _SECOND_LIST_VENDOR_PREFIX):
            continue
        if not _is_text_like_work_file(rel_n):
            continue
        path = repo / rel_n
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        kinds: list[str] = []
        if _UNRESOLVED_BOX.search(text):
            kinds.append("UNCHECKED_BOX")
        if _UNRESOLVED_MARK.search(text):
            kinds.append("UNRESOLVED_MARK")
        if _has_second_queue_table(text):
            kinds.append("QUEUE_TABLE")
        if _TODO_LINE.search(text):
            kinds.append("TODO_COMMENT")
        if _JSON_UNRESOLVED_STATE.search(text):
            kinds.append("JSON_OPEN_STATE")
        if _RC_OPEN_ROW.search(text):
            kinds.append("OPEN_DEFECT_RECORD")
        if _WORK_LANG_NO_TODO.search(text) and not _TODO_LINE.search(text):
            kinds.append("WORDING_NO_TODO")
        for kind in kinds:
            found.append({"path": rel_n, "kind": kind})
    return found


def _unresolved_active_parents(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ACTIVE parents whose proof is FAIL/NOT_PROVEN and still have work.

    Unresolved = named children that are not PASS, or the parent itself when
    it has no children. Closable=false does not excuse the obligation.
    """
    by_id = {str(i.get("id")): i for i in items}
    out: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("execution") or "").upper() != "ACTIVE":
            continue
        proof = str(item.get("proof") or "").upper()
        if proof not in {"NOT_PROVEN", "FAIL"}:
            continue
        child_ids = item.get("children") or []
        if not isinstance(child_ids, list):
            child_ids = []
        unresolved: list[str] = []
        if child_ids:
            for cid in child_ids:
                ch = by_id.get(str(cid))
                ch_proof = str((ch or {}).get("proof") or "").upper()
                if ch_proof != "PASS":
                    unresolved.append(str(cid))
        else:
            unresolved.append(str(item.get("id")))
        if not unresolved:
            unresolved.append(str(item.get("id")))
        out.append({
            "id": str(item.get("id")),
            "proof": proof,
            "unresolved": unresolved,
        })
    return out


def active_parent_obligation_violations(
    payload: dict | None,
) -> list[tuple[str, str]]:
    """Stop-only: ACTIVE FAIL/NOT_PROVEN parents remain obligations.

    Commit (no assistant text) does not use the tree as a permanent commit block.
    A genuine HARD_BLOCKER in the assistant text covers remaining work.
    Calling that state 'proof state, not queued' always BLOCKS — that phrase
    is the documented bypass, not a legal classification.
    """
    text = _assistant_scan_text(payload)
    if not text:
        return []
    parents = _unresolved_active_parents(_requirement_items(payload))
    if not parents:
        return []
    ids = ", ".join(p["id"] for p in parents)
    if _PROOF_STATE_LAUNDER.search(text):
        return [(
            "(active_parent_obligation)",
            f"response called ACTIVE parent(s) {ids} 'proof state, not queued' — "
            "vocabulary cannot convert a FAIL/NOT_PROVEN parent with unresolved "
            "subrequirements into a permitted Stop — FIND IT → FIX IT",
        )]
    if _LINE_HARD_BLOCKED.search(text):
        return []
    return [(
        "(active_parent_obligation)",
        f"ACTIVE parent(s) {ids} remain FAIL/NOT_PROVEN with unresolved "
        "subrequirements and no genuine HARD_BLOCKER — FIND IT → FIX IT Stop BLOCK",
    )]


def unfinished_disposition_violations(payload: dict | None) -> list[tuple[str, str]]:
    """QUEUED / NEXT / remaining-active without a genuine hard blocker → Stop BLOCK.

    Assistant text only. Does not require MATERIAL_DEFECT / DISCOVERED_DEFECT tokens.
    """
    text = _assistant_scan_text(payload)
    if not text:
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _note(key: str, why: str) -> None:
        if key in seen:
            return
        seen.add(key)
        out.append((key, why))

    for item in _remaining_active_items(text):
        if _LINE_HARD_BLOCKED.search(item):
            continue
        _note(
            "(unfinished_disposition)",
            "response declares REMAINING ACTIVE PARENT DEFECTS and lists a "
            "non-hard-blocked fixable defect — FIND IT → FIX IT Stop BLOCK",
        )
        break

    for m in _QUEUED_DISPOSITION_LINE.finditer(text):
        line = m.group("line")
        if _QUEUED_FALSE_POSITIVE.search(line):
            continue
        if _LINE_HARD_BLOCKED.search(line):
            continue
        _note(
            "(unfinished_disposition)",
            "response declares QUEUED unfinished work without a genuine "
            "HARD_BLOCKER on that exact assertion — FIND IT → FIX IT Stop BLOCK",
        )
        break

    for m in _NEXT_DISPOSITION_LINE.finditer(text):
        line = m.group("line")
        if _NEXT_FALSE_POSITIVE.search(line):
            continue
        if _LINE_HARD_BLOCKED.search(line):
            continue
        _note(
            "(unfinished_disposition)",
            "response declares NEXT unfinished work without a genuine "
            "HARD_BLOCKER on that exact assertion — FIND IT → FIX IT Stop BLOCK",
        )
        break
    return out


def discovery_omission_violations(
    payload: dict | None,
    rc_text: str,
) -> list[tuple[str, str]]:
    """Reconcile explicit discovery tokens against the sole master.

    MATERIAL_DEFECT: / DISCOVERED_DEFECT: still bind. The RC log is not the
    obligation surface. Unfinished dispositions are handled separately.
    """
    if not payload:
        return []
    chunks = [json.dumps(payload, default=str)]
    tp = payload.get("transcript_path")
    if tp:
        tpath = Path(str(tp))
        if tpath.is_file():
            try:
                chunks.append(tpath.read_text(encoding="utf-8", errors="replace")[-200_000:])
            except OSError:
                pass
    if payload.get("last_assistant_text"):
        chunks.append(str(payload["last_assistant_text"]))
    text = "\n".join(chunks)
    try:
        master = SOLE_MASTER_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        master = ""
    master_u = master.upper()
    master_l = master.lower()
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _MATERIAL_DECL.finditer(text):
        token = m.group(1)
        key = token.upper()
        if key in seen:
            continue
        seen.add(key)
        if key.startswith("RC-"):
            if key not in master_u:
                out.append((
                    key,
                    "MATERIAL_DEFECT declared in this turn but omitted from the "
                    "sole master — STOP BLOCKS",
                ))
        else:
            slug = token.lower()
            if slug not in master_l:
                out.append((
                    token,
                    "DISCOVERED_DEFECT declared in this turn but omitted from "
                    "the sole master — STOP BLOCKS",
                ))
    return out


def _command_exercises_defect(command: str, row: dict[str, str], *, repo: Path) -> tuple[bool, str]:
    cmd = (command or "").strip()
    if not cmd:
        return False, "REMEDIATED without a cited verification command"
    named: list[str] = []
    for tok in re.split(r"[\s\"'=]+", cmd):
        tok = tok.strip()
        if not tok:
            continue
        if tok.endswith(".py") or "/tests/" in tok or tok.startswith("tests/"):
            named.append(tok.replace("\\", "/"))
    if not named:
        return False, "command does not name a test/module path that can exercise the defect"
    existing = []
    for p in named:
        rel = p[2:] if p.startswith("./") else p
        if (repo / rel).is_file():
            existing.append(rel)
    if not existing:
        return False, f"cited paths do not exist: {named!r}"
    body = _row_text(row).lower()
    rc_id = row.get("id", "").lower()
    exercised = False
    for rel in existing:
        try:
            src = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low = src.lower()
        if rc_id.lower() in low or any(
            Path(p).name.split(".")[0] in low
            for p in _paths_in_text(_row_text(row))
            if p.endswith(".py")
        ):
            exercised = True
            break
        if "assert" in low and any(t in body for t in (rel.lower(), Path(rel).stem.lower())):
            exercised = True
            break
    if not exercised:
        # The cited existing test file itself is the exercise if the RC names it.
        if any(rel in body for rel in existing):
            exercised = True
    if not exercised:
        return False, "cited command/path does not correspond to the defect FIXED scope"
    title = (row.get("defect") or "") + " " + (row.get("why") or "")
    if _PARENT_SCOPE.search(title) and existing:
        if all(_CHILD_TEST.search(rel) for rel in existing):
            return False, (
                "tiny child test presented as parent closure — a CHILD PASS never "
                "closes a parent requirement"
            )
    return True, "ok"


def _execution_evidence_ok(row: dict[str, str], payload: dict | None) -> tuple[bool, str]:
    """When the turn supplies fix_evidence, it must have run and exited 0."""
    if not payload:
        return True, "ok"
    ev = payload.get("fix_evidence")
    if not isinstance(ev, dict):
        return True, "ok"
    rec = ev.get(row.get("id") or "")
    if not rec:
        return True, "ok"
    if rec.get("ran") is False:
        return False, "command exists but was not executed"
    if rec.get("exit") not in (0, "0", None):
        return False, f"verification command failed (exit={rec.get('exit')!r})"
    if rec.get("exit") is None and rec.get("ran") is True:
        return False, "verification ran but no exit status was recorded"
    return True, "ok"


def remediation_ok(
    row: dict[str, str],
    *,
    repo: Path | None = None,
    payload: dict | None = None,
) -> tuple[bool, str]:
    """REMEDIATED requires FIXED: + a real command that names an existing exercising path."""
    repo = repo or REPO
    fix = row.get("fix") or ""
    low = fix.lower()
    if "would run" in low or "not run" in low or "not executed" in low:
        return False, "command exists but was not executed"
    if "FIXED:" not in fix.upper().replace(" ", ""):
        if "FIXED:" not in fix:
            return False, "ACTIVE obligation lacks FIXED:"
    cmds = _BACKTICK_CMD.findall(fix)
    if not cmds:
        return False, "REMEDIATED requires a backticked command that actually names an existing path"
    last_err = "no command accepted"
    for cmd in cmds:
        ok, why = _command_exercises_defect(cmd, row, repo=repo)
        if ok:
            ev_ok, ev_why = _execution_evidence_ok(row, payload)
            if not ev_ok:
                return False, ev_why
            return True, "ok"
        last_err = why
    return False, last_err


def reconcile_active_view(
    authoritative: list[dict[str, str]],
    presented_ids: Iterable[str] | None,
) -> list[tuple[str, str]]:
    """A syntactically valid but incomplete presented view BLOCKS."""
    if presented_ids is None:
        return []
    presented = {str(x) for x in presented_ids}
    out: list[tuple[str, str]] = []
    for row in authoritative:
        rid = row.get("id") or "?"
        if rid not in presented:
            out.append((
                rid,
                "ACTIVE obligation present in the sole-master derived view but omitted "
                "from the active view the gate reads — incomplete active view is a BLOCK",
            ))
    return out


VALID_CHECKBOX_STATUS = frozenset({
    "PASS", "FAIL", "NOT_PROVEN", "UNAVAILABLE", "NOT_APPLICABLE",
})
LEGACY_POINTER_RELS = frozenset({
    "ACTIVE_PROGRAM.md",
    "OPEN_ITEMS.md",
    "governance/root_cause_log.md",
    "governance/unproven_register.md",
    "governance/requirement_tree.json",
})
_AUTHORITY_PROSE_RELS = (
    "AGENTS.md",
    "CLAUDE.md",
    "MEMORY.md",
    "ACTIVE_PROGRAM.md",
    "OPEN_ITEMS.md",
    "tools/stop_guard.py",
    "tools/requirement_proof.py",
    "governance/REHAB_PROGRAM.md",
    "governance/PM_MANDATE.md",
    "governance/AGENT_OPERATING_PROCESS_V1.md",
    "governance/unproven_register.md",
)
# Strong grants of work-state or prioritization to a non-master file.
_SECOND_AUTH_GRANT = (
    (re.compile(r"queue is binding", re.I), "queue-is-binding grant"),
    (re.compile(r"Find & Prove queue is binding", re.I), "legacy F&P queue grant"),
    (re.compile(r"Execute\s+`?ACTIVE_PROGRAM", re.I), "ACTIVE_PROGRAM execute-next grant"),
    (re.compile(r"ACTIVE_PROGRAM\.md`?\s+queue", re.I), "ACTIVE_PROGRAM queue grant"),
    (re.compile(r"(?:One )?defect authority:\s*`?governance/root_cause_log", re.I),
     "RC defect-authority grant"),
    (re.compile(r"Active program state\s+is always", re.I),
     "ACTIVE_PROGRAM state-authority grant"),
    (re.compile(r"Portable rules live in .{0,120}ACTIVE_PROGRAM", re.I),
     "ACTIVE_PROGRAM rules-authority grant"),
    (re.compile(r"ACTIVE_PROGRAM\.md`?\s+[—-]\s+current epic", re.I),
     "ACTIVE_PROGRAM deferred-work grant"),
    (re.compile(r"root-cause row opened (?:TODAY|THAT DAY) is still", re.I),
     "RC Stop-eligibility grant"),
    (re.compile(r"open the next highest P[0-9] from", re.I),
     "census/rehab work-selection grant"),
    (re.compile(r"requirement_tree\.json`? is the machine master", re.I),
     "requirement_tree work-authority grant"),
    (re.compile(r"\"defect_ledger\":\s*\"governance/root_cause_log", re.I),
     "RC defect-ledger grant"),
    (re.compile(r"blocks commits when a row goes overdue", re.I),
     "register due-date commit-block grant"),
    (re.compile(r"past its `due` date fails the gate and blocks", re.I),
     "register due-date commit-block grant"),
    (re.compile(r"no UNPROVEN/DISPROVED claim past its due date", re.I),
     "register due-date commit-block grant"),
    (re.compile(r"Reject mission COMPLETE.{0,80}OPEN RC", re.I),
     "RC-status completion-block grant"),
    (re.compile(r"closable work has exactly TWO homes", re.I),
     "second-list homes grant"),
    (re.compile(r"open its RC row FIRST", re.I),
     "RC-row admission grant"),
    (re.compile(r"No new root-cause row exists", re.I),
     "RC-row admission grant"),
    (re.compile(r"Add a `\| RC-", re.I),
     "RC-row admission grant"),
    (re.compile(r"co-stage a real '\| RC-'", re.I),
     "RC-row admission grant"),
    (re.compile(r"ACTIVE_PROGRAM\.md`? and .{0,60}are sufficient", re.I),
     "ACTIVE_PROGRAM lock-sufficiency grant"),
)
_FOUR_STATUS_PROSE = re.compile(
    r"PASS\s*/\s*FAIL\s*/\s*NOT_PROVEN\s*/\s*UNAVAILABLE(?!\s*/\s*NOT_APPLICABLE)",
    re.I,
)
_FOUR_STATUS_SET = re.compile(
    r"""\{\s*["']PASS["']\s*,\s*["']FAIL["']\s*,\s*["']NOT_PROVEN["']\s*,"""
    r"""\s*["']UNAVAILABLE["']\s*\}"""
)
_FOURTH_SAME_METHOD = re.compile(
    r"fourth\s+(?:variation|attempt|try|iteration)\s+of\s+the\s+same\s+method",
    re.I,
)
_METHOD_PIVOT = re.compile(
    r"method-pivot|change method|different path to the same required outcome",
    re.I,
)
_THREE_PIVOT_CONTRACT = re.compile(
    r"THREE-ITERATION METHOD-PIVOT|three materially similar attempts",
    re.I,
)


def legacy_pointer_selected_work(rel: str, text: str = "") -> list[str]:
    """ACTIVE_PROGRAM / OPEN_ITEMS / RC log / requirement_tree never select work."""
    return []


def _authority_prose_paths(repo: Path) -> list[Path]:
    out: list[Path] = []
    for rel in _AUTHORITY_PROSE_RELS:
        p = repo / rel
        if p.is_file():
            out.append(p)
    rules = repo / ".cursor" / "rules"
    if rules.is_dir():
        out.extend(sorted(rules.glob("*.mdc")))
        out.extend(sorted(rules.glob("*.md")))
    claude = repo / ".claude"
    if claude.is_dir():
        out.extend(sorted(claude.rglob("*.md")))
        out.extend(sorted(claude.rglob("*.mdc")))
        settings = claude / "settings.json"
        if settings.is_file():
            out.append(settings)
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def second_authority_prose_violations(
    *,
    repo: Path | None = None,
    extra_texts: Iterable[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Prose that grants work-state or prioritization to a non-master file FAILs."""
    repo = repo or REPO
    out: list[tuple[str, str]] = []
    blobs: list[tuple[str, str]] = []
    for path in _authority_prose_paths(repo):
        try:
            blobs.append((
                str(path.relative_to(repo)).replace("\\", "/"),
                path.read_text(encoding="utf-8", errors="replace"),
            ))
        except OSError:
            continue
    if extra_texts:
        blobs.extend((str(n), str(t)) for n, t in extra_texts)
    for rel, text in blobs:
        for cre, why in _SECOND_AUTH_GRANT:
            if cre.search(text):
                out.append((rel, why))
    return out


def five_status_authority_violations(
    *,
    repo: Path | None = None,
    extra_texts: Iterable[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Stale four-status authority/parser text FAILs; five-status is required."""
    repo = repo or REPO
    out: list[tuple[str, str]] = []
    blobs: list[tuple[str, str]] = []
    for rel in (
        SOLE_MASTER_REL,
        "tools/requirement_proof.py",
        "AGENTS.md",
        "MEMORY.md",
    ):
        p = repo / rel
        if p.is_file():
            try:
                blobs.append((rel, p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    if extra_texts:
        blobs.extend((str(n), str(t)) for n, t in extra_texts)
    for rel, text in blobs:
        if _FOUR_STATUS_PROSE.search(text) or _FOUR_STATUS_SET.search(text):
            out.append((
                rel,
                "stale four-status vocabulary — required "
                "PASS|FAIL|NOT_PROVEN|UNAVAILABLE|NOT_APPLICABLE",
            ))
    return out


def three_iteration_method_pivot_violations(
    payload: dict | None = None,
    *,
    repo: Path | None = None,
) -> list[tuple[str, str]]:
    """Fourth same-method variation without a method pivot FAILs. Not permission to stop."""
    repo = repo or REPO
    out: list[tuple[str, str]] = []
    agents = repo / "AGENTS.md"
    if agents.is_file():
        try:
            text = agents.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if text and not _THREE_PIVOT_CONTRACT.search(text):
            out.append((
                "AGENTS.md",
                "three-iteration method-pivot contract missing from agent authority",
            ))
    scan = _assistant_scan_text(payload)
    if _FOURTH_SAME_METHOD.search(scan) and not _METHOD_PIVOT.search(scan):
        out.append((
            "(turn)",
            "fourth variation of the same method without method-pivot — change method",
        ))
    return out


def load_optional_derived_view(path: Path | None = None) -> list[str] | None:
    """If active_defects.json exists it is a derived view, not an authority."""
    p = path or ACTIVE_DEFECTS_PATH
    if not p.is_file():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []  # unreadable derived view → treat as empty → omission BLOCK
    defects = doc.get("defects") if isinstance(doc, dict) else None
    if not isinstance(defects, list):
        return []
    ids: list[str] = []
    for d in defects:
        if isinstance(d, dict) and d.get("id"):
            ids.append(str(d["id"]))
        elif isinstance(d, str):
            ids.append(d)
    return ids


def active_obligation_offenders(
    rc_text: str,
    *,
    today: str | None = None,
    mission: dict | None = None,
    dirty_paths: Iterable[str] | None = None,
    presented_ids: Iterable[str] | None = None,
    repo: Path | None = None,
    payload: dict | None = None,
) -> list[tuple[str, str]]:
    """THE ONE authority. Gate + Stop both call this."""
    repo = repo or REPO
    today = today or datetime.date.today().isoformat()
    mission = mission if mission is not None else _mission()
    dirty = list(dirty_paths) if dirty_paths is not None else _dirty_paths()
    out: list[tuple[str, str]] = []
    out.extend(unfinished_disposition_violations(payload))
    out.extend(active_parent_obligation_violations(payload))
    out.extend(second_work_list_violations(payload, repo=repo))
    out.extend(discovery_omission_violations(payload, rc_text))
    if not (payload and payload.get("_skip_second_work_list")):
        out.extend(second_authority_prose_violations(repo=repo))
        out.extend(five_status_authority_violations(repo=repo))
        out.extend(three_iteration_method_pivot_violations(payload, repo=repo))
        out.extend(ticker_specific_fix_scope_violations(repo=repo))
        try:
            new_m = (repo / SOLE_MASTER_REL).read_text(encoding="utf-8", errors="replace")
            old_m = subprocess.check_output(
                ["git", "show", f"HEAD:{SOLE_MASTER_REL}"],
                cwd=str(repo),
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            out.extend(master_closure_missing_root_cause(old_m, new_m))
        except (OSError, subprocess.CalledProcessError):
            pass
    # RC CLASS:ACTIVE / PASSIVE and RC OPEN rows are not work-state.
    return out


def ticker_specific_fix_scope_violations(
    *,
    repo: Path | None = None,
    extra_texts: Iterable[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Ticker-specific implementation scope for a universal defect FAILs."""
    try:
        from tools.universal_scope_lock import (
            ticker_specific_implementation_scope_violation,
        )
    except ImportError:
        from universal_scope_lock import (  # type: ignore
            ticker_specific_implementation_scope_violation,
        )
    repo = repo or REPO
    out: list[tuple[str, str]] = []
    blobs: list[tuple[str, str]] = []
    for path in _authority_prose_paths(repo):
        try:
            blobs.append((
                str(path.relative_to(repo)).replace("\\", "/"),
                path.read_text(encoding="utf-8", errors="replace"),
            ))
        except OSError:
            continue
    if extra_texts:
        blobs.extend((str(n), str(t)) for n, t in extra_texts)
    for rel, text in blobs:
        why = ticker_specific_implementation_scope_violation(text, rel=rel)
        if why:
            out.append((rel, why))
    return out


_MASTER_BOX_RE = re.compile(
    r"^\s*[-*]\s+\[(?P<mark>[ xX])\]\s+`(?P<id>[^`]+)`\s+—\s+STATUS=(?P<status>[A-Z_]+)\s+—\s+(?P<body>.*)$"
)


def master_closure_missing_root_cause(
    old_text: str,
    new_text: str,
) -> list[tuple[str, str]]:
    """A master box may not close without five-why / ROOT evidence on the same item."""
    old_rows = {m.group("id"): m for m in _MASTER_BOX_RE.finditer(old_text or "")}
    out: list[tuple[str, str]] = []
    for m in _MASTER_BOX_RE.finditer(new_text or ""):
        prev = old_rows.get(m.group("id"))
        became_checked = (
            m.group("mark").strip().lower() == "x"
            and (prev is None or prev.group("mark").strip() != "x")
        )
        became_pass = (
            m.group("status") == "PASS"
            and (prev is None or prev.group("status") != "PASS")
        )
        if not (became_checked or became_pass):
            continue
        body = f"{m.group('status')} {m.group('body')}"
        if "ROOT:" in body.upper() and ("(1)" in body or "why" in body.lower()):
            continue
        out.append((
            m.group("id"),
            "master closure requires five-why / ROOT evidence on the same item",
        ))
    return out


def fix_law_blockers(
    *,
    rc_text: str | None = None,
    today: str | None = None,
    presented_ids: Iterable[str] | None = None,
    payload: dict | None = None,
) -> list[tuple[str, str]]:
    """Stop-guard entry. Same function the commit check uses."""
    if rc_text is None:
        try:
            rc_text = RC_LOG.read_text(encoding="utf-8", errors="replace")
        except OSError:
            rc_text = ""
    return active_obligation_offenders(
        rc_text, today=today, presented_ids=presented_ids, payload=payload
    )
