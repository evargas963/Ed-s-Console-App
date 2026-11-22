"use strict";
/**
 * The Vanna and Charm tabs draw the panels the program sends on the page's socket (/ws:
 * server.strike_bars): while a tab is on, the subscribe names its
 * panel and the window it asks (the scope and the operator's pan), and the page asks no route
 * for it. The bars are the producer's own answer for CRWD's real 2026-10-07 chain at Schwab's
 * CRWD price, with the levels verdict it serves beside them, and (INDUCED) the same chain read
 * ten minutes on with nothing renewed (fixtures/vanna_charm_panels_crwd.json, held to the
 * producer by tests/test_vanna_charm_by_strike_v1.py); the "no levels" answer is the producer's
 * own words for a ticker with none published. Offline.
 */
const { test, expect } = require("@playwright/test");
const { served, priceRow } = require("./fixtures/price_socket");
const { routeWatchlist } = require("./fixtures/watchlist");
const PANELS = require("./fixtures/vanna_charm_panels_crwd.json");

// server.strike_bars' answer for a ticker with no levels published yet
const NO_LEVELS = { available: false, reason: "no levels published for this ticker yet" };
// the window a tab asks, at the page's one expiry choice (null: All Expirations)
const AUTO = { scope: "auto", centre: null, shift: 0, expiry: null };

function frame(kind, ticker, body) {
  return JSON.stringify(Object.assign({}, body, { type: kind, ticker: served(ticker).key }));
}
// CRWD's panels as the program answers a subscribe on CRWD: each one it names
function answerCrwd(ws, req) {
  if (req.ticker !== "CRWD") return;
  ["vanna", "charm"].forEach((k) => {
    if (req.panels[k]) ws.send(frame(k, "CRWD", PANELS[k]));
  });
}

// The page on the Options workspace's `sub` tab, on CRWD. `answer(ws, req, n)`: the program's
// side of the page's n-th connection, after its answer naming each symbol.
async function open(page, sub, answer) {
  const subscribes = [],
    asked = [];
  page.on("request", (r) => {
    if (/vanna|charm/.test(r.url())) asked.push(r.url());
  });
  await routeWatchlist(page, ["CRWD", "MRVL"]);
  let n = 0;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    const conn = ++n;
    ws.onMessage((m) => {
      const req = JSON.parse(String(m));
      if (req.op !== "subscribe") return;
      subscribes.push(req);
      ws.send(JSON.stringify({ type: "symbols", symbols: req.symbols.map(served) }));
      answer(ws, req, conn);
    });
  });
  await page.addInitScript((s) => {
    localStorage.setItem("ed_ticker", "CRWD");
    localStorage.setItem("ed_ws", "options");
    localStorage.setItem("ed_sub", s);
  }, sub);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  return { subscribes, asked, last: () => subscribes[subscribes.length - 1] };
}
// the strikes a bar list draws, highest first
function strikes(page, host) {
  return page
    .locator(host + " .gbs-row")
    .evaluateAll((rs) => rs.map((r) => Number(r.getAttribute("data-strike"))));
}
function sentStrikes(kind) {
  return PANELS[kind].rows.map((r) => r.strike).reverse();
}
// a tab's badge as the page draws the levels verdict a panel is served with: its state word, the
// time and the age
function badgeText(panel) {
  return ["terrain", panel.levels_state, panel.levels_time_ct, panel.levels_age_text].join(" · ");
}

test.describe("Vanna and Charm by strike: the panels on the page's socket", () => {
  test("the Vanna tab names its panel and window on the subscribe and draws the bars sent, asking no route", async ({
    page,
  }) => {
    const s = await open(page, "vanna", answerCrwd);
    await expect.poll(() => strikes(page, "#vnBody")).toEqual(sentStrikes("vanna"));
    expect(s.last().panels).toEqual({ expiries: {}, vanna: AUTO });
    expect(s.asked).toEqual([]);
    // the bars are the levels': the tab's badge is the levels verdict served with them
    await expect(page.locator("#vnSrc .asof")).toHaveText(badgeText(PANELS.vanna));
    await expect(page.locator("#vnSrc .asof")).toHaveClass("asof live");
  });

  // INDUCED (tests/test_vanna_charm_by_strike_v1.py): the same chain read ten minutes on with no
  // chain or heartbeat since, as the program serves it
  test("levels that stopped arriving stand on each tab, marked STALE with their time, age and why", async ({
    page,
  }) => {
    await open(page, "vanna", (ws, req) => {
      if (req.ticker !== "CRWD") return;
      ["vanna", "charm"].forEach((k) => {
        if (req.panels[k]) ws.send(frame(k, "CRWD", PANELS[k + "_stale"]));
      });
    });
    for (const [kind, host, src] of [
      ["vanna", "#vnBody", "#vnSrc"],
      ["charm", "#chmBody", "#chmSrc"],
    ]) {
      const panel = PANELS[kind + "_stale"];
      await page.evaluate((k) => window.EdShell.setSubview(k), kind);
      // the last values stand: the bars drawn are the ones sent
      await expect.poll(() => strikes(page, host)).toEqual(sentStrikes(kind));
      const badge = page.locator(src + " .asof");
      await expect(badge).toHaveText(badgeText(panel));
      expect(panel.levels_state).toBe("STALE");
      await expect(badge).toHaveClass("asof stale");
      await expect(badge).toHaveAttribute("title", panel.levels_stale_reason);
    }
  });

  test("switching to the Charm tab swaps the panel the subscribe names", async ({ page }) => {
    const s = await open(page, "vanna", answerCrwd);
    await expect.poll(() => strikes(page, "#vnBody")).toEqual(sentStrikes("vanna"));
    await page.evaluate(() => window.EdShell.setSubview("charm"));
    await expect.poll(() => strikes(page, "#chmBody")).toEqual(sentStrikes("charm"));
    expect(s.last().panels).toEqual({ expiries: {}, charm: AUTO });
  });

  test("vanna and charm are delta-shares, not dollars: no value is drawn with a dollar sign", async ({
    page,
  }) => {
    await open(page, "vanna", answerCrwd);
    await expect.poll(() => strikes(page, "#vnBody")).toEqual(sentStrikes("vanna"));
    const vanna = await page.locator("#vnBody .gbs-v").allTextContents();
    await page.evaluate(() => window.EdShell.setSubview("charm"));
    await expect.poll(() => strikes(page, "#chmBody")).toEqual(sentStrikes("charm"));
    const charm = await page.locator("#chmBody .gbs-v").allTextContents();
    expect(vanna.length).toBe(PANELS.vanna.rows.length);
    expect(charm.length).toBe(PANELS.charm.rows.length);
    expect(vanna.concat(charm).filter((t) => t.includes("$"))).toEqual([]);
    expect(vanna.concat(charm).some((t) => /\d/.test(t))).toBe(true);
  });

  test("a new scope and a pan ask the new window; a double-click follows the price again", async ({
    page,
  }) => {
    const s = await open(page, "vanna", answerCrwd);
    await expect.poll(() => strikes(page, "#vnBody")).toEqual(sentStrikes("vanna"));
    await page.evaluate(() => window.EdShell.setScope("all"));
    await expect
      .poll(() => s.last().panels.vanna)
      .toEqual({ scope: "all", centre: null, shift: 0, expiry: null });
    // drag the strike labels two rows down: two rows from the centre on screen (the one sent)
    const label = page.locator("#vnBody .gbs-k").first();
    const box = await label.boundingBox();
    const row = (await page.locator("#vnBody .gbs-row").first().boundingBox()).height;
    await page.mouse.move(box.x + 2, box.y + 2);
    await page.mouse.down();
    await page.mouse.move(box.x + 2, box.y + 2 + 2 * row, { steps: 4 });
    await page.mouse.up();
    await expect
      .poll(() => s.last().panels.vanna)
      .toEqual({ scope: "all", centre: PANELS.vanna.view.centre, shift: 2, expiry: null });
    await label.dblclick();
    await expect
      .poll(() => s.last().panels.vanna)
      .toEqual({ scope: "all", centre: null, shift: 0, expiry: null });
  });

  test("the expiry chosen is the one each tab asks, and an expiry not listed is said", async ({
    page,
  }) => {
    // the producer's own words for an expiry CRWD's chain does not list (push.strike_bars)
    const NOT_LISTED = "2026-10-17";
    const s = await open(page, "vanna", (ws, req) => {
      if (req.ticker !== "CRWD" || !req.panels.vanna) return;
      ws.send(
        frame(
          "vanna",
          "CRWD",
          req.panels.vanna.expiry === NOT_LISTED
            ? { available: false, reason: "the chain lists no contracts for " + NOT_LISTED }
            : PANELS.vanna,
        ),
      );
    });
    await expect.poll(() => strikes(page, "#vnBody")).toEqual(sentStrikes("vanna"));
    await page.evaluate((e) => window.EdShell.setExpiry(e), NOT_LISTED);
    await expect
      .poll(() => s.last().panels.vanna)
      .toEqual(Object.assign({}, AUTO, { expiry: NOT_LISTED }));
    await expect(page.locator("#vnBody")).toContainText(
      "the chain lists no contracts for " + NOT_LISTED,
    );
    await expect(page.locator("#vnBody .gbs-row")).toHaveCount(0);
    await page.evaluate(() => window.EdShell.setExpiry(""));
    await expect.poll(() => s.last().panels.vanna).toEqual(AUTO);
    await expect.poll(() => strikes(page, "#vnBody")).toEqual(sentStrikes("vanna"));
  });

  test('a ticker switch shows "-" until the new ticker\'s panel; a late one for the ticker left is ignored', async ({
    page,
  }) => {
    let program;
    await open(page, "vanna", (ws, req) => {
      program = ws;
      answerCrwd(ws, req);
    });
    await expect.poll(() => strikes(page, "#vnBody")).toEqual(sentStrikes("vanna"));
    await expect(page.locator("#vnSrc .asof")).toHaveCount(1);
    await page.evaluate(() => window.EdShell.setTicker("MRVL")); // MRVL's panel is held back
    await expect(page.locator("#vnBody .placeholder")).toHaveText("-");
    await expect(page.locator("#vnSrc .asof")).toHaveCount(0); // CRWD's badge left with its bars
    // CRWD's next panel, still in flight to a page that has left CRWD; then a MRVL row drawn
    // after it: once the row is on screen, the panel before it was read
    program.send(frame("vanna", "CRWD", PANELS.vanna));
    program.send(JSON.stringify({ type: "quotes", rows: [priceRow("MRVL", 87.65)] }));
    await expect(page.locator("#hPx")).toContainText("87.65");
    await expect(page.locator("#vnBody .placeholder")).toHaveText("-");
    expect(await page.locator("#vnBody .gbs-row").count()).toBe(0);
    program.send(frame("vanna", "MRVL", NO_LEVELS)); // MRVL's own: no levels yet, said so
    await expect(page.locator("#vnBody .placeholder")).toHaveText(NO_LEVELS.reason);
    await expect(page.locator("#vnSrc .asof")).toHaveCount(0); // no levels, so no verdict to show
  });

  test("the socket drops and returns: the subscribe names the panel again and the bars sent are drawn", async ({
    page,
  }) => {
    let first;
    const s = await open(page, "vanna", (ws, req, n) => {
      if (n === 1) {
        first = ws;
        answerCrwd(ws, req);
        return;
      }
      if (req.panels.vanna) ws.send(frame("vanna", "CRWD", NO_LEVELS)); // the program after the drop
    });
    await expect.poll(() => strikes(page, "#vnBody")).toEqual(sentStrikes("vanna"));
    const before = s.subscribes.length;
    first.close();
    await expect(page.locator("#vnBody .placeholder")).toHaveText(NO_LEVELS.reason);
    expect(s.subscribes.slice(before).map((r) => r.panels.vanna)).toContainEqual(AUTO);
  });

  // live_ui._produce's frame for a producer that raised: the panel's words, nothing else
  const FAILED = {
    failed:
      "the program could not produce this panel: TypeError: 'NoneType' object is not iterable",
  };

  test("a panel the program could not produce says why; the other panels and the prices keep coming", async ({
    page,
  }) => {
    await open(page, "vanna", (ws, req) => {
      ws.send(frame("vanna", "CRWD", FAILED));
      ws.send(frame("expiries", "CRWD", FAILED));
      ws.send(JSON.stringify({ type: "quotes", rows: [priceRow("CRWD", 269.4)] }));
      if (req.panels.charm) ws.send(frame("charm", "CRWD", PANELS.charm));
    });
    await expect(page.locator("#vnBody .placeholder")).toHaveText(FAILED.failed);
    await expect(page.locator("#expSel option[disabled]")).toHaveText(FAILED.failed);
    await expect(page.locator("#hPx")).toContainText("269.40");
    await page.evaluate(() => window.EdShell.setSubview("charm")); // the same socket, still open
    await expect.poll(() => strikes(page, "#chmBody")).toEqual(sentStrikes("charm"));
  });

  test("leaving the tab drops the panel from the subscribe", async ({ page }) => {
    const s = await open(page, "vanna", answerCrwd);
    await expect.poll(() => strikes(page, "#vnBody")).toEqual(sentStrikes("vanna"));
    await page.evaluate(() => window.EdShell.setSubview("gamma"));
    // the Gamma tab's own panels (Key Levels, GEX by Strike, the heatmap, the Options Flow tape) in its place
    await expect
      .poll(() => s.last().panels)
      .toEqual({
        expiries: {},
        "terrain:levels": {},
        "levels:kl": { tf: "1" },
        "strikes:gbs": AUTO,
        tape: {},
        surface: Object.assign({}, AUTO, { cols: expect.any(Number), expiry: null }),
      });
  });
});
