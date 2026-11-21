/*
 * The header is one, the same on every page (docs/DATA_FLOW.md §6, decision 11). Row 1: the
 * selected ticker's price row and the program's status words. Row 2: the market context's three
 * price rows and the news line, which gives way to the alert line. Each value is drawn from its
 * one served producer, and what the socket sends here is the program's own:
 * fixtures/header_volatility.json (held by tests/test_data_path_header_volatility_v1.py: the
 * daemon's beats, and its rows for Schwab's $VIX, $SPX and $NDX messages of 2026-11-20, in
 * regular hours, once Schwab marked the indexes Closed, and with the daemon's Schwab socket not
 * open) and fixtures/header_news.json (held by tests/test_data_path_header_news_v1.py: the news
 * line for Schwab's headlines of 2026-11-20 at three moments). SPY's row is the daemon's of
 * 2026-10-23 (fixtures/price_rows_live.json): captures of other days, not received together.
 * STAND-IN: the program's socket, which answers each subscribe with what each symbol is and
 * sends a frame when the test says. Any page error fails the test.
 */
const { test, expect } = require("@playwright/test");
const { served } = require("./fixtures/price_socket");
const { holdClock } = require("./fixtures/settled");
const { eachPage } = require("./fixtures/pages");
const FX = require("./fixtures/header_volatility.json");
const NEWS = require("./fixtures/header_news.json");
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

// a beat as the program sends it: its status, a row for each symbol, and the news line on the
// beats that carry it
const beat = (feed, rows, news) =>
  Object.assign({ type: "feed", feed: feed, rows: rows }, news ? { news: news } : {});
// the market context as the page was served it, the volatility index marked
const marketContext = (page) => page.evaluate(() => window.EdShell.marketContext());
// row 2's cell of a market-context row
const cellOf = (page, context, row) =>
  page.locator("#hMk" + context.filter((c) => c.key === row.ticker)[0].display);
// row 2's line as drawn, its first copy: each item's parts by their class, in the order drawn
// (t the time, g the symbols or what an alert is about, h the sentence, s the source)
const lineItems = (page) =>
  page
    .locator("#hTape .htrack > .hni")
    .evaluateAll((els) =>
      els.map((el) =>
        Object.fromEntries(Array.from(el.children, (c) => [c.className, c.textContent])),
      ),
    );
// a news frame's items as the line draws them: every story Schwab's headlines of 2026-11-20
// gave the line has a time and a source
const drawn = (news) =>
  news.items.map((n) => ({ t: n.time_ct, g: n.symbols_text, h: n.headline, s: n.source }));
// an alert as the line draws it: what it is about and the sentence, no time and no source
const alert = (about, sentence) => ({ g: about, h: sentence });
// INDUCED: what the program left out, as live_ui.left_out_line words it
const LEFT_OUT = {
  line: "3 records not applied · 1 page frames refused",
  why: "counted since the program started; each is in the daemon's log with what arrived",
  cls: "neg",
};
// INDUCED: the longest line it words, all three counts: no face leaves row 1 the room for it in
// a 1,280 or a 1,440-wide window
const LEFT_OUT_LONGEST = Object.assign({}, LEFT_OUT, {
  line: "12 records not applied · 4 reprices failed · 2 page frames refused",
});

test("row 1 draws the selected ticker's row and the beat's status words, each from its served field; \"-\" before they arrive", async ({
  page,
}) => {
  const errs = pageErrors(page);
  await holdClock(page);
  const sock = await program(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(sock.asked).toBeGreaterThan(0);
  for (const id of ["hPx", "hChgReg", "hChg", "hRecord", "hSignIn"])
    await expect(page.locator("#" + id)).toHaveText("-");
  await expect(page.locator("#hRecord")).toHaveClass(/none/);
  await expect(page.locator("#hLeftOutKv")).toBeHidden();
  sock.send(beat(FX.beat, [SPY, ...FX.market_live], NEWS.morning));
  await expect(page.locator("#hSym")).toHaveText("SPY");
  await expect(page.locator("#hPx")).toHaveText(SPY.spot_disp);
  // Schwab's two change percents, each beside its label
  await expect(page.locator(".hpair.chgs .k")).toHaveText(["Reg", "Ext"]);
  await expect(page.locator("#hChgReg")).toHaveText(SPY.chg_pct_regular_text);
  await expect(page.locator("#hChgReg")).toHaveClass(/neg/);
  await expect(page.locator("#hChg")).toHaveText(SPY.chg_pct_text);
  await expect(page.locator("#hBidAsk")).toHaveText(SPY.bid_text + " × " + SPY.ask_text);
  await expect(page.locator("#hBidAsk")).toHaveAttribute("title", "quote " + SPY.quote_time_ct);
  // the trade's time and age stand beside the price they describe
  await expect(page.locator("#hAge")).toHaveText(SPY.trade_time_ct + " · " + SPY.trade_age_text);
  await expect(page.locator("#hAge")).toHaveClass("v");
  // each status is the program's one word; its whole line is the title
  await expect(page.locator("#hFeed")).toHaveText(SPY.feed_label);
  await expect(page.locator("#hFeed")).toHaveClass("hword");
  await expect(page.locator("#hRecord")).toHaveText(FX.beat.writer.word);
  await expect(page.locator("#hRecord")).toHaveAttribute("title", FX.beat.writer.line);
  await expect(page.locator("#hRecord")).not.toHaveClass(/neg|none/);
  await expect(page.locator("#hSignIn")).toHaveText(FX.beat.sign_in.word);
  await expect(page.locator("#hSignIn")).toHaveAttribute("title", FX.beat.sign_in.why);
  await expect(page.locator("#hSignIn")).not.toHaveClass(/neg|none/);
  await expect(page.locator("#hLeftOutKv")).toBeHidden();
  await expect(page.locator("#hSession")).toHaveText("RTH");
  await expect(page.locator("#hClock")).toHaveText(FX.beat.clock_ct);
  await expect(page.locator("#hClockDate")).toHaveText(FX.beat.day_ct);
  expect(errs).toEqual([]);
});

test('row 2 draws the market context from its served rows, the volatility index first, "-" until a row arrives; the Desk draws the same rows', async ({
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
  const context = await marketContext(page);
  expect(context.map((c) => c.key)).toEqual(FX.market_live.map((r) => r.ticker));
  const vol = context.filter((c) => c.volatility)[0];
  expect(vol.key).toBe(FX.live.ticker);
  // one cell for each symbol the server names, under its served display name; no row has
  // arrived: "-", no change, no time
  await expect(page.locator("#hMarket .hmk")).toHaveCount(context.length);
  for (const c of context) {
    const cell = page.locator("#hMk" + c.display);
    await expect(cell.locator(".k")).toHaveText(c.display);
    await expect(cell.locator(".mp")).toHaveText("-");
    await expect(cell.locator(".mc")).toHaveText("");
    await expect(cell.locator(".mt")).toHaveText("");
    await expect(cell).not.toHaveAttribute("title", /./);
  }
  const lefts = await page
    .locator("#hMarket .hmk")
    .evaluateAll((els) => els.map((el) => [el.id, el.getBoundingClientRect().left]));
  expect(lefts.every((c) => c[0] === "hMk" + vol.display || c[1] > lefts[2][1])).toBe(true);
  expect(lefts[2][0]).toBe("hMk" + vol.display);
  sock.send({ type: "quotes", rows: [...FX.market_live, SPY] });
  for (const row of FX.market_live) {
    const cell = cellOf(page, context, row);
    await expect(cell.locator(".mp")).toHaveText(row.spot_disp);
    await expect(cell.locator(".mp")).toBeVisible();
    await expect(cell.locator(".mc")).toHaveText(row.chg_pct_text);
    await expect(cell.locator(".mc")).toBeVisible();
    await expect(cell.locator(".mc")).toHaveClass(row.chg_pct < 0 ? /neg/ : /pos/);
    await expect(cell.locator(".mt")).toHaveText(""); // live: its time is not on the cell
    await expect(cell).not.toHaveClass(/stale/);
  }
  // one row, two consumers: the Desk's Volatility card and its index strip draw the same values
  await expect(page.locator("#tdmCardVol")).toContainText(
    FX.live.spot_disp + " (" + FX.live.chg_pct_text + ") · last trade " + FX.live.trade_time_ct,
  );
  await expect(page.locator("#tdmIdx" + vol.display)).toContainText(FX.live.spot_disp);
  // the index's next row, with no row of the selected ticker after it: all three draw it, and
  // the Desk's two mark it as the header's cell does (tests/e2e/console-trade-desk.spec.js)
  sock.send({ type: "quotes", rows: FX.market_closed });
  await expect(cellOf(page, context, FX.closed).locator(".mp")).toHaveText(FX.closed.spot_disp);
  await expect(page.locator("#tdmIdx" + vol.display)).toContainText(FX.closed.spot_disp);
  await expect(page.locator("#tdmCardVol")).toContainText(
    FX.closed.spot_disp +
      " (" +
      FX.closed.chg_pct_text +
      ") · " +
      FX.closed.feed_label +
      " · last trade " +
      FX.closed.trade_time_ct +
      " · " +
      FX.closed.trade_age_text,
  );
  expect(errs).toEqual([]);
});

test("the header is one and the same on every page: each workspace and view shows the same header, the market context and the news in it", async ({
  page,
}) => {
  const errs = pageErrors(page);
  await holdClock(page); // no timer of the page runs, so the push never reads silent on the way
  const sock = await program(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(sock.asked).toBeGreaterThan(0);
  sock.send(beat(FX.beat, [SPY, ...FX.market_live], NEWS.morning));
  await expect(page.locator("#hClock")).toHaveText(FX.beat.clock_ct);
  await expect(page.locator("#hPx")).toHaveText(SPY.spot_disp);
  await expect(page.locator("#hTape .htrack > .hni")).toHaveCount(NEWS.morning.items.length);
  await expect(page.locator("header")).toHaveCount(1);
  const header = () => page.evaluate(() => document.querySelector("header").outerHTML);
  const first = await header();
  for (const row of FX.market_live) expect(first).toContain(">" + row.spot_disp + "<");
  expect(first).toContain(">" + NEWS.morning.items[0].source + "<");
  const walked = [];
  const workspaces = await eachPage(page, async ({ ws, sub, view }) => {
    // a workspace as it opens is a page too, with or without a view to open
    const where = [ws, sub, view].filter(Boolean).join(" > ");
    expect(await header(), where).toBe(first);
    walked.push(where);
  });
  // every workspace the shell lists was walked
  expect([...new Set(walked.map((w) => w.split(" > ")[0]))]).toEqual(workspaces);
  expect(errs).toEqual([]);
});

test("a stopped index stands marked with its time and age; the push silent, the header reads OFFLINE, the times have no age and the line says so", async ({
  page,
}) => {
  const errs = pageErrors(page);
  await holdClock(page); // the page's timers run when the test moves its time
  const sock = await program(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(sock.asked).toBeGreaterThan(0);
  const context = await marketContext(page);
  // Schwab marked the indexes Closed: each last value stands dimmed, its trade time and age
  // beside it, and why is its title
  sock.send(beat(FX.beat_closed, [...FX.market_closed, SPY], NEWS.morning));
  await expect(page.locator("#hClock")).toHaveText(FX.beat_closed.clock_ct);
  await expect(page.locator("#hSession")).toHaveText("AH");
  for (const row of FX.market_closed) {
    const cell = cellOf(page, context, row);
    await expect(cell).toHaveClass(/stale/);
    await expect(cell.locator(".mp")).toHaveText(row.spot_disp);
    await expect(cell.locator(".mc")).toHaveText(row.chg_pct_text);
    await expect(cell.locator(".mt")).toHaveText(row.trade_time_ct + " · " + row.trade_age_text);
    await expect(cell.locator(".mt")).toBeVisible();
    await expect(cell).toHaveAttribute("title", row.outage);
  }
  await expect(page.locator("#hLineLabel")).toHaveText("News");
  // INDUCED: the push stops (the socket sends nothing more). The header says OFFLINE; each
  // value stands with its trade time and no age (the last age served is not the age now); the
  // line says the push is down, in the news' place
  await page.clock.runFor(4500);
  await expect(page.locator("#hFeed")).toHaveText("OFFLINE");
  await expect(page.locator("#hFeed")).toHaveClass(/neg/);
  await expect(page.locator("#hPx")).toHaveText(SPY.spot_disp);
  await expect(page.locator("#hAge")).toHaveText(SPY.trade_time_ct);
  await expect(page.locator("#hAge")).toHaveClass(/stale/);
  for (const row of FX.market_closed) {
    const cell = cellOf(page, context, row);
    await expect(cell).toHaveClass(/stale/);
    await expect(cell.locator(".mp")).toHaveText(row.spot_disp);
    await expect(cell.locator(".mt")).toHaveText(row.trade_time_ct);
    await expect(cell).toHaveAttribute("title", "live push down");
  }
  await expect(page.locator("#hLineLabel")).toHaveText("Alert");
  await expect(page.locator("#hLine")).toHaveClass(/alert/);
  expect(await lineItems(page)).toEqual([alert("Feed", "live push down")]);
  // the next beat ends it: the rows are live, and the news it held is back
  sock.send(beat(FX.beat, [...FX.market_live, SPY]));
  await expect(page.locator("#hFeed")).toHaveText(SPY.feed_label);
  await expect(page.locator("#hFeed")).toHaveClass("hword");
  await expect(page.locator("#hAge")).toHaveText(SPY.trade_time_ct + " · " + SPY.trade_age_text);
  for (const row of FX.market_live) {
    const cell = cellOf(page, context, row);
    await expect(cell).not.toHaveClass(/stale/);
    await expect(cell.locator(".mt")).toHaveText("");
  }
  await expect(page.locator("#hLineLabel")).toHaveText("News");
  await expect(page.locator("#hLine")).not.toHaveClass(/alert/);
  expect(await lineItems(page)).toEqual(drawn(NEWS.morning));
  expect(errs).toEqual([]);
});

test("what is wrong takes the news' place on row 2, each the program's own sentence: Schwab's connection, the recorder, the sign-in, and all at once", async ({
  page,
}) => {
  const errs = pageErrors(page);
  await holdClock(page);
  const sock = await program(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(sock.asked).toBeGreaterThan(0);
  // an index is the selected ticker, so row 1's price row is one of the daemon's own for the
  // same instants as the beats
  await page.evaluate(() => window.EdShell.setTicker("SPX"));
  await expect.poll(sock.asked).toBeGreaterThan(1);
  const context = await marketContext(page);
  const spx = (rows) => rows.filter((r) => r.ticker === "$SPX")[0];
  sock.send(beat(FX.beat, FX.market_live, NEWS.morning));
  await expect(page.locator("#hPx")).toHaveText(spx(FX.market_live).spot_disp);
  await expect(page.locator("#hLineLabel")).toHaveText("News");
  expect(await lineItems(page)).toEqual(drawn(NEWS.morning));
  // Schwab's connection is down: the daemon's own words on the line, the feed word marked, and
  // each row OFFLINE with its last value, its time and why
  sock.send(beat(FX.beat_down, FX.market_down));
  await expect(page.locator("#hFeed")).toHaveText(spx(FX.market_down).feed_label);
  await expect(page.locator("#hFeed")).toHaveClass(/neg/);
  await expect(page.locator("#hPx")).toHaveText(spx(FX.market_down).spot_disp);
  await expect(page.locator("#hAge")).toHaveAttribute("title", spx(FX.market_down).outage);
  await expect(page.locator("#hLineLabel")).toHaveText("Alert");
  await expect(page.locator("#hLineLabel")).not.toHaveAttribute("title", /./);
  expect(await lineItems(page)).toEqual([alert("Feed", FX.beat_down.schwab_down)]);
  for (const row of FX.market_down) {
    const cell = cellOf(page, context, row);
    await expect(cell).toHaveClass(/stale/);
    await expect(cell.locator(".mp")).toHaveText(row.spot_disp);
    await expect(cell.locator(".mt")).toHaveText(row.trade_time_ct + " · " + row.trade_age_text);
    await expect(cell).toHaveAttribute("title", row.outage);
  }
  // the recorder is not recording: its word marked in its cell, its whole line on the line
  sock.send(beat(FX.beat_not_recording, FX.market_live));
  await expect(page.locator("#hFeed")).toHaveClass("hword");
  await expect(page.locator("#hRecord")).toHaveText(FX.beat_not_recording.writer.word);
  await expect(page.locator("#hRecord")).toHaveClass(/neg/);
  await expect(page.locator("#hRecord")).toHaveAttribute(
    "title",
    FX.beat_not_recording.writer.line,
  );
  expect(await lineItems(page)).toEqual([alert("Record", FX.beat_not_recording.writer.line)]);
  // Schwab refuses the sign-in: REFUSED in its cell, what to run and Schwab's reason on the line
  const refused = FX.beat_refused.sign_in;
  sock.send(beat(FX.beat_refused, FX.market_live));
  await expect(page.locator("#hRecord")).toHaveText(FX.beat.writer.word);
  await expect(page.locator("#hRecord")).not.toHaveClass(/neg/);
  await expect(page.locator("#hSignIn")).toHaveText(refused.word);
  await expect(page.locator("#hSignIn")).toHaveClass(/neg/);
  await expect(page.locator("#hSignIn")).toHaveAttribute("title", refused.why);
  expect(await lineItems(page)).toEqual([
    alert("Schwab sign-in", refused.line + " · " + refused.why),
  ]);
  // INDUCED: all three at once, and the longest left-out line: each on the line, in that order.
  // This window (1,280 wide) has no room in row 1 for that sentence in any face, so its cell
  // draws its dot and the sentence stands last on the line
  const all = Object.assign({}, FX.beat_down, {
    writer: FX.beat_not_recording.writer,
    sign_in: refused,
    left_out: LEFT_OUT_LONGEST,
  });
  sock.send(beat(all, FX.market_down));
  await expect
    .poll(async () => (await lineItems(page)).map((i) => i.g))
    .toEqual(["Feed", "Record", "Schwab sign-in", "Left out"]);
  expect((await lineItems(page))[3]).toEqual(alert("Left out", LEFT_OUT_LONGEST.line));
  await expect(page.locator("#hLeftOutKv")).toBeVisible();
  await expect(page.locator("#hLeftOut")).toHaveText(LEFT_OUT_LONGEST.line);
  await expect(page.locator("#hLeftOut")).toHaveAttribute(
    "title",
    LEFT_OUT_LONGEST.line + " · " + LEFT_OUT_LONGEST.why,
  );
  await expect(page.locator("#hLeftOut")).toHaveClass(/\bneg\b/);
  // INDUCED: the same alerts with a newer sentence are written in place, in both copies of the
  // line (it is longer than its room here, so it runs); the line is not drawn again, so one in
  // motion keeps its place
  const track = await page.locator("#hTape .htrack").elementHandle();
  const later = Object.assign({}, all.writer, { line: all.writer.line + " · and a second later" });
  sock.send(beat(Object.assign({}, all, { writer: later }), FX.market_down));
  const sentences = [
    FX.beat_down.schwab_down,
    later.line,
    refused.line + " · " + refused.why,
    LEFT_OUT_LONGEST.line,
  ];
  await expect(page.locator("#hTape .htrack > .hni .h")).toHaveText(sentences);
  await expect(page.locator('#hTape .htrack > [aria-hidden="true"] > .hni .h')).toHaveText(
    sentences,
  );
  expect(await track.evaluate((el) => el.isConnected)).toBe(true);
  // all is well again: the news returns, and nothing is left out
  sock.send(beat(FX.beat, FX.market_live));
  await expect(page.locator("#hLineLabel")).toHaveText("News");
  await expect(page.locator("#hLeftOutKv")).toBeHidden();
  expect(await lineItems(page)).toEqual(drawn(NEWS.morning));
  expect(errs).toEqual([]);
});

test("the news line draws each story's served time, symbols, headline and source, newest first; it runs at a steady speed, rests under the pointer, starts again when a story comes and stands still when asked", async ({
  page,
}) => {
  const errs = pageErrors(page);
  await holdClock(page);
  const sock = await program(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(sock.asked).toBeGreaterThan(0);
  // no story held yet: "-", standing
  await expect(page.locator("#hTape .htrack")).toHaveText("-");
  await expect(page.locator("#hTape .htrack")).toHaveClass(/still/);
  sock.send(beat(FX.beat, [SPY, ...FX.market_live], NEWS.morning));
  await expect(page.locator("#hLineLabel")).toHaveText("News");
  await expect(page.locator("#hLineLabel")).toHaveAttribute("title", NEWS.morning.left_out);
  expect(await lineItems(page)).toEqual(drawn(NEWS.morning));
  // longer than its room, it runs: a second copy follows the first, out of the accessibility
  // tree, and one copy's width passes at the drawing module's speed whatever the line holds
  const run = () =>
    page.locator("#hTape").evaluate((tape) => {
      const track = tape.firstChild,
        cs = getComputedStyle(track);
      return {
        name: cs.animationName,
        state: cs.animationPlayState,
        seconds: parseFloat(cs.animationDuration),
        speed: track.scrollWidth / 2 / parseFloat(cs.animationDuration),
        copies: track.querySelectorAll(".hni").length,
        hidden: track.querySelectorAll('[aria-hidden="true"] .hni').length,
        fits: track.scrollWidth / 2 <= tape.clientWidth,
      };
    });
  const morning = await run();
  expect(morning.fits).toBe(false);
  expect([morning.name, morning.state]).toEqual(["htape", "running"]);
  expect([morning.copies, morning.hidden]).toEqual([30, 15]);
  expect(morning.speed).toBeCloseTo(50, 0);
  // it rests while the pointer is on it
  await page.locator("#hTape").hover();
  expect((await run()).state).toBe("paused");
  await page.locator("#hSym").hover();
  expect((await run()).state).toBe("running");
  // a beat that carries no news leaves the line as it is drawn
  const track = await page.locator("#hTape .htrack").elementHandle();
  sock.send(beat(FX.beat, [SPY, ...FX.market_live]));
  await expect(page.locator("#hClock")).toHaveText(FX.beat.clock_ct);
  expect(await track.evaluate((el) => el.isConnected)).toBe(true);
  // a newer story: the line is drawn again from its start, the story first
  sock.send(beat(FX.beat, [SPY, ...FX.market_live], NEWS.story));
  await expect(page.locator("#hTape .htrack > .hni .h").first()).toHaveText(
    NEWS.story.items[0].headline,
  );
  expect(await track.evaluate((el) => el.isConnected)).toBe(false);
  expect(await lineItems(page)).toEqual(drawn(NEWS.story));
  expect((await run()).speed).toBeCloseTo(50, 0);
  // Schwab withdrew it: it is gone from the line
  sock.send(beat(FX.beat, [SPY, ...FX.market_live], NEWS.withdrawn));
  await expect(page.locator("#hTape .htrack > .hni .h").first()).toHaveText(
    NEWS.withdrawn.items[0].headline,
  );
  expect((await lineItems(page)).map((i) => i.h)).not.toContain(NEWS.story.items[0].headline);
  // asked for less motion, it stands still
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect((await run()).name).toBe("none");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  // a line that fits its room stands: one copy, no motion (INDUCED: the first story alone)
  const one = { items: NEWS.morning.items.slice(0, 1), left_out: NEWS.morning.left_out };
  await page.setViewportSize({ width: 2560, height: 900 });
  sock.send(beat(FX.beat, [SPY, ...FX.market_live], one));
  await expect(page.locator("#hTape .htrack > .hni")).toHaveCount(1);
  await expect(page.locator("#hTape .htrack")).toHaveClass(/still/);
  expect((await run()).copies).toBe(1);
  // no story held: "-"
  sock.send(beat(FX.beat, [SPY, ...FX.market_live], { items: [], left_out: one.left_out }));
  await expect(page.locator("#hTape .htrack")).toHaveText("-");
  expect(errs).toEqual([]);
});

// What the header holds at its fullest in each state. The selected ticker is SPX, so row 1's
// price row is the daemon's own for the same instants as the beats and the market's rows.
const STATES = {
  "regular hours": beat(FX.beat, FX.market_live, NEWS.morning),
  "the indexes closed": beat(FX.beat_closed, FX.market_closed, NEWS.morning),
  // INDUCED: something left out, all else well
  "something left out": beat(
    Object.assign({}, FX.beat, { left_out: LEFT_OUT }),
    FX.market_live,
    NEWS.morning,
  ),
  // INDUCED: every alert at once and something left out
  "everything wrong": beat(
    Object.assign({}, FX.beat_down, {
      writer: FX.beat_not_recording.writer,
      sign_in: FX.beat_refused.sign_in,
      left_out: LEFT_OUT,
    }),
    FX.market_down,
  ),
};
// what each state's alert line says is wrong, before what was left out
const WRONG = {
  "regular hours": [],
  "the indexes closed": [],
  "something left out": [],
  "everything wrong": ["Feed", "Record", "Schwab sign-in"],
};
// The page with SPX selected, its socket answering.
async function onSpx(page) {
  const sock = await program(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(sock.asked).toBeGreaterThan(0);
  await page.evaluate(() => window.EdShell.setTicker("SPX"));
  await expect.poll(sock.asked).toBeGreaterThan(1);
  return sock;
}
// One of those states sent, and drawn: its clock, its recorder's word and SPX's price (each
// state differs from the one before it in one of them).
async function drawState(page, sock, frame) {
  sock.send(frame);
  if (frame.feed.left_out)
    await expect(page.locator("#hLeftOut")).toHaveText(frame.feed.left_out.line);
  else await expect(page.locator("#hLeftOutKv")).toBeHidden();
  await expect(page.locator("#hClock")).toHaveText(frame.feed.clock_ct);
  await expect(page.locator("#hRecord")).toHaveText(frame.feed.writer.word);
  await expect(page.locator("#hPx")).toHaveText(
    frame.rows.filter((r) => r.ticker === "$SPX")[0].spot_disp,
  );
}

// The faces the header is drawn in: the console's own, and its fallback. INDUCED: a machine with
// none of the console's own faces, as the Linux runner is, draws the header in the fallback, a
// wide system face scaled to their width (index.html), so the layout is held on both.
const FACES = [
  { name: "the console's own face", draw: async () => {} },
  {
    name: "the fallback face",
    draw: async (page) => {
      await page.addStyleTag({ content: ':root{--ed-faces:"a face no machine has"}' });
      // the header's text is drawn in the fallback: the browser loads a face only to draw with it
      await expect
        .poll(() =>
          page.evaluate(() =>
            Array.from(document.fonts)
              .filter((f) => f.family.includes("Ed Header Fallback"))
              .map((f) => f.status),
          ),
        )
        .toContain("loaded");
    },
  },
];

test("at every window width the browser tests use the header is 82 px tall, no value in it wraps and nothing leaves it; at a narrow one the search box is its icon and still takes a symbol", async ({
  page,
}) => {
  const errs = pageErrors(page);
  await holdClock(page);
  const sock = await onSpx(page);
  for (const face of FACES) {
    await face.draw(page);
    for (const [state, frame] of Object.entries(STATES)) {
      await drawState(page, sock, frame);
      for (const width of [1280, 1440, 1500, 1672, 1920, 2560]) {
        await page.setViewportSize({ width: width, height: 900 });
        const m = await page.evaluate(() => {
          const head = document.querySelector("header").getBoundingClientRect();
          const outside = [],
            over = [],
            wrapped = [],
            undrawn = [];
          const cells = (row) =>
            Array.from(document.querySelectorAll(row)).filter((el) => el.getClientRects().length);
          // each cell of both rows lies inside the header, and none lies over the next
          for (const row of [".hrow1 > *", ".hrow2 > *", "#hMarket > *"]) {
            const boxes = cells(row)
              .map((el) => [el.id || el.className, el.getBoundingClientRect()])
              .sort((a, b) => a[1].left - b[1].left);
            boxes.forEach(([name, b], i) => {
              if (
                b.left < head.left - 0.5 ||
                b.right > head.right + 0.5 ||
                b.top < head.top - 0.5 ||
                b.bottom > head.bottom + 0.5
              )
                outside.push(name);
              if (i && b.left < boxes[i - 1][1].right - 0.5) over.push(name);
            });
          }
          // each text of rows 1 and 2 (the line apart, which runs) is drawn, on one line: a
          // text that wrapped lies in line boxes at more than one height
          const range = document.createRange();
          document.querySelectorAll(".hrow1 *, #hMarket *, #hLineLabel").forEach((el) => {
            const texts = Array.from(el.childNodes).filter(
              (n) => n.nodeType === 3 && n.textContent.trim(),
            );
            if (!texts.length || el.closest("[hidden]")) return;
            const name = el.id || el.textContent;
            if (!el.getClientRects().length) return undrawn.push(name);
            for (const text of texts) {
              range.selectNodeContents(text);
              const tops = Array.from(range.getClientRects()).map((r) => Math.round(r.top));
              if (new Set(tops).size > 1) wrapped.push(name);
            }
          });
          // what was left out: its sentence whole beside its dot, or not at all
          const lo = document.getElementById("hLeftOut");
          range.selectNodeContents(lo);
          const box = lo.getBoundingClientRect(),
            words = range.getBoundingClientRect();
          return {
            height: head.height,
            outside: outside,
            over: over,
            wrapped: wrapped,
            undrawn: undrawn,
            leftOut: !box.width
              ? "not shown"
              : words.top >= box.bottom - 0.5
                ? "its dot alone"
                : words.top >= box.top - 0.5 &&
                    words.bottom <= box.bottom + 0.5 &&
                    words.right <= box.right + 0.5
                  ? "whole"
                  : "cut",
          };
        });
        const where = face.name + ", " + state + " at " + width;
        expect(m.height, where).toBe(82);
        expect(m.outside, where).toEqual([]);
        expect(m.over, where).toEqual([]);
        expect(m.wrapped, where).toEqual([]);
        expect(m.undrawn, where).toEqual([]);
        // what was left out is readable at every width, in either face: whole in its cell, or,
        // where row 1 has no room for it, its dot alone in the cell, never a part of a count,
        // and the sentence on the alert line after the others. Which it is depends on the room
        // the face leaves; the widest window has it in any face
        const forms = !frame.feed.left_out
          ? ["not shown"]
          : width === 2560
            ? ["whole"]
            : ["whole", "its dot alone"];
        expect(forms, where).toContain(m.leftOut);
        const noRoom = m.leftOut === "its dot alone";
        const wrong = WRONG[state].concat(noRoom ? ["Left out"] : []);
        await expect(page.locator("#hLineLabel"), where).toHaveText(
          wrong.length ? "Alert" : "News",
        );
        if (wrong.length) {
          await expect
            .poll(async () => (await lineItems(page)).map((i) => i.g), where)
            .toEqual(wrong);
          if (noRoom)
            expect((await lineItems(page)).pop(), where).toEqual(alert("Left out", LEFT_OUT.line));
        } else expect(await lineItems(page), where).toEqual(drawn(NEWS.morning));
      }
    }
    // INDUCED: the longest line the producer words, all three counts, all else well. A 1,280
    // and a 1,440-wide window have no room for it in row 1 in either face: the cell draws its
    // dot alone and the alert line carries the sentence whole, in the news' place
    await drawState(
      page,
      sock,
      beat(Object.assign({}, FX.beat, { left_out: LEFT_OUT_LONGEST }), FX.market_live),
    );
    for (const width of [1280, 1440]) {
      await page.setViewportSize({ width: width, height: 900 });
      const where = face.name + ", the longest left-out line at " + width;
      await expect
        .poll(() => lineItems(page), where)
        .toEqual([alert("Left out", LEFT_OUT_LONGEST.line)]);
      await expect(page.locator("#hLineLabel"), where).toHaveText("Alert");
      // its words are wrapped out of the cell's one line, whole
      expect(
        await page.locator("#hLeftOut").evaluate((el) => el.scrollHeight > el.clientHeight),
        where,
      ).toBe(true);
    }
  }
  await expect(page.locator("#hLeftOut")).toHaveAttribute(
    "title",
    LEFT_OUT_LONGEST.line + " · " + LEFT_OUT_LONGEST.why,
  );
  // a narrow window: the search box draws as its icon, and opens to take a symbol
  await page.setViewportSize({ width: 1280, height: 900 });
  expect(await page.locator(".search").evaluate((el) => el.getBoundingClientRect().width)).toBe(30);
  await page.locator("#symSearch").fill("nflx");
  expect(await page.locator("#symSearch").evaluate((el) => el.getBoundingClientRect().width)).toBe(
    240,
  );
  await page.locator("#symSearch").press("Enter");
  await expect(page.locator("#hSym")).toHaveText("NFLX");
  // a wide one: the box itself
  await page.setViewportSize({ width: 1920, height: 900 });
  expect(await page.locator(".search").evaluate((el) => el.getBoundingClientRect().width)).toBe(
    200,
  );
  expect(errs).toEqual([]);
});

// the contrast of two colours, each [r, g, b] in 0..255 (WCAG 2.1 relative luminance)
function contrast(a, b) {
  const lum = (c) =>
    c
      .map((v) => v / 255)
      .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
      .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// Every text a state is known to draw, from what was served: row 1's values of SPX's row and the
// beat, each market cell's name, price, change and, not live, its time and age, the search box's
// placeholder, and the line's sentences: what is wrong while it is `alerting`, the news otherwise.
function knownTexts(frame, alerting) {
  const feed = frame.feed,
    spx = frame.rows.filter((r) => r.ticker === "$SPX")[0];
  const when = (row) => row.trade_time_ct + " · " + row.trade_age_text;
  const row1 = [
    "SPX",
    spx.spot_disp,
    spx.chg_pct_regular_text,
    spx.chg_pct_text,
    spx.bid_text + " × " + spx.ask_text,
    when(spx),
    spx.feed_label,
    feed.writer.word,
    feed.sign_in.word,
    { RTH: "RTH", "After-Hours": "AH" }[feed.session],
    feed.day_ct,
    feed.clock_ct,
  ].concat(feed.left_out ? [feed.left_out.line] : []);
  const market = frame.rows.flatMap((row) =>
    [row.ticker.replace(/^\$/, ""), row.spot_disp, row.chg_pct_text].concat(
      row.feed_live ? [] : [when(row)],
    ),
  );
  const wrong = []
    .concat(feed.schwab_down != null ? ["Feed", feed.schwab_down] : [])
    .concat(feed.writer.cls === "neg" ? ["Record", feed.writer.line] : [])
    .concat(
      feed.sign_in.cls === "neg"
        ? ["Schwab sign-in", feed.sign_in.line + " · " + feed.sign_in.why]
        : [],
    );
  const line = alerting
    ? wrong.concat(feed.left_out ? ["Left out"] : [])
    : drawn(frame.news).flatMap((item) => Object.values(item));
  return row1.concat(market, ["Search symbol"], line);
}

test("in both themes every text in the header reads against its background at 4.5 to 1 or better, in regular hours, with the indexes closed and with everything wrong", async ({
  page,
}) => {
  const errs = pageErrors(page);
  await holdClock(page);
  await page.setViewportSize({ width: 1920, height: 900 }); // the search box shows its words
  const sock = await onSpx(page);
  for (const theme of ["dark", "light"]) {
    await page.evaluate((t) => window.EdShell.setTheme(t), theme);
    for (const [state, frame] of Object.entries(STATES)) {
      await drawState(page, sock, frame);
      // each element of the header that holds text of its own (and the search box's
      // placeholder): its colour as the browser paints it over the colour behind it, and that
      // colour (a canvas reads any CSS colour as red, green, blue)
      const texts = await page.evaluate(() => {
        const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
        const painted = (...colours) => {
          ctx.clearRect(0, 0, 1, 1);
          for (const css of colours) {
            ctx.fillStyle = css;
            ctx.fillRect(0, 0, 1, 1);
          }
          return Array.from(ctx.getImageData(0, 0, 1, 1).data);
        };
        const behind = (el) => {
          for (let e = el; e; e = e.parentElement) {
            const css = getComputedStyle(e).backgroundColor;
            if (painted(css)[3] === 255) return css;
          }
          return null;
        };
        const read = (text, ink, ground) => ({
          text: text.trim(),
          ink: painted(ground, ink).slice(0, 3),
          ground: painted(ground).slice(0, 3),
        });
        const out = [];
        document.querySelectorAll("header *").forEach((el) => {
          const own = Array.from(el.childNodes).some(
            (n) => n.nodeType === 3 && n.textContent.trim(),
          );
          if (!own || !el.getClientRects().length) return;
          out.push(read(el.textContent, getComputedStyle(el).color, behind(el)));
        });
        const box = document.getElementById("symSearch");
        out.push(read(box.placeholder, getComputedStyle(box, "::placeholder").color, behind(box)));
        return out;
      });
      // every text the state is known to draw is among those measured: row 1's values, each
      // market cell's, the search box's placeholder, and the line's alerts or news
      const measured = texts.map((t) => t.text);
      expect(measured).toContain("Search symbol");
      const alerting = (await page.locator("#hLineLabel").textContent()) === "Alert";
      for (const known of knownTexts(frame, alerting))
        expect(measured, theme + ", " + state).toContain(known);
      const faint = texts
        .map((t) => Object.assign(t, { ratio: contrast(t.ink, t.ground) }))
        .filter((t) => t.ratio < 4.5)
        .map((t) => theme + ", " + state + ": " + t.text.slice(0, 40) + " " + t.ratio.toFixed(2));
      expect(faint).toEqual([]);
    }
  }
  expect(errs).toEqual([]);
});
