"""RC-287 — a correct line must be excusable without lying about scope.

After RC-286 scoped the CAPS scanner to the git index, exactly two production hits
remained and BOTH are correct code:

    terrain_engine.py  _dte_of        `d if d is not None else 999.0` — a SORT KEY,
                                      never rendered; 999 places an unparseable DTE
                                      last, where a missing one already sorts. The
                                      alternative is a NaN, which makes every
                                      comparison against it false and scrambles order.
    terrain_engine.py  per-strike map `"volume": 0.0` — the IDENTITY of a sum whose
                                      accumulator fills in the loop below it. RC-277
                                      is the record of what happens when this exact
                                      shape gets "repaired".

The gate's only escapes addressed a hit by LOCATION: `CAPS_PREFIX_ALLOWLIST` is
file-scoped and would exempt 400+ lines of terrain_engine.py to excuse two of them —
RC-276's defect exactly — while `CAPS_LINE_ALLOWLIST` pins a LINE NUMBER and hands its
exemption to a different statement the moment anything above it shifts.

An exemption must attach to the THING it excuses, not to where the thing currently sits.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.anti_pattern_sweep import (  # noqa: E402
    CAPS_PREFIX_ALLOWLIST,
    find_unallowlisted_hits,
    iter_py_files,
    line_carries_caps_marker,
)


def test_the_gate_passes_on_merit():
    hits = find_unallowlisted_hits(production_only=True)
    assert hits == [], f"CAPS is red again: {hits}"


def test_the_pass_did_not_come_from_a_collapsed_scope():
    """A gate that passes because it stopped looking is worse than one that fails."""
    rels = {p.relative_to(REPO).as_posix() for p in iter_py_files(production_only=True)}
    assert len(rels) > 200, f"production scope collapsed to {len(rels)}"
    for must in ("server.py", "terrain_engine.py", "math_levels.py", "desk_store.py"):
        assert must in rels, f"{must} fell out of the scan"


def test_terrain_engine_was_not_exempted_wholesale():
    """The tempting fix was a file prefix. That is RC-276 in a second gate."""
    prefixes = {p for p, _ in CAPS_PREFIX_ALLOWLIST}
    assert "terrain_engine.py" not in prefixes, (
        "terrain_engine.py is exempt as a FILE — 400+ lines silenced to excuse two")


def test_a_marker_without_a_reason_does_not_suppress(tmp_path, monkeypatch):
    """A marker you can type without saying anything is the file allowlist, per line."""
    import tools.anti_pattern_sweep as A

    f = tmp_path / "m.py"
    f.write_text(
        'a = float(r.get("x") or 0.0)  # caps-ok:\n'
        'b = float(r.get("y") or 0.0)  # caps-ok: identity of a sum, filled below\n',
        encoding="utf-8")
    monkeypatch.setattr(A, "ROOT", tmp_path, raising=True)
    assert A.line_carries_caps_marker("m.py", 1) is False, "a reasonless marker suppressed"
    assert A.line_carries_caps_marker("m.py", 2) is True


def test_the_marker_travels_with_the_line_not_the_line_number(tmp_path, monkeypatch):
    """The failure mode of CAPS_LINE_ALLOWLIST, stated as a property.

    Insert a line above an excused statement: a line-number exemption would now point at
    the wrong statement. An inline marker cannot, because it moved with its own line.
    """
    import tools.anti_pattern_sweep as A

    f = tmp_path / "m.py"
    f.write_text('x = float(r.get("x") or 0.0)  # caps-ok: sum identity\n', encoding="utf-8")
    monkeypatch.setattr(A, "ROOT", tmp_path, raising=True)
    assert A.line_carries_caps_marker("m.py", 1) is True

    f.write_text('import os\n' + f.read_text(encoding="utf-8"), encoding="utf-8")
    assert A.line_carries_caps_marker("m.py", 1) is False, "line 1 is now the import"
    assert A.line_carries_caps_marker("m.py", 2) is True, (
        "the excused statement moved to line 2 and its marker did not follow it")


def test_the_two_false_reasons_are_gone_and_their_sites_are_repaired():
    """RC-290: BOTH reasons I wrote here were false, and Cursor executed both claims.

    "SORT KEY only, never rendered" — `_per_strike_scopes` classified a missing DTE as
    `far` and rendered it there. "a strike with no contract volume genuinely traded zero" —
    a missing totalVolume and a real zero both produced 0.0.

    Neither was reworded. Both sites were REPAIRED, so the markers are deleted: `_dte_of`
    returns None and unknown maturity joins neither side of the split, and an unreported
    strike volume stays None until a contract supplies a number.
    """
    src = (REPO / "terrain_engine.py").read_text(encoding="utf-8", errors="replace")
    live = [ln.strip() for ln in src.splitlines()
            if "caps-ok:" in ln and not ln.strip().startswith("#")]
    for dead in ("SORT KEY only", "genuinely traded zero"):
        assert not [ln for ln in live if dead in ln], (
            f"a reason Cursor proved false is an active exemption again: {dead!r}")
    assert "return d if d is not None else 999.0" not in src, "the 999.0 stand-in is back"
    assert '"volume": 0.0}' not in src, "the fabricated zero volume is back"


def test_the_surviving_marker_states_a_reason_that_is_true():
    """One marker remains and its claim is checkable: the default IS None."""
    src = (REPO / "terrain_engine.py").read_text(encoding="utf-8", errors="replace")
    live = [ln.strip() for ln in src.splitlines()
            if "caps-ok:" in ln and not ln.strip().startswith("#")]
    assert len(live) == 1, f"expected one surviving marker, saw {len(live)}: {live}"
    assert 'getattr(ex, "net_gex", None)' in live[0], (
        "the surviving marker is on a different line than the one whose reason was verified")
    assert "PRESERVES absence" in live[0]


def test_absent_net_gex_stays_none_not_zero():
    """The claim the surviving marker makes, executed rather than believed."""
    from types import SimpleNamespace

    import terrain_engine as T

    m = T._per_strike_map({740.0: SimpleNamespace()}, [])
    assert m[740.0]["net_gex"] is None, "an exposure with no net_gex acquired a value"


def test_unknown_maturity_joins_neither_side_of_the_split():
    """Cursor's probe: a contract with no DTE was classified `far` and rendered there."""
    from types import SimpleNamespace

    import terrain_engine as T

    scopes = T._per_strike_scopes(
        {740.0: SimpleNamespace(net_gex=1.0)},
        [{"strikePrice": 740.0, "totalVolume": 10}],      # no daysToExpiration
        spot=740.0)
    assert scopes["near"] == [], "unknown maturity rendered under the <=7DTE chip"
    assert scopes["far"] == [], "unknown maturity rendered under the MONTHLY+ chip"


def test_the_marker_is_checked_at_the_hit_site():
    """A rule nobody calls is a comment."""
    import inspect

    import tools.anti_pattern_sweep as A

    src = inspect.getsource(A.find_unallowlisted_hits)
    assert "line_carries_caps_marker(rel, lineno)" in src
    assert line_carries_caps_marker("terrain_engine.py", 1) is False
