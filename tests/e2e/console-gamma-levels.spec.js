// @ts-check
/**
 * D — Options/Gamma "Levels" view. Serializes the canonical levels panel (per-level
 * price/family/evidence_tier/provenance/staleness + carried VWAP) verbatim; computes nothing.
 * Proves the table renders the contract, discloses VWAP/absent/degraded honestly, marks no
 * proximity, and a level click drives the shared strike selection; and that each home of the
 * view (Options · Gamma · Levels, Liquidity · Levels) shows what its rows are made of, as
 * served: the price-level snapshot's time and age, the gamma levels' verdict and the price's
 * not-live mark. Offline.
 */
const { test, expect } = require("@playwright/test");
const { pushExpiries } = require("./fixtures/expiries");
const { routeWatchlist } = require("./fixtures/watchlist");
// the strikes panel as the server sends it on CRWD's real chain (held to the server by
// tests/test_vanna_charm_by_strike_v1.py)
const REAL = require("./fixtures/vanna_charm_panels_crwd.json");
// SPY's levels panel during its session, as the route served it, and (INDUCED) as it read ten
// minutes on with no chain, bar, trade or heartbeat since: the keys that read differently
// (`later`) laid over it (both held to the route by tests/test_e2e_panels_two_day_v1.py)
const SPY = require("./fixtures/panels_spy_two_day.json");
const SERVED = SPY.levels["1"];
const LATER = Object.assign({}, SERVED, SPY.later.levels);
// the view's two badges as the page draws them from a panel: the price-level snapshot's time and
// age, and the gamma levels' verdict (its state word, time and age)
function badges(d) {
  return [
    ["reference levels", d.snapshot_time_ct, d.snapshot_age_text].join(" · "),
    ["terrain", d.levels_state, d.levels_time_ct, d.levels_age_text].join(" · "),
  ];
}
// the view's two homes: where each is, and the host it draws in
const HOMES = [
  ["Options · Gamma · Levels", "options", "gamma", "#levelsBody"],
  ["Liquidity · Levels", "liquidity", "levels", "#lvlBody"],
];

// each price with its text as the server serves it (two decimals, numeric_contract.price_text)
const LEVELS = {
  ticker: "SPY",
  schema_version: 1,
  spot: 100.0,
  spot_text: "100.00",
  spot_source: "streaming_plane", // push.spot.SPOT_SOURCE_PLANE, as the program serves it
  bar_source: "price_bars_1m",
  // served in ladder order (price, highest first) with distance (server.py get_levels)
  levels: [
    {
      id: "PDH",
      price: 101.5,
      price_text: "101.50",
      family: "session",
      label: "Prior Day High",
      evidence_tier: "MEASURED",
      distance: 1.5,
      provenance: { producer: "session_levels" },
      staleness: { as_of_time_ct: null },
    },
    {
      id: "VWAP",
      price: 100.02,
      price_text: "100.02",
      family: "vwap",
      label: "VWAP",
      evidence_tier: "MEASURED",
      distance: 0.02,
      provenance: { producer: "liquidity_value_engine" },
      staleness: { as_of_time_ct: null },
    },
    {
      id: "POC",
      price: 99.4,
      price_text: "99.40",
      family: "value",
      label: "Point of Control",
      evidence_tier: "DERIVED",
      distance: -0.6,
      provenance: { producer: "value_area" },
      staleness: { as_of_time_ct: null },
    },
  ],
  by_distance: ["VWAP", "POC", "PDH"],
  vwap_series: [[1757000000, 100.0]],
  families_absent: [{ family: "gamma", reason: "sent as the terrain panel" }],
  degraded: [],
};

// a 0DTE pair as served: the whole book's largest call gamma strike and the same-day one, each
// with its text
const ZERO_DTE_CALL_WALL = {
  id: "call_wall",
  label: "Gamma Call",
  carried: 600,
  price: 580,
  carried_text: "600.00",
  price_text: "580.00",
  staleness: { as_of_time_ct: "12:32:07 CT" },
};

// the panels the page's socket sends this test (a test sets its own levels before the page
// opens), and the program's side of that socket
let panels, sock;
async function intercept(page) {
  await routeWatchlist(page, ["SPY"]);
  panels = {
    levels: LEVELS,
    bars: { available: false },
    tape: REAL.tape,
    terrain: REAL.terrain,
    strikes: REAL.strikes,
    surface: REAL.surface,
  };
  sock = await pushExpiries(page, ["2026-09-11"], undefined, panels);
}

test.describe("D — Gamma Levels view", () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_view", "levels");
    });
  });

  test("the levels spot keeps its last trade time", async ({ page }) => {
    panels.levels = Object.assign({}, LEVELS, { spot_time_ct: "Fri 10/02 10:00 AM CT" });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("#levelsBody .lv-spot")).toHaveText(
      "spot 100.00 · streaming_plane · last trade Fri 10/02 10:00 AM CT",
    );
  });

  test("a level keeps its price with the time the server sent", async ({ page }) => {
    const LEVEL_TIME = "Fri 09/25 06:59 PM CT";
    const levels = JSON.parse(JSON.stringify(LEVELS));
    levels.levels.forEach(function (r) {
      r.staleness.as_of_time_ct = LEVEL_TIME;
    });
    panels.levels = levels;
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const cell = page
      .locator("#levelsBody .lv-row", { hasText: "Prior Day High" })
      .locator(".lv-px")
      .nth(0);
    await expect(cell).toContainText("101.50");
    await expect(cell.locator(".lv-age")).toHaveText(LEVEL_TIME);
    await expect(cell).not.toContainText("12s");
    await expect(page.locator("#levelsBody th", { hasText: "As-of" })).toHaveCount(0);
  });

  test("renders the canonical levels contract as a table", async ({ page }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const lv = page.locator("#levelsBody");
    await expect(lv.locator("table.lv")).toBeVisible();
    await expect(lv.locator(".lv-row")).toHaveCount(3);
    // the served ladder order: PDH (101.5) first
    await expect(lv.locator("th").nth(0)).toHaveText("Level");
    await expect(lv.locator("th").nth(1)).toHaveText("Regular");
    await expect(lv.locator("th").nth(2)).toHaveText("0DTE");
    await expect(lv.locator("th", { hasText: "Family" })).toHaveCount(0);
    await expect(lv.locator("th", { hasText: "Evidence" })).toHaveCount(0);
    await expect(lv.locator("th", { hasText: "Source" })).toHaveCount(0);
    await expect(lv.locator(".lv-row").first()).toContainText("Prior Day High");
    await expect(lv.locator(".lv-row").first().locator(".lv-px").nth(0)).toHaveText("101.50");
    await expect(lv.locator(".lv-row", { hasText: "VWAP" }).locator(".lv-px").nth(0)).toHaveText(
      "100.02",
    );
    await expect(lv.locator(".lv-row", { hasText: "VWAP" }).locator(".lv-px").nth(1)).toHaveText(
      "-",
    );
    // no proximity marking (operator 2026-09-29); absence disclosed honestly
    await expect(lv.locator(".lv-row.near-spot")).toHaveCount(0);
    await expect(lv.locator(".lv-foot")).toContainText("VWAP curve");
    // the VWAP's standard deviation bands are removed (operator 2026-11-20): none is named
    await expect(lv).not.toContainText("σ");
    await expect(lv.locator(".lv-foot .lv-absent")).toContainText("gamma");
    await page.setViewportSize({ width: 1672, height: 941 });
    await page.screenshot({ path: "test-results/gamma-levels-1672x941.png", fullPage: false });
  });

  test("a level click highlights locally but NEVER writes selStrike (a level price is not a strike)", async ({
    page,
  }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const before = await page.evaluate(() => window.EdShell.getState().selStrike);
    await page.locator("#levelsBody .lv-row", { hasText: "Prior Day High" }).click(); // price 101.5
    await expect(page.locator("#levelsBody .lv-row.lv-sel")).toHaveCount(1); // local highlight only
    const after = await page.evaluate(() => window.EdShell.getState().selStrike);
    expect(after).toBe(before); // selStrike unchanged
    expect(after).not.toBe(101.5); // never the level price
  });

  test("the 0DTE table shows the served same-day price beside the level it reprices", async ({
    page,
  }) => {
    panels.levels = Object.assign({}, LEVELS, { zero_dte: [ZERO_DTE_CALL_WALL] });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const row = page.locator("#levelsBody .zd-row", { hasText: "Gamma Call" });
    await expect(row.locator(".lv-px").nth(0)).toContainText("600.00");
    await expect(row.locator(".lv-px").nth(1)).toContainText("580.00");
    await expect(row.locator(".lv-px").nth(1).locator(".lv-age")).toHaveText("12:32:07 CT");
  });

  test("the largest open interest strike's row shows the served note on hover", async ({
    page,
  }) => {
    // SPY's levels panel during its session: its expiry closes that day with time left, so it has
    // that strike (after the close it has no time left and no value)
    const pin = SERVED.levels.find((r) => r.id === "pin_candidate");
    expect(pin.note).toContain("expected moves");
    panels.levels = SERVED;
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const row = page.locator("#levelsBody .lv-row", { hasText: "OI Pin" });
    await expect(row).toHaveAttribute("title", pin.note);
    await expect(row.locator(".lv-px").nth(0)).toContainText(pin.price.toFixed(2));
  });

  test("the 0DTE table still shows when the canonical list is empty", async ({ page }) => {
    panels.levels = Object.assign({}, LEVELS, { levels: [], zero_dte: [ZERO_DTE_CALL_WALL] });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("#levelsBody .placeholder")).toHaveCount(0);
    await expect(page.locator("#levelsBody th", { hasText: "Regular" })).toBeVisible();
    await expect(page.locator("#levelsBody .zd-row .lv-px").nth(1)).toContainText("580.00");
    await expect(page.locator("#levelsBody .zd-row .lv-px").nth(1).locator(".lv-age")).toHaveText(
      "12:32:07 CT",
    );
  });

  test("new levels reach the view on the page's socket with no ask; levels not produced say why", async ({
    page,
  }) => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const pdh = page
      .locator("#levelsBody .lv-row", { hasText: "Prior Day High" })
      .locator(".lv-px")
      .nth(0);
    await expect(pdh).toContainText("101.50");
    expect(sock.subscribes[sock.subscribes.length - 1].panels["levels:view"]).toEqual({ tf: "1" });
    const asked = sock.subscribes.length;
    panels.levels = Object.assign({}, LEVELS, {
      levels: LEVELS.levels.map((r) =>
        r.id === "PDH" ? Object.assign({}, r, { price: 101.75, price_text: "101.75" }) : r,
      ),
    });
    sock.changed("levels");
    await expect(pdh).toContainText("101.75");
    const words =
      "the program could not produce this panel: ValueError: tf '2' is not one of 1, 3, 5, 15, 30, 60, D";
    panels.levels = { failed: words };
    sock.changed("levels");
    await expect(page.locator("#levelsBody")).toContainText(words);
    expect(sock.subscribes.length).toBe(asked);
  });

  for (const [home, ws, sub, host] of HOMES) {
    test(`${home}: the rows stand with their snapshot's time and age and the levels verdict, live and after they stopped arriving`, async ({
      page,
    }) => {
      panels.levels = SERVED;
      await page.addInitScript(
        ([w, s]) => {
          localStorage.setItem("ed_ws", w);
          localStorage.setItem("ed_sub", s);
        },
        [ws, sub],
      );
      await page.goto("/", { waitUntil: "domcontentloaded" });
      const asof = page.locator(host + " .chart-asof .asof");
      const spot = page.locator(host + " .lv-spot");
      const rows = page.locator(host + " .lv-row");
      // SPY's levels during its session: the snapshot's time and age, the verdict LIVE, and the
      // price with its last trade's time
      expect([SERVED.levels_state, SERVED.spot_not_live_text]).toEqual(["LIVE", null]);
      await expect(asof).toHaveText(badges(SERVED));
      await expect(asof.nth(1)).toHaveClass("asof live");
      await expect(spot).toHaveText(
        `spot ${SERVED.spot_text} · ${SERVED.spot_source} · last trade ${SERVED.spot_time_ct}`,
      );
      const drawn = await rows.allTextContents();
      expect(drawn.length).toBeGreaterThan(SERVED.zero_dte.length);
      // INDUCED: the same levels ten minutes on with nothing renewed. The last values stand,
      // every row as it was; the verdict reads STALE with the chain's time, its age and why, the
      // snapshot is ten minutes older, and the price is marked not live with its time and age
      panels.levels = LATER;
      sock.changed("levels");
      expect([LATER.levels_state, LATER.levels_age_text]).toEqual(["STALE", "10m"]);
      await expect(asof).toHaveText(badges(LATER));
      await expect(asof.nth(1)).toHaveClass("asof stale");
      await expect(asof.nth(1)).toHaveAttribute("title", LATER.levels_stale_reason);
      expect(LATER.spot_not_live_text).toContain("not live · last trade " + LATER.spot_time_ct);
      await expect(spot).toHaveText(
        `spot ${LATER.spot_text} · ${LATER.spot_source} · ${LATER.spot_not_live_text}`,
      );
      expect(await rows.allTextContents()).toEqual(drawn);
    });
  }

  test("a ticker switch leaves nothing of the last ticker: its rows and its badges", async ({
    page,
  }) => {
    await routeWatchlist(page, ["SPY", "QQQ"]);
    panels.levels = (key) => (key === "SPY" ? SERVED : undefined); // QQQ's panel is not sent
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("#levelsBody .chart-asof .asof")).toHaveText(badges(SERVED));
    await page.evaluate(() => window.EdShell.setTicker("QQQ"));
    await expect(page.locator("#levelsBody .placeholder")).toHaveText("-");
    await expect(page.locator("#levelsBody .lv-row")).toHaveCount(0);
    await expect(page.locator("#levelsBody .asof")).toHaveCount(0);
  });
});
