# institutional-synthetic-ok: temp directories stand in for a relocated runtime root.
"""RC-523 — runtime state is rooted in `runtime_layout`, not the source checkout.

Before this, every runtime path was `Path(__file__).parent / "data" | "logs" | "reports"`,
with an override for the database alone, so the production checkout had to be the desk's
cwd and runtime output polluted the source tree (docs/ARCHITECTURE.md §8). These controls
drive the real modules through a subprocess with the two variables set and unset, because
the roots are read at import.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PROBE = r"""
import json, runtime_layout as rl, db_authority as da, db, config
from tools import terrain_backtest_report_v1 as tb, operable_surface_gate as og
cfg = config.build_config(str(rl.SOURCE_ROOT))
print(json.dumps({
    "runtime_root": str(rl.RUNTIME_ROOT), "artifacts_root": str(rl.ARTIFACTS_ROOT),
    "canonical_db": str(da.canonical_console_db_path()), "db_path": str(db.DB_PATH),
    "db_dir": str(db.DB_DIR), "token": cfg.token_path, "barchart": cfg.barchart_dir,
    "terrain_json": str(tb.OUT_JSON), "terrain_history": str(tb.HISTORY),
    "operable_report": str(og.REPORT_LATEST), "separated": rl.describe()["separated"],
}))
"""


def _probe(env_extra: dict[str, str]) -> dict:
    env = dict(os.environ)
    for k in ("ED_RUNTIME_ROOT", "ED_ARTIFACTS_ROOT", "ED_CONSOLE_DB", "ED_DB_PATH"):
        env.pop(k, None)
    env["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] = "1"
    env.update(env_extra)
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=str(REPO), env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_unset_roots_are_the_source_checkout_so_nothing_moves():
    got = _probe({})
    root = str(REPO.resolve())
    assert got["separated"] == "False"
    assert got["runtime_root"] == root and got["artifacts_root"] == root
    assert Path(got["canonical_db"]) == REPO / "data" / "ed_console.db"
    assert Path(got["db_path"]) == REPO / "data" / "ed_console.db"
    assert Path(got["token"]) == REPO / "schwab_token.json"
    assert Path(got["terrain_json"]) == REPO / "reports" / "terrain_backtest_latest.json"
    assert Path(got["operable_report"]) == REPO / "reports" / "operable_surface_gate_latest.json"


def test_runtime_root_moves_database_token_and_data_and_artifacts_follow(tmp_path):
    rt = tmp_path / "runtime"
    got = _probe({"ED_RUNTIME_ROOT": str(rt)})
    assert got["separated"] == "True"
    assert Path(got["canonical_db"]) == (rt / "data" / "ed_console.db").resolve()
    assert Path(got["db_path"]) == (rt / "data" / "ed_console.db").resolve()
    assert Path(got["db_dir"]) == rt.resolve() / "data"
    assert Path(got["token"]) == rt.resolve() / "schwab_token.json"
    assert Path(got["barchart"]) == rt.resolve() / "data" / "barchart"
    # artifacts default to the runtime root
    assert Path(got["terrain_json"]) == rt.resolve() / "reports" / "terrain_backtest_latest.json"
    assert Path(got["terrain_history"]) == rt.resolve() / "reports" / "terrain_scorecard_history.jsonl"
    assert Path(got["operable_report"]) == rt.resolve() / "reports" / "operable_surface_gate_latest.json"
    # nothing under the source checkout is named any more
    for key in ("canonical_db", "db_path", "token", "terrain_json", "operable_report"):
        assert not Path(got[key]).is_relative_to(REPO.resolve()), (key, got[key])


def test_artifacts_root_separates_reports_from_runtime_state(tmp_path):
    rt, art = tmp_path / "runtime", tmp_path / "artifacts"
    got = _probe({"ED_RUNTIME_ROOT": str(rt), "ED_ARTIFACTS_ROOT": str(art)})
    assert Path(got["canonical_db"]) == (rt / "data" / "ed_console.db").resolve()
    assert Path(got["terrain_json"]) == art.resolve() / "reports" / "terrain_backtest_latest.json"
    assert Path(got["operable_report"]) == art.resolve() / "reports" / "operable_surface_gate_latest.json"


def test_the_explicit_db_override_still_wins_over_the_runtime_root(tmp_path):
    rt = tmp_path / "runtime"
    explicit = tmp_path / "elsewhere" / "ed_console.db"
    explicit.parent.mkdir(parents=True)
    explicit.write_bytes(b"")
    got = _probe({"ED_RUNTIME_ROOT": str(rt), "ED_CONSOLE_DB": str(explicit)})
    assert Path(got["db_path"]) == explicit.resolve()
    assert Path(got["canonical_db"]) == (rt / "data" / "ed_console.db").resolve()


def test_runtime_layout_imports_no_governance():
    """The owner of the runtime roots sits on the runtime path (RC-512 boundary)."""
    tree = ast.parse((REPO / "runtime_layout.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(m.split(".")[0] in ("tools", "governance") for m in imported), imported
    assert "config" not in imported, "runtime_layout must stay a leaf (config imports it)"


def test_no_runtime_path_is_rooted_in_the_source_checkout_any_more():
    """The shape RC-523 removed must not come back: `<file>.parent / "data"|"logs"|"reports"`
    or `APP_DIR / "reports"` in the runtime modules and the report-writing tools."""
    offenders: list[str] = []
    for rel in ("server.py", "db.py", "db_authority.py", "config.py", "desk_store.py",
                "stream_spine.py", "order_flow_streaming.py", "ticker_readiness_lookup.py",
                "tools/terrain_backtest_report_v1.py", "tools/operable_surface_gate.py",
                "tools/run_operable_surface_ops.py", "tools/ed_server_warn_quiet_window.py",
                "tools/console_liveness_check.py"):
        for i, line in enumerate((REPO / rel).read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if ('"data"' in line or '"logs"' in line or '"reports"' in line) and (
                    "__file__" in line or "APP_DIR" in line or "ROOT /" in line
                    or "project_root()" in line):
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert offenders == [], offenders
