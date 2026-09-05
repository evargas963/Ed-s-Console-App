"""RC-325 — negative control for the ENFORCED `one_producer` check (SP-01).

Exercises the INSTITUTIONAL GATE's own entry point, `check_institutional_correctness.
check_one_producer`, not the helper underneath it. A control that unit-tests the helper
proves the helper works; it does not prove the gate calls it, and RC-76/84/87/90 are four
inert instruments that passed exactly that way.

Baseline PASS -> inject an unauthorized second producer -> gate FAILS -> remove -> PASS.
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
import check_one_producer as C  # noqa: E402

REGISTRY = REPO / "governance" / "computation_registry.json"


def _gate_violations() -> list:
    """What the institutional gate itself sees."""
    return GATE.check_one_producer()


def test_the_gate_actually_invokes_the_checker():
    """Wiring, not behaviour: the check must be registered ENFORCED in the CHECKS table."""
    src = (REPO / "tools" / "check_institutional_correctness.py").read_text(
        encoding="utf-8", errors="replace")
    assert '("one_producer", check_one_producer, True)' in src, (
        "one_producer is not registered ENFORCED — an unregistered gate enforces nothing")
    names = [n for n, _fn, _enf in GATE.CHECKS]
    assert "one_producer" in names, "one_producer is absent from the live CHECKS table"
    enforced = {n: e for n, _f, e in GATE.CHECKS}
    assert enforced["one_producer"] is True, "one_producer is registered ADVISORY"


def test_a_registered_concept_with_two_producers_fails_the_gate(tmp_path, monkeypatch):
    """The injected violation, driven through the gate's own function.

    A registry entry naming ONE producer, against a repository where two functions compute
    the concept, must produce >= 1 violation. If this passes, the gate is inert.
    """
    fake_repo = tmp_path
    (fake_repo / "governance").mkdir()
    (fake_repo / "prod_a.py").write_text(
        "def canonical(contracts, spot):\n"
        "    total = 0.0\n"
        "    for c in contracts:\n"
        "        total += c['gamma'] * c['openInterest'] * spot * spot * 0.01\n"
        "    return total\n", encoding="utf-8")
    # THE MUTATION: a second, independent computation of the same registered concept.
    (fake_repo / "prod_b.py").write_text(
        "def shadow(rows, spot):\n"
        "    acc = 0.0\n"
        "    for r in rows:\n"
        "        acc += r['gamma'] * r['openInterest'] * spot * spot * 0.01\n"
        "    return acc\n", encoding="utf-8")
    (fake_repo / "governance" / "computation_registry.json").write_text(json.dumps({
        "fields": {
            "gex_dollars_per_1pct_at_strike": {
                "producer": "prod_a.py:canonical",
                "kind": "derived",
                "formula": "gamma * oi * spot^2 * 0.01",
                "computation_inputs": ["gamma", "openInterest", "spot"],
            }
        }
    }), encoding="utf-8")

    monkeypatch.setattr(C, "REPO", fake_repo)
    monkeypatch.setattr(C, "REGISTRY",
                        fake_repo / "governance" / "computation_registry.json")
    monkeypatch.setattr(C, "_tracked_surfaces", lambda root=None: [])
    monkeypatch.setattr(C, "_tracked_python", lambda: ["prod_a.py", "prod_b.py"])

    hits = C.violations()
    assert hits, (
        "TWO functions compute the registered concept and the checker reported nothing — "
        "the one-producer gate is inert (SP-01)")
    assert any("prod_b.py:shadow" in h for h in hits), (
        f"the second producer was not named in the finding: {hits}")

    # RESTORE: remove the mutation, require the gate to go quiet.
    (fake_repo / "prod_b.py").unlink()
    monkeypatch.setattr(C, "_tracked_python", lambda: ["prod_a.py"])
    assert C.violations() == [], (
        "the gate still fails after the second producer was removed — it is not measuring "
        "the duplication it claims to measure")


def test_a_valid_consumer_does_not_trip_the_gate(tmp_path, monkeypatch):
    """MUTATION_VALID_CONSUMER -> PASS. Reading a produced value is not producing it."""
    fake_repo = tmp_path
    (fake_repo / "governance").mkdir()
    (fake_repo / "prod_a.py").write_text(
        "def canonical(contracts, spot):\n"
        "    total = 0.0\n"
        "    for c in contracts:\n"
        "        total += c['gamma'] * c['openInterest'] * spot * spot * 0.01\n"
        "    return total\n", encoding="utf-8")
    (fake_repo / "consumer.py").write_text(
        "from prod_a import canonical\n\n"
        "def render(contracts, spot):\n"
        "    value = canonical(contracts, spot)\n"
        "    return f'{value:,.0f}'\n", encoding="utf-8")
    (fake_repo / "governance" / "computation_registry.json").write_text(json.dumps({
        "fields": {
            "gex_dollars_per_1pct_at_strike": {
                "producer": "prod_a.py:canonical",
                "computation_inputs": ["gamma", "openInterest", "spot"],
            }
        }
    }), encoding="utf-8")
    monkeypatch.setattr(C, "REPO", fake_repo)
    monkeypatch.setattr(C, "REGISTRY",
                        fake_repo / "governance" / "computation_registry.json")
    monkeypatch.setattr(C, "_tracked_surfaces", lambda root=None: [])
    monkeypatch.setattr(C, "_tracked_python", lambda: ["prod_a.py", "consumer.py"])
    assert C.violations() == [], (
        "a consumer that calls the canonical producer was flagged as a second producer — "
        "the gate cannot distinguish consumption from production (SP-01)")


def _surface_fixture(fake_repo: Path, monkeypatch, surfaces: dict[str, str]) -> None:
    (fake_repo / "governance").mkdir()
    (fake_repo / "prod_a.py").write_text(
        "def canonical(contracts, spot):\n"
        "    total = 0.0\n"
        "    for c in contracts:\n"
        "        total += c['gamma'] * c['openInterest'] * spot * spot * 0.01\n"
        "    return total\n", encoding="utf-8")
    for rel, text in surfaces.items():
        p = fake_repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (fake_repo / "governance" / "computation_registry.json").write_text(json.dumps({
        "fields": {
            "gex_dollars_per_1pct_at_strike": {
                "producer": "prod_a.py:canonical",
                "computation_inputs": ["gamma", "openInterest", "spot"],
                "surface_inputs": [["gamma"], ["oi", "openInterest", "open_interest"], ["spot", "spt"]],
            }
        }
    }), encoding="utf-8")
    monkeypatch.setattr(C, "REPO", fake_repo)
    monkeypatch.setattr(C, "REGISTRY", fake_repo / "governance" / "computation_registry.json")
    monkeypatch.setattr(C, "_tracked_python", lambda: ["prod_a.py"])
    monkeypatch.setattr(C, "_tracked_surfaces", lambda root=None: sorted(surfaces))


def test_a_frontend_recomputation_of_a_registered_field_is_a_second_producer(tmp_path, monkeypatch):
    """RC-516 (AGENTS.md law 12): the browser is a connected layer of the same truth."""
    _surface_fixture(tmp_path, monkeypatch, {
        "static/chart.js": "function gexAt(r, spot) {\n  return r.gamma * r.openInterest * spot * spot * 0.01;\n}\n"})
    hits = C.violations()
    assert hits and "static/chart.js:2" in hits[0], hits


def test_an_inline_html_script_and_a_sql_query_are_second_producers(tmp_path, monkeypatch):
    _surface_fixture(tmp_path, monkeypatch, {
        "static/index.html": "<html><script>\nconst g = row.gamma * row.oi * spot * spot;\n</script></html>\n",
        "snapshot_sql/gex.sql": "SELECT strike, gamma * open_interest * spot * spot * 0.01 AS gex FROM chain;\n"})
    hits = C.violations()
    assert hits and "static/index.html:2" in hits[0] and "snapshot_sql/gex.sql:1" in hits[0], hits


def test_a_frontend_consumer_and_a_column_list_are_not_producers(tmp_path, monkeypatch):
    """Rendering the served value, listing columns, passing inputs as arguments: none of
    these joins the inputs arithmetically, so none is a computation."""
    _surface_fixture(tmp_path, monkeypatch, {
        "static/render.js": "function render(p) {\n  return p.gex_total.toFixed(2) + fmt(p.gamma, p.oi, spot);\n}\n",
        "snapshot_sql/cols.sql": "SELECT gamma, open_interest AS oi, spot FROM chain WHERE spot > 0 AND gamma > 0;\n"})
    assert C.violations() == []


def test_a_field_without_surface_inputs_is_not_judged_on_surfaces(tmp_path, monkeypatch):
    """Honest scope: no declared spellings, no surface verdict (NOT_MECHANICALLY_DETECTABLE)."""
    _surface_fixture(tmp_path, monkeypatch, {
        "static/chart.js": "function gexAt(r, spot) {\n  return r.gamma * r.openInterest * spot * spot * 0.01;\n}\n"})
    reg = json.loads((tmp_path / "governance" / "computation_registry.json").read_text(encoding="utf-8"))
    del reg["fields"]["gex_dollars_per_1pct_at_strike"]["surface_inputs"]
    (tmp_path / "governance" / "computation_registry.json").write_text(json.dumps(reg), encoding="utf-8")
    assert C.violations() == []


def test_absent_payload_surface_fails_closed_when_declared(tmp_path, monkeypatch):
    """SERVER_MISSING_FILE_SEMANTICS, case 1: DECLARED but absent -> violation.

    The first fix returned [] for any missing server.py, which turned "I could not inspect
    the payload surface" into "there is nothing to report". That is fail-open. When the
    registry DECLARES a surface, its absence must be a finding.
    """
    fake = tmp_path
    (fake / "governance").mkdir()
    (fake / "governance" / "computation_registry.json").write_text(json.dumps({
        "payload_surfaces": ["server.py"],          # declared...
        "fields": {},
    }), encoding="utf-8")                            # ...and deliberately not created
    monkeypatch.setattr(C, "REPO", fake)
    monkeypatch.setattr(C, "REGISTRY", fake / "governance" / "computation_registry.json")
    monkeypatch.setattr(C, "_tracked_surfaces", lambda root=None: [])
    monkeypatch.setattr(C, "_tracked_python", lambda: [])

    hits = C.violations()
    assert hits, ("a DECLARED payload surface is missing and the gate reported nothing — "
                  "absence was converted into a silent PASS (SP-05)")
    assert "server.py" in hits[0] and "FAILS CLOSED" in hits[0]

    # And the raising form is preserved, so it cannot be mistaken for an empty result set.
    import pytest as _pytest
    with _pytest.raises(C.PayloadSurfaceMissing):
        C.unregistered_payload_fields()


def test_absent_payload_surface_is_silent_when_none_declared(tmp_path, monkeypatch):
    """SERVER_MISSING_FILE_SEMANTICS, case 2: a fixture repo declaring no surface.

    This is the legitimate case the crash-fix existed for. Silence here is correct because
    nothing was claimed; silence in case 1 would be a lie.
    """
    fake = tmp_path
    (fake / "governance").mkdir()
    (fake / "governance" / "computation_registry.json").write_text(
        json.dumps({"fields": {}}), encoding="utf-8")   # no payload_surfaces key
    monkeypatch.setattr(C, "REPO", fake)
    monkeypatch.setattr(C, "REGISTRY", fake / "governance" / "computation_registry.json")
    monkeypatch.setattr(C, "_tracked_surfaces", lambda root=None: [])
    monkeypatch.setattr(C, "_tracked_python", lambda: [])
    assert C.unregistered_payload_fields() == []
    assert C.violations() == []


def test_this_repository_declares_its_payload_surface():
    """The production registry must declare, or case 1 can never fire here."""
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert reg.get("payload_surfaces") == ["server.py"]
    assert (REPO / "server.py").exists()


def test_the_live_repository_state_is_reported_not_hidden():
    """The gate's live verdict, whatever it is, must be the measured one.

    This does NOT assert zero. The repository currently has a real finding, and a control
    that demanded green here would pressure the next author to weaken the registry.
    """
    hits = _gate_violations()
    assert isinstance(hits, list)
    for v in hits:
        assert "computation_registry" in str(v.path) or "check_one_producer" in str(v.path)
