"""Is this checkout actually able to run? A launch preflight, not a governance check.

WHY THIS EXISTS, measured on the production desk 2026-09-03. The launcher refused to start
with `SCHWAB_API_KEY / SCHWAB_APP_SECRET missing after sanitize`. The credentials were not
missing: `.env` was present with both keys non-empty. What was missing was `dotenv` — and
`config._load_dotenv_if_present()` does `except ImportError: return`, correctly treating
python-dotenv as optional, so the canonical load silently became a no-op and a broken
virtualenv wore the face of absent credentials.

The reason nothing caught it is the interesting part. `python_dotenv-1.2.2.dist-info` was still
in site-packages while the `dotenv/` package directory was gone, so:

    importlib.metadata           says python-dotenv 1.2.2 is installed
    pip                          says the requirement is satisfied
    a requirements.txt audit     said 22 of 22 satisfied, 0 missing
    import dotenv                ModuleNotFoundError

A GHOST distribution: metadata without payload. Every provisioning check in this repo asked
metadata, and metadata lied. The same scan found a second ghost, `python-dateutil`, which is
why `import pandas` also failed — the desk could not have loaded a bar even with credentials.

So this asks the question metadata cannot: does each installed distribution actually SHIP
importable files, and are they on disk? Ghost detection needs no distribution-name-to-import-
name mapping (`python-dotenv` -> `dotenv`, `scikit-learn` -> `sklearn`), because it reads what
the distribution itself claims to install. No mapping table, nothing to keep in sync.

WHAT THIS IS NOT. It is not a governance check and must never become one (RC-512: the launch
path executes no repository governance). It asks one runtime question — can this interpreter
run the app — exactly as the Schwab preflight asks whether live credentials are usable. It
imports nothing at launch, so it costs milliseconds rather than the ~40s a real import of the
ML stack would take.

Usage:
    python runtime_preflight.py            # exit 1 with a repair command when unprovisioned
    python runtime_preflight.py --report   # always exit 0, print what was found
"""
from __future__ import annotations

import argparse
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent

#: Extensions that make a shipped file importable. A distribution shipping only data or a
#: console script is legitimate; one shipping NO code at all, when its metadata says it does,
#: is the ghost this module exists to find.
CODE_SUFFIXES = (".py", ".pyd", ".so", ".dll")


def _site_dirs() -> list[Path]:
    """Where a distribution's RECORD paths are resolved from."""
    out = []
    for key in ("purelib", "platlib"):
        try:
            out.append(Path(sysconfig.get_paths()[key]))
        except KeyError:
            continue
    return list(dict.fromkeys(out))


def _top_level_names(dist) -> set[str]:
    """The import names this distribution claims to install.

    Read as RAW TEXT from `top_level.txt`, falling back to the first path segment of each
    RECORD line. `dist.files` answers the same question and is the obvious call, but MEASURED
    on this venv it costs 23.5s across 44k entries because it builds a path object per file —
    unusable in a launcher. These are one small read per distribution.

    Reading what the distribution itself declares is also what keeps this free of a
    distribution-name-to-import-name table (`python-dotenv` -> `dotenv`, `scikit-learn` ->
    `sklearn`): there is no mapping to maintain, and nothing to fall out of sync.
    """
    names: set[str] = set()
    try:
        top = dist.read_text("top_level.txt")
    except (OSError, ValueError):
        top = None
    if top:
        return {ln.strip() for ln in top.splitlines() if ln.strip()}
    try:
        record = dist.read_text("RECORD") or ""
    except (OSError, ValueError):
        return names
    for line in record.splitlines():
        path = line.split(",", 1)[0].strip().strip('"').replace("\\", "/")
        if not path or path.startswith(".."):
            continue                       # console scripts land outside site-packages
        seg = path.split("/", 1)[0]
        if seg.endswith((".dist-info", ".egg-info")) or seg in (".", ""):
            continue
        names.add(seg[:-3] if seg.endswith(".py") else seg)
    return names


def _installed(dists=None) -> list:
    """The distribution list, scanned ONCE.

    Each `metadata.distributions()` walk is cheap on its own but the three callers below used
    to do three of them, and a launch gate pays that on every start.
    """
    return list(metadata.distributions()) if dists is None else dists


def ghost_distributions(dists=None) -> list[tuple[str, str, str]]:
    """`(name, version, why)` for every distribution whose payload is absent.

    ONE rule, and deliberately only one: the distribution NAMES import modules and none of them
    are on disk. Both production ghosts are caught by it, because `top_level.txt` lives inside
    the .dist-info directory — the part that survives when the payload is deleted. MEASURED:
    python-dotenv's surviving dist-info still declared `dotenv`, python-dateutil's still
    declared `dateutil`, and neither directory existed.

    A first cut also flagged "declares NO importable module", and CI proved that wrong within
    one run: `cuda-toolkit 13.0.3.0` ships a toolchain and no Python module at all, and was
    reported as a broken install. A distribution that legitimately ships nothing importable
    cannot be told apart from one whose declaration was lost, so this makes no claim there.
    That is the residual gap, stated rather than papered over with an allowlist — a gate that
    cries wolf on a working environment gets switched off, taking the real protection with it.
    """
    sites = _site_dirs()

    def present(name: str) -> bool:
        return any((site / name).is_dir()
                   or any((site / f"{name}{ext}").is_file() for ext in CODE_SUFFIXES)
                   for site in sites)

    ghosts: list[tuple[str, str, str]] = []
    for dist in _installed(dists):
        name = (dist.metadata["Name"] or "").strip()
        if not name:
            continue
        declared = _top_level_names(dist)
        if declared and not any(present(n) for n in declared):
            ghosts.append((name, dist.version,
                           f"declares {sorted(declared)} — none present on disk"))
    return sorted(ghosts)


def undeclared_missing(req_file: Path, dists=None) -> list[str]:
    """Requirements named in `req_file` with no installed distribution at all."""
    if not req_file.is_file():
        return []
    installed = set()
    for dist in _installed(dists):
        name = (dist.metadata["Name"] or "").strip()
        if name:
            installed.add(name.replace("_", "-").replace(".", "-").lower())
    missing = []
    for raw in req_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = line
        for sep in ("[", "<", ">", "=", "!", "~", ";", " "):
            name = name.split(sep, 1)[0]
        key = name.strip().replace("_", "-").replace(".", "-").lower()
        if key and key not in installed:
            missing.append(name.strip())
    return sorted(set(missing))


def violations(dists=None) -> list[str]:
    dists = _installed(dists)
    out = []
    for name, version, why in ghost_distributions(dists):
        out.append(
            f"{name} {version} is registered as installed but {why}. Metadata says the "
            f"requirement is satisfied while `import` fails, so this reads downstream as a "
            f"missing config value rather than a broken virtualenv.")
    for name in undeclared_missing(ROOT / "requirements.txt", dists):
        out.append(f"{name} is declared in requirements.txt and is not installed.")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Refuse to launch an unprovisioned checkout")
    ap.add_argument("--report", action="store_true",
                    help="print findings and exit 0 (diagnosis, not a gate)")
    args = ap.parse_args(argv)

    dists = _installed()
    bad = violations(dists)
    if not bad:
        print(f"runtime_preflight: OK ({len(dists)} distributions, "
              f"no ghosts, requirements.txt satisfied)")
        return 0

    print("=" * 72, file=sys.stderr)
    print("LAUNCH BLOCKED: this checkout is not provisioned to run.", file=sys.stderr)
    for line in bad:
        print(f"  - {line}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Repair, from the repo root:", file=sys.stderr)
    print('  .venv\\Scripts\\python.exe -m pip install --force-reinstall -r requirements.txt',
          file=sys.stderr)
    print("(--force-reinstall is required: pip trusts the same metadata that is wrong, so a "
          "plain install reports 'already satisfied' and repairs nothing.)", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    if args.report:
        return 0                      # diagnosis prints and exits clean
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
