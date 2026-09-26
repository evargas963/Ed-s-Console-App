"""RC-84/RC-85: the trade-decision path reads no dict key that nothing declares.

A misspelled or stale key is not an error in Python — it is a silent None. RC-15 (`spot_f` where
the producer emits `spot`) and RC-20 (`artifact_sha256` where the verifier emits `actual_sha256`)
both shipped that way, and RC-85 did it again: `_charm_raw.get("top_drivers", [])` reads a key
compute_net_charm has never emitted, so MarketState.charm_top_drivers has been permanently empty.

MEASURED 2026-07-27: the money path held 15 such reads. Four were CHECKER blind spots on correct
code — mc_available, ml_layer_probs, timeframe_reads, startup_git_sha all came back POPULATED from
the live /api/state, so acting on the report would have meant breaking working code. Seven were
genuinely external and are now declared inline with their source. Three were dead reads, removed.
One was a real defect. Count is now 0, and this test is what keeps it there: removing an
`# external-key-ok:` declaration, or adding an undeclared read, fails here rather than silently
serving None to a decision.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Files whose dict reads can reach a trade decision or the vendor boundary feeding one.
#: Tooling and research code carry their own backlog; this contract binds the money path.
MONEY_PATH = {
    "server.py", "terrain_engine.py", "db.py", "schwab_client.py",
    "math_levels.py", "math_exposure_core.py", 
    "liquidity_value_engine.py", "terrain_read.py", "numeric_contract.py",
}

#: TEST_SYSTEM_REHAB_V2: `live_orphans` is now the session-scoped fixture in
#: tests/conftest.py, shared with test_orphan_dict_keys_data_sources_v1.py's pure-read
#: consumers -- both files independently paying the full check_no_orphan_dict_keys()
#: sweep was the actual duplicate cost, not this file's own use of it.


def _money_path_violations(violations) -> list[str]:
    out = []
    for v in violations:
        rel = str(v).strip().split(":")[0].strip().replace("\\", "/")
        if rel in MONEY_PATH:
            out.append(str(v).strip())
    return out


def test_money_path_has_no_undeclared_dict_keys(live_orphans):
    bad = _money_path_violations(live_orphans)
    assert not bad, (
        "a money-path dict read has no writer and no '# external-key-ok: <source>' declaration. "
        "Either the name is wrong (a silent None reaching a decision — RC-15/RC-20/RC-85), or it "
        "genuinely arrives from outside this repo and must say so:\n  " + "\n  ".join(bad[:8])
    )


def test_the_declarations_are_actually_load_bearing(live_orphans):
    """Guard against the test passing because the CHECK is inert rather than the code clean.

    Three instruments shipped silently broken on 2026-07-27 (an alias-blind detector, a
    write-detector missing two shapes, a regex containing literal backspace characters). A count
    of zero from a checker that cannot fire is worthless, so this asserts the checker still finds
    the wider backlog it is supposed to see."""
    total = len(live_orphans)
    assert total > 0, (
        "check_no_orphan_dict_keys reported ZERO violations repo-wide. That is a checker failure, "
        "not perfection — the repo has a known backlog outside the money path."
    )


def test_external_declarations_name_their_source():
    """`# external-key-ok:` must carry a REASON. A bare marker is a mute suppression."""
    bare = []
    for name in sorted(MONEY_PATH):
        p = ROOT / name
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if "external-key-ok:" not in line:
                continue
            reason = line.split("external-key-ok:", 1)[1].strip()
            if len(reason) < 8:
                bare.append(f"{name}:{i} declares an external key with no source: {line.strip()!r}")
    assert not bare, "\n  ".join(bare)



