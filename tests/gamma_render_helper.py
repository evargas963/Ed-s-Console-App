"""Test helper: the gamma heatmap from Schwab's chain to the drawn cell. A chain capture published
by the levels producer (server._publish_levels, as at startup and on a closed market), served by
the heatmap's answer at the capture's time (server.gamma_surface_payload) and drawn by the page's
own render (static/js/ed-gamma.js, through tests/ed_gamma_cells_node.mjs)."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import server


def drawn(tk: str, contracts: list, spot: float, now: datetime, tmp_path: Path) -> "tuple[dict, dict]":
    """`contracts` captured at `now` with Schwab's underlying price `spot`, published, served for
    every strike and column and drawn: (surface, {(strike, expiry): text})."""
    node = shutil.which("node")
    assert node, "Node.js is required on PATH (the same prerequisite as Playwright E2E)"
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    try:
        server._publish_levels(tk, captures=[{"contracts": contracts, "ts_utc": now.timestamp(), "spot": spot,
                                              "spot_ts": None, "spot_from_chain": False, "et_date": now.date().isoformat(),
                                              "basis": server.CAPTURE_BASIS}],
                               now=now)
        surface = server.gamma_surface_payload(tk, "all", None, 0, None, None, now)
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
    path = tmp_path / "surface.json"
    path.write_text(json.dumps(surface), encoding="utf-8")
    r = subprocess.run([node, str(Path(__file__).parent / "ed_gamma_cells_node.mjs"), str(path)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return surface, {(c["strike"], c["expiry"]): c["text"] for c in map(json.loads, r.stdout.splitlines())}
