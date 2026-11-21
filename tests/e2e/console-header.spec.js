/*
 * The header is one, the same on every page, each value in it drawn from its one served producer
 * (docs/DATA_FLOW.md §6, decision 11), and it carries the volatility index: the market-context
 * entry the server marks (live_push.VOLATILITY_INDEX), from the price row the Desk's Volatility
 * card draws. What the socket sends is the program's own (fixtures/header_volatility.json, held
 * by tests/test_data_path_header_volatility_v1.py): what the header reads of the daemon's beat,
 * and the daemon's rows for Schwab's $VIX messages of 2026-11-20, in regular hours and once
 * Schwab marked the index Closed. SPY's row is the daemon's of 2026-10-23
 * (fixtures/price_rows_live.json): captures of two days, not received together. STAND-IN: the
 * program's socket, which answers each subscribe with what each symbol is and sends a frame when
 * the test says. Any page error fails the test.
 */
const { test, expect } = require("@playwright/test");
const { served } = require("./fixtures/price_socket");
const { holdClock } = require("./fixtures/settled");
const FX = require("./fixtures/header_volatility.json");
const SPY = require("./fixtures/price_rows_live.json").SPY;

// The program's socket: `send(frame)` sends one frame to the page, `asked()` is how many
// subscribes it has answered.
async function program(page) {
  const open = new Set();
  let asked = 0;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    open.add(ws);
    ws.onClose(() => open.delete(ws));
    ws.onMessage((m) => {
      const req = JSON.parse(String(m));
      if (req.op !== "subscribe") return;
      ws.send(JSON.stringify({ type: "symbols", symbols: req.symbols.map(served) }));
      asked += 1;
    });
  });
  return {
    send: (frame) => open.forEach((ws) => ws.send(JSON.stringify(frame))),
    asked: () => asked,
  };
}

function pageErrors(page) {
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  return errs;
}

// the market-context entry the server marks as the volatility index, as the page was served it
async function volatilityIndex(page) {
  const context = await page.evaluate(() => window.EdShell.marketContext());
  return context.filter((c) => c.volatility)[0];
}

test('the header shows the volatility index from its served row, "-" until it arrives; the Desk draws the same row', async ({
  page,
}) => {
  const errs = pageErrors(page);
  const sock = await program(page);
  await page.addInitScript(() => {
    localStorage.setItem("ed_ws", "trade-desk");
    localStorage.setItem("ed_sub", "desk");
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(sock.asked).toBeGreaterThan(0);
  const vol = await volatilityIndex(page);
  expect(vol.key).toBe(FX.live.ticker);
  // its name is the served display name; no row has arrived: "-", no change, no time
  await expect(page.locator("#hVolName")).toHaveText(vol.display);
  await expect(page.locator("#hVol")).toHaveText("-");
  await expect(page.locator("#hVolChg")).toHaveText("");
  await expect(page.locator("#hVolKv")).not.toHaveAttribute("title", /./);
  sock.send({ type: "quotes", rows: [FX.live, SPY] });
  await expect(page.locator("#hVol")).toHaveText(FX.live.spot_disp);
  await expect(page.locator("#hVolChg")).toHaveText(FX.live.chg_pct_text);
  await expect(page.locator("#hVolChg")).toHaveClass("pos");
  await expect(page.locator("#hVolName")).toHaveText(vol.display); // live: no word beside it
  await expect(page.locator("#hVolKv")).not.toHaveClass(/stale/);
  await expect(page.locator("#hVolKv")).toHaveAttribute(
    "title",
    "last trade " + FX.live.trade_time_ct + " · " + FX.live.trade_age_text,
  );
  // one row, two consumers: the Desk's Volatility card and its index strip draw the same values
  await expect(page.locator("#tdmCardVol")).toContainText(
    FX.live.spot_disp + " (" + FX.live.chg_pct_text + ") · last trade " + FX.live.trade_time_ct,
  );
  await expect(page.locator("#tdmIdx" + vol.display)).toContainText(FX.live.spot_disp);
  expect(errs).toEqual([]);
});

test("the header is one and the same on every page: each workspace and view shows the same header, the volatility index in it", async ({
  page,
}) => {
  const errs = pageErrors(page);
  await holdClock(page); // no timer of the page runs, so the push never reads silent on the way
  const sock = await program(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(sock.asked).toBeGreaterThan(0);
  sock.send({ type: "feed", feed: FX.beat, rows: [FX.live, SPY] });
  await expect(page.locator("#hClock")).toHaveText(FX.beat.clock_ct);
  await expect(page.locator("#hPx")).toHaveText(SPY.spot_disp);
  await expect(page.locator("#hVol")).toHaveText(FX.live.spot_disp);
  await expect(page.locator("header")).toHaveCount(1);
  const header = () => page.evaluate(() => document.querySelector("header").outerHTML);
  const first = await header();
  const workspaces = await page
    .locator(".navitem[data-ws]")
    .evaluateAll((ns) => ns.map((n) => n.dataset.ws));
  const walked = [];
  const same = async (where) => {
    expect(await header(), where).toBe(first);
    walked.push(where);
  };
  for (const ws of workspaces) {
    await page.locator(`.navitem[data-ws="${ws}"]`).click();
    await same(ws); // as it opens: a workspace with no view to open is a page too
    for (const sub of await page
      .locator("#subnav button[data-sub]:not(.na)")
      .evaluateAll((bs) => bs.map((b) => b.dataset.sub))) {
      await page.locator(`#subnav button[data-sub="${sub}"]`).click();
      const views = await page
        .locator("#viewbar .vtab:not(.na)")
        .evaluateAll((bs) => bs.map((b) => b.dataset.view));
      for (const view of views.length ? views : [null]) {
        if (view) await page.locator(`#viewbar .vtab[data-view="${view}"]`).click();
        await same([ws, sub, view].filter(Boolean).join(" > "));
      }
    }
  }
  // every workspace the shell lists was walked
  expect([...new Set(walked.map((w) => w.split(" > ")[0]))]).toEqual(workspaces);
  expect(errs).toEqual([]);
});

test("a stopped volatility index stands in the header marked not live, with its time; the push silent, it reads OFFLINE and its time has no age", async ({
  page,
}) => {
  const errs = pageErrors(page);
  await holdClock(page); // the page's timers run when the test moves its time
  const sock = await program(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(sock.asked).toBeGreaterThan(0);
  const vol = await volatilityIndex(page);
  // Schwab marked the index Closed: its last value stands, the served word beside its name, and
  // why, its trade time and its age are its title
  sock.send({ type: "quotes", rows: [FX.closed, SPY] });
  await expect(page.locator("#hVolName")).toHaveText(vol.display + " · " + FX.closed.feed_label);
  await expect(page.locator("#hVolKv")).toHaveClass(/stale/);
  await expect(page.locator("#hVol")).toHaveText(FX.closed.spot_disp);
  await expect(page.locator("#hVolChg")).toHaveText(FX.closed.chg_pct_text);
  await expect(page.locator("#hVolKv")).toHaveAttribute(
    "title",
    [FX.closed.outage, "last trade " + FX.closed.trade_time_ct, FX.closed.trade_age_text].join(
      " · ",
    ),
  );
  // INDUCED: the push stops (the socket sends nothing more). The header says OFFLINE, here too;
  // the value stands with its trade time and no age: the last age served is not the age now
  await page.clock.runFor(4500);
  await expect(page.locator("#hFeed")).toHaveText("OFFLINE");
  await expect(page.locator("#hVolName")).toHaveText(vol.display + " · OFFLINE");
  await expect(page.locator("#hVolKv")).toHaveClass(/stale/);
  await expect(page.locator("#hVol")).toHaveText(FX.closed.spot_disp);
  await expect(page.locator("#hVolKv")).toHaveAttribute(
    "title",
    "last trade " + FX.closed.trade_time_ct,
  );
  // its own row ends it
  sock.send({ type: "quotes", rows: [FX.live] });
  await expect(page.locator("#hVolName")).toHaveText(vol.display);
  await expect(page.locator("#hVol")).toHaveText(FX.live.spot_disp);
  await expect(page.locator("#hVolKv")).not.toHaveClass(/stale/);
  expect(errs).toEqual([]);
});

test("the volatility index stays whole at every width the browser tests use: on one line, inside the header, beside the writer's line", async ({
  page,
}) => {
  await holdClock(page);
  const sock = await program(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(sock.asked).toBeGreaterThan(0);
  // its widest state (a word beside its name), beside the header's longest value
  sock.send({ type: "feed", feed: FX.beat, rows: [FX.closed, SPY] });
  await expect(page.locator("#hRecord")).toHaveText(FX.beat.writer.line);
  await expect(page.locator("#hVol")).toHaveText(FX.closed.spot_disp);
  for (const width of [900, 1280, 1500, 1600, 1672, 1920, 2560]) {
    await page.setViewportSize({ width: width, height: 900 });
    const m = await page.evaluate(() => {
      const box = (el) => el.getBoundingClientRect();
      // how many lines an element's text takes: its height over its line height
      const lines = (el) => box(el).height / parseFloat(getComputedStyle(el).lineHeight);
      const head = box(document.querySelector("header"));
      const cell = box(document.getElementById("hVolKv"));
      return {
        inside:
          cell.left >= head.left &&
          cell.right <= head.right &&
          cell.top >= head.top &&
          cell.bottom <= head.bottom,
        name: lines(document.getElementById("hVolName")),
        value: lines(document.getElementById("hVol").parentElement),
      };
    });
    expect(m.inside, "inside the header at " + width).toBe(true);
    expect(m.name, "the name's lines at " + width).toBeLessThan(1.5);
    expect(m.value, "the value's lines at " + width).toBeLessThan(1.5);
  }
});
