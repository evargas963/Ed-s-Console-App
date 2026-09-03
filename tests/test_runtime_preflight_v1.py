"""RC-513 — a broken virtualenv must not be able to wear the face of missing config.

OBSERVED on the production desk 2026-09-03. The launcher refused to start with
`SCHWAB_API_KEY / SCHWAB_APP_SECRET missing after sanitize`. The credentials were not missing:
`.env` was present with both keys non-empty. `dotenv` was missing — and
`config._load_dotenv_if_present()` does `except ImportError: return`, correctly treating
python-dotenv as optional, so the canonical load silently became a no-op.

What made it invisible: `python_dotenv-1.2.2.dist-info` was still in site-packages while the
`dotenv/` package directory was gone. importlib.metadata, pip, and a full requirements.txt
audit all reported the requirement SATISFIED (22 of 22, 0 missing) while `import dotenv` raised
ModuleNotFoundError. A second ghost, `python-dateutil`, was breaking `import pandas` at the
same time.

Every planted case below is that exact shape, built as a real .dist-info on disk rather than a
mock, because the defect lives in what metadata says versus what is actually installed.
"""
from __future__ import annotations

import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import runtime_preflight as rp  # noqa: E402


def make_dist(site: Path, name: str, version: str, record_lines: list[str],
              top_level: str | None = None) -> metadata.Distribution:
    """A real .dist-info directory, so the code under test reads real metadata."""
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8")
    (info / "RECORD").write_text("\n".join(record_lines) + "\n", encoding="utf-8")
    if top_level is not None:
        (info / "top_level.txt").write_text(top_level, encoding="utf-8")
    return metadata.Distribution.at(info)


@pytest.fixture()
def site(tmp_path, monkeypatch):
    sp = tmp_path / "site-packages"
    sp.mkdir()
    monkeypatch.setattr(rp, "_site_dirs", lambda: [sp])
    return sp


def test_the_exact_production_ghost_is_caught(site):
    """python-dotenv as it actually was, reproduced from the artifact rather than imagined.

    MEASURED on the repaired venv: the dist-info that survives ships `top_level.txt` naming
    `dotenv`, while RECORD had been rewritten down to 9 entries whose only non-metadata path
    was `../../Scripts/dotenv.exe`. So the distribution still DECLARES a module and the module
    is gone — which is exactly what read downstream as absent credentials.
    """
    dist = make_dist(site, "python-dotenv", "1.2.2", [
        "../../Scripts/dotenv.exe,sha256=x,1024",
        "python_dotenv-1.2.2.dist-info/METADATA,sha256=y,100",
        "python_dotenv-1.2.2.dist-info/RECORD,,",
    ], top_level="dotenv\n")
    ghosts = rp.ghost_distributions([dist])
    assert [(n, v) for n, v, _ in ghosts] == [("python-dotenv", "1.2.2")], ghosts
    assert "none present on disk" in ghosts[0][2]


def test_a_distribution_that_ships_no_python_module_is_not_flagged(site):
    """The false positive CI caught within one run of the first cut.

    `cuda-toolkit 13.0.3.0` ships a toolchain and no importable module, and was reported as a
    broken install — on a perfectly good environment. A distribution that legitimately declares
    nothing importable cannot be distinguished from one whose declaration was lost, so no claim
    is made about it. A gate that cries wolf gets switched off, and takes the real protection.
    """
    dist = make_dist(site, "cuda-toolkit", "13.0.3.0", [
        "cuda_toolkit-13.0.3.0.dist-info/METADATA,sha256=x,100",
        "cuda_toolkit-13.0.3.0.dist-info/RECORD,,",
    ])
    assert rp.ghost_distributions([dist]) == []


def test_metadata_naming_a_module_that_is_not_on_disk_is_caught(site):
    """The other shape: RECORD names a package, the package was removed."""
    dist = make_dist(site, "python-dateutil", "2.9.0", [
        "dateutil/__init__.py,sha256=x,10",
        "dateutil/parser.py,sha256=y,20",
        "python_dateutil-2.9.0.dist-info/RECORD,,",
    ], top_level="dateutil\n")
    ghosts = rp.ghost_distributions([dist])
    assert [n for n, _v, _w in ghosts] == ["python-dateutil"], ghosts
    assert "none present on disk" in ghosts[0][2]


def test_a_healthy_distribution_is_not_flagged(site):
    """The negative half. A gate that cries wolf on a working venv gets switched off."""
    (site / "dateutil").mkdir()
    (site / "dateutil" / "__init__.py").write_text("", encoding="utf-8")
    dist = make_dist(site, "python-dateutil", "2.9.0", [
        "dateutil/__init__.py,sha256=x,10",
        "python_dateutil-2.9.0.dist-info/RECORD,,",
    ], top_level="dateutil\n")
    assert rp.ghost_distributions([dist]) == []


def test_a_single_module_distribution_is_not_flagged(site):
    """`six.py` ships one module, not a package directory — still healthy."""
    (site / "six.py").write_text("", encoding="utf-8")
    dist = make_dist(site, "six", "1.16.0",
                     ["six.py,sha256=x,10", "six-1.16.0.dist-info/RECORD,,"], top_level="six\n")
    assert rp.ghost_distributions([dist]) == []


def test_top_level_is_preferred_and_record_is_the_fallback(site):
    """Both metadata sources answer the same question, so both are exercised.

    Neither needs a distribution-name-to-import-name table: the distribution states its own
    import names, which is why `python-dotenv` -> `dotenv` needs no mapping to maintain.
    """
    (site / "yaml").mkdir()
    (site / "yaml" / "__init__.py").write_text("", encoding="utf-8")
    with_top = make_dist(site, "PyYAML", "6.0", ["yaml/__init__.py,,"], top_level="yaml\n")
    assert rp._top_level_names(with_top) == {"yaml"}

    site2 = site / "alt"
    site2.mkdir()
    from_record = make_dist(site2, "PyYAML", "6.0", [
        "yaml/__init__.py,sha256=x,10",
        "yaml/loader.py,sha256=y,20",
        "PyYAML-6.0.dist-info/RECORD,,",
        "../../Scripts/some.exe,,",
    ])
    assert rp._top_level_names(from_record) == {"yaml"}, "RECORD fallback did not resolve"


def test_a_declared_requirement_with_no_distribution_at_all_is_reported(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# a comment\npython-dotenv>=1.0\nfastapi\nnot-a-real-package-xyz==1.2\n"
        "uvicorn[standard]>=0.30\n",
        encoding="utf-8")
    missing = rp.undeclared_missing(req)
    assert "not-a-real-package-xyz" in missing, missing
    assert "python-dotenv" not in missing and "fastapi" not in missing, missing
    assert "uvicorn" not in missing, "extras marker was not stripped from the requirement name"


def test_the_live_checkout_is_provisioned():
    """Negative control on the real tree: the gate must not be born failing."""
    result = subprocess.run([sys.executable, str(REPO / "runtime_preflight.py")],
                            capture_output=True, text=True, cwd=str(REPO), timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "runtime_preflight: OK" in result.stdout, result.stdout


def test_report_mode_diagnoses_without_blocking(site, monkeypatch):
    """`--report` is for diagnosis; only the gate form may refuse a launch."""
    ghost = make_dist(site, "python-dotenv", "1.2.2", ["python_dotenv-1.2.2.dist-info/RECORD,,"],
                      top_level="dotenv\n")
    monkeypatch.setattr(rp, "_installed", lambda dists=None: [ghost] if dists is None else dists)
    monkeypatch.setattr(rp, "ROOT", site)          # no requirements.txt there

    assert rp.main(["--report"]) == 0
    assert rp.main([]) == 1


def test_the_launcher_runs_this_before_starting_uvicorn():
    """Wiring pin. The launcher's own probe only asked whether uvicorn imports, which a ghost
    elsewhere in the venv passes — that is how a broken tree reached the credential gate."""
    bat = (REPO / "start_ed_console.bat").read_text(encoding="utf-8", errors="replace")
    assert "runtime_preflight.py" in bat, "the launcher does not run the provisioning preflight"
    assert bat.index("runtime_preflight.py") < bat.index("-m uvicorn server:app"), (
        "the preflight must run BEFORE the server starts")
