/*
 * Trade Desk > Experimental draws the `experimental` panel as the server serves it and computes
 * nothing. The panel is the server's own answer for TSLA at 2026-10-07 09:40 ET, from Schwab's
 * real 5-minute bars and a year of opens (tests/e2e/fixtures/experimental_tsla.json, held to the
 * producer by tests/test_open_gap_v1.py). Any page error fails the test.
 */
const { test, expect } = require("@playwright/test");
const { mockPriceSocket } = require("./fixtures/price_socket");
const { routeWatchlist } = require("./fixtures/watchlist");
const EXPERIMENTAL = require("./fixtures/experimental_tsla.json");

test("today's card, the record and the last 10 opens are drawn as served", async ({ page }) => {
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  await routeWatchlist(page, ["TSLA"]);
  await mockPriceSocket(page, [], [], undefined, { experimental: EXPERIMENTAL });
  await page.addInitScript(() => {
    localStorage.setItem("ed_ticker", "TSLA");
    localStorage.setItem("ed_ws", "trade-desk");
    localStorage.setItem("ed_sub", "experimental");
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const body = page.locator("#xpBody");
  await expect(body.locator(".xp-big").first()).toHaveText(EXPERIMENTAL.today.gap_text);
  const rec = EXPERIMENTAL.records[0];
  await expect(body).toContainText(rec.main.count_text);
  await expect(body).toContainText(EXPERIMENTAL.today.results[0].five_text);
  await expect(body).toContainText(rec.last_title);
  expect(errs).toEqual([]);
});
