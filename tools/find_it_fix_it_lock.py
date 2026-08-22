"""FIND IT → FIX IT lock (RC-452 / RC-453).

ONE defect authority: governance/root_cause_log.md.

Three states, derived from that ledger (no parallel inventory):

  PASSIVE BACKLOG — historical OPEN/PARTIAL debt not implicated by the active mission.
                    Does not block Stop / commit.
  ACTIVE OBLIGATION — belongs to the active parent mission, was discovered this session,
                      or is a previously-passive row now materially implicated by what
                      the active mission is changing / consuming / exposing.
                      Blocks Stop until remediated or genuinely hard-blocked.
  CLOSED / REMEDIATED — root cause and material blast radius fixed with evidence.

Required transitions (mechanical):
  NEW MATERIAL DISCOVERY → ACTIVE   (not PASSIVE)
  PASSIVE + implicated by active mission → ACTIVE
  ACTIVE → PASSIVE is illegal merely to permit Stop.

A syntactically valid but incomplete presented active view BLOCKS (omission
negative control). If governance/active_defects.json exists it is a derived
view and must reconcile completely against the RC-log derivation.

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
import os
import re
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parent.parent
RC_LOG = REPO / "governance" / "root_cause_log.md"
PM_MISSION_PATH = REPO / "governance" / "pm_mission.json"
ACTIVE_DEFECTS_PATH = REPO / "governance" / "active_defects.json"

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


# Mega surfaces named in almost every historical display/collect row. Editing one of
# these does not, by itself, materially implicate the entire historical backlog
# (operator: no permanent globally-blocking backlog). Narrow module paths still
# activate PASSIVE → ACTIVE. Mission-tagged / opened-today rows still activate.
_WIDE_SURFACES_NO_AUTO_IMPLICATE = frozenset({
    "static/chart.html",
    "static/index.html",
    "server.py",
    "db.py",
})


def _path_implicated(row_paths: set[str], dirty: Iterable[str], scope: Iterable[str]) -> bool:
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
) -> list[dict[str, str]]:
    today = today or datetime.date.today().isoformat()
    mission = mission if mission is not None else _mission()
    dirty = list(dirty_paths) if dirty_paths is not None else _dirty_paths()
    out: list[dict[str, str]] = []
    for row in _parse_rc_rows(rc_text):
        if classify_row(row, today=today, mission=mission, dirty_paths=dirty) == "ACTIVE":
            out.append(row)
    return out


def illegal_passive_escape_offenders(
    rc_text: str,
    *,
    today: str | None = None,
    mission: dict | None = None,
    dirty_paths: Iterable[str] | None = None,
) -> list[tuple[str, str]]:
    """ACTIVE → PASSIVE (or new discovery marked PASSIVE) is not an escape hatch."""
    today = today or datetime.date.today().isoformat()
    mission = mission if mission is not None else _mission()
    dirty = list(dirty_paths) if dirty_paths is not None else _dirty_paths()
    out: list[tuple[str, str]] = []
    for row in _parse_rc_rows(rc_text):
        if (row.get("status") or "").upper() not in ("OPEN", "PARTIAL"):
            continue
        declared = _declared_class(row)
        if declared != "PASSIVE":
            continue
        opened_today = row.get("opened") == today
        body = _row_text(row)
        mid = str(mission.get("mission_id") or "")
        mission_tagged = bool(mid) and mid in body
        parent_tagged = any(tok in body for tok in PARENT_MISSION_TOKENS)
        implicated = _path_implicated(
            _paths_in_text((row.get("defect") or "")[:320]),
            dirty,
            mission.get("scope_paths") or [],
        )
        if opened_today:
            out.append((
                row["id"],
                "NEW MATERIAL DISCOVERY marked CLASS:PASSIVE — required transition is "
                "NEW → ACTIVE, not NEW → PASSIVE BACKLOG",
            ))
        elif mission_tagged or parent_tagged or implicated:
            out.append((
                row["id"],
                "CLASS:PASSIVE on a row implicated by the active mission — PASSIVE + "
                "implicated must become ACTIVE; ACTIVE → PASSIVE is not a Stop escape",
            ))
    return out


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


def discovery_omission_violations(
    payload: dict | None,
    rc_text: str,
) -> list[tuple[str, str]]:
    """Agent explicitly declared a material defect this turn but omitted it from the RC log.

    Does not invent semantic discovery. Only tokens the agent wrote
    (MATERIAL_DEFECT: / DISCOVERED_DEFECT:) are reconciled.
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
    rows = _parse_rc_rows(rc_text)
    rc_ids = {r["id"].upper() for r in rows}
    bodies = [(r["id"], _row_text(r).lower()) for r in rows]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _MATERIAL_DECL.finditer(text):
        token = m.group(1)
        key = token.upper()
        if key in seen:
            continue
        seen.add(key)
        if key.startswith("RC-"):
            if key not in rc_ids:
                out.append((
                    key,
                    "MATERIAL_DEFECT declared in this turn but omitted from "
                    "governance/root_cause_log.md — STOP BLOCKS",
                ))
        else:
            slug = token.lower()
            if not any(slug in body for _, body in bodies):
                out.append((
                    token,
                    "DISCOVERED_DEFECT declared in this turn but omitted from "
                    "authoritative RC state — STOP BLOCKS",
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
                "ACTIVE obligation present in authoritative RC log but omitted from the "
                "active view the gate reads — incomplete active view is a BLOCK",
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
    out.extend(discovery_omission_violations(payload, rc_text))
    out.extend(illegal_passive_escape_offenders(
        rc_text, today=today, mission=mission, dirty_paths=dirty
    ))
    active = derive_active_obligations(
        rc_text, today=today, mission=mission, dirty_paths=dirty
    )
    if presented_ids is None:
        presented_ids = load_optional_derived_view(ACTIVE_DEFECTS_PATH)
    out.extend(reconcile_active_view(active, presented_ids))
    for row in active:
        rid = row["id"]
        status = row.get("status") or ""
        fix = row.get("fix") or ""
        banned = _banned_blocker_language(fix)
        if banned:
            out.append((rid, f"self-authored {banned!r} is never a blocker — keep fixing"))
            continue
        blocker = _parse_hard_blocker(fix)
        if blocker:
            ok, why = blocker_evidence_ok(blocker, repo=repo)
            if not ok:
                out.append((rid, f"HARD_BLOCKER evidence invalid: {why}"))
            continue
        if status == "CLOSED":
            ok, why = remediation_ok(row, repo=repo, payload=payload)
            if not ok:
                out.append((rid, f"CLOSED active obligation lacks remediation evidence: {why}"))
            continue
        if "FIXED:" in fix:
            ok, why = remediation_ok(row, repo=repo, payload=payload)
            if not ok:
                out.append((rid, f"ACTIVE FIXED row lacks remediation evidence: {why}"))
            continue
        out.append((
            rid,
            f"ACTIVE {status} obligation is not REMEDIATED (FIXED: + exercising command) "
            f"and has no valid HARD_BLOCKER — FIND IT → FIX IT",
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
            return [("(rc_log)", "governance/root_cause_log.md unreadable — fail-closed")]
    return active_obligation_offenders(
        rc_text, today=today, presented_ids=presented_ids, payload=payload
    )
