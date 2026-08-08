#!/usr/bin/env python3
"""RC-319 — a claim about how the MARKET behaves must be checkable by a reader.

WHAT WAS OBSERVED (2026-08-09). I wrote "Hedging MAGNITUDE pins price regardless of net
sign" into governance/mega2_traceable_inventory.py and built a decision on it. It is false:
magnitude sets the SIZE of the re-hedging flow at a strike, while the SIGN of the dealer
position sets whether that flow stabilises or repels. Cursor refuted it in an independent
audit the next day. The claim was not unknowable — it was uncited. Nothing in the row, and
nothing in the register line, pointed at a source or a derivation a reader could check, so
the only way to catch it was for someone to already know the mechanism.

WHY THE EXISTING LOCKS DID NOT FIRE. `rc_numeric_claims_cite_a_command` demands provenance
for NUMBERS and this claim contains none. `five_why_recursive_lock` enforces the SHAPE of a
chain — five levels, a named terminal or a spawned child — and RC-315's chain satisfied all
of it while resting on a false premise. Depth was enforced; checkability was not.

THE RULE. Not "is this claim true" — no static check can know that, and pretending otherwise
would be the same overreach the claim itself was. The rule is narrower: a row that asserts a
market MECHANISM must carry a DOI, a URL, a named source, or a backticked reproducible
command. It makes the claim refutable. RC-315 took a day to refute because Cursor had to
supply the citation I should have.

HOW IT WAS VALIDATED. Prototyped against all 288 rows BEFORE wiring: 36 make a mechanism
claim, 35 already cite, one does not, and zero uncited claims exist among the 21 rows opened
under the recursion lock. Then tested against the REAL historical text rather than a
reconstruction — `git show 6f95a237:governance/mega2_traceable_inventory.py` — where it
fires on the exact sentence I committed. RC-317 records what happens when a negative control
is built from the author's memory of a defect instead of the defect.

    .venv/Scripts/python.exe tools/check_rc_mechanism_claims_cite_a_source.py
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Rows opened before the rule existed. Frozen, and the reason is the same one the numeric
#: citation rule records: a lock binds new work; rewriting history is not enforcement.
MECHANISM_CITATION_CUTOVER = "2026-08-09"

#: An asserted MARKET mechanism — a verb of CONSEQUENCE acting on price, moves or dealers.
#:
#: The VERB sense specifically. A first pass matched bare `pins?|magnet|hedging flow`, which
#: is how the field is NAMED — "Pin strength vs neighbors", "the gamma pin row",
#: "_pick_gamma_pin" — and it produced six register hits of which five were nouns. Naming a
#: metric is description; saying it pins price is a causal claim. Matching the noun would
#: have taught the next author to reword rather than to cite, which is the citation theater
#: `rc_numeric_claims_cite_a_command` records itself fighting.
_MECHANISM_RE = re.compile(
    r"\b(pins?\s+(?:price|spot|the\s+\w+)|pinning\s+(?:effect|mechanism)"
    r"|attracts?\s+(?:price|spot)|repels?|dampens?"
    r"|amplifie?s?\s+(?:moves?|volatility)"
    r"|stabilis\w+|destabilis\w+|acts?\s+as\s+a\s+magnet"
    r"|dealer\w*\s+(?:sell|buy)\w*\s+(?:rallies|dips|into)"
    r"|hedging\s+magnitude\s+pins?)\b",
    re.I,
)

#: The registers canonise a claim the way a row does — the RC-315 sentence lived in
#: mega2_traceable_inventory.py, not in the log — so both are in scope.
_REGISTER_GLOB = "mega*_traceable_inventory.py"

#: RC-320: and so does a PRODUCTION DOCSTRING, which is where the register's wording came
#: from. This gate shipped scanning the log and the registers, and Cursor's next audit found
#: the same refuted sentence still sitting in `math_exposure_core.pick_pin_and_strength` —
#: green and blind on the origin, within one turn of being written. RC-311's ambiguity
#: (repaired versus not-looked-at) demonstrated for the third time.
_DOCSTRING_SCOPE = ("math_exposure_core.py", "math_levels.py", "terrain_engine.py",
                    "math_probabilities.py", "math_volatility.py", "regime_engine.py")

#: What makes a claim checkable: an identifier a reader can follow, or a command they can
#: run. A backticked span that is prose rather than a command does not count, which is the
#: same standard `rc_numeric_claims_cite_a_command` holds numbers to.
_CITATION_RE = re.compile(
    r"(doi[:.]|https?://"
    r"|`[^`]*(python|pytest|node |curl |SELECT |tools/|\.py)[^`]*`"
    r"|\b(finite difference|closed form|first principles derivation"
    r"|Avellaneda|Ni, Pearson|Journal of Financial Economics)\b)",
    re.I,
)


def violations(log_path: Path | None = None) -> list[str]:
    path = log_path or (REPO / "governance" / "root_cause_log.md")
    out: list[str] = []
    if not path.exists():
        return out
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7:
            continue                      # schema breakage is rc_log_rows_keep_schema's job
        rc_id, opened = cells[0], cells[2]
        if opened < MECHANISM_CITATION_CUTOVER:
            continue
        body = " ".join(cells[4:7])
        hit = _MECHANISM_RE.search(body)
        if not hit or _CITATION_RE.search(body):
            continue
        out.append(
            f"{path.name}:{n}  {rc_id} asserts a MARKET MECHANISM ({hit.group(0)!r}) and "
            f"cites no source or derivation. A reader cannot refute what they cannot check: "
            f"RC-315 put 'hedging MAGNITUDE pins price regardless of net sign' into the "
            f"derivation register and it took an outside audit a day to overturn it. Add a "
            f"DOI, a URL, a named paper, or a backticked command that establishes the "
            f"claim — or state the mechanism as UNPROVEN and say what would settle it.")
    out += register_violations()
    out += docstring_violations()
    return out


def docstring_violations() -> list[str]:
    """RC-320 — the same rule over the docstrings of the structural-metric producers.

    A docstring is the most binding place a mechanism claim can live: the register
    paraphrases it, the RC rows cite it, and every reader of the function takes it as the
    function's contract. RC-315 corrected the register and left the docstring it was
    paraphrasing, so the refuted sentence survived the repair that was named after it.

    Scoped to the modules that COMPUTE structural levels, not the whole tree, because that
    is where a causal claim about price is both likely and consequential. The scope is
    listed explicitly rather than inferred, so widening it is a visible decision.
    """
    import ast

    out: list[str] = []
    for rel in _DOCSTRING_SCOPE:
        path = REPO / rel
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module,
                                     ast.ClassDef)):
                continue
            doc = ast.get_docstring(node)
            if not doc:
                continue
            hit = _MECHANISM_RE.search(doc)
            if not hit or _CITATION_RE.search(doc):
                continue
            name = getattr(node, "name", "<module>")
            out.append(
                f"{rel}:{getattr(node, 'lineno', 1)}  `{name}` asserts a MARKET MECHANISM "
                f"({hit.group(0)!r}) in its docstring with no source or derivation. This is "
                f"where RC-315 actually lived: the register was corrected and this text — "
                f"the wording the register paraphrased — was left standing, so the refuted "
                f"claim survived its own repair (RC-320). Cite it, derive it, or describe "
                f"what the function MEASURES without claiming what it does to price.")
    return out


def register_violations() -> list[str]:
    """The same rule over the derivation registers, where RC-315's claim actually lived.

    A justification row is where a metric's meaning becomes canonical, so a causal claim
    there is at least as binding as one in the log — and harder to notice, because the row
    is one line among hundreds.
    """
    out: list[str] = []
    for path in sorted((REPO / "governance").glob(_REGISTER_GLOB)):
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace")
                                 .splitlines(), start=1):
            if "TraceableDerivation(" not in line:
                continue
            hit = _MECHANISM_RE.search(line)
            if not hit or _CITATION_RE.search(line):
                continue
            out.append(
                f"governance/{path.name}:{n}  a derivation justification asserts a MARKET "
                f"MECHANISM ({hit.group(0)!r}) with no source or derivation. This is the "
                f"exact file and the exact shape of RC-315: 'hedging MAGNITUDE pins price "
                f"regardless of net sign' was canonised here and stood until an outside "
                f"audit refuted it. Cite it, derive it, or describe the metric without "
                f"claiming what it does to price.")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    v = violations()
    if v:
        print("check_rc_mechanism_claims_cite_a_source: FAIL — uncited mechanism claims:")
        for line in v:
            print("  " + line)
        return 1
    if not args.quiet:
        print("check_rc_mechanism_claims_cite_a_source: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
