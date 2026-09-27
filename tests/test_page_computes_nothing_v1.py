"""The page computes nothing (AGENTS.md rule 4): every page script is scanned for the calculation
patterns the 2026-09-27 inventory found (tools/data_faucet_audit.py PAGE_CALCULATIONS), through the
same audit the single_faucet_provenance gate runs. The scan cannot see every calculation; DATA_FLOW
section 5 states its limit."""
from tools.data_faucet_audit import page_calculation_hits, page_calculations

# Lines the page ran before P1-3 (static/js at be314629) and P1-9 (the strike sorts) moved them to
# the server, one per pattern.
OLD_PAGE_CODE = """
var t0 = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
var ex = expiryFilter() || Object.keys(byExp).sort()[0] || '';
if (isFinite(sp)) strikes.forEach(function (k, i) { var d = Math.abs(Number(k) - sp); if (d < best) { best = d; c = i; } });
  .sort(function (a, b) { return Math.abs(a.price - spot) - Math.abs(b.price - spot); });
if (r.gx > 0) { sPos += r.k * r.gx; wPos += r.gx; }
var totVol = win.reduce(function (a, r) { return a + (r[2] || 0); }, 0);
var asc = rows.slice().sort(function (a, b) { return a[0] - b[0]; });
var strikes = Object.keys(byStrike).map(Number).sort(function (a, b) { return b - a; });
"""


def test_the_page_scripts_compute_nothing():
    assert page_calculations() == [], "a page script computes a value the server must serve"


def test_the_scan_catches_each_calculation_the_page_used_to_make():
    kinds = {h.split(" ", 1)[1].split(":", 1)[0] for h in page_calculation_hits(OLD_PAGE_CODE, "old.js")}
    assert kinds == {"calendar arithmetic", "first-key pick", "distance to spot", "sort by distance",
                     "weighted sum", "sum", "sort by strike"}


def test_drawing_and_formatting_pass():
    drawing = """
var maxAbs = win.reduce(function (m, r) { return Math.max(m, Math.abs(Number(r[1]) || 0)); }, 0) || 1;
var w = Math.min(100, Math.abs(v) / maxAbs * 100);
var y = padTop + (priceRows - 1 - row) * rowH;
return String(Math.round(Math.abs(n)));
"""
    assert page_calculation_hits(drawing, "draw.js") == []
