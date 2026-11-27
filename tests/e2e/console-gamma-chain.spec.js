// @ts-check
/**
 * D — Options/Gamma "Chain" subview. Full vendor ladder from the socket's chain panel (calls left, puts right,
 * strike centre), served VERBATIM. Proves: single-expiry disclosure (B), exact CALL/PUT vendor-symbol
 * selection for the Flow panel, named to the console to stream (C), duplicate vendor rows retained
 * (D), and the centre strike selects only the shared strike. Symbols are the vendor's own, never
 * reconstructed.
 */
const { test, expect } = require("./fixtures/test");
const { expiriesAnswer, pushExpiries } = require("./fixtures/expiries");
const { expiriesFrame, priceRow, served: servedSymbol } = require("./fixtures/price_socket");
const { routeWatchlist } = require("./fixtures/watchlist");
// the strikes panel as the server sends it on CRWD's real chain (held to the server by
// tests/test_vanna_charm_by_strike_v1.py)
const REAL = require("./fixtures/vanna_charm_panels_crwd.json");
// SPY's chain panels at 10:30:41 ET on 2026-11-12, its front expiry and its second (held to the
// producer by tests/test_e2e_panels_two_day_v1.py)
const TWO_DAY = require("./fixtures/panels_spy_two_day.json");
const FRONT = TWO_DAY.chain;
const SECOND = TWO_DAY.chain_second_expiry;
// SPY's 2026-10-23 chain panel (its 2026-10-22 close capture) at the 761 call's first stored quote
// and at its last: the same rows, the call's values moved (held to the producer by
// tests/test_options_order_flow_production_v1.py)
const CHAINS = require("./fixtures/chain_panels_spy_tsla.json");
const FIRST = CHAINS.spy_call_first_quote;
const LAST = CHAINS.spy_call_last_quote;
const CALL_761 = "SPY   261023C00761000";

// the row of the strike nearest the spot, the one under it and the ladder's top
const SPOT_ROW = FRONT.ladder.findIndex((r) => r.spot);
const AT_SPOT = FRONT.ladder[SPOT_ROW];
const UNDER_SPOT = FRONT.ladder[SPOT_ROW + 1];
const TOP = FRONT.ladder[0];
// each row's strike as the ladder draws it
const strikes = (panel) => panel.ladder.map((r) => r.strike_text);
// the 761 call's volume as a panel serves it
const volume761 = (panel) => panel.ladder.find((r) => r.call.symbol === CALL_761).call.volume_text;
// the 761 call's volume cell on the drawn ladder
const volumeCell = (page) => page.locator('#chainBody tr[data-csym="' + CALL_761 + '"] td').nth(1);

//: each contract the page names to the console for the Flow panel (POST /api/flow-contract)
const flowPosts = [];

async function intercept(page) {
  await page.route("**/api/flow-contract", (route, request) => {
    const contract = JSON.parse(request.postData()).contract;
    flowPosts.push(contract);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, contract: contract }),
    });
  });
  await routeWatchlist(page, ["SPY"]);
  panels = chainPanels(() => FRONT);
  sock = await pushExpiries(page, [FRONT.expiry, SECOND.expiry], undefined, panels);
}
// the panels the page's socket sends this test: the chain panel `chainOf(expiry)` (each reader's
// expiry; null: the front one) as the program serves it, and the Gamma tab's own (a test may
// change one before the page opens); `sock` is the program's side of the socket
let panels, sock;
function chainPanels(chainOf) {
  return {
    chain: (key, params) => chainOf(params.expiry),
    bars: { available: false },
    tape: REAL.tape,
    terrain: REAL.terrain,
    strikes: REAL.strikes,
    surface: REAL.surface,
  };
}

async function toChain(page) {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("#subnav .tab", { hasText: "Chain" }).click();
  // the ladder now renders as two separate tables (header + body) so the header can genuinely
  // stick on scroll -- see ed-gamma-chain.js's chn-headwrap/chn-bodytbl split (2026-09-13).
  await expect(page.locator("#chainBody table.chn-bodytbl")).toBeVisible();
}

test.describe("D — Gamma Chain subview", () => {
  test.beforeEach(async ({ page }) => {
    await intercept(page);
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
    });
  });

  // AGENTS.md rule 4: what the chain screens say with no row to draw is the program's sentence
  // (push.chain none_said). INDUCED: SPY's chain answered unavailable, its sentence worded
  // otherwise
  test("a chain with no row says the program's sentence", async ({ page }) => {
    const said = "SERVED: chain unavailable — its reason";
    panels.chain = () =>
      Object.assign({}, FRONT, { status: "unavailable", ladder: [], none_said: said });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.locator("#subnav .tab", { hasText: "Chain" }).click();
    await expect(page.locator("#chainBody .placeholder")).toHaveText(said);
  });

  test("Chain swaps in the ladder + single-expiry disclosure; Gamma restores on switch back", async ({
    page,
  }) => {
    await toChain(page);
    await expect(page.locator('.sub-pane[data-sub-pane="gamma"]')).toBeHidden();
    await expect(page.locator("#chainBody tbody tr")).toHaveCount(FRONT.ladder.length);
    await expect(page.locator("#chainBody tbody tr").first().locator("td.k")).toHaveText(
      TOP.strike_text,
    );
    await expect(page.locator("#chainBody tbody tr.spot td.k")).toHaveText(AT_SPOT.strike_text);
    // each Greek drawn as served (every digit Schwab sent, never in exponent form): the call's
    // delta and gamma, then the put's gamma and delta, either side of the strike
    const cells = page.locator("#chainBody tbody tr.spot td");
    await expect(cells.nth(3)).toHaveText(AT_SPOT.call.delta_text);
    await expect(cells.nth(4)).toHaveText(AT_SPOT.call.gamma_text);
    await expect(cells.nth(10)).toHaveText(AT_SPOT.put.gamma_text);
    await expect(cells.nth(11)).toHaveText(AT_SPOT.put.delta_text);
    // B: single-expiry truth — the null filter is "Default Expiry", the ladder says SINGLE EXPIRY
    await expect(page.locator("#chainBody .chn-head")).toContainText(
      "SINGLE EXPIRY · " + FRONT.expiry,
    );
    await expect(page.locator("#chainBody .chn-head")).toContainText("server default");
    await expect(page.locator("#expSel option").first()).toHaveText("Default Expiry");
    await expect(page.locator("#chSrc .asof")).toContainText("complete (ALL)");
    await page.locator("#subnav .tab", { hasText: "Gamma" }).click();
    await expect(page.locator('.sub-pane[data-sub-pane="gamma"]')).toBeVisible();
    await expect(page.locator("#expSel option").first()).toHaveText("All Expirations"); // Gamma: null = all
  });

  test("the chain spot keeps its last trade time", async ({ page }) => {
    // the spot is the header's own row (one producer): Schwab's last trade the panels were made
    // with (757.075), its trade time and age
    await toChain(page);
    sock.quotes([priceRow("SPY", 757.075, { trade_time_ct: "Thu 11/12 09:30 AM CT" })]);
    await expect(page.locator("#chainBody .chn-head")).toContainText(
      "spot 757.08 · last trade Thu 11/12 09:30 AM CT · 1s",
    );
    await expect(page.locator("#hPx")).toHaveText("757.08");
  });

  test("CALL click selects the exact CALL vendor symbol; PUT click the exact PUT symbol, each named to stream", async ({
    page,
  }) => {
    flowPosts.length = 0;
    await toChain(page);
    const call = AT_SPOT.call.symbol;
    const put = UNDER_SPOT.put.symbol;
    // click the CALL side of the strike at the spot
    await page
      .locator('#chainBody tr[data-csym="' + call + '"] td.chn-call')
      .first()
      .click();
    expect(await page.evaluate(() => window.EdFlow.selected())).toBe(call);
    // click the PUT side of the strike under it
    await page
      .locator('#chainBody tr[data-psym="' + put + '"] td.chn-put')
      .first()
      .click();
    expect(await page.evaluate(() => window.EdFlow.selected())).toBe(put);
    await expect.poll(() => flowPosts).toEqual([call, put]);
    // shared strike/expiry context follows the selection
    const s = await page.evaluate(() => window.EdShell.getState());
    expect(s.selStrike).toBe(UNDER_SPOT.strike);
  });

  test("the centre Strike selects ONLY the shared strike (no contract)", async ({ page }) => {
    flowPosts.length = 0;
    await toChain(page);
    await page.locator('#chainBody tr[data-strike="' + TOP.strike + '"] td.k').click();
    expect(await page.evaluate(() => window.EdShell.getState().selStrike)).toBe(TOP.strike);
    expect(await page.evaluate(() => window.EdFlow.selected())).toBeNull(); // no contract chosen
    expect(flowPosts).toEqual([]);
  });

  // Independent-review finding (2026-09-13), REPRODUCED by direct browser measurement, then
  // narrowed to a two-sticky-row defect and "fixed" with a sticky div wrapping a header table
  // -- but the operator kept reproducing a real, moving visual fault on genuine trackpad
  // scrolling that survived TWO follow-up `position:sticky` fixes (a compositing-layer
  // promotion, then overscroll containment), neither provably addressing the actual
  // mechanism because neither could be reproduced by any scroll technique available in this
  // test harness. Root-caused instead of patched again: `position:sticky` is removed
  // entirely. The header is now a FROZEN (non-scrolling) sibling of a separate `.chn-scroll`
  // div that holds only the body table -- there is no sticky positioning anywhere left for a
  // compositor or scroll-chaining bug to intermittently mishandle, so the header's position
  // is asserted EXACTLY constant (no pixel tolerance needed, unlike the old sticky-offset
  // math), including through a real mouse-wheel scroll (not just programmatic scrollTop) and
  // a concurrent data refresh.
  test("the header table never moves regardless of scrolling the body, including real wheel scroll during a refresh (state-authority review)", async ({
    page,
  }) => {
    let frame = FIRST;
    panels.chain = () => frame;
    await page.setViewportSize({ width: 900, height: 640 }); // a representative, not maximal, size
    await toChain(page);
    await expect(page.locator("#chainBody tbody tr")).toHaveCount(FIRST.ladder.length);

    const headBox = () => page.locator(".chn-headtbl").boundingBox();
    const scrollTop = () => page.locator("#chainScroll").evaluate((el) => el.scrollTop);
    // the pointer on the actual scroll element first: Playwright's hover scrolls the PAGE to
    // bring it into view, which is not the body's scroll this test is about, so the header's
    // place is taken after it
    await page.locator("#chainScroll").hover();
    const before = await headBox();
    expect(before).toBeTruthy();

    // A real wheel scroll (not a programmatic scrollTop assignment) on the actual scroll
    // element, exercising the same input path a real trackpad/mouse produces.
    await page.mouse.wheel(0, 1200);
    await expect.poll(scrollTop).toBeGreaterThan(0); // the wheel has scrolled the body
    const duringScroll = await headBox();

    // Fire a background refresh (same context) WHILE scrolled, with genuinely changed data,
    // and confirm both the new value lands AND the header still has not moved at all.
    frame = LAST;
    sock.changed("chain"); // the program sends the chain again: a quote moved the 761 call
    await expect(volumeCell(page)).toHaveText(volume761(LAST));
    const afterRefresh = await headBox();

    const bottom = await page
      .locator("#chainScroll")
      .evaluate((el) => el.scrollHeight - el.clientHeight);
    await page.mouse.wheel(0, bottom);
    await expect.poll(scrollTop).toBe(bottom); // a body's height more takes the body to its end
    const afterMoreScroll = await headBox();

    // Exact equality: a frozen (non-scrolling) header cannot move by even one pixel, at any
    // point in this sequence -- this is a structural guarantee now, not an approximation.
    expect(duringScroll.y).toBe(before.y);
    expect(afterRefresh.y).toBe(before.y);
    expect(afterMoreScroll.y).toBe(before.y);
    expect(duringScroll.x).toBe(before.x);
    expect(afterMoreScroll.x).toBe(before.x);

    // Column alignment: the header table and the body table are unrelated table layouts
    // sharing only a <colgroup> -- prove a header cell's left edge and width actually match
    // its corresponding body column, not merely that both tables render.
    const headCell = await page
      .locator(".chn-headtbl thead tr")
      .last()
      .locator("th")
      .first()
      .boundingBox();
    const bodyCell = await page
      .locator(".chn-bodytbl tbody tr")
      .first()
      .locator("td")
      .first()
      .boundingBox();
    expect(Math.abs(headCell.x - bodyCell.x)).toBeLessThan(1);
    expect(Math.abs(headCell.width - bodyCell.width)).toBeLessThan(1);

    // No gap and no overlap between the two header rows: the second row's top must equal
    // (within sub-pixel rounding) the first row's own bottom edge.
    const rows = await page
      .locator(".chn-headtbl thead tr")
      .evaluateAll((trs) => trs.map((tr) => tr.getBoundingClientRect()));
    expect(rows.length).toBe(2);
    expect(Math.abs(rows[1].top - rows[0].bottom)).toBeLessThan(1);

    await page.setViewportSize({ width: 1280, height: 800 }); // restore default
  });

  // A FOURTH independent review (2026-09-13) found this test waited a fixed 300ms without ever
  // establishing that a refresh with CHANGED data actually completed -- it could pass simply
  // because nothing re-rendered at all. Strengthened: the second chain response carries a
  // DIFFERENT value (volume), and the test asserts that value actually reached the DOM before
  // checking the scroll position was preserved.
  test("a routine background refresh with changed data completes, and preserves a manually-scrolled position", async ({
    page,
  }) => {
    let frame = FIRST;
    panels.chain = () => frame;
    await toChain(page);
    await expect(page.locator("#chainBody tbody tr")).toHaveCount(FIRST.ladder.length);
    await expect(volumeCell(page)).toHaveText(volume761(FIRST));

    await page.evaluate(() => {
      document.getElementById("chainScroll").scrollTop = 1800;
    });
    const before = await page.evaluate(() => document.getElementById("chainScroll").scrollTop);

    // The NEXT chain sent carries a genuinely different value -- proof a refresh actually
    // completed comes from the DOM showing THIS new value, not merely from time having passed.
    frame = LAST;
    sock.changed("chain");
    await expect(volumeCell(page)).toHaveText(volume761(LAST));

    // A routine background refresh (same ticker/expiry context) must not recentre the ladder,
    // even though it just genuinely re-rendered with new data.
    const after = await page.evaluate(() => document.getElementById("chainScroll").scrollTop);
    expect(after).toBe(before);
  });

  test("a quote that moves a value is written into the drawn ladder: the same table, its cell's new text", async ({
    page,
  }) => {
    let frame = FIRST;
    panels.chain = () => frame;
    await toChain(page);
    const first = volumeCell(page);
    await expect(first).toHaveText(volume761(FIRST));
    await page.evaluate(() => {
      document.querySelector("#chainBody table.chn-bodytbl").dataset.drawn = "first";
    });
    // the next frame: the same rows, the 761 call's values moved by its streamed quotes
    frame = LAST;
    sock.changed("chain");
    await expect(first).toHaveText(volume761(LAST));
    const table = page.locator("#chainBody table.chn-bodytbl");
    await expect(table).toHaveAttribute("data-drawn", "first"); // written in place, not rebuilt
  });

  // each expiry's own contracts: the ladder changes to the selected expiry's, so a view that kept
  // the expiry left fails
  test("switching the expiry dropdown re-fetches and renders that expiry's own distinct contracts", async ({
    page,
  }) => {
    const symA = FRONT.ladder[0].call.symbol;
    const symB = SECOND.ladder[0].call.symbol;
    panels = chainPanels((asked) => (asked === SECOND.expiry ? SECOND : FRONT));
    sock = await pushExpiries(page, [FRONT.expiry, SECOND.expiry], undefined, panels);
    await toChain(page);
    await expect(page.locator("#chainBody .chn-head")).toContainText(
      "SINGLE EXPIRY · " + FRONT.expiry,
    );
    await expect(page.locator("#chainBody tbody tr td.k")).toHaveText(strikes(FRONT));

    await page.locator("#expSel").selectOption(SECOND.expiry);
    await expect(page.locator("#chainBody .chn-head")).toContainText(
      "SINGLE EXPIRY · " + SECOND.expiry,
    );
    await expect(page.locator("#chainBody tbody tr td.k")).toHaveText(strikes(SECOND));
    await expect(page.locator('#chainBody tr[data-csym="' + symB + '"]')).toHaveCount(1);
    await expect(page.locator('#chainBody tr[data-csym="' + symA + '"]')).toHaveCount(0);
  });

  // A -> B -> A: the program's B frame, sent before it read the page's return to A, arrives
  // after A's own frame has been drawn; it is not drawn. A is SPY's 2026-10-23 expiry, its next
  // frame the one after the 761 call's quotes; B is SPY's 2026-11-12 expiry.
  test("A -> B -> A: a frame of an expiry no longer selected is not drawn over the selected one", async ({
    page,
  }) => {
    const EXP_A = FIRST.expiry,
      EXP_B = FRONT.expiry;
    const symB = FRONT.ladder[0].call.symbol;
    panels = chainPanels((asked) => (asked === EXP_B ? FRONT : FIRST));
    sock = await pushExpiries(page, [EXP_A, EXP_B], undefined, panels);
    await toChain(page);
    await expect(page.locator("#chainBody tbody tr td.k")).toHaveText(strikes(FIRST));
    await page.locator("#expSel").selectOption(EXP_B);
    await expect(page.locator("#chainBody tbody tr td.k")).toHaveText(strikes(FRONT));
    await page.locator("#expSel").selectOption(EXP_A);
    await expect(page.locator("#chainBody tbody tr td.k")).toHaveText(strikes(FIRST));

    await page.evaluate(() => {
      // every ladder drawn from here on: its calls
      window.__draws = [];
      new MutationObserver(() =>
        window.__draws.push(
          [...document.querySelectorAll("#chainBody tbody tr")]
            .map((e) => e.getAttribute("data-csym"))
            .join(","),
        ),
      ).observe(document.getElementById("chainBody"), { childList: true, subtree: true });
    });
    sock.frame("chain:ladder", "SPY", FRONT); // the late B frame ...
    sock.frame("chain:ladder", "SPY", LAST); // ... and A's next, behind it
    await expect(volumeCell(page)).toHaveText(volume761(LAST));
    expect((await page.evaluate(() => window.__draws)).filter((d) => d.includes(symB))).toEqual([]);
    await expect(page.locator("#chainBody .chn-head")).toContainText(EXP_A);
  });
});

test.describe("expiry dropdown (register P-03): the list on the page's socket", () => {
  // it formatted each date on the page and ignored the served reason when none is listed; the
  // list is the program's, sent on /ws after each subscribe on the selected ticker and again on
  // each new chain (server.expiries), and the page asks no route for it
  const SPY_LIST = expiriesAnswer(["2026-10-16"], { "2026-10-16": 18 });
  const QQQ_LIST = expiriesAnswer(["2026-10-17"], { "2026-10-17": 19 });
  const LISTS = { SPY: SPY_LIST, QQQ: QQQ_LIST };
  // `onSocket(ws, n)`: the stand-in for the program's side of the page's n-th connection
  async function open(page, onSocket) {
    const asked = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/expiries")) asked.push(r.url());
    });
    await routeWatchlist(page, ["SPY"]);
    let n = 0;
    await page.routeWebSocket(/\/ws$/, (ws) => onSocket(ws, ++n));
    await page.goto("/", { waitUntil: "domcontentloaded" });
    return asked;
  }
  // the program's answer to each subscribe: what each symbol is, then the selected ticker's list
  function answering(ws, lists) {
    ws.onMessage((m) => {
      const req = JSON.parse(String(m));
      if (req.op !== "subscribe") return;
      ws.send(JSON.stringify({ type: "symbols", symbols: req.symbols.map(servedSymbol) }));
      if (req.ticker && lists[req.ticker]) ws.send(expiriesFrame(req.ticker, lists[req.ticker]));
    });
  }
  function options(page) {
    return page.locator("#expSel option").evaluateAll((os) => os.map((o) => o.textContent));
  }

  test("each option shows its served label, at once on the subscribe, with no request", async ({
    page,
  }) => {
    const asked = await open(page, (ws) => answering(ws, LISTS));
    await expect(page.locator('#expSel option[value="2026-10-16"]')).toHaveText(
      "10/16/2026 · 18DTE",
    );
    expect(asked).toEqual([]);
  });

  test("a ticker with no chain yet shows the served reason", async ({ page }) => {
    await open(page, (ws) =>
      answering(ws, {
        SPY: {
          expiries: null,
          dte: null,
          labels: null,
          dte_text: null,
          reason: "market closed; no chain capture of this ticker yet",
        },
      }),
    );
    await expect(page.locator("#expSel option[disabled]")).toHaveText(
      "market closed; no chain capture of this ticker yet",
    );
  });

  test('no list received (the socket down): "-", never a list', async ({ page }) => {
    await open(page, (ws) => ws.close());
    await expect(page.locator("#expSel option[disabled]")).toHaveText("-");
    expect(await options(page)).toEqual(["All Expirations", "-"]);
  });

  test("switching ticker shows the new ticker's list at once; a list for the ticker left is ignored", async ({
    page,
  }) => {
    let program;
    await open(page, (ws) => {
      program = ws;
      answering(ws, LISTS);
    });
    await expect(page.locator('#expSel option[value="2026-10-16"]')).toHaveCount(1);
    await page.locator("#symInput").fill("QQQ");
    await page.locator("#symInput").press("Enter");
    await expect.poll(() => options(page)).toEqual(["All Expirations", "10/17/2026 · 19DTE"]);
    // SPY's next chain, still in flight to a page that has left SPY; then a row of QQQ's, drawn
    // after it: once the row is on screen, the list before it was read
    program.send(expiriesFrame("SPY", SPY_LIST));
    program.send(JSON.stringify({ type: "quotes", rows: [priceRow("QQQ", 512.34)] }));
    await expect(page.locator("#hPx")).toContainText("512.34");
    expect(await options(page)).toEqual(["All Expirations", "10/17/2026 · 19DTE"]);
  });

  test("the socket drops and returns: the list is sent again on the resubscribe", async ({
    page,
  }) => {
    let first;
    await open(page, (ws, n) => {
      if (n === 1) {
        first = ws;
        answering(ws, LISTS);
        return;
      }
      // the program's list after the drop: the next chain's, so the page shows the one resent
      answering(ws, { SPY: expiriesAnswer(["2026-10-30"], { "2026-10-30": 23 }) });
    });
    await expect(page.locator('#expSel option[value="2026-10-16"]')).toHaveCount(1);
    first.close();
    await expect.poll(() => options(page)).toEqual(["All Expirations", "10/30/2026 · 23DTE"]);
  });
});
