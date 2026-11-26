/*
 * Trade Desk (Desk + Right Now) renders what the server serves and computes nothing (P1-3, PR B,
 * 2026-09-27): the attention queue is the desk panel (numbered, ordered, window-counted on the
 * server); book side, tape side, flip relation, wall distances, spot-vs-zones, levels by distance
 * and the positioning migration are served fields. The panels are the server's own answers for
 * SPY at 2026-11-12 10:30:41 ET (tests/e2e/fixtures/trade_desk.js); a test's induced condition is
 * that answer with the named part changed. Any page error fails the test.
 */
const { test, expect } = require("@playwright/test");
const path = require("path");
const { mockPriceSocket, priceRow } = require("./fixtures/price_socket");
const { routeWatchlist } = require("./fixtures/watchlist");
const { watchRequests, holdClock } = require("./fixtures/settled");

const {
  REAL,
  EVENTS,
  SPOT,
  TERRAIN,
  LEVELS,
  MICRO,
  LIQ,
  STRIKES,
  BARS,
  intercept,
  openView,
  watchErrors,
  deskPanels,
  deskSocket,
  levelsAt,
  tfAt,
} = require("./fixtures/trade_desk");
// the composite of Schwab's two books, as the book panel's readout answers it
const COMP = MICRO.readout.venues.COMPOSITE;
// a strikes window as GEX by Strike lists it: highest strike first
const listed = (strikes) => strikes.today.map((r) => String(r.strike)).reverse();
// the zone the price is inside (the liquidity panel types each zone by its side of the price)
const INSIDE = LIQ.zones.find((z) => z.zone_label === "Price inside zone");
// INDUCED: that zone's top moved, the panel as the program would send it
const TOP_MOVED = Object.assign({}, LIQ, {
  zones: LIQ.zones.map((z) =>
    z === INSIDE ? Object.assign({}, z, { zone_high: 758.5, zone_high_text: "758.50" }) : z,
  ),
  location_said: "Price inside zone (757.00–758.50, levels in zone 4)",
});
// the marks a panel of the levels' values is served with, as the page draws them: the price-level
// snapshot's time and age, and the levels verdict (its state word, time and age)
const snapshotMark = (d) =>
  ["reference levels", d.snapshot_time_ct, d.snapshot_age_text].join(" · ");
const verdictMark = (d) =>
  ["terrain", d.levels_state, d.levels_time_ct, d.levels_age_text].join(" · ");
// push.liquidity.liquidity_snapshot's answer with no price levels published
// (NO_PRICE_LEVELS_REASON): no zone, and why
const NO_PRICE_LEVELS = {
  ticker: "SPY",
  available: false,
  zones: [],
  reason:
    "no reference levels published for this ticker for the market's session yet (they are " +
    "built from its 1-minute bars on each new bar and at the console's start)",
};
// a level far above the candles' range: the GRC as the levels panel serves one
const FAR_GRC = {
  id: "grc",
  price: 837.58,
  price_text: "837.58",
  family: "gamma",
  label: "GRC",
  short: "GRC",
  evidence_tier: "DERIVED",
  distance: 66.28,
  side: "ABOVE",
};

test("every chart is the one TradingView-style chart, with its controls", async ({ page }) => {
  // operator 2026-09-28: "each and every chart in the app needs to use the same TV controls" --
  // the Gamma chart (SVG), the book heatmap (canvas) and the liquidity map (DOM) each had their
  // own pan/zoom code; each now draws on ed-tv-chart.js (.tvc, its A / L controls, click-to-pin)
  const errs = watchErrors(page);
  await intercept(page);
  const views = [
    ["trade-desk", "desk", "", "#tdmChart"],
    ["options", "gamma", "chart", "#chartBody"],
    ["order-flow", "heatmap", "", "#ofhBody"],
    ["liquidity", "map", "", "#liqmBody"],
  ];
  for (const [ws, sub, view, host] of views) {
    await openView(page, ws, sub, view);
    await expect(page.locator(host + " .tvc-auto"), ws + "/" + sub).toBeVisible();
    await expect(page.locator(host + " .tvc-log"), ws + "/" + sub).toBeVisible();
  }
  // the liquidity map draws the served zones and shows the prior-day level from the levels panel: a line
  // when it is inside the candles' price range, else named at the pane's edge (the scale fits the
  // candles, 2026-09-29)
  await expect
    .poll(() =>
      page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().zones),
    )
    .toBe(LIQ.zones.length);
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window.EdLiquidityMap.state() || { levels: [] }).levels.join(" ") +
          " " +
          document.querySelector("#liqmBody .tvc-edge-top").textContent,
      ),
    )
    .toContain("PDH");
  expect(errs).toEqual([]);
});

// 2026-09-29 RTH, measured in the operator's browser: a fresh desk load asked for every value twice
// (start() ran on ed:view and ed:ticker; the second saw no bars yet and loaded again), and a
// timeframe switch re-asked for the zones, strikes, options lean and flow bars (and the terrain, now the
// socket's panel), none of which
// depend on the timeframe -- 6.8 s to redraw.
test("a desk load asks for each value once; a timeframe switch asks only for that timeframe and says it is loading", async ({
  page,
}) => {
  const errs = watchErrors(page);
  const sock = await intercept(page);
  // each ask the desk made of a panel, in order (one per change of its parameters)
  const asks = (name) =>
    sock.subscribes
      .map((s) => s.panels[name])
      .filter((p) => p !== undefined)
      .filter((p, i, a) => i === 0 || JSON.stringify(p) !== JSON.stringify(a[i - 1]));
  const levelsAsks = () => asks("levels:map").map((p) => p.tf);
  let barsHeld = true; // the 15m bars are not sent until the test says
  deskPanels().bars = (key, params, name) =>
    barsHeld && params.tf === "15"
      ? undefined
      : name === "bars:flow"
        ? REAL.bars_flow
        : REAL.bars[params.tf];
  await page.addInitScript(() => {
    localStorage.setItem("ed_ticker", "SPY");
    localStorage.setItem("ed_ws", "trade-desk");
    localStorage.setItem("ed_sub", "desk");
    localStorage.setItem("ed.desk.tf", "5");
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect
    .poll(() => page.evaluate(() => window.EdTradeDeskMap.state().bars))
    .toBeGreaterThan(0);
  const DESK = [
    "desk",
    "liquidity:deskmap",
    "option_book:desk",
    "book:deskmap",
    "bars:deskmap",
    "bars:flow",
  ];
  for (const name of DESK) expect(asks(name).length, name).toBe(1);
  expect(asks("bars:deskmap")[0].tf).toBe("5");
  expect(asks("bars:flow")[0].tf).toBe("1");
  expect(levelsAsks()).toEqual(["5"]);

  await page.locator('#tdmToolbar [data-tf="15"]').click();
  // while the 15m bars are on their way the 5m view is gone and the chart says what is loading
  await expect(page.locator("#tdmChartEmpty")).toHaveText(/Loading SPY · 15m/);
  expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.bars)).toBe(0);
  expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.markers.length)).toBe(0);
  barsHeld = false;
  sock.changed("bars");
  await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.tf)).toBe("15");
  // the switch changed the ask of the timeframe's panels alone
  expect(DESK.filter((name) => asks(name).length !== 1)).toEqual(["desk", "bars:deskmap"]);
  expect(asks("desk").map((p) => p.tf)).toEqual(["5", "15"]);
  expect(asks("bars:deskmap").map((p) => p.tf)).toEqual(["5", "15"]);
  expect(levelsAsks()).toEqual(["5", "15"]);
  expect(errs).toEqual([]);
});

test("Liquidity map: the live price keeps its last trade time", async ({ page }) => {
  // the price line is the header's own row (one producer), not a panel's copy
  await intercept(page, [priceRow("SPY", SPOT, { trade_time_ct: "Fri 10/02 10:00 AM CT" })]);
  deskPanels().levels = levelsAt(LEVELS);
  await openView(page, "liquidity", "map");
  await expect
    .poll(() =>
      page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().liveTitle),
    )
    .toBe("LAST · last trade Fri 10/02 10:00 AM CT");
  await expect
    .poll(() =>
      page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().livePrice),
    )
    .toBe(SPOT);
});

test("a level at 0 draws as a price: the map lists its zone, the desk its value words", async ({
  page,
}) => {
  // the route's answer on SPY's bars with a session's prices at 0 (tests/test_data_path_liquidity_zero_v1.py
  // keeps this file equal to it): a reported 0 is 0
  const AT_ZERO = require(
    path.join(__dirname, "fixtures", "standin_liquidity_with_a_session_at_zero.json"),
  );
  const errs = watchErrors(page);
  await intercept(page);
  deskPanels().liquidity = AT_ZERO;
  await openView(page, "liquidity", "map");
  const atZero = AT_ZERO.zones.find((z) => z.zone_low === 0); // the zone the 0 prices made
  await expect(page.locator(".liqm-zones")).toContainText(atZero.zone_label + " 0.00");
  await expect
    .poll(() =>
      page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().zones),
    )
    .toBe(AT_ZERO.zones.length);
  // no chain is published for the stand-in ticker, and the zones' marks say so as served: the
  // snapshot's time and age, and the levels STALE with why on hover and no time to show
  const asof = page.locator("#liqmSrc .asof");
  expect([AT_ZERO.levels_time_ct, AT_ZERO.levels_age_text]).toEqual([null, null]);
  await expect(asof).toHaveText([snapshotMark(AT_ZERO), "terrain · " + AT_ZERO.levels_state]);
  await expect(asof.nth(1)).toHaveClass("asof stale");
  await expect(asof.nth(1)).toHaveAttribute("title", AT_ZERO.levels_stale_reason);
  // each level type's hold rate as served, and what it is on hover
  const hold = page.locator(".liqm-hold");
  await expect(hold).toHaveAttribute("title", AT_ZERO.hold_note);
  await expect(hold.locator(".fl-row")).toHaveCount(AT_ZERO.hold_rates.length);
  await expect(hold.locator(".fl-row").first()).toContainText(
    AT_ZERO.hold_rates[0].level + AT_ZERO.hold_rates[0].text,
  );
  await page.addInitScript(() => {
    localStorage.setItem("ed_ws", "trade-desk");
    localStorage.setItem("ed_sub", "desk");
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator("#tdmAgree")).toContainText("VALUElower");
  await expect(page.locator("#tdmAgree")).toContainText("above value");
  expect(errs).toEqual([]);
});

test("Liquidity map: a failed request is named, and an empty snapshot shows the served reason", async ({
  page,
}) => {
  // the liquidity panel's answer with no price levels published, and the bars panel not produced
  // (the program's words on the socket): the map says so for each, never draws a failure as an
  // empty answer
  const barsWords = "the program could not produce this panel: RuntimeError: bars lock timed out";
  const liqWords = "the program could not produce this panel: KeyError: 'SPY'";
  const errs = watchErrors(page);
  await intercept(page);
  deskPanels().liquidity = NO_PRICE_LEVELS;
  deskPanels().bars = { failed: barsWords };
  await openView(page, "liquidity", "map");
  await expect(page.locator(".liqm-zones")).toContainText(NO_PRICE_LEVELS.reason);
  await expect(page.locator(".liqm-empty")).toHaveText(barsWords);
  deskPanels().liquidity = { failed: liqWords };
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".liqm-zones .sm")).toHaveText("-"); // no zones known: never "no zones for this session yet"
  await expect(page.locator(".liqm-empty")).toHaveText(liqWords + " · " + barsWords);
  await expect(page.locator("#liqmSrc .asof")).toHaveCount(0); // no zones drawn: nothing to mark
  expect(errs).toEqual([]);
});

test("Liquidity map: a list with no zone says the served words, words only the server knows too", async ({
  page,
}) => {
  // push.liquidity.liquidity_snapshot's answer when the published levels make no zone: an empty
  // list, no summary, and the words the list says for that (no_zones_text;
  // tests/test_liquidity_snapshot_spot_identity_v1.py). INDUCED: SPY's own answer with its zones
  // taken out and those words; then with words no page could hold
  const noZone = (words) =>
    Object.assign({}, LIQ, { zones: [], summary: null, location_said: null, no_zones_text: words });
  const errs = watchErrors(page);
  await intercept(page);
  deskPanels().liquidity = noZone("no zones for this session yet");
  await openView(page, "liquidity", "map");
  await expect(page.locator(".liqm-zones .sm")).toHaveText("no zones for this session yet");
  deskPanels().liquidity = noZone("Words ONLY the server knows");
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".liqm-zones .sm")).toHaveText("Words ONLY the server knows");
  expect(errs).toEqual([]);
});

test("Liquidity map: what the zones are made of is marked as served, live and after it stopped arriving", async ({
  page,
}) => {
  const errs = watchErrors(page);
  const sock = await intercept(page);
  await openView(page, "liquidity", "map");
  const asof = page.locator("#liqmSrc .asof");
  const zones = () =>
    page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().zones);
  // SPY's zones during its session, served with the time and age of the price-level snapshot they
  // are built from and the verdict of the option levels fused into them
  expect(LIQ.levels_state).toBe("LIVE");
  await expect(asof).toHaveText([snapshotMark(LIQ), verdictMark(LIQ)]);
  await expect(asof.nth(1)).toHaveClass("asof live");
  await expect.poll(zones).toBe(LIQ.zones.length);
  // INDUCED: the same zones ten minutes on with no chain, bar, trade or heartbeat since (the keys
  // that read differently, held to the route by tests/test_e2e_panels_two_day_v1.py). The last
  // values stand; the verdict reads STALE with the chain's time, its age and why, and the
  // snapshot is ten minutes older
  const later = Object.assign({}, LIQ, REAL.later.liquidity);
  expect([later.levels_state, later.levels_age_text]).toEqual(["STALE", "10m"]);
  expect(later.snapshot_age_text).not.toBe(LIQ.snapshot_age_text);
  deskPanels().liquidity = later;
  sock.changed("liquidity");
  await expect(asof).toHaveText([snapshotMark(later), verdictMark(later)]);
  await expect(asof.nth(1)).toHaveClass("asof stale");
  await expect(asof.nth(1)).toHaveAttribute("title", later.levels_stale_reason);
  expect(await zones()).toBe(LIQ.zones.length);
  // no price levels published: no zone is drawn, so nothing is marked
  deskPanels().liquidity = NO_PRICE_LEVELS;
  sock.changed("liquidity");
  await expect(asof).toHaveCount(0);
  await expect.poll(zones).toBe(0);
  expect(errs).toEqual([]);
});

test("Liquidity map: a ticker switch leaves nothing of the last ticker: its zones, lines, price and badges", async ({
  page,
}) => {
  const errs = watchErrors(page);
  // SPY's live price, the header's own row (one producer), pushed on each subscribe
  await intercept(page, [priceRow("SPY", SPOT)]);
  await routeWatchlist(page, ["SPY", "QQQ"]);
  // the program sends SPY's panels and holds QQQ's back
  const spyOnly = (panel) => (key, params, name) =>
    key === "SPY" ? panel(key, params, name) : undefined;
  const sent = deskPanels();
  sent.liquidity = spyOnly(() => LIQ);
  sent.levels = spyOnly(sent.levels);
  sent.bars = spyOnly(sent.bars);
  await openView(page, "liquidity", "map");
  // the zones, whether a reference level is drawn (a line, or named at the pane's edge), the live
  // price and whether bars are drawn
  const drawn = () =>
    page.evaluate(() => {
      const s = window.EdLiquidityMap.state();
      const edges = ["top", "bot"]
        .map((e) => document.querySelector("#liqmBody .tvc-edge-" + e).textContent)
        .join("");
      return s && [s.zones, s.levels.length > 0 || edges !== "", s.livePrice, s.bars > 0];
    });
  await expect.poll(drawn).toEqual([LIQ.zones.length, true, SPOT, true]);
  await expect(page.locator("#liqmSrc .asof")).toHaveCount(2);
  await page.evaluate(() => window.EdShell.setTicker("QQQ"));
  await expect.poll(drawn).toEqual([0, false, null, false]);
  await expect(page.locator("#liqmSrc .asof")).toHaveCount(0);
  await expect(page.locator(".liqm-zones .sm")).toHaveText("-");
  await expect(page.locator(".liqm-hold")).toHaveCount(0);
  expect(errs).toEqual([]);
});

test("Liquidity map: the lines drawn are the levels the program marks, whatever their family", async ({
  page,
}) => {
  // the levels panel marks the prior day's six and the extended hours' two as the chart's reference
  // lines (reference_line; tests/test_e2e_panels_two_day_v1.py). INDUCED: that answer with the
  // marks moved, the session's VWAP marked and none of the eight: the map draws the VWAP and
  // none of them, for the choice is the program's and the page holds no list of families
  const served = REAL.levels["1"]; // the map asks the 1-minute levels
  const lines = served.levels.filter((l) => l.reference_line);
  expect(lines.map((l) => l.id).sort()).toEqual([
    "OVERNIGHT_HIGH",
    "OVERNIGHT_LOW",
    "PDC",
    "PDH",
    "PDL",
    "PD_POC",
    "PD_VAH",
    "PD_VAL",
  ]);
  const errs = watchErrors(page);
  await intercept(page);
  deskPanels().levels = levelsAt(
    Object.assign({}, served, {
      levels: served.levels.map((l) => Object.assign({}, l, { reference_line: l.id === "VWAP" })),
    }),
  );
  await openView(page, "liquidity", "map");
  await expect(page.locator("#liqmBody .tvc-auto")).toBeVisible();
  // a level is a line inside the candles' price range, else named at the pane's edge
  const drawn = () =>
    page.evaluate(
      () =>
        (window.EdLiquidityMap.state() || { levels: [] }).levels.join(" ") +
        " " +
        document.querySelector("#liqmBody .tvc-edge-top").textContent +
        " " +
        document.querySelector("#liqmBody .tvc-edge-bot").textContent,
    );
  await expect.poll(drawn).toContain("VWAP");
  const text = await drawn();
  for (const l of lines) expect(text, l.id).not.toContain(l.short);
  expect(errs).toEqual([]);
});

test("the liquidity map fits its price scale to the candles; a far zone does not flatten them", async ({
  page,
}) => {
  // 2026-09-29 RTH: SPY's served zones at 750 and 800 joined the auto-fit, the scale ran 735-805
  // and the candles (765) were a flat line
  const errs = watchErrors(page);
  await intercept(page);
  // induced: SPY's real resistance zone at 775 moved to 800-801, far above the candles
  const far = Object.assign(
    {},
    LIQ.zones.find((z) => z.zone_side === "resistance" && z.zone_low === 775),
    { zone_low: 800, zone_high: 801 },
  );
  deskPanels().liquidity = Object.assign({}, LIQ, { zones: LIQ.zones.concat([far]) });
  await openView(page, "liquidity", "map");
  await expect
    .poll(() =>
      page.evaluate(() => window.EdLiquidityMap.state() && window.EdLiquidityMap.state().zones),
    )
    .toBe(LIQ.zones.length + 1);
  const st = await page.evaluate(() => window.EdLiquidityMap.state());
  expect(st.priceTop).toBeLessThan(far.zone_low); // the bars' range (near 757) sets the scale
  expect(errs).toEqual([]);
});

test("the Gamma chart and the liquidity map carry the Trade Desk toolbar; a timeframe click redraws at that timeframe", async ({
  page,
}) => {
  // operator 2026-09-29: "for all other charts you were supposed to apply the tv characteristics" --
  // only the Trade Desk had the timeframes, candles/line, drawing tools, reset, screenshot and full screen
  const errs = watchErrors(page);
  const sock = await intercept(page);
  for (const [ws, sub, view, host, api, bars] of [
    ["options", "gamma", "chart", "#chartBody", "EdGammaChart", "bars:chart"],
    ["liquidity", "map", "", "#liqmBody", "EdLiquidityMap", "bars:liq"],
  ]) {
    await openView(page, ws, sub, view);
    for (const sel of [
      '[data-act="style"]',
      '[data-tool="hline"]',
      '[data-act="reset"]',
      '[data-act="shot"]',
      '[data-act="full"]',
    ])
      await expect(page.locator(host + " .tvc-toolbar " + sel), ws + " " + sel).toBeVisible();
    const before = sock.subscribes.length;
    await page.locator(host + ' .tvc-toolbar [data-tf="15"]').click();
    await expect(page.locator(host + ' .tvc-toolbar [data-tf="15"]')).toHaveClass(/on/);
    await expect
      .poll(() => page.evaluate((a) => window[a].state() && window[a].state().tf, api), ws)
      .toBe("15");
    expect(
      sock.subscribes.slice(before).map((s) => s.panels[bars] && s.panels[bars].tf),
      ws,
    ).toContain("15");
  }
  expect(errs).toEqual([]);
});

test("Desk: an offline price keeps its last trade time on the map", async ({ page }) => {
  await intercept(page);
  await deskSocket(page, [
    priceRow("$SPX", 5800.12, {
      trade_time_ct: "14:00:01 CT",
      feed_live: false,
      feed_label: "OFFLINE",
      outage: "Schwab LEVELONE_EQUITIES feed down during RTH",
    }),
    priceRow("$VIX", 16.4, {
      trade_time_ct: "14:00:02 CT",
      chg_pct: 1.2,
      chg_pct_text: "+1.20%",
      feed_live: false,
      feed_label: "OFFLINE",
      outage: "Schwab LEVELONE_EQUITIES feed down during RTH",
    }),
    priceRow("SPY", 771.3, {
      trade_time_ct: "14:00:03 CT",
      feed_live: false,
      feed_label: "OFFLINE",
      outage: "Schwab LEVELONE_EQUITIES feed down during RTH",
      total_volume: 1000,
    }),
  ]);
  await openView(page, "trade-desk", "desk");
  await expect(page.locator("#tdmIdxSPX")).toContainText("OFFLINE · last trade 14:00:01 CT");
  await expect(page.locator("#tdmIdxSPX")).toHaveAttribute(
    "title",
    "Schwab LEVELONE_EQUITIES feed down during RTH",
  );
  await expect(page.locator("#tdmCardVol")).toContainText(
    "16.40 (+1.20%) · OFFLINE · last trade 14:00:02 CT",
  );
  await expect(page.locator("#tdmCardFlow")).toContainText("OFFLINE");
  await expect(page.locator("#tdmCardFlow .tdm-src")).toContainText("last trade 14:00:03 CT");
  await expect(page.locator("#tdmCardFlow .tdm-src")).toContainText(
    "Schwab LEVELONE_EQUITIES feed down during RTH",
  );
});

test("Desk: an index that stops stands marked on the Volatility card and the foot strip, with the served word, its trade time and age and why; the push silent, each stands marked with its time and no age", async ({
  page,
}) => {
  // the daemon's own rows for Schwab's $VIX, $SPX and $NDX messages of 2026-11-20
  // (fixtures/header_volatility.json, held by tests/test_data_path_header_volatility_v1.py): in
  // regular hours, once Schwab marked the indexes Closed, and with the daemon's Schwab socket
  // not open; SPY's row is the daemon's of 2026-10-23 (fixtures/price_rows_live.json)
  const MARKET = require(path.join(__dirname, "fixtures", "header_volatility.json"));
  const SPY_ROW = require(path.join(__dirname, "fixtures", "price_rows_live.json")).SPY;
  const errs = watchErrors(page);
  await holdClock(page); // the page's timers run when the test moves its time
  const sock = await intercept(page);
  await openView(page, "trade-desk", "desk");
  await expect.poll(() => sock.subscribes.length).toBeGreaterThan(0);
  const name = (row) => row.ticker.replace(/^\$/, "");
  // what follows an index's value: the mark's word when it is stopped, then its trade time,
  // with its age while the push delivers one
  const tail = (row, word, aged) =>
    (word ? " · " + word : "") +
    " · last trade " +
    row.trade_time_ct +
    (aged ? " · " + row.trade_age_text : "");
  // every index reads so, on the strip and (the volatility index) on the Volatility card
  const reads = async (rows, word, aged, why) => {
    for (const row of rows) {
      const cell = page.locator("#tdmIdx" + name(row));
      const words = tail(row, word, aged);
      await expect(cell).toHaveText(name(row) + row.spot_disp + row.chg_pct_text + words);
      await expect(cell).toHaveAttribute("title", why(row));
      await expect(cell.locator(".tdm-stopped")).toHaveText(word ? [words] : []);
    }
    const vix = rows.filter((r) => r.ticker === MARKET.live.ticker)[0];
    const onCard = page.locator("#tdmVolIdx");
    await expect(onCard).toHaveText(
      name(vix) + " " + vix.spot_disp + " (" + vix.chg_pct_text + ")" + tail(vix, word, aged),
    );
    await expect(onCard).toHaveAttribute("title", why(vix));
    await expect(onCard.locator("b")).toHaveClass(word ? "tdm-stopped" : "");
  };
  const lastTrade = (row) => "last trade " + row.trade_time_ct;
  // no row has arrived: each index reads "-", on the strip and on the card, never a sentence
  // in the value's place; that its row is waited for is the title
  for (const row of MARKET.market_live) {
    const cell = page.locator("#tdmIdx" + name(row));
    await expect(cell).toHaveText(name(row) + "-");
    await expect(cell).toHaveAttribute("title", "waiting for the " + name(row) + " stream");
  }
  await expect(page.locator("#tdmVolIdx")).toHaveText(name(MARKET.live) + " -");
  await expect(page.locator("#tdmVolIdx")).toHaveAttribute(
    "title",
    "waiting for the " + name(MARKET.live) + " stream",
  );
  // live: each value with its trade time, unmarked
  sock.quotes([SPY_ROW, ...MARKET.market_live]);
  await reads(MARKET.market_live, null, false, lastTrade);
  // Schwab marked the indexes Closed, and no row of the selected ticker follows: each stands
  // marked NOT LIVE, the served word, with its trade time and age, and why is the title
  sock.quotes(MARKET.market_closed);
  expect(MARKET.market_closed.map((r) => r.feed_label)).toEqual([
    "NOT LIVE",
    "NOT LIVE",
    "NOT LIVE",
  ]);
  await reads(MARKET.market_closed, "NOT LIVE", true, (row) => row.outage);
  // the daemon's Schwab socket is not open: OFFLINE, as served, and why
  sock.quotes(MARKET.market_down);
  expect(MARKET.market_down.map((r) => r.feed_label)).toEqual(["OFFLINE", "OFFLINE", "OFFLINE"]);
  await reads(MARKET.market_down, "OFFLINE", true, (row) => row.outage);
  // live again
  sock.quotes([SPY_ROW, ...MARKET.market_live]);
  await reads(MARKET.market_live, null, false, lastTrade);
  // INDUCED: the push stops (the socket sends nothing more). The header reads OFFLINE, and each
  // index stands marked so, its trade time with no age (the last age served is not the age now)
  await page.clock.runFor(4500);
  await expect(page.locator("#hFeed")).toHaveText("OFFLINE");
  await reads(MARKET.market_live, "OFFLINE", false, () => "live push down");
  // an index's own row ends its mark, the selected ticker's not yet back: the closed index reads
  // as Schwab's row says, the others still as the push left them
  sock.quotes([MARKET.closed]);
  const others = MARKET.market_live.filter((r) => r.ticker !== MARKET.closed.ticker);
  await expect(page.locator("#tdmVolIdx")).toHaveText(
    name(MARKET.closed) +
      " " +
      MARKET.closed.spot_disp +
      " (" +
      MARKET.closed.chg_pct_text +
      ")" +
      tail(MARKET.closed, "NOT LIVE", true),
  );
  for (const row of others)
    await expect(page.locator("#tdmIdx" + name(row) + " .tdm-stopped")).toHaveText(
      tail(row, "OFFLINE", false),
    );
  // the push is back with every row: live, unmarked
  sock.quotes([SPY_ROW, ...MARKET.market_live]);
  await reads(MARKET.market_live, null, false, lastTrade);
  expect(errs).toEqual([]);
});

test("Desk: a price push that stops reads OFFLINE on the map, not its last row's LIVE", async ({
  page,
}) => {
  // the daemon's own rows for SPY's and $SPX's real messages in regular hours (tests/test_order_flow_book_payload_v1.py)
  const ROWS = require(path.join(__dirname, "fixtures", "price_rows_live.json"));
  const BOOK_TIME = "Fri 09/25 06:59 PM CT";
  await intercept(page);
  // SPY's row, then nothing (the push down, said by the page's own silence watch); the test then
  // resumes the push with $SPX's row, and later SPY's, each at the step it means (never a timer)
  const sock = await deskSocket(page, [ROWS.SPY]);
  await openView(page, "trade-desk", "desk");
  await expect(page.locator("#tdmTrust")).toContainText("PRICE LIVE");
  await expect(page.locator("#hFeed")).toHaveText("OFFLINE", { timeout: 6000 }); // the socket sends nothing more
  await expect(page.locator("#tdmTrust")).toContainText("PRICE OFFLINE");
  await expect(page.locator("#tdmTrust")).not.toContainText("PRICE LIVE");
  await expect(page.locator("#tdmCardFlow")).toContainText("OFFLINE");
  // the push resumes with another symbol's row: SPY's last row is not SPY's state now, here or in
  // the header, even after the map repaints (a new book, sent on the socket, redraws it)
  sock.quotes([ROWS["$SPX"]]);
  await expect(page.locator("#tdmIdxSPX")).toContainText(
    "last trade " + ROWS["$SPX"].trade_time_ct,
    { timeout: 10000 },
  );
  deskPanels().book = Object.assign({}, MICRO, { book_time_ct: BOOK_TIME });
  sock.changed("book");
  await expect(page.locator("#tdmTrust")).toContainText("BOOK " + BOOK_TIME); // the new book has landed and the map has repainted
  // read once: SPY's own row is not sent yet, so the outage stands
  expect(await page.locator("#hFeed").textContent()).toBe("OFFLINE");
  const trust = await page.locator("#tdmTrust").textContent();
  expect(trust).toContain("PRICE OFFLINE");
  expect(trust).not.toContain("PRICE LIVE");
  // SPY's own row ends the outage: the header and the map read LIVE again
  sock.quotes([ROWS.SPY]);
  await expect(page.locator("#hFeed")).toHaveText("LIVE", { timeout: 6000 });
  await expect(page.locator("#tdmTrust")).toContainText("PRICE LIVE");
  await expect(page.locator("#tdmCardFlow")).not.toContainText("OFFLINE");
});

test("Desk: the first ticker chosen on it reads WAITING, its panels not sent yet, and no error", async ({
  page,
}) => {
  // INDUCED: a browser that never chose a ticker, on the Desk, and a program that says nothing.
  // The shell says the push is WAITING before the Desk holds the ticker; a panel nothing was
  // asked for used to read as one the program could not produce, its words read off nothing:
  // the page threw.
  const errs = watchErrors(page);
  await page.routeWebSocket(/\/ws$/, () => {});
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem("ed_ws", "trade-desk");
    localStorage.setItem("ed_sub", "desk");
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#hFeed")).toHaveText("NO SYMBOL");
  await page.evaluate(() => window.EdShell.setTicker("SPY"));
  const trust = page.locator("#tdmTrust");
  await expect(trust).toContainText("PRICE WAITING");
  for (const panel of ["BOOK", "LEVELS", "GAMMA"]) await expect(trust).toContainText(panel + " …");
  await expect(trust).not.toContainText("FAILED");
  await expect(page.locator("#tdmCardVol")).not.toContainText("UNAVAILABLE");
  expect(errs).toEqual([]);
});

test("Desk: a book whose market is closed reads BOOK NOT LIVE and keeps Schwab's book time (the route's own answer)", async ({
  page,
}) => {
  // SPY's real book and quotes at 22:00 ET as the route serves them (tests/test_order_flow_book_payload_v1.py)
  const CLOSED_BOOK = require(
    path.join(__dirname, "fixtures", "order_flow_book_closed_payload.json"),
  );
  const errs = watchErrors(page);
  await intercept(page);
  deskPanels().book = CLOSED_BOOK;
  // the fixture holds NYSE_BOOK only: the card shows that book
  await page.addInitScript(() => {
    localStorage.setItem("ed_ticker", "SPY");
    localStorage.setItem("ed_ws", "trade-desk");
    localStorage.setItem("ed_sub", "desk");
    localStorage.setItem("ed_book_venue", "NYSE_BOOK");
    localStorage.setItem("ed.desk.liqvenue", "BOOK");
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#tdmCardLiq")).toContainText("BOOK NOT LIVE");
  await expect(page.locator("#tdmCardLiq .tdm-src")).toContainText(
    "book " +
      CLOSED_BOOK.book_time_ct +
      " · " +
      CLOSED_BOOK.readout.venues.NYSE_BOOK.book_age_text +
      " old · not live",
  );
  // Schwab's top-5 totals as served (800 and 2,160 shares), the last numbers kept
  await expect(page.locator("#tdmCardLiq .liq-body")).toContainText("2,160");
  await expect(page.locator("#tdmCardLiq .liq-bar-h").first()).toHaveText("Bids800");
  // the stock's own book, named: its shares and the exchange's book, never an option's
  await expect(page.locator("#tdmLiqTitle")).toHaveText("SPY shares");
  await expect(page.locator('#tdmCardLiq [data-venue="NYSE_BOOK"]')).toHaveClass(/\bon\b/);
  await expect(page.locator("#tdmTrust")).toContainText(
    "BOOK " + CLOSED_BOOK.book_time_ct + " · NOT LIVE",
  );
  await expect(page.locator("#tdmTrust")).not.toContainText("STALE");
  // with one book held, the composite is that book: its numbers, named on the source line
  const comp = CLOSED_BOOK.readout.venues.COMPOSITE;
  await page.locator('#tdmCardLiq [data-liqvenue="COMPOSITE"]').click();
  await expect(page.locator("#tdmCardLiq .liq-pct")).toHaveText(comp.views["5"].pct_text);
  await expect(page.locator("#tdmLiqTitle")).toHaveText("SPY shares");
  await expect(page.locator('#tdmCardLiq [data-liqvenue="COMPOSITE"]')).toHaveClass(/\bon\b/);
  await expect(page.locator("#tdmCardLiq .liq-body")).toContainText("2,160");
  await expect(page.locator("#tdmCardLiq .tdm-src")).toContainText(
    "Schwab NYSE_BOOK · aggregate, newest quote of each exchange",
  );
  expect(errs).toEqual([]);
});

test("Desk: the book age keeps Schwab's book time", async ({ page }) => {
  const errs = watchErrors(page);
  const BOOK_TIME = "Fri 09/25 06:59 PM CT";
  await intercept(page);
  deskPanels().book = Object.assign({}, MICRO, { book_time_ct: BOOK_TIME });
  await openView(page, "trade-desk", "desk");
  // the card's footnote keeps the served composite's book time; its side word and totals are served
  await expect(page.locator("#tdmCardLiq")).toContainText("Book " + COMP.book_time_ct);
  await expect(page.locator("#tdmCardLiq .liq-word")).toHaveText(COMP.views["5"].side_word);
  await expect(page.locator("#tdmCardLiq .liq-body")).toContainText(COMP.views["5"].ask_text);
  await expect(page.locator("#tdmTrust")).toContainText(
    "BOOK " + BOOK_TIME + " · " + MICRO.book_age_text,
  );
  expect(errs).toEqual([]);
});

test("Desk: the chain age keeps the chain's time", async ({ page }) => {
  const errs = watchErrors(page);
  const CHAIN_TIME = "Fri 09/25 06:59 PM CT";
  await intercept(page);
  deskPanels().terrain = Object.assign({}, TERRAIN, {
    levels_age_text: "4s",
    levels_state: "LIVE",
    levels_time_ct: CHAIN_TIME,
  });
  await openView(page, "trade-desk", "desk");
  await expect(page.locator("#tdmCardOpt .tdm-src")).toContainText(
    "Schwab option chain · " + CHAIN_TIME + " · LIVE · 4s",
  );
  // SPY's real Gamma Call and Gamma Put, each on its row in its colour
  const card = (name) => page.locator("#tdmCardOpt .tdm-r", { hasText: name });
  await expect(card("Gamma Call")).toHaveText("Gamma Call 775.00");
  await expect(card("Gamma Call").locator("b.up")).toHaveText("775.00");
  await expect(card("Gamma Put")).toHaveText("Gamma Put 760.00");
  await expect(card("Gamma Put").locator("b.dn")).toHaveText("760.00");
  // the served regime word (SPY's: NEGATIVE_GAMMA), toned from the one regime table
  await expect(page.locator("#tdmCardOpt .tdm-state")).toHaveText("Negative gamma");
  await expect(page.locator("#tdmCardOpt .tdm-state")).toHaveClass("tdm-state dn");
  await expect(page.locator("#tdmCardVol .tdm-src")).toContainText(CHAIN_TIME + " · LIVE · 4s");
  await expect(page.locator("#tdmTrust")).toContainText("GAMMA " + CHAIN_TIME + " · LIVE · 4s");
  expect(errs).toEqual([]);
});

test("Desk: the levels pill keeps the snapshot time", async ({ page }) => {
  const SNAP_TIME = "Fri 09/25 06:59 PM CT";
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  await intercept(page);
  deskPanels().levels = levelsAt(
    Object.assign({}, LEVELS, {
      snapshot_time_ct: SNAP_TIME,
      snapshot_age_text: "2d",
    }),
  );
  await openView(page, "trade-desk", "desk");
  await expect(page.locator("#tdmTrust")).toContainText("LEVELS " + SNAP_TIME + " · 2d"); // the served age, not the page's clock
  expect(errs).toEqual([]);
});

test("Right Now: the spot keeps its last trade time", async ({ page }) => {
  // the header's own row (one producer): its price and its trade time and age, as the header
  await intercept(page, [priceRow("SPY", SPOT, { trade_time_ct: "Fri 10/02 10:00 AM CT" })]);
  deskPanels().levels = levelsAt(LEVELS);
  await openView(page, "trade-desk", "right-now");
  await expect(page.locator("#tdBody .fl-meta")).toHaveText(
    "spot " + SPOT.toFixed(2) + " · last trade Fri 10/02 10:00 AM CT · 1s",
  );
  await expect(page.locator("#hPx")).toHaveText(SPOT.toFixed(2));
});

test.describe("Trade Desk renders served values", () => {
  test("Desk after the close: levels drawn from the served order; dark by default", async ({
    page,
  }) => {
    // 2026-09-28 21:40 ET: after the close the levels served an empty by_distance and the chart drew
    // no key level; the spot is now Schwab's last trade at any hour and orders them (by_distance)
    const errs = watchErrors(page);
    // every panel sent in its real shape, and the price live (the header's own row); after the
    // close, nothing crossed
    await intercept(page, [priceRow("SPY", SPOT)]);
    // INDUCED: the empty window's sentence worded otherwise, so a sentence of the page's own shows
    const NOTHING = "SERVED: nothing crossed in this window";
    deskPanels().desk = tfAt(
      Object.assign({}, EVENTS, {
        items: [],
        cross_counts: { up: 0, down: 0 },
        none_said: NOTHING,
      }),
    );
    await openView(page, "trade-desk", "desk");
    expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe(
      "dark",
    );
    // the nearest six of SPY's levels (756.59 to 757.88) are drawn under three labels (a label
    // closer than its height to a nearer one is counted on that one); the largest put gamma strike
    // (760, the price is through it) is the nearest level above the bars' price range, pinned at
    // the edge
    await expect
      .poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown))
      .toBe(3);
    await expect(page.locator("#tdmChart .tvc-edge-top")).toContainText(
      "Gamma Put · BREACHED — spot below 760.00",
    );
    // the profile is drawn after the close too (the session's served profile): its served note
    await expect(page.locator("#tdmProfNote")).toHaveText(LEVELS.profile_note);
    // the empty queue says the desk panel's own sentence for it
    await expect(page.locator("#tdmQueue .tdm-empty")).toHaveText(NOTHING);
    expect(errs).toEqual([]);
  });

  // AGENTS.md rule 5: an entry whose time was not sent reads "-", never words of the page's own.
  // INDUCED: the first entry served with no time (push.desk serves None for one with none)
  test("Desk: a queue entry with no time reads -", async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page, [priceRow("SPY", SPOT)]);
    deskPanels().desk = tfAt(
      Object.assign({}, EVENTS, {
        items: [Object.assign({}, EVENTS.items[0], { time_ct: null })],
      }),
    );
    await openView(page, "trade-desk", "desk");
    await expect(page.locator("#tdmQueue .tdm-q .tdm-q-m")).toHaveText(
      EVENTS.items[0].src + " · -",
    );
    expect(errs).toEqual([]);
  });

  test("Desk: a failed request is named on its cards, never told as an empty market", async ({
    page,
  }) => {
    // the terrain panel not produced (the program's words on the socket) and the flow bars
    // failing: the options, volatility and flow cards say so; before, they said no expiry
    // carries open interest and no bars for the symbol
    const errs = watchErrors(page);
    const words = "the program could not produce this panel: RuntimeError: chain lock timed out";
    await intercept(page); // every panel sent in its real shape, then the two that fail
    deskPanels().terrain = { failed: words };
    deskPanels().bars = (key, params, name) =>
      name === "bars:flow" ? { failed: words } : REAL.bars[params.tf];
    await openView(page, "trade-desk", "desk");
    await expect(page.locator("#tdmCardOpt .tdm-plot-none")).toHaveText(words);
    await expect(page.locator("#tdmCardVol .tdm-plot-none")).toHaveText(words);
    // the GAMMA pill says the word the Options card says in this state, and why on hover
    const gamma = page.locator("#tdmTrust .tdm-pill", { hasText: "GAMMA" });
    await expect(gamma).toHaveText(
      "GAMMA " + (await page.evaluate(() => window.EdShell.pageWords.unavailable)),
    );
    await expect(gamma).toHaveAttribute("title", words);
    await expect(page.locator("#tdmCardOpt .tdm-state")).toHaveText(
      await page.evaluate(() => window.EdShell.pageWords.unavailable),
    );
    await expect(page.locator("#tdmCardFlow .tdm-plot-none")).toHaveText(
      "the program could not produce the bars",
    );
    expect(errs).toEqual([]);
  });

  // AGENTS.md rule 4: a card whose series is empty says the program's sentence for it, never one
  // of the page's own. INDUCED: each served answer holds nothing, its sentence worded otherwise
  test("Desk: an empty series is said in the program's sentence", async ({ page }) => {
    const errs = watchErrors(page);
    await intercept(page);
    deskPanels().terrain = Object.assign({}, TERRAIN, {
      pcr_by_expiry: {},
      atm_iv_pct_by_expiry: {},
      pcr_none_said: "SERVED: no expiry carries open interest",
      atm_iv_none_said: "SERVED: no expiry has both ATM legs priced",
    });
    deskPanels().bars = (key, params, name) =>
      name === "bars:flow"
        ? Object.assign({}, REAL.bars_flow, { bars: [], none_said: "SERVED: no 1-minute bars" })
        : REAL.bars[params.tf];
    await openView(page, "trade-desk", "desk");
    await expect(page.locator("#tdmCardOpt .tdm-plot-none")).toHaveText(
      "SERVED: no expiry carries open interest",
    );
    await expect(page.locator("#tdmCardVol .tdm-plot-none")).toHaveText(
      "SERVED: no expiry has both ATM legs priced",
    );
    await expect(page.locator("#tdmCardFlow .tdm-plot-none")).toHaveText(
      "SERVED: no 1-minute bars",
    );
    expect(errs).toEqual([]);
  });

  test("Desk: the levels are drawn when they arrive, not held for the event queue", async ({
    page,
  }) => {
    // 2026-09-29 14:52 CT, deployed: QQQ's levels answered in 28 ms and were drawn after 1.34 s,
    // when the event queue answered
    const errs = watchErrors(page);
    await intercept(page); // every panel sent in its real shape, but the event queue
    deskPanels().desk = () => undefined; // the event queue has not been sent
    await openView(page, "trade-desk", "desk");
    await expect
      .poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown))
      .toBeGreaterThan(0);
    await expect(page.locator("#tdmQueue")).toContainText("Loading");
    expect(errs).toEqual([]);
  });

  test("Desk: the prior value area band, its words, the VWAP's and the POC label are drawn as served", async ({
    page,
  }) => {
    // register P-16: the map picked PD_VAL, PD_VAH, VWAP and TODAY_POC out of the levels by id
    // and wrote "VA … – …" and "POC est …" itself; it draws the levels panel's fields
    const errs = watchErrors(page);
    await intercept(page); // every panel sent in its real shape
    await openView(page, "trade-desk", "desk");
    const pva = LEVELS.prior_value_area;
    const chart = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chart()).valueArea).toEqual([pva.low, pva.high]);
    expect((await chart()).volumeProfileMark).toBe(LEVELS.volume_profile.poc_label);
    await expect(page.locator('#tdmFamilies [data-famv="prior_day"]')).toHaveText(pva.text);
    await expect(page.locator('#tdmFamilies [data-famv="vwap"]')).toHaveText(LEVELS.vwap_text);
    expect(errs).toEqual([]);
  });

  test("Desk: no one-day move or its ±1σ band is switched, drawn or written", async ({ page }) => {
    // operator 2026-11-20: the standard deviation bands of the implied one-day move are removed
    // from everywhere; SPY's real panels, as served
    const errs = watchErrors(page);
    await intercept(page);
    await openView(page, "trade-desk", "desk");
    await expect
      .poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown))
      .toBeGreaterThan(0);
    await expect(page.locator('#tdmFamilies [data-fam="vwap"]')).toHaveCount(1);
    await expect(page.locator('#tdmFamilies [data-fam="expected_move"]')).toHaveCount(0);
    await expect(page.locator("#tdmFamilies")).not.toContainText("σ move");
    const titles = await page.evaluate(() => window.EdTradeDeskMap.state().chart.levels);
    expect(titles.filter((t) => /σ move/.test(t))).toEqual([]);
    await expect(page.locator("#tdmCardVol")).not.toContainText(/1-day move|1σ|Move from/);
    expect(errs).toEqual([]);
  });

  test("Desk: no prior value area band when the prior value area is absent", async ({ page }) => {
    // INDUCED: SPY's levels with the prior session's value area absent, as the program serves
    // $SPX's (Schwab's index bars carry no volume; tests/test_trade_desk_served_v1.py)
    const errs = watchErrors(page);
    await intercept(page);
    const reason = "no RTH volume in the prior session 2026-11-11's bars for its volume profile";
    deskPanels().levels = levelsAt((key, params) =>
      Object.assign({}, REAL.levels[params.tf], {
        prior_value_area: null,
        levels: REAL.levels[params.tf].levels.filter((r) => !/^PD_(VAL|VAH|POC)$/.test(r.id)),
        families_absent: REAL.levels[params.tf].families_absent.concat([
          { family: "prior_value_area", reason: reason },
        ]),
      }),
    );
    await openView(page, "trade-desk", "desk");
    await expect
      .poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown))
      .toBeGreaterThan(0);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.valueArea)).toEqual([
      null,
      null,
    ]);
    // not received: "-" beside its switch (AGENTS.md rule 5), never a blank
    await expect(page.locator('#tdmFamilies [data-famv="prior_day"]')).toHaveText("-");
    expect(errs).toEqual([]);
  });

  test("Desk: levels sent for a timeframe the chart has left are not drawn", async ({ page }) => {
    // the program's 5m levels, sent before it read the switch to 15m, arrive after it
    const errs = watchErrors(page);
    const sock = await intercept(page);
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "desk");
      localStorage.setItem("ed.desk.tf", "5");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect
      .poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.levelsShown))
      .toBeGreaterThan(0);
    await page.locator('#tdmToolbar [data-tf="15"]').click();
    await expect.poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.tf)).toBe("15");
    const far = FAR_GRC;
    sock.frame(
      "levels:map",
      "SPY",
      Object.assign({}, LEVELS, {
        tf: "5",
        levels: LEVELS.levels.concat([far]),
        by_distance: LEVELS.by_distance.concat(["grc"]),
      }),
    ); // 5m's, late ...
    sock.frame(
      "terrain:map",
      "SPY",
      Object.assign(
        {},
        TERRAIN, // ... and a panel behind it
        { call_wall: 776, call_wall_text: "776.00" },
      ),
    );
    await expect(page.locator("#tdmCardOpt")).toContainText("776.00");
    await expect(page.locator("#tdmChart .tvc-edge-top")).not.toContainText("GRC");
    expect(errs).toEqual([]);
  });

  test("Desk: the served queue, counts, book side, tape side and flip relation", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    await intercept(page);
    // induced: SPY's real levels with the second expiry's put/call ratio not known (SPY's 34
    // expiries each have one), so the card's line has a gap to draw
    const second = Object.keys(TERRAIN.pcr_by_expiry)[1];
    deskPanels().terrain = Object.assign({}, TERRAIN, {
      pcr_by_expiry: Object.assign({}, TERRAIN.pcr_by_expiry, { [second]: null }),
    });
    await openView(page, "trade-desk", "desk");
    // the queue as served: the day's recorded crosses in the window, the put wall
    await expect(page.locator("#tdmQueue .tdm-q")).toHaveCount(EVENTS.items.length);
    await expect(page.locator("#tdmQueueCount")).toHaveText(String(EVENTS.items.length));
    // each entry's time is the one the server labels it with (time_et.ct_label), drawn as sent;
    // none sent: "-" (AGENTS.md rule 5)
    for (const [i, it] of EVENTS.items.entries())
      await expect(page.locator("#tdmQueue .tdm-q .tdm-q-m").nth(i)).toContainText(
        it.time_ct == null ? "-" : it.time_ct,
      );
    await expect(page.locator("#tdmCardLiq .liq-word")).toHaveText(COMP.views["5"].side_word);
    // Schwab sends no trade side: the Order Flow card claims none (operator 2026-09-29)
    await expect(page.locator("#tdmCardFlow")).not.toContainText(
      /NET BUYING|NET SELLING|tick rule|PROXY|delta/i,
    );
    await expect(page.locator("#tdmCardFlow")).toContainText(
      EVENTS.cross_counts.up + " up · " + EVENTS.cross_counts.down + " down",
    );
    // the window's words are the server's (a page copy of the lookback table: register P-15)
    await expect(page.locator("#tdmCardFlow")).toContainText(
      "Crosses (" + EVENTS.window_label + ")",
    );
    await expect(page.locator("#tdmLookback")).toHaveText(EVENTS.window_label);
    await expect(page.locator("#tdmAgree")).toContainText("Below Gamma Flip"); // 757.08 against the flip at 761.22
    // the served session volume profile, every bin drawn at the chart's left edge, with its basis
    await expect
      .poll(() => page.evaluate(() => window.EdTradeDeskMap.state().chart.volumeProfileBins))
      .toBe(LEVELS.volume_profile.bins.length);
    await expect(page.locator("#tdmProfNote")).toHaveText(LEVELS.profile_note);
    // each card draws its served series (2026-09-28): the Liquidity card's 2m and 5m lean lines,
    // volume bars, and lines for put/call OI and ATM IV by expiry (a null expiry breaks the line)
    await expect(page.locator("#tdmCardLiq .liq-lean svg path")).toHaveCount(2);
    await expect(page.locator("#tdmCardFlow .tdm-plot svg rect")).toHaveCount(
      REAL.bars_flow.bars.length,
    );
    await expect(page.locator("#tdmCardOpt .tdm-plot svg path")).toHaveCount(2);
    await expect(page.locator("#tdmCardVol .tdm-plot svg path")).toHaveCount(1);
    await expect(page.locator("#tdmCardVol figcaption")).toHaveText(
      "ATM implied vol by expiry, nearest first",
    );
    await expect(page.locator("#tdmAgree")).toContainText(COMP.views["5"].tilt_text); // served
    expect(errs).toEqual([]);
  });

  test("Desk: the markers the chart has no bar for are counted and worded as served", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    await intercept(page);
    // the program's answers for the 15-minute desk whose chart spans the newest hour of minutes:
    // the queue's older markers are before its first bar
    const DESK_HOUR = REAL.desk_newest_hour;
    deskPanels().desk = (key, params) => (params.tf === "15" ? DESK_HOUR : REAL.desk[params.tf]);
    deskPanels().bars = (key, params, name) =>
      name === "bars:flow"
        ? REAL.bars_flow
        : params.tf === "15"
          ? REAL.bars_newest_hour
          : REAL.bars[params.tf];
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "desk");
      localStorage.setItem("ed.desk.tf", "15");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const marked = DESK_HOUR.items.filter((it) => it.marker);
    expect(DESK_HOUR.markers_off_chart).toBeGreaterThan(0);
    await expect(page.locator("#tdmQueueOff")).toHaveText(DESK_HOUR.markers_off_chart_text);
    // the chart draws the rest, and the served count is the ones it leaves out
    await expect
      .poll(
        async () => (await page.evaluate(() => window.EdTradeDeskMap.state().chart.markers)).length,
      )
      .toBe(marked.length - DESK_HOUR.markers_off_chart);
    // the full chart has a bar for every marker: no line
    await page.locator('#tdmToolbar [data-tf="5"]').click();
    await expect(page.locator("#tdmQueue .tdm-q")).toHaveCount(REAL.desk["5"].items.length);
    await expect(page.locator("#tdmQueueOff")).toBeHidden();
    expect(errs).toEqual([]);
  });

  test("Desk: each chart marker is its queue entry, and selecting the entry selects that marker", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    await intercept(page);
    // at 15 minutes the queue's window is the last 4 hours: SPY crossed three levels in it (max
    // pain, the flip, the two delta walls at 750), and the chart marks the newest cross at each
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "desk");
      localStorage.setItem("ed.desk.tf", "15");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const marked = REAL.desk["15"].items.filter((it) => it.marker).map((it) => it.key);
    expect(marked).toHaveLength(3);
    await expect
      .poll(async () =>
        (await page.evaluate(() => window.EdTradeDeskMap.state().chart.markers)).slice().sort(),
      )
      .toEqual(marked.slice().sort());
    const key = marked[0];
    await page.locator('#tdmQueue [data-q="' + key + '"]').click();
    await expect(page.locator('#tdmQueue [data-q="' + key + '"]')).toHaveClass(/sel/);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.markerSelected)).toBe(key);
    // and the other way: a click on a callout's number on the chart selects its queue entry
    const other = marked[1];
    const all = await page.evaluate(() => window.EdTradeDeskMap.state().chart.callouts);
    const c = all.filter((x) => x.id === other)[0];
    expect(c).toBeTruthy();
    // no callout's number covers another's, crosses of one bar included
    for (const a of all)
      for (const b of all)
        if (a !== b) expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(22);
    // the chart may still be settling its opening view: read the number where it is drawn now, click it
    const box = await page.locator("#tdmChart .tvc-plot").boundingBox();
    await expect
      .poll(async () => {
        const now = (
          await page.evaluate(() => window.EdTradeDeskMap.state().chart.callouts)
        ).filter((x) => x.id === other)[0];
        await page.mouse.click(box.x + now.x, box.y + now.y);
        return page.evaluate(() => window.EdTradeDeskMap.state().chart.markerSelected);
      })
      .toBe(other);
    await expect(page.locator('#tdmQueue [data-q="' + other + '"]')).toHaveClass(/sel/);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.markerSelected)).toBe(
      other,
    );
    expect(errs).toEqual([]);
  });

  test("Desk: the footer names the bars source only while this ticker has bars", async ({
    page,
  }) => {
    await routeWatchlist(page, ["SPY", "MU"]);
    // INDUCED: MU's panel with no bar says it in words other than the producer's (push.bars
    // none_said), so a sentence of the page's own shows
    const NO_BARS = "SERVED: no bars for this symbol";
    await mockPriceSocket(page, [], undefined, {
      bars: (key, params) =>
        Object.assign({}, key === "SPY" ? BARS : { bars: [], none_said: NO_BARS }, {
          tf: params.tf,
        }),
    });
    await openView(page, "trade-desk", "desk");
    const bars = page.locator("#tdmFoot span", { hasText: "Bars:" }).locator("b");
    await expect(bars).toHaveText("streamed 1m bars");
    await page.evaluate(() => window.EdShell.setTicker("MU"));
    await expect(page.locator("#tdmChartEmpty")).toHaveText(NO_BARS);
    await expect(bars).toHaveText("-");
  });

  test("Desk: selecting a ticker asks for its book on the socket", async ({ page }) => {
    const sock = await intercept(page);
    // the ticker of each subscribe that asks for the desk's book
    const opened = () =>
      sock.subscribes.filter((s) => s.panels["book:deskmap"]).map((s) => s.ticker);
    await openView(page, "trade-desk", "desk");
    await expect.poll(opened).toContain("SPY");
    await page.evaluate(() => window.EdShell.setTicker("MU"));
    await expect.poll(opened).toContain("MU");
  });

  test("Price chart:the wheel over the price axis rescales price (as TradingView); over the plot it does not", async ({
    page,
  }) => {
    // operator 2026-09-29: "in tv all you do is scroll [on the price legend] and it will expand the
    // chart vertically; the way you have it you have to click and drag"
    await intercept(page);
    await openView(page, "trade-desk", "desk");
    await expect
      .poll(() => page.evaluate(() => window.EdTradeDeskMap.state().bars))
      .toBeGreaterThan(0);
    const box = await page.locator("#tdmChart").boundingBox();
    const span = async () =>
      page.evaluate(() => {
        const c = window.EdTradeDeskMap.state().chart;
        return c.priceTop - c.priceBottom;
      });
    const before = await span();
    await page.mouse.move(box.x + box.width - 20, box.y + box.height / 2); // on the price axis
    await page.mouse.wheel(0, 400);
    await expect.poll(span).toBeGreaterThan(before * 1.5);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().chart.autoScale)).toBe(false);
    const widened = await span();
    const range = () =>
      page.evaluate(() => {
        const c = window.EdTradeDeskMap.state().chart;
        return [c.from, c.to];
      });
    const times = await range();
    await page.mouse.move(box.x + box.width / 3, box.y + box.height / 2); // on the plot: time, not price
    await page.mouse.wheel(0, 400);
    await expect.poll(range).not.toEqual(times); // the wheel has been taken: time moved
    expect(await span()).toBeCloseTo(widened, 6);
  });

  test("Desk: the live price line keeps its last trade time", async ({ page }) => {
    await intercept(page);
    await deskSocket(page, []);
    await openView(page, "trade-desk", "desk");
    await expect
      .poll(() => page.evaluate(() => window.EdTradeDeskMap.state().bars))
      .toBeGreaterThan(0);
    await page.evaluate(
      (spot) =>
        window.dispatchEvent(
          new CustomEvent("ed:quote_tick", {
            detail: {
              ticker: "SPY",
              spot: spot,
              feed_live: false,
              feed_label: "OFFLINE",
              trade_age_text: "1s",
              trade_time_ct: "14:00:01 CT",
              trade_said: "last trade 14:00:01 CT",
              outage: "Schwab LEVELONE_EQUITIES feed down during RTH",
            },
          }),
        ),
      SPOT,
    );
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            window.EdTradeDeskMap.state().chart && window.EdTradeDeskMap.state().chart.liveTitle,
        ),
      )
      .toBe("LAST · last trade 14:00:01 CT");
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            window.EdTradeDeskMap.state().chart && window.EdTradeDeskMap.state().chart.livePrice,
        ),
      )
      .toBe(SPOT);
  });

  test("Price chart:the served last completed bar; a price tick moves the live LAST line and asks for no bars", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    await intercept(page);
    const requests = watchRequests(page);
    const sock = await deskSocket(page, []); // the daemon answers what SPY is (its served key)
    const barReads = sock.subscribes; // each ask the page makes of the program, the bars among them
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "desk");
    });
    await holdClock(page); // the page's timers run when the test moves its time
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect.poll(() => page.evaluate(() => window.EdShell.getState().key)).toBe("SPY");
    const legend = page.locator("#tdmChart .tvc-legend");
    await expect(legend).toContainText("Last completed bar " + BARS.last_bar.label);
    const before = barReads.length;
    await page.evaluate((spot) => {
      for (let i = 0; i < 3; i++)
        window.dispatchEvent(
          new CustomEvent("ed:quote_tick", {
            detail: {
              ticker: "SPY",
              spot: spot + i / 100,
              spot_disp: (spot + i / 100).toFixed(2),
              feed_live: true,
              trade_age_text: "1s",
            },
          }),
        );
    }, SPOT);
    const chartState = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
    await expect.poll(async () => (await chartState()).livePrice).toBeCloseTo(SPOT + 0.02, 6);
    expect((await chartState()).liveTitle).toBe("LAST · 1s");
    expect((await chartState()).bars).toBe(BARS.bars.length); // the candles are untouched
    await page.evaluate(() =>
      window.dispatchEvent(
        new CustomEvent("ed:quote_tick", {
          detail: {
            ticker: "SPY",
            spot: null,
            spot_disp: null,
            feed_live: false,
            feed_label: "OFFLINE",
            trade_age_text: null,
          },
        }),
      ),
    );
    await expect.poll(async () => (await chartState()).livePrice).toBeNull(); // Schwab sent no price: no line
    await requests.settled(); // the ticks' own work, and any read it made, is done
    await page.clock.runFor(1500); // every page timer due in 1.5 s has run
    await requests.settled(); // and every read those made
    expect(barReads.length).toBe(before);
    // a bar completes: the program sends the bars again, whole, and the chart shows the new bar
    const last = BARS.bars[BARS.bars.length - 1];
    deskPanels().bars = tfAt(
      Object.assign({}, BARS, {
        bars: BARS.bars.concat([Object.assign({}, last, { t: last.t + 300 })]),
      }),
    );
    sock.changed("bars");
    await expect.poll(async () => (await chartState()).bars).toBe(BARS.bars.length + 1);
    expect(barReads.length).toBe(before);
    expect(errs).toEqual([]);
  });

  test("Price chart:a pinned bar shows its served change (the chart kept the bar without it)", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    await intercept(page);
    // induced: SPY's last 60 real 5-minute bars, each with its served change set to 0.25, so a
    // click lands on one whose change is known
    const bars = BARS.bars
      .slice(-60)
      .map((b) => Object.assign({}, b, { chg: 0.25, chg_pct: 0.0325, chg_text: "+0.25 (+0.03%)" })); // as live_price_rows serves it
    deskPanels().bars = tfAt(Object.assign({}, BARS, { bars: bars }));
    await openView(page, "trade-desk", "desk");
    await expect(page.locator("#tdmChart .tvc-legend")).toContainText("Last completed bar");
    const box = await page.locator("#tdmChart .tvc-plot").boundingBox();
    await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5);
    const pin = page.locator("#tdmChart .tvc-pin");
    await expect(pin).toBeVisible();
    await expect(pin).toContainText("Bar change+0.25 (+0.03%)");
    // its time is the one served with the bar (push.bars' time_ct), not formatted on the page
    const shown = await pin.textContent();
    expect(bars.some((b) => shown.includes(b.time_ct))).toBe(true);
    expect(errs).toEqual([]);
  });

  test("Desk: the venue switch asks for one Schwab book at a time", async ({ page }) => {
    const errs = watchErrors(page);
    const sock = await intercept(page);
    // the venue of each ask the desk made of the book, in order; the event queue is no venue's
    const venues = (name) =>
      sock.subscribes
        .map((s) => s.panels[name])
        .filter((p) => p !== undefined && p !== null)
        .map((p) => p.venue);
    const asked = () => venues("book:deskmap").slice(-1);
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "desk");
      localStorage.removeItem("ed_book_venue");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const nyse = page.locator('#tdmCardLiq .bookvenue [data-venue="NYSE_BOOK"]');
    const nasdaq = page.locator('#tdmCardLiq .bookvenue [data-venue="NASDAQ_BOOK"]');
    await expect(nyse).toHaveClass(/on/);
    await expect.poll(asked).toEqual(["NYSE_BOOK"]);
    await nasdaq.click();
    await expect(nasdaq).toHaveClass(/on/);
    await expect.poll(asked).toEqual(["NASDAQ_BOOK"]);
    expect(venues("book:deskmap").every((v) => /^(NYSE|NASDAQ)_BOOK$/.test(v))).toBe(true);
    expect(venues("desk").length).toBeGreaterThan(0);
    expect(venues("desk").every((v) => v === undefined)).toBe(true);
    expect(errs).toEqual([]);
  });

  // AGENTS rule 5: the levels as the real code serves them on SPY's 2026-10-22 close publication,
  // its 16:39 print (773.1269) the last price and the daemon's connection ended, read at 18:00
  // (tests/test_level_crosses_wire.py keeps this file equal to the panel's answer)
  const STOPPED = require(
    path.join(__dirname, "..", "fixtures", "real_spy_levels_at_a_stopped_price_2026_10_22.json"),
  );
  // the price row of that print as the daemon serves it then: OFFLINE, with its trade time and age
  const STOPPED_ROW = priceRow("SPY", 773.1269, {
    feed_live: false,
    feed_label: "OFFLINE",
    outage: "Schwab LEVELONE_EQUITIES feed down during After-Hours",
    trade_time_ct: "Thu 10/22 03:39 PM CT",
    trade_age_text: "1h 21m",
  });
  // the words the header's row puts beside every value computed from that price (one producer)
  const STOPPED_MARK =
    " · OFFLINE: Schwab LEVELONE_EQUITIES feed down during After-Hours · last trade Thu 10/22 03:39 PM CT · 1h 21m";
  async function routeStopped(page) {
    await intercept(page, [STOPPED_ROW]); // every route answered in its real shape, then the stopped price's levels
    deskPanels().levels = levelsAt(STOPPED);
  }

  test("Right Now: distances from a price that has stopped are marked not live with its time and age", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    await routeStopped(page);
    await openView(page, "trade-desk", "right-now");
    const row = (id) => STOPPED.levels.find((r) => r.id === id);
    const nearest = row(STOPPED.by_distance[0]);
    const body = page.locator("#tdBody");
    await expect(body).toContainText(nearest.from_spot_text + STOPPED_MARK);
    await expect(body).toContainText(
      "Gamma Put " +
        row("put_wall").from_spot_text +
        ", Gamma Call " +
        row("call_wall").from_spot_text +
        STOPPED_MARK,
    );
    expect(errs).toEqual([]);
  });

  test("Price chart:the flip side from a price that has stopped is marked not live with its time and age", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    await routeStopped(page);
    await openView(page, "trade-desk", "desk");
    // the flip side is the terrain's (SPY's real one: below the flip), marked with the header row's words
    await expect(page.locator("#tdmAgree")).toContainText("Below Gamma Flip" + STOPPED_MARK);
    expect(errs).toEqual([]);
  });

  test("Right Now: a failed read is named, never told as no book, no levels, no regime or no gamma", async ({
    page,
  }) => {
    // the book, the levels, the regime and the per-strike panels not produced (the program's
    // words on the socket): before, they read "No book yet", "No levels", "No regime" and "no
    // per-strike gamma for this symbol yet"
    const errs = watchErrors(page);
    const words = "the program could not produce this panel: RuntimeError: chain lock timed out";
    const levelsWords = "the program could not produce this panel: KeyError: 'SPY'";
    const bookWords = "the program could not produce this panel: OSError: book read failed";
    const regimeWords = "the program could not produce this panel: ValueError: no chain held";
    await intercept(page); // every panel sent in its real shape, then the four that fail
    deskPanels().strikes = { failed: words };
    deskPanels().levels = { failed: levelsWords };
    deskPanels().book = { failed: bookWords };
    deskPanels().terrain = { failed: regimeWords };
    await openView(page, "trade-desk", "right-now");
    await expect(page.locator("#tdBody")).toContainText(bookWords);
    await expect(page.locator("#tdBody")).toContainText(levelsWords);
    await expect(page.locator("#tdMigration")).toContainText(words);
    // the regime's stage names the failure in the served word, with the program's reason
    const regime = page.locator("#tdBody .td-stage.td-accent-amber");
    await expect(regime.locator(".td-hero")).toHaveText("FAILED" + regimeWords);
    expect(errs).toEqual([]);
  });

  test("Right Now: detect, frame, context and the migration read the served fields", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    await intercept(page);
    await openView(page, "trade-desk", "right-now");
    const body = page.locator("#tdBody");
    // the book's lean is the Liquidity readout's, served (one producer for the desk), its tilt in
    // the words served for running text: the page changes no case
    const nq5 = MICRO.readout.venues.NASDAQ_BOOK.views["5"];
    expect(nq5.tilt_text).toBe(
      { BID_HEAVY: "buy-heavy", BALANCED: "neutral", OFFER_HEAVY: "sell-heavy" }[nq5.tilt],
    );
    // beside the venue's served name, never its service code
    const nq = MICRO.readout.venues.NASDAQ_BOOK.name;
    expect(nq).toBe("Nasdaq");
    await expect(body).toContainText(nq5.pct_text + nq5.tilt_text + " (" + nq + ", top 5)");
    // SPY's real levels (Right Now asks them at 1 minute): max pain is the nearest, 0.08 below
    // the price; the price is through the largest put gamma strike, so both are above it
    const level = (id) => REAL.levels["1"].levels.find((r) => r.id === id);
    await expect(body).toContainText("Max Pain 757.00"); // nearest by the served by_distance
    await expect(body).toContainText("0.08 below spot");
    await expect(body).toContainText(
      "Gamma Put " +
        level("put_wall").from_spot_text +
        ", Gamma Call " +
        level("call_wall").from_spot_text,
    ); // the levels panel's own rows
    // the price is inside the pivot zone 757.00-758.01 (the liquidity panel's own spot_location);
    // its four levels (max pain, today's VAH, the opening range high, the prior day's VAL; no VWAP
    // band since 2026-11-20), the price not among them
    await expect(body).toContainText("Price inside zone (757.00–758.01, levels in zone 4)");
    expect([INSIDE.zone_low, INSIDE.zone_high, INSIDE.confluence_score]).toEqual([
      757.0, 758.01, 4,
    ]);
    // the largest call and put gamma strikes' and the flip's own moves since the prior close, as
    // served (no drift word)
    await expect(body).toContainText(
      "Gamma Call 760 → 775 (+15) · Gamma Put 760 → 760 (unchanged) · Gamma Flip 760.77 → 761.22 (+0.45)",
    );
    await expect(body).toContainText("Gamma grew most at 775/770");
    // the busiest strikes 757 and 760 against the put wall at 760: one below it, one on it, so
    // they sit across it, served in those words, never "inside" by default and never a dash
    await expect(body).toContainText("Heaviest option trading at 757–760That is across Gamma Put.");
    expect(errs).toEqual([]);
  });

  // AGENTS.md rule 4: where the price sits among the zones and the largest gamma strikes from it
  // are the program's sentences (push.liquidity location_said, push.levels walls_said). INDUCED:
  // each worded otherwise, then neither served, which leaves both lines out
  test("Right Now: the context summary draws the program's sentences, and leaves out one not served", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    const sock = await intercept(page);
    deskPanels().liquidity = Object.assign({}, LIQ, { location_said: "SERVED: where it sits" });
    deskPanels().levels = levelsAt((key, params) =>
      Object.assign({}, REAL.levels[params.tf], { walls_said: "SERVED: the gamma strikes" }),
    );
    await openView(page, "trade-desk", "right-now");
    const summary = page.locator("#tdBody .td-context");
    await expect(summary).toContainText("LocationSERVED: where it sits");
    await expect(summary).toContainText("Gamma strikesSERVED: the gamma strikes");
    deskPanels().liquidity = Object.assign({}, LIQ, { location_said: null });
    deskPanels().levels = levelsAt((key, params) =>
      Object.assign({}, REAL.levels[params.tf], { walls_said: null }),
    );
    sock.changed("liquidity");
    sock.changed("levels");
    await expect(summary).not.toContainText("Location");
    await expect(summary).not.toContainText("Gamma strikes");
    await expect(summary).toContainText("Regime"); // the served lines stand
    expect(errs).toEqual([]);
  });

  test("Right Now: each card of levels shows their marks as served, live and after they stopped arriving", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    const sock = await intercept(page);
    await openView(page, "trade-desk", "right-now");
    const asof = (card) => page.locator("#tdBody " + card + " .asof");
    const FRAME = ".td-stage.td-accent-green .chart-asof",
      CONFIRM = ".td-stage.td-accent-amber .chart-asof",
      MIGRATION = "#tdMigration .mig-chips";
    // SPY's panels during its session (Right Now asks the levels at 1 minute). Frame's rows are
    // the session's price levels and the gamma levels carried beside them: the snapshot's time
    // and age and the levels verdict. Confirm and the migration: the verdict their own panel is
    // served with. Detect draws no level and has no as-of line
    const levels = REAL.levels["1"];
    await expect(asof(FRAME)).toHaveText([snapshotMark(levels), verdictMark(levels)]);
    await expect(asof(CONFIRM)).toHaveText([verdictMark(TERRAIN)]);
    await expect(asof(MIGRATION)).toHaveText([verdictMark(STRIKES)]);
    for (const card of [FRAME, CONFIRM, MIGRATION])
      await expect(asof(card).last()).toHaveClass("asof live");
    await expect(page.locator("#tdBody .td-stage.td-accent-blue .chart-asof")).toHaveCount(0);
    // INDUCED: the same panels ten minutes on with no chain, bar, trade or heartbeat since: the
    // levels' and the terrain's own later answers (the keys that read differently, held to the
    // route by tests/test_e2e_panels_two_day_v1.py), and the strikes with that later verdict (the
    // one verdict every panel serves). The last values stand, each card's marked STALE with the
    // chain's time, its age and why
    const laterLevels = Object.assign({}, levels, REAL.later.levels);
    const laterTerrain = Object.assign({}, TERRAIN, REAL.later.terrain);
    const laterStrikes = Object.assign({}, STRIKES, {
      levels_state: laterTerrain.levels_state,
      levels_stale_reason: laterTerrain.levels_stale_reason,
      levels_age_text: laterTerrain.levels_age_text,
    });
    expect([laterTerrain.levels_state, laterTerrain.levels_age_text]).toEqual(["STALE", "10m"]);
    deskPanels().levels = levelsAt(laterLevels);
    deskPanels().terrain = laterTerrain;
    deskPanels().strikes = laterStrikes;
    for (const kind of ["levels", "terrain", "strikes"]) sock.changed(kind);
    await expect(asof(FRAME)).toHaveText([snapshotMark(laterLevels), verdictMark(laterLevels)]);
    await expect(asof(CONFIRM)).toHaveText([verdictMark(laterTerrain)]);
    await expect(asof(MIGRATION)).toHaveText([verdictMark(laterStrikes)]);
    for (const card of [FRAME, CONFIRM, MIGRATION]) {
      await expect(asof(card).last()).toHaveClass("asof stale");
      await expect(asof(card).last()).toHaveAttribute("title", laterTerrain.levels_stale_reason);
    }
    const body = page.locator("#tdBody");
    await expect(body).toContainText("Max Pain 757.00"); // SPY's nearest level, as before
    await expect(body).toContainText("Gamma Call" + TERRAIN.call_wall_text);
    // a ticker switch leaves nothing of the last ticker: its cards' values and their marks
    for (const kind of ["book", "levels", "liquidity", "terrain", "strikes"])
      deskPanels()[kind] = () => undefined; // the new ticker's panels are not sent yet
    await page.evaluate(() => window.EdShell.setTicker("QQQ"));
    await expect(page.locator("#tdBody .td-stage.td-accent-green .td-hero")).toHaveText("-");
    await expect(page.locator("#tdBody .asof")).toHaveCount(0);
    expect(errs).toEqual([]);
  });

  test("Desk: the regime is said in the served words on the Options card and the agreement strip", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    const sock = await intercept(page);
    await openView(page, "trade-desk", "desk");
    const card = page.locator("#tdmCardOpt .tdm-state");
    const strip = page.locator("#tdmAgree");
    // SPY's real levels: net GEX at the price is negative
    await expect(card).toHaveText("Negative gamma");
    await expect(strip).toContainText("OPTIONSNegative gamma");
    // INDUCED: those levels with each other regime the server serves and the words it serves with
    // it (calc.terrain_read.REGIME_TEXT), then a regime the page has never held: the card and the
    // strip draw the served words and pick none
    for (const [regime, words] of [
      ["POSITIVE_GAMMA", "Positive gamma"],
      ["UNAVAILABLE", "unavailable"],
      ["A_REGIME_ONLY_THE_SERVER_KNOWS", "as only the server says"],
    ]) {
      deskPanels().terrain = Object.assign({}, TERRAIN, { regime: regime, regime_text: words });
      sock.changed("terrain");
      await expect(card).toHaveText(words);
      await expect(strip).toContainText("OPTIONS" + words);
    }
    expect(errs).toEqual([]);
  });

  test("Desk: the agreement strip says the value area, the VWAP and the flip in the served words", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    const sock = await intercept(page);
    await openView(page, "trade-desk", "desk");
    const strip = page.locator("#tdmAgree");
    // SPY's real panels, each state with the words served beside it
    await expect(strip).toContainText("VALUE" + LIQ.summary.value_state_text);
    await expect(strip).toContainText("VWAP" + LIQ.summary.vwap_relation_text);
    await expect(strip).toContainText("GAMMA" + TERRAIN.flip_relation_text);
    // INDUCED: those panels with every state the server serves and the words it serves with it
    // (push.liquidity.VALUE_STATE_TEXT, VWAP_RELATION_TEXT; calc.terrain_read.FLIP_RELATION_TEXT),
    // then none known (no words: the dash), then states the page has never held: the strip draws
    // the served words and picks none. Each row: the state, its served words, the cell as drawn.
    for (const [value, vwap, flip] of [
      [
        ["unchanged", "unchanged", "unchanged"],
        ["above_value", "above value", "above value"],
        ["ABOVE", "Above Gamma Flip", "Above Gamma Flip"],
      ],
      [
        ["higher", "higher", "higher"],
        ["below_value", "below value", "below value"],
        ["AT", "At Gamma Flip", "At Gamma Flip"],
      ],
      [
        ["inside", "inside", "inside"],
        ["inside_value", "inside value", "inside value"],
        ["BELOW", "Below Gamma Flip", "Below Gamma Flip"],
      ],
      [
        ["outside", "outside", "outside"],
        [null, null, "-"],
        [null, null, "-"],
      ],
      [
        ["overlapping_higher", "overlapping higher", "overlapping higher"],
        ["above_value", "above value", "above value"],
        ["ABOVE", "Above Gamma Flip", "Above Gamma Flip"],
      ],
      [
        ["overlapping_lower", "overlapping lower", "overlapping lower"],
        ["below_value", "below value", "below value"],
        ["BELOW", "Below Gamma Flip", "Below Gamma Flip"],
      ],
      [
        [null, null, "-"],
        ["a_state_only_the_server_knows", "as only the server says", "as only the server says"],
        ["ELSEWHERE", "Where only the server says", "Where only the server says"],
      ],
    ]) {
      deskPanels().liquidity = Object.assign({}, LIQ, {
        summary: {
          value_state: value[0],
          vwap_relation: vwap[0],
          value_state_text: value[1],
          vwap_relation_text: vwap[1],
        },
      });
      deskPanels().terrain = Object.assign({}, TERRAIN, {
        flip_relation: flip[0],
        flip_relation_text: flip[1],
      });
      sock.changed("liquidity");
      sock.changed("terrain");
      await expect(strip).toContainText("VALUE" + value[2]);
      await expect(strip).toContainText("VWAP" + vwap[2]);
      await expect(strip).toContainText("GAMMA" + flip[2]);
    }
    expect(errs).toEqual([]);
  });

  test("Right Now: where the busiest strikes sit is said in the served words, each place", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    const sock = await intercept(page);
    await openView(page, "trade-desk", "right-now");
    const body = page.locator("#tdBody");
    // SPY's real panel: its busiest strikes sit across the put wall, served as a whole sentence
    expect(STRIKES.migration.busiest_where_said).toBe("That is across Gamma Put.");
    await expect(body).toContainText("Heaviest option trading at 757–760That is across Gamma Put.");
    // INDUCED: that panel with no place known (a wall not known): the sentence is left out, no
    // dash in it
    deskPanels().strikes = Object.assign({}, STRIKES, {
      migration: Object.assign({}, STRIKES.migration, {
        busiest_vs_walls: null,
        busiest_where_said: null,
      }),
    });
    sock.changed("strikes");
    await expect(body.locator(".mig-coach").last()).toHaveText(
      "Heaviest option trading at 757–760",
    );
    // INDUCED: that panel with each place the server serves and the words it serves with it
    // (push.strikes.BUSIEST_VS_WALLS_TEXT), then with a place and words the page has never held:
    // the page draws the served words, whichever they are, and picks none
    for (const [place, words] of [
      ["ABOVE_CALL_WALL", "ABOVE Gamma Call"],
      ["BELOW_PUT_WALL", "BELOW Gamma Put"],
      ["INSIDE_WALLS", "between Gamma Put and Gamma Call"],
      ["ACROSS_CALL_WALL", "across Gamma Call"],
      ["ACROSS_WALLS", "across Gamma Put and Gamma Call"],
      ["A_PLACE_ONLY_THE_SERVER_KNOWS", "where only the server says"],
    ]) {
      deskPanels().strikes = Object.assign({}, STRIKES, {
        migration: Object.assign({}, STRIKES.migration, {
          busiest_vs_walls: place,
          busiest_where_said: "That is " + words + ".",
        }),
      });
      sock.changed("strikes");
      await expect(body).toContainText("Heaviest option trading at 757–760That is " + words + ".");
    }
    expect(errs).toEqual([]);
  });

  test("Right Now: the regime is said by its served name in the Confirm stage and the context summary", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    const sock = await intercept(page);
    await openView(page, "trade-desk", "right-now");
    const hero = page.locator("#tdBody .td-stage.td-accent-amber .td-hero");
    const row = page
      .locator("#tdBody .td-ctx-row")
      .filter({ has: page.locator(".lbl", { hasText: /^Regime$/ }) })
      .locator(".val");
    // SPY's real levels: the regime in words as the terrain panel serves it, never its code
    expect([TERRAIN.regime, TERRAIN.regime_text]).toEqual(["NEGATIVE_GAMMA", "Negative gamma"]);
    await expect(hero).toHaveText(TERRAIN.regime_text);
    await expect(row).toHaveText(TERRAIN.regime_text);
    // INDUCED: those levels with each other regime the server serves and its words
    // (calc.terrain_read.REGIME_TEXT), then words the page has never held: both places draw the
    // served words and pick none
    for (const [regime, words] of [
      ["POSITIVE_GAMMA", "Positive gamma"],
      ["UNAVAILABLE", "unavailable"],
      ["A_REGIME_ONLY_THE_SERVER_KNOWS", "as only the server says"],
    ]) {
      deskPanels().terrain = Object.assign({}, TERRAIN, { regime, regime_text: words });
      sock.changed("terrain");
      await expect(hero).toHaveText(words);
      await expect(row).toHaveText(words);
    }
    // INDUCED: no regime served: the dash in both places, never a code
    deskPanels().terrain = Object.assign({}, TERRAIN, { regime: null, regime_text: null });
    sock.changed("terrain");
    await expect(hero).toHaveText("-");
    await expect(row).toHaveText("-");
    expect(errs).toEqual([]);
  });

  test("Right Now: the book age keeps Schwab's book time", async ({ page }) => {
    const errs = watchErrors(page);
    const BOOK_TIME = "Fri 09/25 06:59 PM CT";
    await intercept(page);
    deskPanels().book = Object.assign({}, MICRO, {
      book_time_ct: BOOK_TIME,
      book_when_age_text: BOOK_TIME + " · 1s",
      top_outage: "Schwab NASDAQ_BOOK feed down during RTH",
      top_feed_label: "OFFLINE",
    });
    await openView(page, "trade-desk", "right-now");
    const body = page.locator("#tdBody");
    await expect(body).toContainText("OFFLINE");
    await expect(body).toContainText(BOOK_TIME + " · 1s");
    await expect(body).toContainText("757.05 × 757.07"); // Schwab's best bid and ask
    await expect(body).toContainText(
      MICRO.readout.venues.NASDAQ_BOOK.views["5"].tilt_text + " (Nasdaq, top 5)",
    );
    expect(errs).toEqual([]);
  });

  test("Right Now: the book's tilt is drawn in the served words, words only the server knows too", async ({
    page,
  }) => {
    // INDUCED on SPY's real book panel: the NASDAQ book's Top 5 view staged with words no script
    // could hold. The page draws tilt_text beside the venue and depth and changes no case.
    const errs = watchErrors(page);
    await intercept(page);
    const book = JSON.parse(JSON.stringify(MICRO));
    book.readout.venues.NASDAQ_BOOK.views["5"].tilt_text = "Words ONLY the server knows";
    deskPanels().book = book;
    await openView(page, "trade-desk", "right-now");
    await expect(page.locator("#tdBody")).toContainText(
      book.readout.venues.NASDAQ_BOOK.views["5"].pct_text +
        "Words ONLY the server knows (Nasdaq, top 5)",
    );
    expect(errs).toEqual([]);
  });

  test("Right Now draws each of its panels again when the program sends it, and asks for each once", async ({
    page,
  }) => {
    const sock = await intercept(page);
    await openView(page, "trade-desk", "right-now");
    const body = page.locator("#tdBody");
    await expect(body).toContainText("Max Pain 757.00");
    // Schwab's SPY set: the largest put and call gamma strikes are both above the price, so the
    // line names each one's own side, each by its served name
    const side = (id) => LEVELS.levels.find((r) => r.id === id).from_spot_text;
    expect([side("put_wall"), side("call_wall")]).toEqual(["2.92 above spot", "17.92 above spot"]);
    await expect(body).toContainText(
      "Gamma strikesGamma Put 2.92 above spot, Gamma Call 17.92 above spot",
    );
    const asked = sock.subscribes.length;
    // DETECT's book and FRAME's zones, FRAME's levels (each with its distance from the live
    // price), CONFIRM's levels and the migration's rows are the book, liquidity, levels, terrain
    // and strikes panels the program sends on the socket when they change, the levels with each
    // price row too
    // induced: each panel again with one value changed
    deskPanels().book = Object.assign({}, MICRO, {
      top_of_book: Object.assign({}, MICRO.top_of_book, { bid: 757.0, bid_text: "757.00" }),
    });
    sock.changed("book");
    await expect(body).toContainText("757.00 × 757.07"); // DETECT's book
    deskPanels().liquidity = TOP_MOVED;
    sock.changed("liquidity");
    await expect(body).toContainText("Price inside zone (757.00–758.50"); // FRAME's zones
    await expect(body).toContainText("Max Pain 757.00");
    deskPanels().terrain = Object.assign({}, TERRAIN, { max_pain: 771, max_pain_text: "771.00" });
    sock.changed("terrain");
    await expect(body).toContainText("Gamma Flip761.22Max Pain (0DTE)771.00"); // CONFIRM's rows
    await expect(body).not.toContainText("Gamma Flip note"); // this set's flip carries no note
    // induced: the flip's note as the server words it (calc.terrain_read.FLIP_CURVE_DISAGREES)
    deskPanels().terrain = Object.assign({}, TERRAIN, {
      flip_note:
        "Gamma Flip is placed by a modelled curve that disagrees with Schwab's gamma at today's price.",
    });
    sock.changed("terrain");
    await expect(body).toContainText(
      "Gamma Flip noteGamma Flip is placed by a modelled curve that disagrees with Schwab's gamma at today's price.",
    );
    deskPanels().levels = levelsAt(
      Object.assign({}, LEVELS, {
        levels: LEVELS.levels.map((r) =>
          r.id === "max_pain" ? Object.assign({}, r, { from_spot_text: "0.30 below spot" }) : r,
        ),
      }),
    );
    sock.changed("levels");
    await expect(body).toContainText("0.30 below spot"); // FRAME's nearest level
    expect(sock.subscribes.length).toBe(asked); // a panel sent is drawn, never asked for again
  });

  test("Right Now: a new scope's strike window stays drawn through the next push", async ({
    page,
  }) => {
    const sock = await intercept(page);
    // the server's own windows: Auto (11 strikes, 752 to 762) and Wider (23), each as its scope is asked
    const wider = REAL.strikes_wider;
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "right-now");
      localStorage.setItem("ed_scope", "auto");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const strikes = page.locator("#tdMigration .gbs-k");
    await expect(strikes).toHaveText(listed(STRIKES));
    await page.evaluate(() => window.EdShell.setScope("wider"));
    await expect(strikes).toHaveText(listed(wider));
    for (const kind of ["strikes", "liquidity"]) sock.changed(kind); // the program sends the panels again
    deskPanels().book = Object.assign({}, MICRO, {
      top_of_book: Object.assign({}, MICRO.top_of_book, { bid: 757.0, bid_text: "757.00" }),
    });
    sock.changed("book");
    await expect(page.locator("#tdBody")).toContainText("757.00 × 757.07"); // the push has been drawn
    await expect(strikes).toHaveText(listed(wider)); // the window asked for, not the old one
  });

  test("no panel stays marked busy once its panel has landed", async ({ page }) => {
    await intercept(page);
    const CONTRACT = "SPY   261002C00768000";
    deskPanels().contract = (key, params) => ({ available: false, contract: params.contract });
    await page.route("**/api/flow-contract", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ok: true, contract: CONTRACT }),
      }),
    );
    // every panel the page takes, by its name, in the order it arrives
    await page.addInitScript(() => {
      window.__landed = [];
      document.addEventListener("ed:panel", (e) => window.__landed.push(e.detail.type));
    });
    // each view and the panel it shows; Flow asks only once a contract is chosen
    const panels = [
      ["trade-desk", "right-now", "", "book:desk"],
      ["options", "gamma", "heatmap", "tape"],
      ["options", "flow", "", "contract"],
      ["order-flow", "book", "", "book:dom"],
    ];
    for (const [ws, sub, view, name] of panels) {
      await openView(page, ws, sub, view);
      if (sub === "flow") await page.evaluate((c) => window.EdFlow.select(c), CONTRACT);
      await expect
        .poll(() => page.evaluate(() => window.__landed), sub + " " + view)
        .toContain(name); // the panel has landed
      expect(await page.locator('[aria-busy="true"]').count(), sub + " " + view).toBe(0);
    }
  });

  test("Right Now: the old venue's book arriving after a venue switch is never drawn", async ({
    page,
  }) => {
    const sock = await intercept(page);
    let held = false; // NASDAQ's book is sent when the test says
    deskPanels().book = (key, params) =>
      held && params.venue === "NASDAQ_BOOK"
        ? undefined
        : Object.assign({}, MICRO, { venue: params.venue });
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "right-now");
      localStorage.setItem("ed_book_venue", "NYSE_BOOK");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const body = page.locator("#tdBody");
    await expect(body).toContainText("(NYSE, top 5)");
    await page.evaluate(() => {
      // the venue each draw from here on shows
      window.__draws = [];
      new MutationObserver(() =>
        window.__draws.push(
          (document.getElementById("tdBody").textContent.match(/\((NYSE|Nasdaq),/) || [""])[0],
        ),
      ).observe(document.getElementById("tdBody"), { childList: true });
    });
    held = true;
    await page.evaluate(() =>
      document.querySelector('.bookvenue [data-venue="NASDAQ_BOOK"]').click(),
    );
    await expect
      .poll(() =>
        sock.subscribes.some(
          (s) => s.panels && s.panels["book:desk"] && s.panels["book:desk"].venue === "NASDAQ_BOOK",
        ),
      )
      .toBe(true);
    sock.frame("book:desk", "SPY", Object.assign({}, MICRO, { venue: "NYSE_BOOK" })); // NYSE's, already on its way ...
    held = false;
    sock.changed("book"); // ... and NASDAQ's behind it
    await expect(body).toContainText("(Nasdaq, top 5)");
    expect(await page.evaluate(() => window.__draws)).toEqual(["(Nasdaq,"]);
  });

  test("Right Now: a strike of GEX not known keeps its row: no bar, no ghost, the dash, no page error", async ({
    page,
  }) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await intercept(page);
    // induced: SPY's real rows with today's GEX and volume of the strike at the price (757) not known
    const K = STRIKES.today.find((r) => r.marks.some((m) => m.kind === "spot")).strike;
    const today = STRIKES.today.map((r) =>
      r.strike === K
        ? {
            strike: K,
            strike_text: r.strike_text,
            value: null,
            volume: null,
            text: null,
            volume_text: null,
            marks: r.marks,
          }
        : r,
    );
    deskPanels().strikes = Object.assign({}, STRIKES, {
      today: today,
      migration: Object.assign({}, STRIKES.migration, {
        rows: STRIKES.migration.rows.map((r) =>
          r.strike === K
            ? { strike: K, value: null, prior: r.prior, change: null, change_text: null }
            : r,
        ),
      }),
    });
    await openView(page, "trade-desk", "right-now");
    await expect(page.locator("#tdMigration .gbs-k")).toHaveText(listed(STRIKES));
    const row = page
      .locator("#tdMigration .mig-row")
      .filter({ has: page.locator(".gbs-k", { hasText: new RegExp("^" + K + "$") }) });
    await expect(row.locator(".gbs-v")).toHaveText("-");
    await expect(row.locator(".mig-delta")).toHaveText("-");
    await expect(row.locator(".gbs-vol")).toHaveText("-");
    expect(await row.locator(".gbs-bar").evaluate((el) => el.style.width)).toBe("0%");
    await expect(row.locator(".mig-ghost")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("Right Now: each row draws the marks the server serves it (the price's strike, the walls)", async ({
    page,
  }) => {
    await intercept(page);
    await openView(page, "trade-desk", "right-now");
    await expect(page.locator("#tdMigration .gbs-k")).toHaveText(listed(STRIKES));
    // SPY's real rows, high strikes on top: 757 the price's strike, 760 the put wall
    const served = STRIKES.today.slice().reverse();
    expect(served.filter((r) => r.marks.length).map((r) => r.strike)).toEqual([760, 757]);
    const rows = page.locator("#tdMigration .mig-row");
    for (let i = 0; i < served.length; i++) {
      const marks = served[i].marks;
      await expect(rows.nth(i).locator(".mig-mark")).toHaveText(marks.map((m) => m.label));
      await expect(rows.nth(i)).toHaveClass(
        ["gbs-row", "mig-row"].concat(marks.map((m) => "mark-" + m.kind)).join(" "),
      );
    }
  });

  test("Right Now: the migration follows the expiry chosen, and says one the chain does not list", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    const sock = await intercept(page);
    // the server's own answers on SPY's chain: its second expiry chosen, and a date it lists none on
    const ONE = REAL.strikes_second_expiry;
    const MISSING = REAL.strikes_missing_expiry;
    const MISSING_DATE = "2026-11-14"; // tests/test_e2e_panels_two_day_v1.py MISSING_EXPIRY
    const asked = () =>
      sock.subscribes
        .map((s) => s.panels && s.panels["strikes:migration"])
        .filter(Boolean)
        .pop();
    const drawn = (rows, key) =>
      rows
        .slice()
        .reverse()
        .map((r) => (r[key] == null ? "-" : r[key]));
    await openView(page, "trade-desk", "right-now");
    const panel = page.locator("#tdMigration");
    await expect(panel.locator(".mig-exp")).toHaveText("All Expirations");
    // the one expiry dropdown stands on the Trade Desk too; the Options grid's measure does not
    await expect(page.locator("#expSel")).toBeVisible();
    await expect(page.locator("#measureSel")).toBeHidden();
    await expect(panel.locator(".gbs-v")).toHaveText(drawn(STRIKES.today, "text"));
    await expect(panel.locator("[data-mig-scope]")).toHaveCount(0); // no fixed DTE chips
    await page.evaluate((e) => window.EdShell.setExpiry(e), ONE.expiry);
    await expect.poll(() => asked().expiry).toBe(ONE.expiry);
    await expect(panel.locator(".mig-exp")).toHaveText(ONE.expiry_text);
    // that expiry's own rows, and each one's change against the same expiry on the prior day
    await expect(panel.locator(".gbs-v")).toHaveText(drawn(ONE.today, "text"));
    const change = Object.fromEntries(ONE.migration.rows.map((r) => [r.strike, r.change_text]));
    await expect(panel.locator(".mig-delta")).toHaveText(
      ONE.today
        .slice()
        .reverse()
        .map((r) => (change[r.strike] == null ? "-" : change[r.strike])),
    );
    // an expiry the chain does not list: the program's words, never another expiry's rows
    await page.evaluate((e) => window.EdShell.setExpiry(e), MISSING_DATE);
    await expect(panel).toContainText(MISSING.reason);
    await expect(panel.locator(".mig-row")).toHaveCount(0);
    await page.evaluate(() => window.EdShell.setExpiry(""));
    await expect(panel.locator(".mig-exp")).toHaveText("All Expirations");
    await expect(panel.locator(".gbs-v")).toHaveText(drawn(STRIKES.today, "text"));
    expect(errs).toEqual([]);
  });

  test("Right Now: a panel landing after a scope change draws only the new window", async ({
    page,
  }) => {
    // the price is the header's own row (one producer), with its trade time and age
    const sock = await intercept(page, [
      priceRow("SPY", SPOT, { trade_time_ct: "Thu 11/12 09:30 AM CT" }),
    ]);
    // the server's own windows: Auto, then Wider as its scope is asked
    const wide =
      listed(REAL.strikes_wider).join(",") +
      " | spot " +
      SPOT.toFixed(2) +
      " · last trade Thu 11/12 09:30 AM CT · 1s";
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "right-now");
      localStorage.setItem("ed_scope", "auto");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("#tdMigration .gbs-k")).toHaveText(listed(STRIKES));
    await page.evaluate(() => {
      // every draw of the page from here on: its strikes and its spot
      window.__draws = [];
      new MutationObserver(() => {
        const ks = [...document.querySelectorAll("#tdMigration .gbs-k")]
          .map((e) => e.textContent)
          .join(",");
        const meta = document.querySelector("#tdBody .fl-meta");
        window.__draws.push(ks + " | " + (meta ? meta.textContent : ""));
      }).observe(document.getElementById("tdBody"), { childList: true });
    });
    await page.evaluate(() => window.EdShell.setScope("wider")); // the scope changes ...
    await expect(page.locator("#tdMigration .gbs-k")).toHaveText(listed(REAL.strikes_wider));
    deskPanels().liquidity = TOP_MOVED;
    sock.changed("liquidity"); // ... and a panel of another kind lands after it
    await expect(page.locator("#tdBody")).toContainText("Price inside zone (757.00–758.50");
    // once the new window is drawn, every later draw is the new window: none goes back to the
    // old one, the later panel's included
    const draws = await page.evaluate(() => window.__draws);
    const first = draws.indexOf(wide);
    expect(first).toBeGreaterThan(-1);
    expect(draws.slice(first).filter((d) => d !== wide)).toEqual([]);
  });

  test("Price chart:3m, line mode, a level beyond the visible range pinned at the edge, and the flip note", async ({
    page,
  }) => {
    const errs = watchErrors(page);
    const far = FAR_GRC;
    const wall = {
      id: "call_wall",
      price: 772,
      price_text: "772.00",
      family: "gamma",
      label: "Gamma Call",
      evidence_tier: "DERIVED",
      distance: 0.7,
      side: "ABOVE",
    };
    await routeWatchlist(page, ["SPY"]);
    await mockPriceSocket(page, [], undefined, {
      desk: tfAt(EVENTS),
      book: MICRO,
      liquidity: LIQ,
      bars: tfAt(BARS),
      terrain: Object.assign({}, TERRAIN, {
        call_wall: 772,
        call_wall_text: "772.00",
        call_wall_lean: null,
        flip_note: "the flip's note, as served",
      }),
      levels: levelsAt(
        Object.assign({}, LEVELS, {
          levels: LEVELS.levels.concat([wall, far]),
          by_distance: ["call_wall", "max_pain", "PDH", "grc"],
        }),
      ),
    });
    await openView(page, "trade-desk", "desk");
    await expect(page.locator('#tdmToolbar [data-tf="3"]')).toHaveText("3m");
    await expect(page.locator("#tdmChart .tvc-edge-top")).toContainText("GRC 837.58");
    await expect(page.locator("#tdmCardOpt")).toContainText(
      "Gamma Flip note the flip's note, as served",
    ); // induced
    await page.locator('#tdmToolbar [data-act="style"]').click();
    await expect(page.locator('#tdmToolbar [data-act="style"]')).toHaveClass(/on/);
    expect(errs).toEqual([]);
  });

  test("Price chart:no shaded wall band, whatever the terrain carries", async ({ page }) => {
    // operator 2026-10-04: no shaded area on the chart. The call- and put-wall gamma ranges were
    // drawn as green and red bands across the pane; a terrain that still carries ranges (as the
    // server sent them before) draws exactly the same chart as one without them.
    async function chartImage(terrain) {
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await routeWatchlist(page, ["SPY"]);
      await mockPriceSocket(page, [], undefined, {
        terrain: terrain,
        levels: levelsAt(LEVELS),
        desk: tfAt(EVENTS),
        book: MICRO,
        liquidity: LIQ,
        bars: tfAt(BARS),
      });
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await expect(page.locator("#tdmCardOpt")).toContainText("775.00"); // the terrain panel has landed
      await expect
        .poll(() =>
          page.evaluate(
            () => window.EdTradeDeskMap.state().chart && window.EdTradeDeskMap.state().chart.bars,
          ),
        )
        .toBeGreaterThan(0);
      // the terrain's answer is painted on the next frames
      await page.evaluate(
        () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
      );
      await page.mouse.move(0, 0);
      // what the chart draws: every canvas's pixels and the chart's DOM (its labels and
      // controls: each element, its attributes in name order, its text). A screenshot of the same
      // drawing differs by a level in a few anti-aliased pixels under load, and the order the
      // chart library writes a canvas's attributes in varies, so the drawing itself is compared.
      return page.evaluate(() => {
        const host = document.getElementById("tdmChart");
        const tree = (n) =>
          n.nodeType !== Node.ELEMENT_NODE
            ? n.textContent
            : [
                n.nodeName,
                Array.from(n.attributes, (a) => [a.name, a.value]).sort(),
                Array.from(n.childNodes, tree),
              ];
        return {
          canvases: Array.from(host.querySelectorAll("canvas"), (c) => c.toDataURL()),
          dom: tree(host),
        };
      });
    }
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "desk");
    });
    const plain = await chartImage(TERRAIN);
    const withRanges = await chartImage(
      Object.assign({}, TERRAIN, {
        call_wall_range: { lo: 700, hi: 800, coverage_pct: 70, method: "gamma value area" },
        put_wall_range: { lo: 700, hi: 800, coverage_pct: 70, method: "gamma value area" },
      }),
    );
    expect(plain.canvases.length).toBeGreaterThan(0);
    expect(withRanges).toEqual(plain);
  });
});
