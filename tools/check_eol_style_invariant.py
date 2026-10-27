"""A file's line-ending style must survive an edit.

A writer that reconstructs a file can re-choose its terminator, so a one-line edit lands as a
whole-file diff that buries the intended change (an 8-line addition to .claude/settings.json
committed as 78 insertions / 71 deletions). This check refuses that before the commit.

The rule is tested on the BYTES, not as "use newline=''" or "pass lineterminator", which bind
one library at a time: whatever produced the change (a text-mode write, an editor, a script,
csv.DictWriter's CRLF), the file's terminator may not change.

Two refusals:
  PURE EOL REFLOW  — EOL-normalised content is IDENTICAL to HEAD but raw bytes differ.
                     The entire diff is noise; there is no intent to preserve.
  EOL STYLE FLIP   — content genuinely changed AND the dominant terminator switched.
                     The real edit is legitimate; the reflow riding along is not.

Exemptions are read from git, never guessed: binary blobs and paths marked `-text`.

Usage:
    python tools/check_eol_style_invariant.py            # staged changes (pre-commit)
    python tools/check_eol_style_invariant.py --measure  # worktree vs HEAD, reports only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, check=False,
    )


def _text(*args: str) -> str:
    out = _git(*args).stdout
    return out.decode("utf-8", errors="replace")


def changed_paths(staged: bool) -> list[str]:
    """Paths modified against HEAD. Staged for pre-commit, worktree for --measure."""
    args = ["diff", "--name-only", "--diff-filter=ACMR"]
    if staged:
        args.insert(1, "--cached")
    return [p for p in _text(*args).splitlines() if p.strip()]


def is_text_governed(path: str) -> bool:
    """False when git itself says this path is binary or `-text` (exempt).

    Read from git attributes rather than inferred from the extension.
    """
    attr = _text("check-attr", "text", "--", path).strip()
    if attr.endswith(": unset") or attr.endswith(": -text"):
        return False
    return True


def pinned_eol(path: str) -> str | None:
    """'lf'/'crlf' when .gitattributes pins this path's committed terminator, else None.

    A pinned path is one git NORMALISES on the way into the blob, so its worktree bytes are
    ALLOWED to differ from HEAD — that is the point of the pin (the harness can leave
    .claude/settings.json CRLF on disk; git stores it LF). Comparing raw worktree bytes for such a path would
    report a flip on a file behaving exactly as configured, so the comparison is made on the
    form git will STORE.
    """
    line = _text("check-attr", "eol", "--", path).strip()
    value = line.rsplit(":", 1)[-1].strip() if ":" in line else ""
    return value if value in ("lf", "crlf") else None


def apply_pin(data: bytes, pin: str | None) -> bytes:
    """The bytes git will commit for this content under its pin."""
    if pin == "lf":
        return data.replace(b"\r\n", b"\n")
    if pin == "crlf":
        return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data


def head_bytes(path: str) -> bytes | None:
    proc = _git("show", f"HEAD:{path}")
    return proc.stdout if proc.returncode == 0 else None


def current_bytes(path: str, staged: bool) -> bytes | None:
    if staged:
        proc = _git("show", f":{path}")
        return proc.stdout if proc.returncode == 0 else None
    p = REPO / path
    try:
        return p.read_bytes()
    except OSError:
        return None


def normalize(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def dominant_terminator(data: bytes) -> str | None:
    """'crlf', 'lf', or None when the file has no line endings to speak of."""
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    if crlf == 0 and lf == 0:
        return None
    return "crlf" if crlf >= lf else "lf"


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8000]


def violations(staged: bool = True) -> list[str]:
    out: list[str] = []
    for path in changed_paths(staged):
        before = head_bytes(path)
        if before is None:          # newly added file: no prior style to preserve
            continue
        after = current_bytes(path, staged)
        if after is None:
            continue
        # judge a pinned path on the form git will STORE, not on what the harness left on
        # disk, and apply the pin to BOTH sides: a blob committed against its pin (CRLF before
        # its pattern was pinned) compared raw would read as PURE EOL REFLOW on the commit that
        # restores it. The pin defines what a path's committed bytes MEAN wherever they are read.
        pin = pinned_eol(path)
        before, after = apply_pin(before, pin), apply_pin(after, pin)
        if before == after:
            continue
        if is_binary(before) or is_binary(after) or not is_text_governed(path):
            continue

        before_style, after_style = dominant_terminator(before), dominant_terminator(after)
        if normalize(before) == normalize(after):
            out.append(
                f"{path}: PURE EOL REFLOW — every changed line is a line-ending change and "
                f"nothing else ({before_style} -> {after_style}). The diff is 100% noise; "
                f"restore the original terminator."
            )
            continue
        if before_style and after_style and before_style != after_style:
            changed_lines = sum(
                1 for a, b in zip(before.split(b"\n"), after.split(b"\n")) if a != b
            )
            out.append(
                f"{path}: EOL STYLE FLIP — the content change is real, but the file's "
                f"terminator also switched {before_style} -> {after_style}, so ~{changed_lines} "
                f"lines report as changed and bury the intended edit. Write the file back with "
                f"its original terminator."
            )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Refuse commits that change a file's line-ending style")
    ap.add_argument("--measure", action="store_true",
                    help="check the worktree against HEAD and report without failing the gate")
    args = ap.parse_args(argv)

    bad = violations(staged=not args.measure)
    if not bad:
        scope = "worktree" if args.measure else "staged"
        print(f"[PASS] eol_style_invariant — no line-ending flips in {scope} changes")
        return 0
    print(f"[FAIL] eol_style_invariant — {len(bad)} violation(s):")
    for b in bad:
        print(f"  {b}")
    return 0 if args.measure else 1


if __name__ == "__main__":
    sys.exit(main())
