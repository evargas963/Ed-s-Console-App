#!/usr/bin/env python3
"""Phase B: remove dead JS/CSS blocks flagged in Schwab walk chunks 1–5."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "static" / "index.html"
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)


def find_line(substr: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if substr in lines[i]:
            return i
    raise SystemExit(f"not found: {substr!r}")


def delete_span(s: int, e: int) -> None:
    del lines[s : e + 1]


# CSS orphan clusters
s = find_line("  /* The Call card: state-based background")
e = find_line("  #call-stack > #mhap-card {")
while e < len(lines) and lines[e].strip() != "}":
    e += 1
delete_span(s, e)

s = find_line("  .call-section { margin-bottom: 8px;")
e = find_line("  .call-section-label {")
while e < len(lines) and "}" not in lines[e]:
    e += 1
delete_span(s, e)

s = find_line("  /* ── Right Now v2 (narrative + order flow sub-card)")
e = find_line("  .of-meta-val { font-weight: 600; }")
delete_span(s, e)

s = find_line("  /* ── What the Data Says: compact chips")
e = find_line("  #wds-card #acc-chart {")
delete_span(s, e)

s = find_line("  /* ── Call readiness toast")
e = find_line("  #call-toast.show {")
while e < len(lines) and "}" not in lines[e]:
    e += 1
delete_span(s, e)

s = find_line("  .override-btn, .override-btn-clear {")
e = s
while e < len(lines) and "override-btn-clear { margin-left" not in lines[e]:
    e += 1
delete_span(s, e)

# Globals
drop_globals = (
    "let _priorCallState = null;\n",
    "let _priorReadinessScore = null;\n",
    "let _cumDeltaHistory = [];\n",
    "let _prevSpotForChart = null;\n",
    "let _cumDeltaForInterp = [];\n",
)
lines = [ln for ln in lines if ln not in drop_globals]

text = "".join(lines)
text = text.replace(
    "    _cumDeltaHistory   = [];\n"
    "    _cumDeltaForInterp = [];\n"
    "    _prevSpotForChart  = null;\n",
    "",
)
lines = text.splitlines(keepends=True)

# showCallToast
s = find_line("function showCallToast(msg) {")
e = s
depth = 0
while e < len(lines):
    depth += lines[e].count("{") - lines[e].count("}")
    if e > s and depth <= 0 and lines[e].strip() == "}":
        delete_span(s, e)
        break
    e += 1

# renderMultiHorizon
s = find_line("function renderMultiHorizon(d) {")
e = s
depth = 0
while e < len(lines):
    depth += lines[e].count("{") - lines[e].count("}")
    if e > s and depth <= 0 and lines[e].strip() == "}":
        delete_span(s, e)
        if s < len(lines) and lines[s].strip() == "":
            del lines[s]
        break
    e += 1

# _orderFlowInterpFromDeltasAndPrice
s = find_line("function _orderFlowInterpFromDeltasAndPrice")
e = s
while e < len(lines) and lines[e].strip() != "}":
    e += 1
delete_span(s, e)
if s < len(lines) and lines[s].strip() == "":
    del lines[s]

# applyFastSpotOrderFlowOverlay
s = find_line("function applyFastSpotOrderFlowOverlay(f) {")
e = s
depth = 0
while e < len(lines):
    depth += lines[e].count("{") - lines[e].count("}")
    if e > s and depth <= 0 and lines[e].strip() == "}":
        delete_span(s, e)
        break
    e += 1
lines = [ln for ln in lines if "applyFastSpotOrderFlowOverlay(f)" not in ln]

# render() dead block
s = find_line("  // ── Card 1: Right Now")
e = find_line("  } catch (e) { console.warn('WTDS render:', e); }")
delete_span(s, e)

# renderCharmDriftRow
s = find_line("  function renderCharmDriftRow(d) {")
e = s
depth = 0
while e < len(lines):
    depth += lines[e].count("{") - lines[e].count("}")
    if e > s and depth <= 0 and lines[e].strip() == "}":
        e += 1
        break
    e += 1
if e < len(lines) and "__renderCharmDriftRowLive" in lines[e]:
    e += 1
delete_span(s, e - 1)

lines = [ln for ln in lines if "renderCharmDriftRow(d)" not in ln]
lines = [ln for ln in lines if "__renderCharmDriftRowLive" not in ln]

# override listeners
s = find_line("// ── Prediction override (user manual override)")
e = find_line("function renderDBStats(d)")
delete_span(s, e - 1)

lines = [ln for ln in lines if 'id="call-toast"' not in ln]

p.write_text("".join(lines), encoding="utf-8")
print(f"Phase B cleanup wrote {p} ({len(lines)} lines)")
