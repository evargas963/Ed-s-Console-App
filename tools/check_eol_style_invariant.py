"""RC-382 — a file's line-ending style must survive an edit.

WHY THIS EXISTS. Three times in one session a one-line intent produced a whole-file
diff, because the writer reconstructed the file and re-chose its terminator:

  RC-372  a test restored the real AGENTS.md through a platform-newline text write,
          flipping the charter LF->CRLF on every run and breaking audit identity.
  .claude/settings.json   an 8-line addition committed as 78 insertions / 71 deletions.
  RC-381 slice 1          a 15-line declaration pass committed as 2428 / 2427, because
          three files were LF in the blob and landed as CRLF.

Each was caught by reading `git diff --numstat` AFTER committing, which is a human
choosing to look. That is not a control.

WHAT THIS LOCKS, and why it is stated as an outcome. The rule is not "use newline=''"
or "pass lineterminator" — those bind one library at a time, and the class already
arrived through three different writers (a text-mode restore, an editor, and a hand
script) plus a near-miss through a fourth (csv.DictWriter emits CRLF regardless of how
the handle was opened). So the invariant is tested on the BYTES: whatever produced the
change, the file's terminator may not change. A writer nobody anticipated is covered by
construction.

Two refusals:
  PURE EOL REFLOW  — EOL-normalised content is IDENTICAL to HEAD but raw bytes differ.
                     The entire diff is noise; there is no intent to preserve.
  EOL STYLE FLIP   — content genuinely changed AND the dominant terminator switched.
                     The real edit is legitimate; the reflow riding along is not.

Exemptions are read from git, never guessed: binary blobs and paths marked `-text`
(models/** carries it, because ML_PIPE Item 4 pins exact artifact bytes).

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

    Read from git attributes rather than inferred from the extension: models/** is
    deliberately `-text` because the bundle integrity manifests pin exact bytes, and
    guessing by suffix would either miss that or invent exemptions of its own.
    """
    attr = _text("check-attr", "text", "--", path).strip()
    if attr.endswith(": unset") or attr.endswith(": -text"):
        return False
    return True


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
        if after is None or before == after:
            continue
        if is_binary(before) or is_binary(after) or not is_text_governed(path):
            continue

        before_style, after_style = dominant_terminator(before), dominant_terminator(after)
        if normalize(before) == normalize(after):
            out.append(
                f"{path}: PURE EOL REFLOW — every changed line is a line-ending change and "
                f"nothing else ({before_style} -> {after_style}). The diff is 100% noise; "
                f"restore the original terminator (RC-382)."
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
                f"its original terminator (RC-382)."
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
