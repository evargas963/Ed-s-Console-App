"""RC-301 — absence-coerced-to-a-value class gate is present and enforced."""

from pathlib import Path

from tools.check_absence_has_a_type import violations

REPO = Path(__file__).resolve().parent.parent


def test_absence_gate_passes_on_this_tree():
    assert violations() == []


def test_absence_gate_is_wired_into_hardening():
    src = (REPO / ".github" / "workflows" / "hardening.yml").read_text(encoding="utf-8")
    assert "check_absence_has_a_type.py" in src


def test_parity_except_no_longer_returns_zero_literal():
    src = (REPO / "math_levels.py").read_text(encoding="utf-8")
    start = src.find("def parity_f_minus_spot_from_contracts")
    block = src[start : start + 400]
    assert "return None" in block
    assert "-> float | None" in block


def test_absence_gate_docstring_names_what_it_does_not_catch():
    """RC-301/318: a green gate is the except-literal shape, not the CLASS."""
    src = (REPO / "tools" / "check_absence_has_a_type.py").read_text(encoding="utf-8")
    assert "WHAT THIS DOES NOT CATCH" in src
    for needle in (
        "unannotated functions",
        "float | None",
        "return x or 0.0",
        "if v is None: return 0.0",
        "# absence-ok:",
    ):
        assert needle in src, needle


def test_absence_gate_flags_except_literal_on_uncited_function():
    """Defect-learning: except-literal `-> float` fires on a def the last audit did not name."""
    from tools.check_absence_has_a_type import fabricated_absence_returns_in_source

    plant = (
        "def unrelated_score(x: float) -> float:\n"
        "    try:\n"
        "        return float(x)\n"
        "    except TypeError:\n"
        "        return float(0)\n"
    )
    hits = fabricated_absence_returns_in_source(plant)
    assert [(h[1], h[2]) for h in hits] == [("unrelated_score", "0")]


def test_rc318_board_lists_every_absence_ok_site():
    """Z2 acceptance: every # absence-ok site is a named RC-318 row (file:line)."""
    import re
    import subprocess

    board = (REPO / "OPEN_ITEMS.md").read_text(encoding="utf-8")
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=True,
    )
    sites: list[str] = []
    for rel in [p for p in proc.stdout.split("\0") if p]:
        if rel.startswith(("tests/", "tools/")):
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"#\s*absence-ok", line):
                sites.append(f"{rel}:{i}")
    assert sites, "expected at least the encoder # absence-ok site"
    for site in sites:
        assert site in board, f"RC-318 board missing {site}"
