"""Canonical machine computations for hard laws 1-7.

Not a second obligation authority. Sole master remains
ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md.
Existing Stop / PreToolUse / commit / CI hooks invoke these functions.

# next-rth-ok: derived via time_et.next_rth_session_et
# universal-scope-ok: laws apply to the enrolled obligation set, not a ticker sample
# chart-intent-ok: this module does not claim Chart Done
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parent.parent
SOLE_MASTER_REL = "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md"
OPERATOR_GO_PATH = REPO / "governance" / "operator_go.json"

#: Frozen when the 2387-item denominator was the live master on this line.
#: Changing this constant resets the 5:1 comparison baseline — tests pin the SHA.
BURN_DOWN_BASELINE_REF = "3a7799c5093f867d6bacc915a3f5b3fdcbabfaf2"
BURN_DOWN_RATIO = 5

CLOSED_STATUSES = frozenset({"PASS"})
UNRESOLVED_STATUSES = frozenset({"NOT_PROVEN", "FAIL"})
# NOT_APPLICABLE is a terminal classification but is never a CLOSE for 5:1.
NOT_CLOSE_TERMINAL = frozenset({"NOT_APPLICABLE", "UNAVAILABLE"})

_MASTER_BOX_RE = re.compile(
    r"^\s*[-*]\s+\[(?P<mark>[ xX])\]\s+`(?P<id>[^`]+)`\s+—\s+STATUS=(?P<status>[A-Z_]+)\s+—\s+(?P<body>.*)$",
    re.MULTILINE,
)

P01B_CLUSTER = tuple(
    [f"OS-A1-{i:03d}" for i in range(1, 24)] + ["OS-A2-002", "OS-A2-003", "OS-A2-004"]
)

REQUIRED_CI_NAMES = ("hardening", "pytest-full")
_REQUIRED_CI_CLAIM = re.compile(
    r"\b("
    r"merge-ready|CI green|all green|pytest-full\s+PASS|PYTEST_FULL\s*=\s*PASS|"
    r"HARDENING_GATES\s*=\s*PASS|required CI.{0,48}(?:green|PASS|SUCCESS)|"
    r"LIVE_ENFORCED|mechanically locked and green|"
    r"COMPLETE(?:/CLOSED)?(?:\s+for|\s+on|\s+—|\s+-|\s*:|\s+the|\s+collect|\s+live|\s+lock)"
    r")\b",
    re.I,
)
_ENV_OFF = frozenset({"off", "0", "false"})

_HARD_BLOCKER_RE = re.compile(
    r"HARD_BLOCKER:\s*(?P<body>.+?)(?:\s{2,}|$)",
    re.I,
)


@dataclass(frozen=True)
class MasterItem:
    item_id: str
    mark: str
    status: str
    body: str
    body_hash: str

    @property
    def unresolved(self) -> bool:
        return self.status in UNRESOLVED_STATUSES or (
            self.mark.strip() != "x" and self.status not in CLOSED_STATUSES
            and self.status not in NOT_CLOSE_TERMINAL
        )

    @property
    def closed_pass(self) -> bool:
        return self.status in CLOSED_STATUSES and self.mark.strip().lower() == "x"


@dataclass
class BurnDown:
    new_unresolved: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    na_inflation: list[str] = field(default_factory=list)
    rename_launder: list[str] = field(default_factory=list)
    baseline_unresolved: int = 0
    current_unresolved: int = 0
    current_pass: int = 0

    @property
    def new_count(self) -> int:
        return len(self.new_unresolved)

    @property
    def closed_count(self) -> int:
        return len(self.closed)

    @property
    def net_unresolved_reduction(self) -> int:
        return self.closed_count - self.new_count


def _body_hash(body: str) -> str:
    norm = re.sub(r"\s+", " ", (body or "").strip().lower())
    # Strip volatile calendar / next-RTH tokens so date edits are not a new obligation.
    norm = re.sub(r"20\d{2}-\d{2}-\d{2}", "", norm)
    norm = re.sub(r"next rth:[^.]*", "", norm)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def parse_master_items(text: str) -> dict[str, MasterItem]:
    out: dict[str, MasterItem] = {}
    for m in _MASTER_BOX_RE.finditer(text or ""):
        body = m.group("body")
        item = MasterItem(
            item_id=m.group("id"),
            mark=m.group("mark"),
            status=m.group("status"),
            body=body,
            body_hash=_body_hash(body),
        )
        out[item.item_id] = item
    return out


def load_master_text(repo: Path | None = None, *, ref: str | None = None) -> str:
    repo = repo or REPO
    if ref:
        proc = subprocess.run(
            ["git", "show", f"{ref}:{SOLE_MASTER_REL}"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"baseline master unreadable at {ref}: {proc.stderr.strip()}")
        return proc.stdout
    return (repo / SOLE_MASTER_REL).read_text(encoding="utf-8", errors="replace")


def compute_burn_down(
    baseline_text: str,
    current_text: str,
) -> BurnDown:
    """NEW_UNRESOLVED and CLOSED vs a frozen baseline. Anti-laundering is identity-based."""
    base = parse_master_items(baseline_text)
    cur = parse_master_items(current_text)
    bd = BurnDown(
        baseline_unresolved=sum(1 for i in base.values() if i.unresolved),
        current_unresolved=sum(1 for i in cur.values() if i.unresolved),
        current_pass=sum(1 for i in cur.values() if i.closed_pass),
    )
    base_unres = {i: it for i, it in base.items() if it.unresolved}
    cur_unres = {i: it for i, it in cur.items() if it.unresolved}
    disappeared = [i for i in base_unres if i not in cur]
    appeared = [i for i in cur if i not in base]
    # Rename / delete-readd: vanished unresolved ID + new ID with same body hash.
    used_new: set[str] = set()
    for old_id in disappeared:
        old_h = base_unres[old_id].body_hash
        match = next((n for n in appeared if n not in used_new and cur[n].body_hash == old_h), None)
        if match:
            bd.rename_launder.append(f"{old_id}->{match}")
            used_new.add(match)
            if cur[match].unresolved:
                bd.new_unresolved.append(match)
        # vanished without PASS on a surviving ID is not CLOSED
    for nid in appeared:
        if nid in used_new:
            continue
        if cur[nid].unresolved:
            bd.new_unresolved.append(nid)
    for iid, it in cur.items():
        prev = base.get(iid)
        if prev is None:
            continue
        if prev.unresolved and it.closed_pass:
            if "ROOT:" in it.body.upper() and ("(1)" in it.body or "why" in it.body.lower()):
                bd.closed.append(iid)
            # trivial / status-only close is not CLOSED
        if prev.unresolved and it.status in NOT_CLOSE_TERMINAL and prev.status not in NOT_CLOSE_TERMINAL:
            bd.na_inflation.append(iid)
        if prev.unresolved and not it.unresolved and not it.closed_pass:
            # checked box without PASS, or UNAVAILABLE without being a close
            pass
    return bd


def burn_down_ratio_violations(
    bd: BurnDown,
    *,
    remaining_all_legitimately_blocked: bool,
    ratio: int | None = None,
) -> list[tuple[str, str]]:
    r = BURN_DOWN_RATIO if ratio is None else int(ratio)
    if bd.new_count <= 0:
        return []
    if remaining_all_legitimately_blocked:
        return []
    if bd.closed_count < r * bd.new_count:
        return [(
            "(burn_down_5_to_1)",
            f"NEW_UNRESOLVED={bd.new_count} CLOSED={bd.closed_count} "
            f"requires CLOSED >= {r}*NEW; rename_launder={bd.rename_launder} "
            f"na_inflation={bd.na_inflation}",
        )]
    return []


def idle_stop_violations(
    bd: BurnDown,
    *,
    safely_fixable_ids: Iterable[str],
    machine_active_work: bool,
) -> list[tuple[str, str]]:
    safe = [s for s in safely_fixable_ids if s]
    if not safe:
        return []
    if machine_active_work:
        return []
    if bd.net_unresolved_reduction <= 0:
        return [(
            "(idle_stop)",
            f"SAFELY_FIXABLE_UNRESOLVED={len(safe)} "
            f"NET_UNRESOLVED_REDUCTION={bd.net_unresolved_reduction} "
            f"first={safe[0]} — normal Stop forbidden",
        )]
    return []


def parse_hard_blocker_body(body: str) -> dict[str, Any] | None:
    m = _HARD_BLOCKER_RE.search(body or "")
    if not m:
        return None
    raw = m.group("body").strip()
    if raw.startswith("{"):
        try:
            end = raw.find("}")
            doc = json.loads(raw[: end + 1] if end >= 0 else raw)
            return {str(k): v for k, v in doc.items()} if isinstance(doc, dict) else None
        except (ValueError, TypeError):
            return None
    fields: dict[str, Any] = {}
    for tok in raw.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            fields[k.strip().lower()] = v.strip()
        elif tok.upper().rstrip(".,;") in {"RTH_ONLY", "EXTERNAL_DATA_UNAVAILABLE",
                                           "DESTRUCTIVE_APPROVAL_REQUIRED", "ENVIRONMENT_BLOCKED"}:
            fields["type"] = tok.upper().rstrip(".,;")
    return fields if fields.get("type") else None


def item_blocker_valid(item: MasterItem, *, repo: Path | None = None) -> bool:
    try:
        from tools.find_it_fix_it_lock import blocker_evidence_ok
    except ImportError:
        from find_it_fix_it_lock import blocker_evidence_ok  # type: ignore
    hb = parse_hard_blocker_body(item.body)
    if not hb:
        return False
    ok, _why = blocker_evidence_ok(hb, repo=repo)
    return bool(ok)


def applicable_item_ids(
    items: dict[str, MasterItem],
    *,
    dirty_paths: Iterable[str] | None = None,
    extra_ids: Iterable[str] | None = None,
    include_p01b_cluster: bool = True,
) -> list[str]:
    out: set[str] = set(extra_ids or ())
    if include_p01b_cluster:
        out.update(i for i in P01B_CLUSTER if i in items)
    dirty = {str(p).replace("\\", "/") for p in (dirty_paths or ())}
    if dirty:
        for iid, it in items.items():
            if not it.unresolved:
                continue
            sm = re.search(r"SURFACES=([^\s]+)", it.body)
            if not sm:
                continue
            surfaces = {s.strip() for s in sm.group(1).split(";") if s.strip()}
            if surfaces & dirty:
                out.add(iid)
    return sorted(i for i in out if i in items and items[i].unresolved)


def safely_fixable_ids(
    items: dict[str, MasterItem],
    applicable: Iterable[str],
    *,
    repo: Path | None = None,
) -> list[str]:
    return [i for i in applicable if i in items and not item_blocker_valid(items[i], repo=repo)]


def blocker_locality_violations(
    items: dict[str, MasterItem],
    applicable: Iterable[str],
    *,
    repo: Path | None = None,
) -> list[tuple[str, str]]:
    """A blocker binds one obligation. One RTH-blocked item cannot stop deterministic work."""
    app = [i for i in applicable if i in items]
    if not app:
        return []
    blocked = [i for i in app if item_blocker_valid(items[i], repo=repo)]
    unblocked = [i for i in app if i not in blocked]
    if unblocked:
        return [(
            "(blocker_locality)",
            f"obligation {unblocked[0]} is safely fixable now; "
            f"RTH/external blocker on {blocked[:1] or ['(none)']} does not block the program",
        )]
    return []


def approach_fingerprint(paths: Iterable[str], failure_ids: Iterable[str]) -> str:
    payload = {
        "paths": sorted({str(p).replace("\\", "/") for p in paths if p}),
        "failures": sorted({str(f) for f in failure_ids if f}),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def method_pivot_violations(
    attempts: Iterable[dict[str, Any]],
    *,
    next_fingerprint: str,
    stable_id: str,
) -> list[tuple[str, str]]:
    """Fourth materially equivalent attempt on the same stable_id is blocked.

    Material equivalence is the fingerprint of paths + failure identity, not prose.
    """
    if not stable_id or not next_fingerprint:
        return []
    same = [
        a for a in attempts
        if str(a.get("stable_id") or "") == stable_id
        and str(a.get("approach_fp") or "") == next_fingerprint
        and str(a.get("outcome") or "fail") == "fail"
    ]
    if len(same) >= 3:
        return [(
            "(method_pivot)",
            f"CURRENT APPROACH FAILED — CHANGING METHOD for {stable_id}: "
            f"{len(same)} equivalent failures (fp={next_fingerprint}); "
            f"fourth equivalent action blocked",
        )]
    return []


def required_ci_violations(
    text: str,
    *,
    head_sha: str,
    ci_status: dict[str, Any] | None,
) -> list[str]:
    if not text or not _REQUIRED_CI_CLAIM.search(text):
        return []
    if not ci_status:
        return [
            "required CI: no machine evidence for this HEAD — pending is not PASS; "
            "targeted tests are not a substitute"
        ]
    sha = str(ci_status.get("sha") or "").strip()
    if sha and sha != head_sha:
        return [
            f"required CI: evidence SHA {sha[:12]} is not HEAD {head_sha[:12]} — "
            "prior SHA green is not PASS"
        ]
    if ci_status.get("environment_blocked"):
        err = str(ci_status.get("observed_error") or "")
        cmd = str(ci_status.get("command") or "")
        if err and cmd and re.search(r"(Error|Exception|E_|exit [1-9]|ConnectionRefused|OSError)", err):
            return []  # legitimate GitHub outage, recorded
        return ["required CI: ENVIRONMENT_BLOCKED claimed without machine error+command"]
    checks = ci_status.get("checks") or {}
    if not isinstance(checks, dict):
        return ["required CI: checks must be a name→conclusion map"]
    out: list[str] = []
    for name in REQUIRED_CI_NAMES:
        raw = None
        for k, v in checks.items():
            if str(k).lower() == name or name in str(k).lower():
                raw = v
                break
        if raw is None:
            out.append(f"required CI: {name} missing (pending is not PASS)")
            continue
        conc = str(raw).strip().upper()
        if conc in {"PENDING", "QUEUED", "IN_PROGRESS", ""}:
            out.append(f"required CI: {name} is {conc or 'pending'} — not PASS")
        elif conc not in {"SUCCESS", "PASS"}:
            out.append(f"required CI: {name} is {conc} — completion blocked")
    return out


def load_required_ci_status(
    repo: Path | None = None,
    *,
    head_sha: str,
    injected: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if injected is not None:
        return injected
    repo = repo or REPO
    report = repo / "reports" / "required_ci_latest.json"
    if report.is_file():
        try:
            doc = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            doc = None
        if isinstance(doc, dict) and str(doc.get("sha") or "") == head_sha:
            return doc
    try:
        proc = subprocess.run(
            ["gh", "pr", "checks", "--json", "name,state,bucket"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {
            "sha": head_sha,
            "environment_blocked": True,
            "observed_error": f"{type(e).__name__}: {e}",
            "command": "gh pr checks --json name,state,bucket",
        }
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if re.search(r"(API rate|HTTP 5|connection|network|timeout)", err, re.I):
            return {
                "sha": head_sha,
                "environment_blocked": True,
                "observed_error": err or f"exit {proc.returncode}",
                "command": "gh pr checks --json name,state,bucket",
            }
        return None
    try:
        rows = json.loads(proc.stdout)
    except (ValueError, json.JSONDecodeError):
        return None
    checks: dict[str, str] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("name"):
                checks[str(row["name"])] = str(row.get("bucket") or row.get("state") or "")
    return {"sha": head_sha, "checks": checks}


def operator_guard_escape_granted(guard_name: str, *, repo: Path | None = None) -> bool:
    """Genuine operator emergency escape. Env-off alone is never enough.

    Distinguishable from agent self-authorization: operator_go.json must be
    granted=true, granted_by must start with 'operator', and scope must name
    'guard_escape' (or 'all'). Agents cannot grant this file without the
    existing GO / SoD machinery.
    """
    repo = repo or REPO
    try:
        doc = json.loads((repo / "governance" / "operator_go.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(doc, dict) or doc.get("granted") is not True:
        return False
    by = str(doc.get("granted_by") or "").strip().lower()
    if not by.startswith("operator"):
        return False
    scopes = doc.get("scope") or []
    if not isinstance(scopes, list):
        return False
    norm = {str(s).strip().lower() for s in scopes}
    if "guard_escape" not in norm and "all" not in norm:
        return False
    _ = guard_name  # named for the caller; grant is guard-wide emergency
    return True


def env_guard_is_disabled(env_name: str, *, repo: Path | None = None) -> bool:
    val = os.environ.get(env_name, "").strip().lower()
    if val not in _ENV_OFF:
        return False
    return operator_guard_escape_granted(env_name, repo=repo)


def stop_reentry_bypasses_hard_laws(payload: dict | None) -> bool:
    """Anti-loop may skip recursive hook invocation. It must never convert a violation into pass."""
    _ = payload
    return False


def production_l1_wiring_facts(src: str) -> dict[str, Any]:
    """AST / call-graph wiring. Not authenticated-feed proof."""
    tree = ast.parse(src)
    attrs: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                attrs.add(fn.attr)
            elif isinstance(fn, ast.Name):
                names.add(fn.id)
        if isinstance(node, ast.Name):
            names.add(node.id)
        if isinstance(node, ast.Attribute):
            attrs.add(node.attr)
    return {
        "proof_class": "static_wiring",
        "constructs_stream_client": "StreamClient" in names,
        "registers_level_one_handler": "add_level_one_equity_handler" in attrs,
        "subscribes_level_one": "level_one_equity_subs" in attrs,
        "consumes_via_push_level_one": "push_level_one" in names or "push_level_one" in attrs,
        "timesale_subs_present": "timesale_equity_subs" in attrs or "timesale_equity_subs" in names,
        "named_rest_fallback": "rest_fallback_explicit" in src,
    }


def current_head_sha(repo: Path | None = None) -> str:
    repo = repo or REPO
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def stop_hard_law_violations(
    *,
    repo: Path | None = None,
    payload: dict | None = None,
    master_text: str | None = None,
    baseline_text: str | None = None,
    dirty_paths: Iterable[str] | None = None,
) -> list[tuple[str, str]]:
    """Stop-only bundle: 5:1, idle-stop, blocker locality, method pivot."""
    repo = repo or REPO
    payload = payload or {}
    if master_text is None:
        master_text = payload.get("_master_text") or load_master_text(repo)
    if baseline_text is None:
        baseline_text = payload.get("_baseline_text")
        if baseline_text is None:
            try:
                baseline_text = load_master_text(repo, ref=payload.get("_baseline_ref") or BURN_DOWN_BASELINE_REF)
            except RuntimeError as e:
                return [("(burn_down_baseline)", str(e))]
    items = parse_master_items(master_text)
    bd = compute_burn_down(baseline_text, master_text)
    extra = list(payload.get("_applicable_ids") or [])
    dirty = list(dirty_paths or payload.get("_dirty_paths") or [])
    app = applicable_item_ids(
        items,
        dirty_paths=dirty,
        extra_ids=extra,
        include_p01b_cluster=payload.get("_include_p01b_cluster", True),
    )
    safe = safely_fixable_ids(items, app, repo=repo)
    remaining_blocked = bool(app) and not safe
    out: list[tuple[str, str]] = []
    out.extend(burn_down_ratio_violations(bd, remaining_all_legitimately_blocked=remaining_blocked))
    out.extend(idle_stop_violations(
        bd,
        safely_fixable_ids=safe,
        machine_active_work=bool(payload.get("_machine_active_work")),
    ))
    out.extend(blocker_locality_violations(items, app, repo=repo))
    attempts = payload.get("_method_attempts") or []
    next_fp = payload.get("_next_approach_fp") or ""
    stable = str(payload.get("_stable_failure_id") or "")
    if attempts and next_fp and stable:
        out.extend(method_pivot_violations(attempts, next_fingerprint=next_fp, stable_id=stable))
    return out
