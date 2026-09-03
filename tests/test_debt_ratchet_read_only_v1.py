"""RC-385 — the ratchet reads its reference; it never writes it.

MEASURED 2026-08-15 on a pristine checkout of origin/main 573b96e8: one call to
check_debt_ratchet() rewrote governance/advisory_debt_baseline.json, moving
file_length 37->49, function_complexity 462->547, function_length 393->438,
mypy_types 756->835, ruff_quality 1081->1301, and flipping the file LF->CRLF. The act of
MEASURING left a clean clone dirty with RAISED debt ceilings, so anyone committing with
blind staging would have legitimised debt the ratchet exists to refuse — the RC-67 gaming
class arriving by accident, which is worse than intent because nobody has to decide.

A SECOND defect surfaced while fixing it: `--rebaseline`, the deliberate recording path
both docstrings have pointed at since RC-90, was NEVER IMPLEMENTED. The contract said
recording was an explicit act while the only recording that existed was the invisible
side effect. Prose was doing a lock's job.

These controls pin both halves: the check cannot write, and the writer that now exists
cannot be used to launder a correctness rise.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


GATE_SRC = REPO / "tools" / "check_institutional_correctness.py"


def _load():
    spec = importlib.util.spec_from_file_location("cic_rc385", GATE_SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cheap_advisory_catalog(gate):
    """Keep the ratchet/rebaseline WRITE path; do not re-pay the advisory catalog.

    `check_debt_ratchet` / `rebaseline` compute `current` by calling every advisory
    checker (`ruff_quality`, `mypy_types`, whole-repo AST, orphan-key walk, …).
    MEASURED on serial required pytest-full 32227366665: this file alone was 129.0s,
    and `test_the_cli_flag_runs_end_to_end_without_touching_the_real_baseline`
    then invoked the full `--enforced-only` catalog on top. These tests assert
    READ-ONLY / LF / argv wiring — not the advisory counts. The catalog stays
    owned by hardening (`check_delta_adds_no_debt.py`) and the advisory CLI.
    """

    def _one() -> list[object]:
        return [object()]

    return tuple(
        (name, (_one if not enforced else fn), enforced)
        for name, fn, enforced in gate.CHECKS
    )


def test_running_the_ratchet_leaves_the_baseline_byte_identical(monkeypatch):
    """THE PROPERTY. Any write here is the defect, whatever the counts happen to be."""
    gate = _load()
    monkeypatch.setattr(gate, "CHECKS", _cheap_advisory_catalog(gate))
    path = gate._debt_baseline_path()
    before = path.read_bytes()
    gate.check_debt_ratchet()
    assert path.read_bytes() == before, (
        "check_debt_ratchet mutated the baseline it measures — a gate may READ its "
        "reference or CHANGE it, never both in one call (RC-385)")


def test_running_it_twice_is_still_byte_identical(monkeypatch):
    gate = _load()
    monkeypatch.setattr(gate, "CHECKS", _cheap_advisory_catalog(gate))
    path = gate._debt_baseline_path()
    before = path.read_bytes()
    gate.check_debt_ratchet()
    gate.check_debt_ratchet()
    assert path.read_bytes() == before


def test_a_missing_baseline_is_reported_not_silently_seeded(monkeypatch):
    """Seeding is an explicit act. Absence must surface, not self-heal."""
    gate = _load()
    monkeypatch.setattr(gate, "CHECKS", _cheap_advisory_catalog(gate))
    real = gate._debt_baseline_path()
    saved = real.read_bytes()
    try:
        real.unlink()
        out = gate.check_debt_ratchet()
        assert out, "a missing baseline was silently seeded instead of reported"
        assert "--rebaseline" in out[0].msg, out[0].msg
        assert not real.exists(), "the check re-created the file it was asked only to read"
    finally:
        real.write_bytes(saved)


def test_the_rebaseline_flag_exists_and_is_wired():
    """RC-90's docstrings promised this path for weeks while it did not exist."""
    gate = _load()
    assert hasattr(gate, "rebaseline"), "no rebaseline() implementation"
    src = GATE_SRC.read_text(encoding="utf-8", errors="replace")
    assert '"--rebaseline" in args' in src, "--rebaseline is not wired into main()"
    # Source-lock: hermetic CLI tests must not delete the catalog call sites.
    # Kept inside this existing reader so the RC-311 source-text census does not
    # grow a new function for the same inspect-the-source property.
    assert '"--enforced-only" in args' in src
    assert 'run_checks(mode="enforced")' in src
    assert "check_debt_ratchet" in src
    for name in ("ruff_quality", "mypy_types", "orphan_dict_keys"):
        assert name in src, f"advisory catalog lost {name}"


def test_rebaseline_refuses_to_launder_a_correctness_rise(tmp_path, monkeypatch, capsys):
    """A recorder, not an amnesty: correctness debt may never be rebaselined UPWARD."""
    gate = _load()
    fake = tmp_path / "advisory_debt_baseline.json"
    # Must be a metric that is BOTH on the blocks-on-rise allowlist AND an advisory check,
    # or rebaseline never compares it: the first attempt picked an enforced name, which is
    # filtered out of `current`, so the "refusal" passed vacuously.
    advisory = {n for n, _f, e in gate.CHECKS if not e}
    blocked = sorted(gate._RATCHET_BLOCKS_ON_RISE & advisory)[0]
    fake.write_text(json.dumps({blocked: 1}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(gate, "_debt_baseline_path", lambda: fake)
    # Force a large current count for the blocked metric. Other advisory
    # checkers stay cheap — this test asserts the RISE refusal, not ruff/mypy.
    def _count_for(name: str):
        if name == blocked:
            return lambda: [object()] * 99
        return lambda: [object()]

    monkeypatch.setattr(
        gate, "CHECKS",
        tuple((n, (_count_for(n) if not e else f), e)
              for n, f, e in gate.CHECKS),
    )
    rc = gate.rebaseline()
    assert rc == 1, "rebaseline accepted a correctness RISE"
    assert "REFUSED" in capsys.readouterr().out
    assert json.loads(fake.read_text(encoding="utf-8"))[blocked] == 1, "baseline was raised"


def test_rebaseline_writes_lf_not_platform_newlines(tmp_path, monkeypatch):
    """RC-382/RC-383: the writer must not reflow a committed-LF governance file."""
    gate = _load()
    fake = tmp_path / "advisory_debt_baseline.json"
    monkeypatch.setattr(gate, "_debt_baseline_path", lambda: fake)
    monkeypatch.setattr(gate, "CHECKS", _cheap_advisory_catalog(gate))
    gate.rebaseline()
    assert fake.exists()
    assert fake.read_bytes().count(b"\r\n") == 0, "rebaseline wrote CRLF into a governed file"


def test_the_cli_flag_runs_end_to_end_without_touching_the_real_baseline(monkeypatch, capsys):
    """Argv path: `--enforced-only` reaches main() and does not write the baseline.

    The docstring called this help-level smoke; the body used to subprocess the
    full `--enforced-only` catalog (~100s, already owned by hardening). Drive
    the same main() branch with a cheap run_checks so the write-guard is what
    we time, not a second copy of the required CI gate.
    """
    gate = _load()
    real = GATE_SRC.parent.parent / "governance" / "advisory_debt_baseline.json"
    before = real.read_bytes()
    monkeypatch.setattr(gate, "run_checks", lambda mode="enforced": (0, [], []))
    rc = gate.main(["--enforced-only"])
    assert rc == 0, capsys.readouterr()
    assert real.read_bytes() == before, (
        "a normal gate run mutated the baseline — the RC-385 defect is back")
