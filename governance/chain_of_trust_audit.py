"""
Chain-of-trust audit: consumer field reads must resolve to Schwab leaves or allowlisted sources.

Builds producer→consumer linkage from:
  - Section derivation inventories (§1–§16)
  - AST extraction of dict/SignalInput reads (consumers) and writes (producers)
  - Recursive resolution for KEEP_DERIVED inventory rows
"""

from __future__ import annotations

import ast
import importlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent

# Downstream consumers (per Path A plan)
CONSUMER_SECTIONS = (4, 6, 7, 10, 11, 13, 14, 16)

# Upstream producers (Schwab ingest + canonical builders)
PRODUCER_SECTIONS = (1, 2, 3, 4, 5, 9)

SCHWAB_LEAF_MARKERS = (
    "chains.",
    "quotes.",
    "pricehistory.",
    "pricehistory.candles",
)

ALLOWLIST_LEAF_MARKERS = (
    "clock",
    "et",
    "sqlite",
    "env",
    "macro",
    "calendar",
    "finnhub",
    "alphavantage",
    "external api",
    "http 429",
    "contract schema",
    "feature contract",
    "sql template",
    "labeled counts",
    "audit counter",
    "universe config",
    "ticker metadata",
    "design constant",
    "display",
    "formatter",
    "cli",
    "oauth",
    "token",
    "none",
    "—",
)

# Critical fields that must close (user contamination examples + SignalInput price/structure)
PRIORITY_FIELDS: tuple[tuple[str, str], ...] = (
    ("ms_dict", "spot"),
    ("ms_dict", "bid"),
    ("ms_dict", "ask"),
    ("ms_dict", "net_gamma"),
    ("ms_dict", "net_delta"),
    ("ms_dict", "iv_level"),
    ("ms_dict", "atm_iv"),
    ("ms_dict", "mc_iv_level"),
    ("ms_dict", "realized_vol"),
    ("ms_dict", "vwap"),
    ("ms_dict", "zone"),
    ("ms_dict", "call_gamma_wall"),
    ("ms_dict", "put_gamma_wall"),
    ("signal_input", "spot"),
    ("signal_input", "net_gamma"),
    ("signal_input", "iv_level"),
    ("signal_input", "vwap"),
    ("signal_input", "zone"),
    ("snapshot", "spot"),
    ("mvp", "price.spot"),
    ("mvp", "structure.net_gamma"),
    ("mvp", "structure.zone"),
    ("mvp", "anchor.vwap_side"),
)

# Known primary producers (architecture anchors)
FIELD_PRODUCER_OVERRIDES: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("ms_dict", "spot"): [
        ("server.py", "_build_rest_fast_quote_payload"),
        ("server.py", "_fetch_state"),
        ("market_state.py", "build_market_state"),
    ],
    ("ms_dict", "bid"): [
        ("server.py", "_build_rest_fast_quote_payload"),
        ("market_state.py", "build_market_state"),
    ],
    ("ms_dict", "ask"): [
        ("server.py", "_build_rest_fast_quote_payload"),
        ("market_state.py", "build_market_state"),
    ],
    ("ms_dict", "net_gamma"): [
        ("math_exposure_core.py", "compute_exposures_by_strike"),
        ("market_state.py", "build_market_state"),
    ],
    ("ms_dict", "net_delta"): [
        ("math_exposure_core.py", "compute_exposures_by_strike"),
        ("market_state.py", "build_market_state"),
    ],
    ("ms_dict", "zone"): [("market_state.py", "build_market_state"), ("market_state.py", "derive_zone")],
    ("ms_dict", "vwap"): [("market_context.py", "fetch_price_levels"), ("market_state.py", "build_market_state")],
    ("ms_dict", "iv_level"): [("market_state.py", "build_market_state")],
    ("ms_dict", "atm_iv"): [("math_exposure_core.py", "compute_exposures_by_strike"), ("market_state.py", "build_market_state")],
    ("ms_dict", "mc_iv_level"): [("server.py", "_fetch_state"), ("market_state.py", "build_market_state")],
    ("ms_dict", "call_gamma_wall"): [("market_state.py", "build_market_state"), ("math_levels.py", "build_summary_rows")],
    ("ms_dict", "put_gamma_wall"): [("market_state.py", "build_market_state"), ("math_levels.py", "build_summary_rows")],
    ("signal_input", "spot"): [("market_state.py", "build_market_state")],
    ("signal_input", "net_gamma"): [("market_state.py", "build_market_state")],
    ("signal_input", "iv_level"): [("market_state.py", "build_market_state")],
    ("signal_input", "vwap"): [("market_state.py", "build_market_state")],
    ("signal_input", "zone"): [("market_state.py", "build_market_state")],
    ("snapshot", "spot"): [("market_state.py", "build_market_state"), ("features/inference_snapshot.py", "build_inference_snapshot_v1")],
    ("l1_payload", "spot"): [("server.py", "_fetch_state"), ("server.py", "_build_rest_fast_quote_payload")],
    ("l1_payload", "net_gamma"): [("market_state.py", "build_market_state")],
    ("l1_payload", "zone"): [("market_state.py", "build_market_state")],
    ("l1_payload", "vwap_side"): [("market_context.py", "fetch_price_levels")],
    ("mvp", "price.spot"): [("features/live_feature_adapter.py", "build_live_mvp_feature_row")],
    ("mvp", "structure.net_gamma"): [("features/live_feature_adapter.py", "build_live_mvp_feature_row")],
    ("mvp", "structure.zone"): [("features/live_feature_adapter.py", "build_live_mvp_feature_row")],
    ("mvp", "anchor.vwap_side"): [("features/live_feature_adapter.py", "build_live_mvp_feature_row")],
}

MS_ROOT_NAMES = frozenset({"ms", "ms_dict", "market_state", "state"})
SNAPSHOT_ROOT_NAMES = frozenset({"snapshot", "row", "snap", "payload", "features", "feat"})
L1_ROOT_NAMES = frozenset({"l1_payload", "l1", "tier_b", "ctx_l1"})
INP_ROOT_NAMES = frozenset({"inp", "signal_inp", "sig_inp", "signal_input", "si"})

# MVP canonical key -> Tier B / L1 payload key
MVP_L1_SOURCE_KEYS: dict[str, str] = {
    "price.spot": "spot",
    "price.spread_pts": "spread_pts",
    "structure.zone": "zone",
    "structure.nearest_above_dist": "nearest_above_dist",
    "structure.nearest_below_dist": "nearest_below_dist",
    "structure.net_gamma": "net_gamma",
    "anchor.vwap_side": "vwap_side",
    "anchor.vwap_dist_pts": "dist_to_vwap_pts",
}

# Composition roots: must verify ms_dict deps close before ALLOWLISTED
COMPOSITION_ROOT_CHECKS: dict[tuple[str, str], tuple[str, ...]] = {
    ("market_state.py", "build_market_state"): (
        "spot",
        "bid",
        "ask",
        "net_gamma",
        "net_delta",
        "zone",
    ),
}

WRITE_SCAN_SKIP_FILES = frozenset({"db.py", "db_safety.py", "db_authority.py", "db_health_audit.py"})

PRODUCER_FN_PREFIXES = (
    "build_",
    "compute_",
    "normalize_",
    "fetch_",
    "derive_",
    "attach_",
    "refresh_",
    "_build_",
    "_fetch_",
    "run_weighted",
    "get_sentiment",
)


class TrustStatus(str, Enum):
    SCHWAB_LEAF = "schwab_leaf"
    ALLOWLISTED = "allowlisted"
    UNRESOLVED = "unresolved"
    CYCLIC = "cyclic"


@dataclass(frozen=True)
class FieldRef:
    carrier: str
    name: str


@dataclass
class TrustGap:
    consumer_file: str
    consumer_fn: str
    field: FieldRef
    reason: str


@dataclass
class ChainAuditResult:
    consumer_reads: int
    gaps: list[TrustGap] = field(default_factory=list)
    priority_gaps: list[TrustGap] = field(default_factory=list)

    @property
    def closes(self) -> bool:
        return not self.gaps and not self.priority_gaps


def _load_section(section_num: int) -> tuple[frozenset[str], tuple[Any, ...]]:
    mod = importlib.import_module(f"governance.section{section_num}_derivation_inventory")
    files = getattr(mod, f"SECTION{section_num}_FILES")
    inv = getattr(mod, f"SECTION{section_num}_DERIVATION_INVENTORY")
    return files, inv


def _all_section_files(nums: Iterable[int]) -> frozenset[str]:
    out: set[str] = set()
    for n in nums:
        files, _ = _load_section(n)
        out.update(files)
    return frozenset(out)


def _inventory_index(nums: Iterable[int]) -> dict[tuple[str, str], Any]:
    idx: dict[tuple[str, str], Any] = {}
    for n in nums:
        _, inv = _load_section(n)
        for row in inv:
            idx[(row.file, row.derivation)] = row
    return idx


def _is_schwab_leaf_text(leaf: str) -> bool:
    low = (leaf or "").lower()
    return any(m in low for m in SCHWAB_LEAF_MARKERS)


def _is_allowlisted_leaf(leaf: str, disposition: str) -> bool:
    if disposition == "NONE":
        low = (leaf or "").lower()
        return any(m in low for m in ALLOWLIST_LEAF_MARKERS) or low in ("—", "-", "")
    low = (leaf or "").lower()
    return any(m in low for m in ALLOWLIST_LEAF_MARKERS)


def _fn_body(repo_root: Path, rel: str, qual: str) -> str:
    from governance.section_inventory_gate import all_functions_in_file

    text = (repo_root / rel).read_text(encoding="utf-8")
    tree = ast.parse(text)
    for fn in all_functions_in_file(repo_root, rel):
        if fn.qualified_name != qual:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.lineno == fn.line
                and node.name == qual.split(".")[-1]
            ):
                seg = ast.get_source_segment(text, node)
                if seg:
                    return seg
                end = node.end_lineno or node.lineno
                return "\n".join(text.splitlines()[node.lineno - 1 : end])
    return ""


class _FieldReadVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.reads: set[FieldRef] = set()

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.value, ast.Name):
            base = node.value.id
            key = _const_key(node.slice)
            if key is None:
                return
            if base in MS_ROOT_NAMES:
                self.reads.add(FieldRef("ms_dict", key))
            elif base in SNAPSHOT_ROOT_NAMES:
                self.reads.add(FieldRef("snapshot", key))
            elif base in L1_ROOT_NAMES:
                self.reads.add(FieldRef("l1_payload", key))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if isinstance(node.func.value, ast.Name):
                base = node.func.value.id
                if node.args:
                    key = _const_key(node.args[0])
                    if key:
                        if base in MS_ROOT_NAMES:
                            self.reads.add(FieldRef("ms_dict", key))
                        elif base in SNAPSHOT_ROOT_NAMES:
                            self.reads.add(FieldRef("snapshot", key))
                        elif base in L1_ROOT_NAMES:
                            self.reads.add(FieldRef("l1_payload", key))
        if isinstance(node.func, ast.Name) and node.func.id == "SignalInput":
            for kw in node.keywords:
                if kw.arg:
                    self.reads.add(FieldRef("signal_input", kw.arg))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id in INP_ROOT_NAMES:
            self.reads.add(FieldRef("signal_input", node.attr))
        self.generic_visit(node)


class _FieldWriteVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.writes: set[FieldRef] = set()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "SignalInput":
            for kw in node.keywords:
                if kw.arg:
                    self.writes.add(FieldRef("signal_input", kw.arg))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for tgt in node.targets:
            if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name):
                if tgt.value.id in MS_ROOT_NAMES:
                    self.writes.add(FieldRef("ms_dict", tgt.attr))
            elif isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name):
                key = _const_key(tgt.slice)
                if key and tgt.value.id in MS_ROOT_NAMES | SNAPSHOT_ROOT_NAMES:
                    carrier = "ms_dict" if tgt.value.id in MS_ROOT_NAMES else "snapshot"
                    self.writes.add(FieldRef(carrier, key))
        self.generic_visit(node)


def _const_key(slice_node: ast.AST) -> str | None:
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        return slice_node.value
    return None


def extract_reads(repo_root: Path, rel: str, qual: str) -> set[FieldRef]:
    import textwrap

    body = _fn_body(repo_root, rel, qual)
    if not body:
        return set()
    try:
        tree = ast.parse(body)
    except SyntaxError:
        try:
            tree = ast.parse(textwrap.dedent(body))
        except SyntaxError:
            return set()
    v = _FieldReadVisitor()
    v.visit(tree)
    # dotted MVP keys in .get("price.spot")
    for m in re.finditer(r"""\.get\(\s*["']([a-z][a-z0-9_.]+)["']""", body):
        key = m.group(1)
        if "." in key:
            v.reads.add(FieldRef("mvp", key))
        elif key in ("spot", "bid", "ask"):
            v.reads.add(FieldRef("ms_dict", key))
    return v.reads


def extract_writes_in_function(repo_root: Path, rel: str, qual: str) -> set[FieldRef]:
    body = _fn_body(repo_root, rel, qual)
    if not body:
        return set()
    import textwrap

    try:
        tree = ast.parse(body)
    except SyntaxError:
        tree = ast.parse(textwrap.dedent(body))
    v = _FieldWriteVisitor()
    v.visit(tree)
    return v.writes


def _likely_producer_fn(qual: str) -> bool:
    name = qual.split(".")[-1]
    return any(name.startswith(p) for p in PRODUCER_FN_PREFIXES)


def build_producer_index(repo_root: Path) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Map (carrier, field) -> [(file, qualified_fn), ...]."""
    idx: dict[tuple[str, str], list[tuple[str, str]]] = {}
    producer_files = _all_section_files(PRODUCER_SECTIONS)
    from governance.section_inventory_gate import all_functions_in_file

    for rel in sorted(producer_files):
        if rel in WRITE_SCAN_SKIP_FILES:
            continue
        for fn in all_functions_in_file(repo_root, rel):
            if not _likely_producer_fn(fn.qualified_name):
                continue
            for w in extract_writes_in_function(repo_root, rel, fn.qualified_name):
                idx.setdefault((w.carrier, w.name), []).append((rel, fn.qualified_name))
    for key, producers in FIELD_PRODUCER_OVERRIDES.items():
        idx.setdefault(key, [])
        for p in producers:
            if p not in idx[key]:
                idx[key].append(p)
    return idx


@dataclass
class _Resolution:
    status: TrustStatus
    detail: str


def resolve_function(
    repo_root: Path,
    inv: dict[tuple[str, str], Any],
    producer_idx: dict[tuple[str, str], list[tuple[str, str]]],
    file: str,
    qual: str,
    *,
    visited: frozenset[tuple[str, str]] | None = None,
) -> _Resolution:
    key = (file, qual)
    if visited is None:
        visited = frozenset()
    if key in visited:
        return _Resolution(TrustStatus.CYCLIC, f"cycle at {file}:{qual}")
    visited = visited | {key}

    row = inv.get(key)
    if row is None:
        return _Resolution(TrustStatus.UNRESOLVED, f"no inventory row for {file}:{qual}")

    leaf = str(row.schwab_leaf or "")
    disp = str(row.disposition or "")

    if disp in ("PASS_THROUGH", "REPLACED") and _is_schwab_leaf_text(leaf):
        return _Resolution(TrustStatus.SCHWAB_LEAF, leaf)

    comp_deps = COMPOSITION_ROOT_CHECKS.get(key)
    if comp_deps is not None:
        for dep in comp_deps:
            sub = resolve_field_for_consumer(
                repo_root, inv, producer_idx, FieldRef("ms_dict", dep), _field_seen=visited
            )
            if sub.status not in (TrustStatus.SCHWAB_LEAF, TrustStatus.ALLOWLISTED):
                return _Resolution(
                    TrustStatus.UNRESOLVED,
                    f"composition root {file}:{qual} missing closed dep ms_dict.{dep}: {sub.detail}",
                )
        return _Resolution(TrustStatus.ALLOWLISTED, f"composition root {file}:{qual}")

    if disp == "PASS_THROUGH" and not _is_schwab_leaf_text(leaf):
        return _resolve_dependency_reads(repo_root, inv, producer_idx, file, qual, visited)

    if disp == "NONE" and _is_allowlisted_leaf(leaf, disp):
        return _Resolution(TrustStatus.ALLOWLISTED, leaf or "NONE")

    if disp == "KEEP_DERIVED":
        return _resolve_dependency_reads(repo_root, inv, producer_idx, file, qual, visited)

    if _is_allowlisted_leaf(leaf, disp):
        return _Resolution(TrustStatus.ALLOWLISTED, leaf)

    return _Resolution(TrustStatus.UNRESOLVED, f"{disp} {file}:{qual} leaf={leaf!r}")


def _resolve_dependency_reads(
    repo_root: Path,
    inv: dict[tuple[str, str], Any],
    producer_idx: dict[tuple[str, str], list[tuple[str, str]]],
    file: str,
    qual: str,
    visited: frozenset[tuple[str, str]],
) -> _Resolution:
    reads = extract_reads(repo_root, file, qual)
    if not reads:
        row = inv.get((file, qual))
        leaf = str(getattr(row, "schwab_leaf", "") or "")
        if _is_schwab_leaf_text(leaf):
            return _Resolution(TrustStatus.SCHWAB_LEAF, leaf)
        if row and _is_allowlisted_leaf(leaf, str(row.disposition)):
            return _Resolution(TrustStatus.ALLOWLISTED, leaf)
        return _Resolution(
            TrustStatus.UNRESOLVED,
            f"{file}:{qual} has no extractable reads and leaf={leaf!r}",
        )
    for r in reads:
        sub = resolve_field_for_consumer(repo_root, inv, producer_idx, r, _field_seen=visited)
        if sub.status not in (TrustStatus.SCHWAB_LEAF, TrustStatus.ALLOWLISTED):
            return _Resolution(
                TrustStatus.UNRESOLVED,
                f"{file}:{qual} depends on {r.carrier}.{r.name}: {sub.detail}",
            )
    return _Resolution(TrustStatus.ALLOWLISTED, f"deps closed ({file}:{qual})")


def resolve_field_for_consumer(
    repo_root: Path,
    inv: dict[tuple[str, str], Any],
    producer_idx: dict[tuple[str, str], list[tuple[str, str]]],
    field: FieldRef,
    *,
    _field_seen: frozenset[tuple[str, str]] | None = None,
) -> _Resolution:
    # signal_input mirrors ms_dict when built inside build_market_state
    if field.carrier == "signal_input":
        ms_res = resolve_field_for_consumer(
            repo_root, inv, producer_idx, FieldRef("ms_dict", field.name), _field_seen=_field_seen
        )
        if ms_res.status in (TrustStatus.SCHWAB_LEAF, TrustStatus.ALLOWLISTED):
            return ms_res

    # MVP features map through L1 payload keys
    if field.carrier == "mvp":
        l1_key = MVP_L1_SOURCE_KEYS.get(field.name)
        if l1_key:
            l1_res = resolve_field_for_consumer(
                repo_root, inv, producer_idx, FieldRef("l1_payload", l1_key), _field_seen=_field_seen
            )
            if l1_res.status in (TrustStatus.SCHWAB_LEAF, TrustStatus.ALLOWLISTED):
                return l1_res

    producers = list(producer_idx.get((field.carrier, field.name), []))
    if not producers:
        return _Resolution(TrustStatus.UNRESOLVED, f"no producer registered for {field.carrier}.{field.name}")
    for pf, pq in producers:
        res = resolve_function(repo_root, inv, producer_idx, pf, pq, visited=_field_seen)
        if res.status in (TrustStatus.SCHWAB_LEAF, TrustStatus.ALLOWLISTED):
            return res
    return _Resolution(
        TrustStatus.UNRESOLVED,
        f"producers for {field.carrier}.{field.name} do not close: {producers[:3]}",
    )


def run_chain_of_trust_audit(repo_root: Path | None = None) -> ChainAuditResult:
    repo_root = repo_root or ROOT
    inv = _inventory_index(range(1, 17))
    producer_idx = build_producer_index(repo_root)
    consumer_files = _all_section_files(CONSUMER_SECTIONS)
    from governance.section_inventory_gate import all_functions_in_file

    gaps: list[TrustGap] = []
    read_count = 0

    for rel in sorted(consumer_files):
        for fn in all_functions_in_file(repo_root, rel):
            row = inv.get((rel, fn.qualified_name))
            if row is None:
                continue
            if row.disposition == "NONE":
                continue
            reads = extract_reads(repo_root, rel, fn.qualified_name)
            read_count += len(reads)
            for field in sorted(reads, key=lambda f: (f.carrier, f.name)):
                res = resolve_field_for_consumer(repo_root, inv, producer_idx, field)
                if res.status not in (TrustStatus.SCHWAB_LEAF, TrustStatus.ALLOWLISTED):
                    gaps.append(
                        TrustGap(
                            consumer_file=rel,
                            consumer_fn=fn.qualified_name,
                            field=field,
                            reason=res.detail,
                        )
                    )

    priority_gaps: list[TrustGap] = []
    for carrier, name in PRIORITY_FIELDS:
        field = FieldRef(carrier, name)
        res = resolve_field_for_consumer(repo_root, inv, producer_idx, field)
        if res.status not in (TrustStatus.SCHWAB_LEAF, TrustStatus.ALLOWLISTED):
            priority_gaps.append(
                TrustGap(
                    consumer_file="(priority)",
                    consumer_fn="(priority)",
                    field=field,
                    reason=res.detail,
                )
            )

    return ChainAuditResult(
        consumer_reads=read_count,
        gaps=gaps,
        priority_gaps=priority_gaps,
    )


def format_gap_report(result: ChainAuditResult, *, limit: int = 50) -> str:
    lines = [
        f"Chain-of-trust: {len(result.priority_gaps)} priority gap(s), "
        f"{len(result.gaps)} consumer read gap(s) ({result.consumer_reads} reads scanned)",
    ]
    for g in (result.priority_gaps + result.gaps)[:limit]:
        lines.append(
            f"  {g.consumer_file}:{g.consumer_fn} "
            f"{g.field.carrier}.{g.field.name} — {g.reason}"
        )
    rest = len(result.priority_gaps) + len(result.gaps) - limit
    if rest > 0:
        lines.append(f"  ... and {rest} more")
    return "\n".join(lines)


def assert_chain_of_trust_closes(repo_root: Path | None = None) -> ChainAuditResult:
    result = run_chain_of_trust_audit(repo_root)
    problems = result.priority_gaps or result.gaps
    if problems:
        raise AssertionError(format_gap_report(result))
    return result


if __name__ == "__main__":
    import sys

    outcome = run_chain_of_trust_audit()
    print(format_gap_report(outcome, limit=100))
    sys.exit(0 if outcome.closes else 1)
