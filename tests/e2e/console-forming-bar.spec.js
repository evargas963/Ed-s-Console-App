// @ts-check
/*
 * The chart's newest candle moves with each trade, as trading platforms draw it: the `forming`
 * panel (push.bars.forming) is drawn over the `bars` panel's newest bar, and Schwab's own bar
 * replaces it when it arrives. The frames are the server's own answers on SPY's real stream of
 * 2026-11-19 10:00-10:05 ET at the 5-minute timeframe (forming_spy_2026_11_19.json, held to the
 * server by tests/test_forming_bar_v1.py). Any page error fails the test.
 */
const { test, expect } = require("@playwright/test");
const { REAL, intercept, openView, watchErrors, deskPanels } = require("./fixtures/trade_desk");
const F = require("./fixtures/forming_spy_2026_11_19.json");

// a served bar as the chart's candle series holds it
const candle = (b) => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c });

test("the desk chart's newest candle redraws from each forming bar, and Schwab's bar replaces it", async ({
  page,
}) => {
  const errs = watchErrors(page);
  const sock = await intercept(page);
  deskPanels().bars = (key, params, name) => (name === "bars:flow" ? REAL.bars_flow : F.bars);
  deskPanels().forming = F.forming_early;
  // the levels and zones of the desk's own set are another day's (757): none sent, so the chart
  // is these bars alone
  deskPanels().levels = () => undefined;
  deskPanels().liquidity = () => undefined;
  await openView(page, "trade-desk", "desk", "");
  const chart = () => page.evaluate(() => window.EdTradeDeskMap.state().chart);
  // 10:04:30: the 10:00 bar is Schwab's 10:00-10:03 and the built 10:04, drawn over the served one
  await expect
    .poll(async () => (await chart()).lastCandle)
    .toEqual(candle(F.forming_early.bars[0]));
  expect((await chart()).bars).toBe(F.bars.bars.length);
  await expect(page.locator("#tdmChart .tvc-legend")).toContainText(
    "Forming · last trade " + F.forming_early.trade_time_ct,
  );
  await expect(page.locator("#tdmChart .tvc-legend")).toContainText(
    "C " + F.forming_early.bars[0].c_text,
  );
  // 10:04:59: 10:04's later trades move the same candle
  sock.frame("forming:deskmap", "SPY", F.forming_late);
  await expect.poll(async () => (await chart()).lastCandle).toEqual(candle(F.forming_late.bars[0]));
  expect((await chart()).bars).toBe(F.bars.bars.length);
  // 10:05:10: Schwab's 10:04 bar arrived (the bars, then the forming bars after it): the 10:00 bar
  // is Schwab's minutes alone, and the built 10:05 opens a new candle
  sock.frame("bars:deskmap", "SPY", F.bars_after);
  sock.frame("forming:deskmap", "SPY", F.forming_after);
  await expect
    .poll(async () => (await chart()).lastCandle)
    .toEqual(candle(F.forming_after.bars[0]));
  expect((await chart()).bars).toBe(F.bars_after.bars.length + 1);
  await page
    .locator("#tdmChart")
    .screenshot({ path: test.info().outputPath("forming-candle.png") });
  expect(errs).toEqual([]);
});

test("the liquidity map keeps the forming candle when another panel redraws it", async ({
  page,
}) => {
  // the map draws again on each of its panels (the zones come with every price row): the same
  // served bars keep the forming candle drawn over them
  const errs = watchErrors(page);
  const sock = await intercept(page);
  deskPanels().bars = F.bars;
  deskPanels().forming = F.forming_late;
  await openView(page, "liquidity", "map", "");
  const chart = () => page.evaluate(() => window.EdLiquidityMap.state());
  await expect.poll(chart).not.toBeNull();
  await expect.poll(async () => (await chart()).lastCandle).toEqual(candle(F.forming_late.bars[0]));
  sock.changed("liquidity");
  await expect.poll(async () => (await chart()).zones).toBe(REAL.liquidity.zones.length);
  expect((await chart()).lastCandle).toEqual(candle(F.forming_late.bars[0]));
  expect(errs).toEqual([]);
});
