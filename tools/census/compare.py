"""Before and after: two census reports compared, section by section and category by category.

    python -m tools.census.compare <before census .md> <after census .md>

Prints, as Markdown, each section's issues before and after and the change, the whole total, and
every category whose count moved. Only issue rows are compared; reported rows have no target.

A row's count is what its check found, 0 included. A category one report does not list is 0 there
only when that report shows the same checker ran in that section (a row with the same "Counted
by"); otherwise it is unknown, shown "-", and every total that would include it is marked
incomplete, never filled in.
"""

import argparse
import re
import sys
from pathlib import Path

ROW = re.compile(r"^\| (.+?) \| (.+?) \| .+? \| (.+?) \| ([\d,]+) \| (\w+) \|$", re.M)
UNKNOWN = "-"


def rows(report: Path) -> dict[tuple[str, str], tuple[str, int, str]]:
    """Every row of a census report: (section, category) -> (counted by, count, kind)."""
    text = report.read_text(encoding="utf-8")
    return {
        (m.group(1), m.group(2)): (m.group(3), int(m.group(4).replace(",", "")), m.group(5))
        for m in ROW.finditer(text)
    }


def count(report_rows, other_rows, key) -> int | str:
    """The issue count of `key` in a report: its row's count; 0 when its checker (named by the
    other report's row) ran in that section of this report; otherwise unknown."""
    if key in report_rows:
        return report_rows[key][1]
    tool = other_rows[key][0]
    ran = any(sec == key[0] and t == tool for (sec, _), (t, _, _) in report_rows.items())
    return 0 if ran else UNKNOWN


def total(values) -> str:
    """The sum of the known counts, marked incomplete when any is unknown; unknown when none is
    known."""
    known = [v for v in values if v != UNKNOWN]
    if not known:
        return f"{UNKNOWN} (incomplete)"
    marked = " (incomplete)" if len(known) < len(values) else ""
    return f"{sum(known):,}{marked}"


def change(before, after) -> str:
    return UNKNOWN if UNKNOWN in (before, after) else f"{after - before:+,}"


def head(report: Path) -> str:
    return report.read_text(encoding="utf-8").splitlines()[0].removeprefix("# ")


def compare(before: Path, after: Path) -> str:
    b, a = rows(before), rows(after)
    keys = [k for k in dict.fromkeys([*b, *a]) if (b[k] if k in b else a[k])[2] == "issue"]
    pairs = {k: (count(b, a, k), count(a, b, k)) for k in keys}
    lines = [
        f"Before: {head(before)}  ",
        f"After: {head(after)}",
        "",
        "| Section | Before | After | Change |",
        "|---|---|---|---|",
    ]
    for s in dict.fromkeys(sec for sec, _ in keys):
        vb = [pairs[k][0] for k in keys if k[0] == s]
        va = [pairs[k][1] for k in keys if k[0] == s]
        known = UNKNOWN not in vb + va
        diff = f"{sum(va) - sum(vb):+,}" if known else UNKNOWN
        lines.append(f"| {s} | {total(vb)} | {total(va)} | {diff} |")
    vb, va = [p[0] for p in pairs.values()], [p[1] for p in pairs.values()]
    known = UNKNOWN not in vb + va
    lines += [
        f"| ALL | {total(vb)} | {total(va)} | {f'{sum(va) - sum(vb):+,}' if known else UNKNOWN} |",
        "",
        "Categories that moved or are unknown on one side:",
        "",
        "| Section | Category | Before | After | Change |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {s} | {c} | {pb if pb == UNKNOWN else f'{pb:,}'} | "
        f"{pa if pa == UNKNOWN else f'{pa:,}'} | {change(pb, pa)} |"
        for (s, c), (pb, pa) in pairs.items()
        if pb != pa
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    sys.stdout.write(compare(args.before, args.after))
