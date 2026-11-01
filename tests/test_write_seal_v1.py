"""The seal carries the repository's own hooks, anchored, and locks them in."""

from __future__ import annotations

import json
from pathlib import Path

from tools import write_seal

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))


def _commands(settings: dict) -> list[str]:
    return [
        hook["command"]
        for groups in settings["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]


def test_every_hook_is_sealed_and_runs_from_the_given_checkout():
    root = Path("C:/production")
    seal = write_seal.sealed(SETTINGS, root)
    wired = _commands(SETTINGS)
    anchored = _commands(seal)
    assert len(anchored) == len(wired) > 0
    for command, plain in zip(anchored, wired, strict=True):
        program, script, *guards = command.split()
        assert program == "C:/production/.venv/Scripts/python.exe"
        assert script.startswith("C:/production/tools/")
        assert plain.split()[2:] == guards


def test_the_seal_refuses_every_other_hook():
    seal = write_seal.sealed(SETTINGS, Path("C:/production"))
    assert seal["allowManagedHooksOnly"] is True
    assert set(seal["hooks"]) == set(SETTINGS["hooks"])
    matchers = [group.get("matcher") for group in seal["hooks"]["PreToolUse"]]
    assert matchers == [group.get("matcher") for group in SETTINGS["hooks"]["PreToolUse"]]
