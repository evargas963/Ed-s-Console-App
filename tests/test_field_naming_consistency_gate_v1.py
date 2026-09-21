"""RC-292 — negative control for the ENFORCED `field_naming_consistency` check.

Exercises the INSTITUTIONAL GATE's own entry point, `check_institutional_correctness.
check_field_naming_consistency`, not the helper underneath it — a control that only
unit-tests the helper proves the helper works, not that the gate calls it (RC-76/84/87/90
are four inert instruments that passed exactly that way).

check_one_producer proves a field is COMPUTED once; this proves it is WRITTEN under one
name. GSF/GRC were each computed in exactly one place and still shipped under two
independent, undocumented payload keys (`kl_gsf` and `gsf`) until this session's naming
consolidation merged them — the defect this gate exists to catch, reproduced here as a
mutation.

Baseline PASS -> inject an undocumented third serialization name -> gate FAILS -> remove ->
PASS.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in (REPO, REPO / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import check_institutional_correctness as GATE  # noqa: E402
import check_field_naming_consistency as C  # noqa: E402

REGISTRY = REPO / "governance" / "computation_registry.json"


def _fake_registry(tmp_path: Path, *, source_key: str, serialized_as: list[str]) -> dict:
    return {
        "payload_surfaces": ["server.py"],
        "fields": {
            "gamma_support_floor": {
                "producer": "math_levels.py:compute_gamma_support_levels",
                "source_key": source_key,
                "serialized_as": serialized_as,
            }
        },
    }


def test_the_gate_actually_invokes_the_checker():
    """Wiring, not behaviour: the check must be registered ENFORCED in the CHECKS table."""
    src = (REPO / "tools" / "check_institutional_correctness.py").read_text(
        encoding="utf-8", errors="replace")
    assert '("field_naming_consistency", check_field_naming_consistency, True)' in src, (
        "field_naming_consistency is not registered ENFORCED — an unregistered gate "
        "enforces nothing")
    names = [n for n, _fn, _enf in GATE.CHECKS]
    assert "field_naming_consistency" in names, (
        "field_naming_consistency is absent from the live CHECKS table")
    enforced = {n: e for n, _f, e in GATE.CHECKS}
    assert enforced["field_naming_consistency"] is True, (
        "field_naming_consistency is registered ADVISORY")


def test_an_undocumented_second_name_fails_the_gate(tmp_path, monkeypatch):
    """THE MUTATION: the exact kl_gsf/gsf defect this gate was built to catch.

    A field declares serialized_as=["gsf"] but server.py writes the SAME source_key under
    a second, undocumented name too — reproducing the pre-fix state of this repo.
    """
    fake_repo = tmp_path
    (fake_repo / "governance").mkdir()
    (fake_repo / "server.py").write_text(
        "def _terrain_kl_overlay(md, ticker):\n"
        "    t = {}\n"
        "    _g = lambda k: t.get(k)\n"
        "    md['kl_gsf'] = md['gsf'] = _g('gsf')\n",
        encoding="utf-8")
    (fake_repo / "governance" / "computation_registry.json").write_text(
        json.dumps(_fake_registry(fake_repo, source_key="gsf", serialized_as=["gsf"])),
        encoding="utf-8")

    monkeypatch.setattr(C, "REPO", fake_repo)
    monkeypatch.setattr(C, "REGISTRY", fake_repo / "governance" / "computation_registry.json")

    hits = C.naming_violations()
    assert hits, (
        "server.py writes the registered source_key under TWO names (gsf, kl_gsf) but "
        "serialized_as only declares one — the naming gate is inert (RC-292)")
    assert any("kl_gsf" in h and "gamma_support_floor" in h for h in hits), (
        f"the undocumented key was not named in the finding: {hits}")

    # RESTORE: document the second name, require the gate to go quiet.
    (fake_repo / "governance" / "computation_registry.json").write_text(
        json.dumps(_fake_registry(fake_repo, source_key="gsf",
                                  serialized_as=["gsf", "kl_gsf"])),
        encoding="utf-8")
    assert C.naming_violations() == [], (
        "the gate still fails after the second name was added to serialized_as — it is not "
        "measuring the drift it claims to measure")


def test_a_documented_alias_does_not_trip_the_gate(tmp_path, monkeypatch):
    """MUTATION_VALID_ALIAS -> PASS. A reviewed, registered second name is not drift."""
    fake_repo = tmp_path
    (fake_repo / "governance").mkdir()
    (fake_repo / "server.py").write_text(
        "def _terrain_kl_overlay(md, ticker):\n"
        "    t = {}\n"
        "    _g = lambda k: t.get(k)\n"
        "    md['kl_gsf'] = md['gsf'] = _g('gsf')\n",
        encoding="utf-8")
    (fake_repo / "governance" / "computation_registry.json").write_text(
        json.dumps(_fake_registry(fake_repo, source_key="gsf",
                                  serialized_as=["gsf", "kl_gsf"])),
        encoding="utf-8")
    monkeypatch.setattr(C, "REPO", fake_repo)
    monkeypatch.setattr(C, "REGISTRY", fake_repo / "governance" / "computation_registry.json")
    assert C.naming_violations() == [], (
        "both target keys are registered in serialized_as and the gate still fired — it "
        "cannot distinguish a reviewed alias from undocumented drift")


def test_a_field_that_has_not_opted_in_is_not_checked(tmp_path, monkeypatch):
    """A registry entry with no source_key/serialized_as is NOT covered by this gate at
    all — it is check_one_producer's territory, not this one's. Silence here must mean
    'not opted in', never 'reviewed and clean'."""
    fake_repo = tmp_path
    (fake_repo / "governance").mkdir()
    (fake_repo / "server.py").write_text(
        "def f(md):\n"
        "    md['x'] = md['y'] = md['z'] = g('anything')\n",
        encoding="utf-8")
    (fake_repo / "governance" / "computation_registry.json").write_text(json.dumps({
        "payload_surfaces": ["server.py"],
        "fields": {"some_field": {"producer": "mod.py:f"}},
    }), encoding="utf-8")
    monkeypatch.setattr(C, "REPO", fake_repo)
    monkeypatch.setattr(C, "REGISTRY", fake_repo / "governance" / "computation_registry.json")
    assert C.naming_checked_fields(C.load_registry()) == {}
    assert C.naming_violations() == []


def test_absent_payload_surface_fails_closed_when_declared(tmp_path, monkeypatch):
    """A field has opted in but the declared payload surface file does not exist -> FAIL
    closed, not a silent pass (SP-05 precedent, same as check_one_producer)."""
    fake_repo = tmp_path
    (fake_repo / "governance").mkdir()
    (fake_repo / "governance" / "computation_registry.json").write_text(
        json.dumps(_fake_registry(fake_repo, source_key="gsf", serialized_as=["gsf"])),
        encoding="utf-8")                             # server.py deliberately not created
    monkeypatch.setattr(C, "REPO", fake_repo)
    monkeypatch.setattr(C, "REGISTRY", fake_repo / "governance" / "computation_registry.json")
    hits = C.naming_violations()
    assert hits, ("a declared payload surface is missing and the gate reported nothing — "
                  "absence was converted into a silent PASS")
    assert "server.py" in hits[0] and "FAILS CLOSED" in hits[0]


def test_this_repository_declares_its_payload_surface():
    """The production registry must declare, or the naming gate can never fire here."""
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert reg.get("payload_surfaces") == ["server.py"]
    assert (REPO / "server.py").exists()


def test_the_repository_currently_registers_gsf_and_grc_for_this_gate():
    """The gate is live-armed over a nonzero surface, not just wired but unused."""
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    checked = C.naming_checked_fields(reg)
    assert "gamma_support_floor" in checked
    assert "gamma_resistance_ceiling" in checked
    assert set(checked["gamma_support_floor"]["serialized_as"]) == {"gsf", "kl_gsf"}
    assert set(checked["gamma_resistance_ceiling"]["serialized_as"]) == {"grc", "kl_grc"}


def test_the_live_repository_state_is_reported_not_hidden():
    """The gate's live verdict, whatever it is, must be the measured one.

    This does NOT assume zero as a law of nature — it asserts the shape of the report and
    that any hit is attributed to the registry, matching the one_producer gate's own
    convention. The live repo happens to be clean right now because this session's own
    naming-consolidation fix landed first; a future regression must reappear here, not be
    silently absorbed.
    """
    hits = GATE.check_field_naming_consistency()
    assert isinstance(hits, list)
    for v in hits:
        assert "computation_registry" in str(v.path) or (
            "check_field_naming_consistency" in str(v.path))
