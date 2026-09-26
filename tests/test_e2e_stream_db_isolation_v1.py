"""Test processes own isolated runtime state and deterministic Schwab capability.

Negative controls poison every inherited input with live-looking values. The
canonical resolvers must still select one process-private root, preserve the
poisoned signal bytes, and fail Schwab closed without a second production
StreamClient.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_KEY = "ci-placeholder-api-key"
PLACEHOLDER_SECRET = "ci-placeholder-app-secret"


def _e2e_server_env(poison_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "ED_CONSOLE_DB": str(poison_root / "production_console.db"),
        "STREAM_CAPTURE_DB_PATH": str(poison_root / "production_stream.db"),
        "SCHWAB_TOKEN_PATH": str(poison_root / "production_token.json"),
        "ED_CI_OFFLINE": "0",
        "SCHWAB_API_KEY": "live-looking-inherited-key",
        "SCHWAB_APP_SECRET": "live-looking-inherited-secret",
        "ED_TERRAIN_QUARANTINE_LEDGER": str(poison_root / "production_terrain.jsonl"),
    })
    script = (
        "import {e2eServerEnv,e2eRuntimeRoot} from './playwright.config.mjs';"
        "console.log(JSON.stringify({env:e2eServerEnv,root:e2eRuntimeRoot}));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout.strip().splitlines()[-1])
    server_env = doc["env"]
    server_env["_E2E_RUNTIME_ROOT"] = doc["root"]
    return server_env


def test_e2e_boundary_rejects_poisoned_inherited_runtime_state(tmp_path):
    """Live-looking parent values cannot select E2E paths or make Schwab live."""
    server_env = _e2e_server_env(tmp_path)
    root = Path(server_env.pop("_E2E_RUNTIME_ROOT")).resolve()

    assert root.name.startswith("ed-console-e2e-runtime-")
    # RC-534: the one isolation knob is ED_RUNTIME_ROOT; the forbidden ambient DB overrides
    # are deleted from the server env, and the canonical DBs resolve under <root>/data.
    assert Path(server_env["ED_RUNTIME_ROOT"]).resolve() == root
    assert Path(server_env["ED_ARTIFACTS_ROOT"]).resolve() == root / "artifacts"
    assert "ED_CONSOLE_DB" not in server_env
    assert "STREAM_CAPTURE_DB_PATH" not in server_env
    for key in ("SCHWAB_TOKEN_PATH", "ED_TERRAIN_QUARANTINE_LEDGER"):
        resolved = Path(server_env[key]).resolve()
        assert resolved.parent == root, (key, resolved)
        assert tmp_path not in resolved.parents
    assert server_env["ED_CI_OFFLINE"] == "1"
    assert server_env["SCHWAB_API_KEY"] == PLACEHOLDER_KEY
    assert server_env["SCHWAB_APP_SECRET"] == PLACEHOLDER_SECRET


def test_e2e_boundary_blocks_an_inherited_valid_token_from_building_a_client(tmp_path):
    """A valid-looking parent token cannot cross the E2E capability boundary."""
    inherited_token = tmp_path / "production_token.json"
    inherited_token.write_text(json.dumps({
        "creation_timestamp": 1_788_000_000,
        "token": {
            "access_token": "live-looking-access-token",
            "refresh_token": "live-looking-refresh-token",
            "expires_at": 4_000_000_000,
            "token_type": "Bearer",
            "scope": "api",
        },
    }), encoding="utf-8")
    server_env = _e2e_server_env(tmp_path)
    server_env.pop("_E2E_RUNTIME_ROOT")

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json;"
                "from config import build_config;"
                "from schwab_client import build_client_from_token;"
                "cfg=build_config('.');"
                "state=build_client_from_token(cfg.token_path,cfg.api_key,cfg.app_secret);"
                "print(json.dumps({'ok':state.ok,'has_client':state.client is not None,"
                "'token_path':cfg.token_path}))"
            ),
        ],
        cwd=ROOT,
        env=server_env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert child.returncode == 0, child.stdout + child.stderr
    result = json.loads(child.stdout.strip())
    assert result["ok"] is False and result["has_client"] is False
    assert Path(result["token_path"]).resolve() != inherited_token.resolve()


