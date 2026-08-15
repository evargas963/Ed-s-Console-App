"""Monday debt wake — wall-clock alarm for RC-166 / RC-180 / RC-181 live proofs.

Writes a GO marker + copies the wake prompt to the clipboard (when possible) and
opens the prompt file so the operator can paste into Cursor/Claude immediately.

Intended host schedule: Mondays 08:25 America/Chicago (slightly before 08:30 CT RTH open).
See reports/monday_debt_alarm_setup.md.

Decide path: untouched (Collect / governance hygiene only).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
PROMPT_PATH = REPO / "reports" / "monday_debt_wake_prompt.md"
MARKER_DIR = REPO / "reports" / "_wake"
CT = ZoneInfo("America/Chicago")
#: RC-307: ET comes from the COH-SA-2 authority, never from a second local literal. This file
#: constructed its own eastern ZoneInfo, which is what that law forbids — two
#: definitions of the same zone drift independently and the older one is invisible. The
#: violation survived because the test enforcing it was walking the filesystem and drowning
#: in untracked scratch, so its genuine finding never reached a reader. CT stays local: the
#: operator's wall clock is Central and time_et is the MARKET calendar, which has no CT.
if str(REPO) not in sys.path:            # this module runs standalone from tools/
    sys.path.insert(0, str(REPO))
from time_et import ET  # noqa: E402


def _now_ct() -> datetime:
    return datetime.now(tz=CT)


def _write_marker(force: bool) -> Path:
    MARKER_DIR.mkdir(parents=True, exist_ok=True)
    now = _now_ct()
    day = now.date().isoformat()
    marker = MARKER_DIR / f"monday_debt_go_{day}.json"
    payload = {
        "status": "GO",
        "written_at_ct": now.isoformat(timespec="seconds"),
        "written_at_et": now.astimezone(ET).isoformat(timespec="seconds"),
        "next_rth_proof": "2026-08-03",
        "residue": ["RC-166", "RC-180", "RC-181"],
        "prompt_path": str(PROMPT_PATH.relative_to(REPO)).replace("\\", "/"),
        "force": bool(force),
        "operator_message": (
            "MONDAY DEBT WAKE — finish RC-166/180/181 live proofs. "
            "Paste reports/monday_debt_wake_prompt.md into Cursor or Claude. "
            "Halt words only: STOP / PAUSE / HANG IT UP / DO NOT CONTINUE."
        ),
    }
    marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    latest = MARKER_DIR / "monday_debt_go_LATEST.json"
    latest.write_text(marker.read_text(encoding="utf-8"), encoding="utf-8")
    return marker


def _copy_prompt_to_clipboard(text: str) -> bool:
    """Best-effort clipboard via PowerShell Set-Clipboard (Windows)."""
    if os.name != "nt":
        return False
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(text)
            tmp = fh.name
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-Content -Raw -Encoding UTF8 '{tmp}' | Set-Clipboard",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return True
    except Exception:
        return False


def _notify_windows(title: str, body: str) -> None:
    if os.name != "nt":
        return
    # Balloon via PowerShell; fail open if toast APIs unavailable.
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Information; "
        "$n.BalloonTipTitle = '" + title.replace("'", "''") + "'; "
        "$n.BalloonTipText = '" + body.replace("'", "''")[:220] + "'; "
        "$n.Visible = $true; "
        "$n.ShowBalloonTip(12000); "
        "Start-Sleep -Seconds 8; "
        "$n.Dispose()"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:  # institutional-swallow-ok: best-effort console beep on wake; a failed beep must never kill the wake itself
        pass


def _open_prompt() -> None:
    if not PROMPT_PATH.exists():
        print(f"MISSING_PROMPT {PROMPT_PATH}", file=sys.stderr)
        return
    if os.name == "nt":
        os.startfile(str(PROMPT_PATH))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(PROMPT_PATH)])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--force",
        action="store_true",
        help="Run even if today is not Monday (operator smoke).",
    )
    ap.add_argument(
        "--no-open",
        action="store_true",
        help="Write marker + notify only; do not open the prompt file.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended actions; write nothing.",
    )
    args = ap.parse_args(argv)

    now = _now_ct()
    is_monday = now.weekday() == 0
    if not is_monday and not args.force:
        print(
            f"SKIP not_monday ct={now.isoformat(timespec='seconds')} "
            f"(use --force for smoke)"
        )
        return 0

    if args.dry_run:
        print("DRY_RUN would write", MARKER_DIR / f"monday_debt_go_{now.date().isoformat()}.json")
        print("DRY_RUN prompt", PROMPT_PATH)
        return 0

    if not PROMPT_PATH.exists():
        print(f"FAIL missing {PROMPT_PATH}", file=sys.stderr)
        return 2

    marker = _write_marker(force=args.force)
    text = PROMPT_PATH.read_text(encoding="utf-8")
    clipped = _copy_prompt_to_clipboard(text)
    _notify_windows(
        "Ed Console — Monday debt wake",
        "RC-166 / RC-180 / RC-181 — paste monday_debt_wake_prompt.md into Cursor/Claude",
    )
    if not args.no_open:
        _open_prompt()

    print("GO", marker)
    print("CLIPBOARD", "ok" if clipped else "skipped")
    print("PROMPT", PROMPT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
