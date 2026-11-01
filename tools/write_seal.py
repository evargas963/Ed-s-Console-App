"""Write the seal: the repository's hooks as managed settings, out of the agent's reach.

Claude Code reads `C:/Program Files/ClaudeCode/managed-settings.json` above every other settings
file, and changing it takes Windows administrator rights, so the agent cannot switch a hook off.
The hooks run from the production checkout, which moves only by merges `locks` has judged.

The operator runs this once, in an administrator shell, from the production checkout, and again
when a merge changes the hooks in `.claude/settings.json`:

    .venv/Scripts/python.exe tools/write_seal.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEAL = Path("C:/Program Files/ClaudeCode/managed-settings.json")


def _anchored(command: str, root: Path) -> str:
    """Return `command` with its program and script as absolute paths under `root`."""
    program, script, *rest = command.split()
    return " ".join([(root / program).as_posix(), (root / script).as_posix(), *rest])


def sealed(settings: dict, root: Path) -> dict:
    """Return the managed settings for the hooks in `settings`, run from `root`."""
    hooks = {
        event: [
            {
                **group,
                "hooks": [
                    {**hook, "command": _anchored(hook["command"], root)} for hook in group["hooks"]
                ],
            }
            for group in groups
        ]
        for event, groups in settings["hooks"].items()
    }
    return {
        "allowManagedHooksOnly": True,
        "hooks": hooks,
        "permissions": {"disableBypassPermissionsMode": "disable"},
    }


def main() -> int:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    SEAL.parent.mkdir(exist_ok=True)
    SEAL.write_text(json.dumps(sealed(settings, ROOT), indent=2), encoding="utf-8")
    print(f"sealed {SEAL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
