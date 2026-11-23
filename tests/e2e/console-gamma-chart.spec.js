// @ts-check
/**
 * Options/Gamma "Chart" subview (Price + GEX Profile / GEX Dot Map). The strikes panel is a
 * genuine all-expiry aggregate -- no single mark has one real expiry to attribute, confirmed by
 * reading terrain_engine.py's _per_strike_rows and compute_exposures_by_strike (they collapse
 * call+put across EVERY expiry sharing a strike; there is no principled way to pick "the" call
 * and put symbol for an aggregate row without first choosing one specific expiry, which the
 * aggregate deliberately does not track). But clicking a mark is still a deliberate strike
 * selection, and every OTHER view that calls EdShell.setStrike (heatmap: the column's real
 * expiry; Chain: the one displayed expiry) always supplies a real expiry so Strike Detail can
 * resolve one. Chart's click handler used to pass NO expiry at all, unconditionally clobbering
 * state.selExpiry to null (ed-core.js setStrike) even when the operator had a specific expiry
 * filter selected in the workspace -- silently discarding that context and sending Strike
 * Detail's chain panel to the server's own default-expiry resolution instead.
 *
 * Independent-review finding (2026-09-13), REPRODUCED. Fixed: the click now carries through
 * whatever workspace expiry filter (EdShell.getExpiry()) is currently set, matching the
 * established convention, while still passing null when the filter itself is null (Chart has no
 * per-mark expiry to invent in that case either).
 *
 * Every click is a real pointer `.click()` on the hit target ed-gamma-chart.js draws beside each
 * mark, and the CHAIN fixture carries native OSI-style symbols, so the whole path runs: Chart
 * click -> expiry carried through -> Strike Detail's chain panel -> that strike's call and put.
 */
const { test, expect } = require("@playwright/test");
const { pushExpiries } = require("./fixtures/expiries");
const { routeWatchlist } = require("./fixtures/watchlist");

// the strikes panel as the server sends it on CRWD's real chain (held to the server by
// tests/test_vanna_charm_by_strike_v1.py): eleven strikes around 270, with the DEX and OI measures
const STRIKES = require("./fixtures/vanna_charm_panels_crwd.json").strikes;
const SPOT = STRIKES.today.find((r) => r.marks.some((m) => m.kind === "spot")).strike; // 270
const K = STRIKES.today[6].strike; // 272.5, the strike a test clicks
// each level with its text as the server serves it (two decimals, numeric_contract.price_text)
const PUT_WALL = STRIKES.today[4].strike;
const TERRAIN = {
  spot: SPOT,
  gamma_flip: SPOT - 0.5,
  call_wall: K,
  put_wall: PUT_WALL,
  gamma_flip_text: (SPOT - 0.5).toFixed(2),
  call_wall_text: K.toFixed(2),
  put_wall_text: PUT_WALL.toFixed(2),
  same_day_text: {},
  // the regime, and as the screen says it (calc.terrain_read.REGIME_TEXT)
  regime: "POSITIVE_GAMMA",
  regime_text: "Positive gamma",
  levels_state: "LIVE",
  levels_mark: "LIVE",
};
const BARS = {
  bars: [
    {
      t: 1757000000,
      o: SPOT - 1,
      h: SPOT + 1,
      l: SPOT - 2,
      c: SPOT,
      v: 1,
      o_text: (SPOT - 1).toFixed(2),
      h_text: (SPOT + 1).toFixed(2),
      l_text: (SPOT - 2).toFixed(2),
      c_text: SPOT.toFixed(2),
      v_text: "1",
    },
  ],
};
const CALL_SYM = "CRWD  260918C00272500";
const PUT_SYM = "CRWD  260918P00272500";
const CHAIN = {
  expiry: "2026-09-18",
  status: "ok",
  scope: { kind: "complete_single_expiry", kind_text: "complete (ALL)" }, // push.chain.SCOPE_TEXT
  // push.chain's ladder: the strike's call and put rows, no surface value (net_gex unknown)
  ladder: [
    {
      strike: K,
      strike_text: String(K),
      net_gex: null,
      call: {
        symbol: CALL_SYM,
        gamma: 0.021,
        delta: 0.5,
        oi_text: "1,200",
        volume_text: "540",
        iv_text: "12.00",
      },
      put: {
        symbol: PUT_SYM,
        gamma: 0.019,
        delta: -0.5,
        oi_text: "980",
        volume_text: "410",
        iv_text: "12.00",
      },
    },
  ],
};

// the page's socket sends `terrain` (the flip and the walls), `strikes` (the profile) and `bars`
// as the panels' bodies; returns those `panels`, read at each send
async function intercept(page, terrain = TERRAIN, strikes = STRIKES) {
  const chainRequests = []; // the expiry Strike Detail's chain panel asks, each time it is sent
  const panels = {
    terrain: terrain,
    strikes: strikes,
    bars: BARS,
    chain: (key, params, name) => {
      if (name === "chain:detail") chainRequests.push(params.expiry);
      return Object.assign({}, CHAIN, params.expiry ? { expiry: params.expiry } : {});
    },
  };
  await routeWatchlist(page, ["SPY"]);
  await pushExpiries(page, ["2026-09-11", "2026-09-18"], undefined, panels);
  return { chainRequests, panels };
}

// a real mouse click where the chart draws the strike's profile row, once the row has stopped
// moving: after the first draw the price axis widens to fit its labels, so a point read at once
// can sit on the axis by the time the click lands
async function clickStrike(page, strike) {
  let pt = null;
  await expect
    .poll(
      async () => {
        const prev = pt;
        pt = await page.evaluate((k) => window.EdGammaChart.profilePoint(k), strike);
        return !!(prev && pt && prev.x === pt.x && prev.y === pt.y);
      },
      { intervals: [150] },
    )
    .toBe(true);
  await page.mouse.click(pt.x, pt.y);
}

test.describe("Options/Gamma Chart subview", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
    });
  });

  test("a real click on a Chart mark carries the workspace expiry through to Strike Detail's real native call/put identity (state-authority review)", async ({
    page,
  }) => {
    const { chainRequests } = await intercept(page);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.locator('.vtab[data-view="chart"]').click();
    await page.locator("#expSel").selectOption("2026-09-18");
    await expect
      .poll(() =>
        page.evaluate(() => (window.EdGammaChart.state() || { profile: {} }).profile.rows),
      )
      .toBeGreaterThan(0);

    chainRequests.length = 0;
    // A genuine pointer click on strike K's profile row on the shared chart
    await clickStrike(page, K);

    // the page applies a click on its own schedule: wait for the selection, never read it at once
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().selStrike)).toBe(K);
    const state = await page.evaluate(() => window.EdShell.getState());
    expect(state.selExpiry).toBe("2026-09-18"); // NOT null -- the workspace filter, carried through
    await expect.poll(() => chainRequests.length).toBeGreaterThan(0);
    expect(chainRequests.every((e) => e === "2026-09-18")).toBeTruthy();

    // Strike Detail shows strike K's call AND put at this expiry, each its own contract's open
    // interest as served -- the complete workflow, not just the numeric strike+expiry handoff.
    await expect(page.locator("#sdBody table.sd tbody tr").nth(0).locator("td").nth(1)).toHaveText(
      "1,200",
    );
    await expect(page.locator("#sdBody table.sd tbody tr").nth(1).locator("td").nth(1)).toHaveText(
      "980",
    );
  });

  test("with no expiry filter set, a Chart click leaves selExpiry null (no invented expiry)", async ({
    page,
  }) => {
    await intercept(page);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator("#expSel")).toHaveValue("");
    await expect
      .poll(() =>
        page.evaluate(() => (window.EdGammaChart.state() || { profile: {} }).profile.rows),
      )
      .toBeGreaterThan(0);

    await clickStrike(page, K);
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().selStrike)).toBe(K);
    expect(await page.evaluate(() => window.EdShell.getState().selExpiry)).toBeNull();
  });

  test("the GEX profile leaves a strike of GEX not known undrawn, with no page error", async ({
    page,
  }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    // induced: the real rows with the GEX of the strike at the price not known
    const today = STRIKES.today.map((row) =>
      row.strike === SPOT ? Object.assign({}, row, { value: null, text: null }) : row,
    );
    await intercept(page, TERRAIN, Object.assign({}, STRIKES, { today }));
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect
      .poll(() =>
        page.evaluate(() => (window.EdGammaChart.state() || { profile: {} }).profile.rows),
      )
      .toBe(STRIKES.today.length - 1);
    expect(errors).toEqual([]);
  });

  test("a failed request is named on the chart, never drawn as an empty answer", async ({
    page,
  }) => {
    // the program unable to produce the terrain panel while the bars and the profile arrive: the
    // flip and the walls are not drawn and the chart says the program's words; then the bars
    // panel not produced either
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    const words = "the program could not produce this panel: RuntimeError: chain lock timed out";
    const barsWords = "the program could not produce this panel: OSError: bars read failed";
    const { panels } = await intercept(page, { failed: words });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator("#chartBody .gchart-empty")).toHaveText(words);
    await expect.poll(() => page.evaluate(() => window.EdGammaChart.state().levels.length)).toBe(0);
    panels.bars = { failed: barsWords };
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator('.vtab[data-view="chart"]').click();
    await expect(page.locator("#chartBody .gchart-empty")).toHaveText(barsWords + " · " + words);
    expect(errors).toEqual([]);
  });

  test("the Delta / DEX and Open Interest Chart views draw the served profile of their measure", async ({
    page,
  }) => {
    // operator 2026-09-29: "dex has a chart, oi has a chart" -- both views were blank
    await intercept(page);
    for (const [sub, rows, title] of [
      ["dex", STRIKES.measures.dex.rows.length, "Price + DEX Profile"],
      ["oi", STRIKES.measures.oi.rows.length, "Price + Open Interest Profile"],
    ]) {
      await page.addInitScript((s) => {
        localStorage.setItem("ed_ws", "options");
        localStorage.setItem("ed_sub", s);
        localStorage.setItem("ed_view", "chart");
        localStorage.setItem("ed_scope", "all");
      }, sub);
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.locator("#mvTitle")).toHaveText(title);
      await expect
        .poll(() =>
          page.evaluate(() => (window.EdGammaChart.state() || { profile: {} }).profile.rows),
        )
        .toBe(rows);
      await expect(page.locator("#chartBody .chart-legend")).toContainText(
        "largest |" +
          (sub === "oi" ? "OI" : "DEX") +
          "| " +
          STRIKES.measures[sub].max_abs_row.strike,
      );
    }
  });
});
