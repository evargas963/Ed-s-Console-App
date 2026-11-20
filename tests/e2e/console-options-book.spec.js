"use strict";
/**
 * The Options Book tab and the Trade Desk's Options Positioning card draw the option_book panel
 * the program sends on the page's socket (push.option_book): every row's served numbers on bars
 * against the served scales, the summary's split bars at the served shares, and the options lean's
 * gauge with its needle at the served angle and its served words. The panels are the producer's
 * own answers for SPY's front expiry at 2026-11-19 10:01:50 ET, Auto and Wider windows
 * (fixtures/option_book_spy.json, held to the producer by tests/test_option_book_v1.py). The page
 * computes nothing; the test works out each bar's length from the served value and scale.
 * Offline. Each test saves its screen as an attachment (option-book.png, options-card.png).
 */
const { test, expect } = require("@playwright/test");
const { mockPriceSocket } = require("./fixtures/price_socket");
const { routeWatchlist } = require("./fixtures/watchlist");
const { intercept, deskPanels, OPTION_BOOK, watchErrors } = require("./fixtures/trade_desk");
const BOOK = require("./fixtures/option_book_spy.json");

const AUTO = { scope: "auto", centre: null, shift: 0, expiry: null };
// the Options workspace's Book tab (Order Flow has a Book tab of its own)
const BOOK_PANE = '[data-ws-pane="options"] .sub-pane[data-sub-pane="book"]';
// the cells of a row, in the order the Book draws them: [side, field]
const CELLS = [
  ["call", "bid"],
  ["call", "ask"],
  ["call", "volume"],
  ["put", "bid"],
  ["put", "ask"],
  ["put", "volume"],
];

// the page on Options · Book for SPY, the program answering each window with its own panel
async function openBook(page) {
  await routeWatchlist(page, ["SPY"]);
  const sock = await mockPriceSocket(page, [], [], undefined, {
    option_book: (key, params) => (params.scope === "wider" ? BOOK.wider : BOOK.auto),
  });
  await page.setViewportSize({ width: 1500, height: 980 });
  await page.addInitScript(() => {
    localStorage.setItem("ed_ticker", "SPY");
    localStorage.setItem("ed_ws", "options");
    localStorage.setItem("ed_sub", "book");
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  return sock;
}
// a share of a bar's track (0 to 1) as the browser reads back the width the page set to a tenth
function pct(share) {
  return ((share * 100).toFixed(1) + "%").replace(".0%", "%");
}
// what each drawn row shows: its strike and its six cells' text and bar width
function drawn(page) {
  return page.locator("#opbBody .ob-row").evaluateAll((rows) =>
    rows.map((r) => ({
      strike: Number(r.getAttribute("data-strike")),
      spot: r.classList.contains("mark-spot"),
      cells: Array.from(r.querySelectorAll(".ob-n")).map((c) => {
        const bar = c.querySelector("i");
        return [c.querySelector("span").textContent, bar ? bar.style.width : null];
      }),
    })),
  );
}
// what the served panel says each row shows: the served text or "-", and the bar at the served
// value's share of its served scale
function expected(panel) {
  return panel.rows.map((r) => ({
    strike: r.strike,
    spot: r.marks.length > 0,
    cells: CELLS.map(([side, field]) => {
      const leg = r[side];
      const v = leg ? leg[field] : null;
      const scale = field === "volume" ? panel.scales.volume : panel.scales.resting;
      return [
        leg && leg[field + "_text"] != null ? leg[field + "_text"] : "-",
        v == null ? null : pct(Math.min(1, v / scale)),
      ];
    }),
  }));
}

test.describe("Options Book: the panel on the page's socket", () => {
  test("the Book tab asks its panel and draws every served row, bar, summary and the gauge", async ({
    page,
  }, testInfo) => {
    const errs = watchErrors(page);
    const sock = await openBook(page);
    const panel = BOOK.auto;
    await expect.poll(() => drawn(page)).toEqual(expected(panel));
    expect(sock.subscribes[sock.subscribes.length - 1].panels["option_book:book"]).toEqual(AUTO);
    // the row at the price, marked as served
    await expect(page.locator("#opbBody .ob-row.mark-spot .ob-k")).toHaveText("737SPOT");
    await expect(page.locator("#opbCtx")).toHaveText(panel.expiry + " · " + panel.books_held_text);
    await expect(page.locator("#opbSrc .asof")).toContainText("books · LIVE");
    // the summary: each split's served totals and shares, its track split at the served shares
    const s = panel.summary;
    const splits = page.locator("#opbBody .ob-split");
    await expect(splits).toHaveCount(3);
    for (const [i, key] of ["calls", "puts", "volume"].entries()) {
      const one = splits.nth(i);
      await expect(one.locator(".ob-split-n")).toContainText(s[key].left_text);
      await expect(one.locator(".ob-split-n")).toContainText(s[key].right_share_text);
      expect(await one.locator(".ob-split-track i.l").evaluate((e) => e.style.width)).toBe(
        pct(s[key].left_share),
      );
    }
    await expect(page.locator("#opbBody .ob-note")).toHaveText(s.summed_text);
    // the gauge: the needle at the served angle, the served value and zone, the three readings
    const lean = panel.lean;
    expect(await page.locator("#opbBody .olg-dial .needle").getAttribute("transform")).toBe(
      "rotate(" + lean.needle_deg.toFixed(2) + " 100 100)",
    );
    await expect(page.locator("#opbBody .olg-dial path[class^='z']")).toHaveCount(5);
    await expect(page.locator("#opbBody .olg-v")).toHaveText(lean.value_text);
    await expect(page.locator("#opbBody .olg-z")).toHaveText(lean.zone);
    await expect(page.locator("#opbBody .olg-z")).toHaveClass("olg-z z" + lean.zone_index);
    await expect(page.locator("#opbBody .olg-parts")).toHaveText(
      "Calls resting " +
        lean.calls_text +
        "Puts resting " +
        lean.puts_text +
        "Volume " +
        lean.volume_text,
    );
    await expect(page.locator("#opbBody .olg-ends")).toHaveText(panel.zones[0] + panel.zones[4]);
    await page.locator(BOOK_PANE + " > .panel").screenshot({
      path: testInfo.outputPath("option-book.png"),
    });
    // the same screen in the light palette: the theme is a token swap, nothing redrawn
    await page.evaluate(() => window.EdTheme.setPref("light"));
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.locator(BOOK_PANE + " > .panel").screenshot({
      path: testInfo.outputPath("option-book-light.png"),
    });
    expect(errs).toEqual([]);
  });

  test('a contract with no book streamed shows "-" with no bar, and the summary says what it leaves out', async ({
    page,
  }) => {
    const errs = watchErrors(page);
    const sock = await openBook(page);
    await expect.poll(() => drawn(page)).toEqual(expected(BOOK.auto));
    await page.evaluate(() => window.EdShell.setScope("wider"));
    await expect
      .poll(() => sock.subscribes[sock.subscribes.length - 1].panels["option_book:book"])
      .toEqual(Object.assign({}, AUTO, { scope: "wider" }));
    await expect.poll(() => drawn(page)).toEqual(expected(BOOK.wider));
    const unbooked = (await drawn(page)).filter((r) => r.cells[0][0] === "-");
    expect(unbooked.length).toBe(11);
    for (const r of unbooked) {
      expect([r.cells[0], r.cells[1], r.cells[3], r.cells[4]]).toEqual([
        ["-", null],
        ["-", null],
        ["-", null],
        ["-", null],
      ]);
      expect(r.cells[2][1]).not.toBeNull(); // the volume is still Schwab's, on its bar
    }
    await expect(page.locator("#opbBody .ob-note")).toContainText(BOOK.wider.summary.left_out_text);
    expect(errs).toEqual([]);
  });

  test("a panel the program could not produce, or with nothing to show, says why", async ({
    page,
  }) => {
    await routeWatchlist(page, ["SPY"]);
    await mockPriceSocket(page, [], [], undefined, {
      option_book: {
        available: false,
        reason: "the daemon has not delivered this ticker's chain yet",
      },
    });
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "options");
      localStorage.setItem("ed_sub", "book");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("#opbBody .placeholder")).toHaveText(
      "the daemon has not delivered this ticker's chain yet",
    );
    await expect(page.locator("#opbBody .ob-row")).toHaveCount(0);
  });
});

test.describe("Trade Desk: the Options Positioning card's options lean", () => {
  test("the card shows the compact gauge and no below/above rows; its Open tab goes to the Book", async ({
    page,
  }, testInfo) => {
    const errs = watchErrors(page);
    const sock = await intercept(page);
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "desk");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const card = page.locator("#tdmCardOpt");
    const lean = OPTION_BOOK.lean;
    await expect(card.locator(".olg.compact .olg-v")).toHaveText(lean.value_text);
    await expect(card.locator(".olg-z")).toHaveText(lean.zone);
    expect(await card.locator(".olg-dial .needle").getAttribute("transform")).toBe(
      "rotate(" + lean.needle_deg.toFixed(2) + " 100 100)",
    );
    await expect(card.locator(".olg-parts")).toContainText("Puts resting " + lean.puts_text);
    await expect(card.locator(".tdm-lean-h")).toHaveText(
      "Options lean" + OPTION_BOOK.expiry + " · books " + OPTION_BOOK.book_state,
    );
    expect(sock.subscribes[sock.subscribes.length - 1].panels["option_book:desk"]).toEqual(AUTO);
    // the card follows the one expiry chosen, and All Expirations again (its front one)
    const deskAsk = () => sock.subscribes[sock.subscribes.length - 1].panels["option_book:desk"];
    await page.evaluate((e) => window.EdShell.setExpiry(e), OPTION_BOOK.expiry);
    await expect.poll(() => deskAsk().expiry).toBe(OPTION_BOOK.expiry);
    await page.evaluate(() => window.EdShell.setExpiry(""));
    await expect.poll(deskAsk).toEqual(AUTO);
    // the four below/above rows are gone, the other facts stay
    await expect(card).toContainText("Call wall");
    await expect(card).not.toContainText("below / above");
    await card.screenshot({ path: testInfo.outputPath("options-card.png") });
    await card.locator(".tdm-open").click();
    await expect
      .poll(() =>
        page.evaluate(() => [
          window.EdShell.getState().workspace,
          window.EdShell.getState().subview,
        ]),
      )
      .toEqual(["options", "book"]);
    await expect(page.locator(BOOK_PANE)).toBeVisible();
    expect(errs).toEqual([]);
  });

  test("with no Options Book answered the card's gauge says why, the rest of the card stands", async ({
    page,
  }) => {
    await intercept(page);
    deskPanels().option_book = { failed: "the program could not produce this panel: KeyError" };
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "desk");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const card = page.locator("#tdmCardOpt");
    await expect(card.locator(".tdm-lean")).toHaveText(
      "Options lean: the program could not produce the options book",
    );
    await expect(card.locator(".olg")).toHaveCount(0);
    await expect(card).toContainText("Call wall");
  });
});
