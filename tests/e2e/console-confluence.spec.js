/*
 * Confluence Matrix. The page draws the `confluence` panel on its socket and computes nothing.
 * The panel sent again (the chain or the levels changed) redraws the table at the page's one
 * expiry choice (the shared expiry dropdown; none chosen: the program reads the front one).
 *
 * Real data: the confluence body as the real code served it on MRVL's full chain captured
 * 2026-10-07 10:31:20 ET (tests/fixtures/real_mrvl_confluence_payloads_2026_10_07.json).
 */
const { test, expect } = require("@playwright/test");
const { mockPriceSocket, priceRow } = require("./fixtures/price_socket");
const FX = require("../fixtures/real_mrvl_confluence_payloads_2026_10_07.json");

const FRONT = "2026-10-09";
const NEXT = "2026-10-16";
// the columns in the order decision 62 reads them, Composite first
const HEADS = [
  "Read · strength",
  "Strike",
  "Δ pts",
  "σ",
  "Key levels here",
  "Gamma if here",
  "Visits",
  "Net GEX",
  "OI",
  "ΔOI 1d",
  "DEX",
  "Charm",
  "Vanna",
  "IV",
  "IV chg",
  "Volume",
  "Vol/OI",
  "P/C vol",
  "Pace",
  "Bought−sold",
  "Flow",
];
const GROUPS = [
  "Composite",
  "Price and levels",
  "Gamma profile and levels",
  "Positioning (open interest)",
  "Second-order Greeks (charm, vanna, IV)",
  "Volume and flow",
  "Hedging flow (est.)",
];

function served(expiry) {
  return FX.by_expiry[expiry] || FX.by_expiry[FRONT];
}

async function openMatrix(page) {
  await page.addInitScript(() => {
    localStorage.setItem("ed_ticker", "MRVL");
    localStorage.setItem("ed_ws", "trade-desk");
    localStorage.setItem("ed_sub", "confluence");
  });
  await page.goto("/");
}

// a strike row's cell of one column, by its head
const cellOf = (page, i, head) =>
  page.locator('#cmRows tr[data-i="' + i + '"] td').nth(HEADS.indexOf(head));

test("the groups and columns read left to right by importance, the Composite first", async ({
  page,
}) => {
  await mockPriceSocket(page, [], undefined, { confluence: served(FRONT) });
  await openMatrix(page);
  await expect(page.locator("#cmFrame thead tr").first().locator("th")).toHaveText(GROUPS);
  const heads = page.locator("#cmFrame thead tr").nth(1).locator("th");
  await expect(heads).toHaveCount(HEADS.length);
  for (let k = 0; k < HEADS.length; k++) {
    await expect(heads.nth(k)).toContainText(HEADS[k]);
  }
});

test("a cell shades by its value against its column peak, in the theme heat colours", async ({
  page,
}) => {
  // the straight proportion: the theme's zero toward its negative colour by |value| / peak,
  // worked out here from the served numbers and the page's own colour tokens
  const body = served(FRONT);
  await mockPriceSocket(page, [], undefined, { confluence: body });
  await openMatrix(page);
  const i = body.rows.findIndex((r, n) => n > 0 && r.net_gex != null && r.net_gex < 0);
  expect(i).toBeGreaterThan(0);
  const v = body.rows[i].net_gex,
    peak = body.peaks.net_gex;
  const cell = cellOf(page, i, "Net GEX");
  await expect(cell).toHaveText(body.rows[i].net_gex_text);
  const [zero, neg, bg] = await cell.evaluate((el) => {
    const cs = getComputedStyle(document.documentElement);
    return [
      cs.getPropertyValue("--ed-heat-zero"),
      cs.getPropertyValue("--ed-heat-neg"),
      getComputedStyle(el).backgroundColor,
    ];
  });
  const rgb = (h) => {
    const n = parseInt(h.trim().slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  const t = Math.abs(v) / peak,
    a = rgb(zero),
    b = rgb(neg);
  expect(t).toBeGreaterThan(0);
  expect(t).toBeLessThan(1);
  expect(bg).toBe("rgb(" + a.map((x, k) => Math.round(x + (b[k] - x) * t)).join(", ") + ")");
});

test("the Composite cell says the served words and shades by its served strength", async ({
  page,
}) => {
  const body = served(FRONT);
  const i = body.rows.findIndex((r) => r.composite_text != null);
  expect(i).toBeGreaterThanOrEqual(0);
  await mockPriceSocket(page, [], undefined, { confluence: body });
  await openMatrix(page);
  const cell = cellOf(page, i, "Read · strength");
  await expect(cell).toHaveText(body.rows[i].composite_text);
  await expect(cell).toHaveAttribute("title", body.rows[i].composite_hover);
  // a strike with no Composite says why on hover, never a number
  const blank = body.rows.findIndex((r) => r.composite_text == null);
  if (blank >= 0) {
    await expect(cellOf(page, blank, "Read · strength")).toHaveText("-");
    await expect(cellOf(page, blank, "Read · strength")).toHaveAttribute(
      "title",
      body.rows[blank].composite_reason,
    );
  }
});

// AGENTS rule 5: the confluence panel as the real code serves it on SPY's 2026-10-22 close
// publication, its 16:39 print the last price and the daemon's connection ended, read at 18:00
// (tests/test_level_crosses_wire.py keeps this file equal to the program's answer); the price row
// of that print as the daemon serves it then: OFFLINE, its trade time and age
const STOPPED = require("../fixtures/real_spy_confluence_at_a_stopped_price_2026_10_22.json");
const STOPPED_ROW = priceRow("SPY", 773.1269, {
  feed_live: false,
  feed_label: "OFFLINE",
  outage: "Schwab LEVELONE_EQUITIES feed down during After-Hours",
  trade_time_ct: "Thu 10/22 03:39 PM CT",
  trade_age_text: "1h 21m",
});

async function openSpyMatrix(page, rows) {
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  const sock = await mockPriceSocket(page, rows, undefined, { confluence: STOPPED });
  await page.addInitScript(() => {
    localStorage.setItem("ed_ticker", "SPY");
    localStorage.setItem("ed_ws", "trade-desk");
    localStorage.setItem("ed_sub", "confluence");
  });
  await page.goto("/");
  return { sock, errs };
}

// where the price line sits, against the middles of the two rows whose strikes hold `price`,
// worked out here from the drawn rows and the served strikes
async function expectedTop(page, price) {
  const mids = await page.locator("#cmRows tr[data-i]").evaluateAll((trs) => {
    const top = document.getElementById("cmWrap").getBoundingClientRect().top;
    return trs.map((tr) => {
      const r = tr.getBoundingClientRect();
      return r.top - top + r.height / 2;
    });
  });
  const strikes = STOPPED.rows.map((r) => r.strike);
  const k = strikes.findIndex(
    (s, i) => i + 1 < strikes.length && s >= price && price >= strikes[i + 1],
  );
  expect(k).toBeGreaterThanOrEqual(0);
  return mids[k] + ((strikes[k] - price) / (strikes[k] - strikes[k + 1])) * (mids[k + 1] - mids[k]);
}

test("a price that has stopped marks the spot not live with its time and age", async ({ page }) => {
  // the price is one line at its place between the two strikes, drawn from the header's own row
  // (one producer): its price, and while not live dashed, with the row's word, time and age
  const { errs } = await openSpyMatrix(page, [STOPPED_ROW]);
  const line = page.locator("#cmSpot");
  await expect(line).toBeVisible();
  await expect(page.locator("#hPx")).toHaveText("773.13");
  await expect(line.locator("span")).toHaveText("773.13");
  await expect(line.locator("span")).toHaveClass(/stale/);
  const said =
    "OFFLINE: Schwab LEVELONE_EQUITIES feed down during After-Hours · last trade Thu 10/22 03:39 PM CT · 1h 21m";
  await expect(line.locator("span")).toHaveAttribute("title", said);
  expect(await line.evaluate((el) => getComputedStyle(el).borderTopStyle)).toBe("dashed");
  const top = await line.evaluate((el) => parseFloat(el.style.top));
  expect(Math.abs(top - (await expectedTop(page, 773.1269)))).toBeLessThan(0.5);
  // the SPOT card is the same row's: its price, and the row's words beneath
  const card = page.locator("#cmBody .stat").filter({ hasText: "SPOT" });
  await expect(card.locator("strong")).toHaveText("773.13");
  await expect(card.locator("small")).toHaveText(said);
  // no price of the panel's own anywhere: no row inserted among the strikes
  await expect(page.locator("#cmRows tr")).toHaveCount(STOPPED.rows.length);
  expect(errs).toEqual([]);
});

test("a new price moves only its line; the rows hold, and a price past them hides it", async ({
  page,
}) => {
  const strikes = STOPPED.rows.map((r) => r.strike);
  const { sock, errs } = await openSpyMatrix(page, [priceRow("SPY", 773.1269)]);
  const line = page.locator("#cmSpot");
  await expect(line).toBeVisible();
  await expect(line.locator("span")).not.toHaveClass(/stale/);
  // the page asks again with the centre the rows were served on, so the next answers hold them
  await expect
    .poll(() =>
      sock.subscribes.some(
        (s) =>
          s.panels && s.panels.confluence && s.panels.confluence.centre === STOPPED.view.centre,
      ),
    )
    .toBe(true);
  // mark one drawn row: a redraw would replace it
  await page.locator('#cmRows tr[data-i="0"]').evaluate((tr) => (tr.dataset.kept = "yes"));
  const moved = (strikes[1] + strikes[2]) / 2;
  sock.quotes([priceRow("SPY", moved)]);
  await expect(page.locator("#hPx")).toHaveText(moved.toFixed(2));
  await expect(line.locator("span")).toHaveText(moved.toFixed(2));
  await expect
    .poll(async () =>
      Math.abs(
        (await line.evaluate((el) => parseFloat(el.style.top))) - (await expectedTop(page, moved)),
      ),
    )
    .toBeLessThan(0.5);
  await expect(page.locator('#cmRows tr[data-i="0"]')).toHaveAttribute("data-kept", "yes");
  // a price above every row shown: no line drawn at a wrong place
  sock.quotes([priceRow("SPY", strikes[0] + 5)]);
  await expect(line).toBeHidden();
  expect(errs).toEqual([]);
});

// The matrix's own state, no strike chosen, is said in the words served with the page
// (server.PAGE_WORDS choose_strike); a strike chosen, its heading is the row's served sentence
// (heading_said). INDUCED: the served list words the prompt otherwise, and the first panel holds
// no row, so none is chosen.
test("with no strike chosen the served prompt; once chosen, the row's served heading", async ({
  page,
}) => {
  await page.route(/\/$/, async (route) => {
    const served = await route.fetch();
    const html = (await served.text()).replace(
      /&quot;choose_strike&quot;: &quot;.*?&quot;/,
      "&quot;choose_strike&quot;: &quot;SERVED: choose a strike&quot;",
    );
    await route.fulfill({ response: served, body: html });
  });
  let rowsSent = false;
  const sock = await mockPriceSocket(page, [], undefined, {
    confluence: (key, params) =>
      rowsSent ? served(params.expiry) : Object.assign({}, served(params.expiry), { rows: [] }),
  });
  await openMatrix(page);
  await expect(page.locator("#cmDetail")).toContainText("SERVED: choose a strike");
  rowsSent = true;
  sock.changed("confluence");
  const rows = served(FRONT).rows;
  await expect(page.locator('#cmBody tbody tr[data-i="1"]')).toBeVisible();
  await page.locator('#cmBody tbody tr[data-i="1"]').click();
  await expect(page.locator("#cmDetail h2")).toHaveText(rows[1].heading_said);
});

test("the matrix redraws its served tags and readings as the chain updates, keeping the expiry", async ({
  page,
}) => {
  const errs = [];
  const expiries = [];
  page.on("pageerror", (e) => errs.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/WebSocket|EventSource|Failed to load resource/.test(m.text()))
      errs.push(m.text());
  });
  // the expiry each confluence panel sent was asked with (none: the program's front one)
  const sock = await mockPriceSocket(page, [], undefined, {
    confluence: (key, params) => {
      expiries.push(params.expiry);
      return served(params.expiry);
    },
  });
  const confluenceAsks = () => sock.subscribes.map((s) => JSON.stringify(s.panels.confluence));
  // the page's ask once its rows are served: again, with the centre they were served on
  const held = (expiry) =>
    JSON.stringify({ expiry: expiry, lookback: null, centre: served(expiry).view.centre });
  await openMatrix(page);
  const body = served(FRONT);
  const rows = body.rows;
  await expect
    .poll(() => confluenceAsks().at(-1))
    .toBe(JSON.stringify({ expiry: null, lookback: null, centre: body.view.centre }));
  await expect(page.locator("#cmBody")).toContainText(rows[0].strike_text);
  await expect(page.locator("#cmBody td", { hasText: /^-$/ }).first()).toBeVisible();
  await expect(page.locator("#cmBody h1")).toHaveCount(0);
  await expect(page.locator("#cmBody .cm-exp")).toHaveText("Expiry " + FRONT); // served
  await expect(page.locator("#cmBody select")).toHaveCount(0); // no dropdown of its own
  // each served tag on the row the program placed it, its served words on hover
  const tagged = rows.map((r, i) => [r, i]).filter(([r]) => r.tags.length);
  expect(tagged.length).toBeGreaterThan(0);
  for (const [r, i] of tagged) {
    const tags = cellOf(page, i, "Key levels here").locator(".cm-tag");
    await expect(tags).toHaveText(r.tags.map((t) => t.text));
    await expect(tags.first()).toHaveAttribute("title", r.tags[0].hover);
  }
  for (const lv of body.levels_above) {
    await expect(page.locator("#cmAbove")).toContainText(lv.text);
  }
  for (const lv of body.levels_below) {
    await expect(page.locator("#cmBelow")).toContainText(lv.text);
  }
  const font = await page.locator(".cm-page").evaluate((el) => getComputedStyle(el).fontSize);
  expect(font).toBe("13px");
  const opened = expiries.length;
  expect(opened).toBeGreaterThan(0);

  // a strike clicked: its served readings and their words
  const row = rows.find((r) => r.oi_hover && r.composite_hover);
  await page.locator('#cmBody tbody tr[data-i="' + rows.indexOf(row) + '"]').click();
  await expect(page.locator("#cmDetail")).toContainText(row.composite_hover);
  await expect(page.locator("#cmDetail")).toContainText(row.oi_hover);

  // the panel sent again: the front expiry stays (the page asked All Expirations, null: the
  // program's front one), and so does the strike clicked
  sock.changed("confluence");
  await expect.poll(() => expiries.length).toBe(opened + 1);
  expect(expiries[expiries.length - 1]).toBeNull();
  await expect(page.locator("#cmBody .cm-exp")).toHaveText("Expiry " + FRONT);
  await expect(page.locator("#cmDetail")).toContainText(row.oi_hover);

  // the one expiry dropdown's choice is the matrix's: asked around the price, then with the
  // centre its rows were served on
  await page.evaluate((e) => window.EdShell.setExpiry(e), NEXT);
  await expect.poll(() => expiries[expiries.length - 1]).toBe(NEXT);
  await expect.poll(() => confluenceAsks().at(-1)).toBe(held(NEXT));
  await expect.poll(() => expiries.filter((e) => e === NEXT).length).toBe(2);
  const picked = expiries.length;

  sock.changed("confluence");
  await expect.poll(() => expiries.length).toBe(picked + 1);
  expect(expiries[expiries.length - 1]).toBe(NEXT);
  await expect(page.locator("#cmBody .cm-exp")).toHaveText("Expiry " + NEXT);

  // the view opened again asks for the same panel of the same expiry: nothing new is asked or sent
  const asks = confluenceAsks();
  expect(asks[asks.length - 1]).toBe(held(NEXT));
  await page.getByRole("button", { name: "Confluence Matrix" }).click();
  // then a marker the page sends on the same socket: a subscribe the click caused would arrive
  // before it (one socket keeps its messages' order), so the marker's is the first after the
  // click, by its cause and never a stopwatch (.claude/rules/tests.md)
  await page.evaluate(() => window.EdShell.showPanel("marker", {}));
  const marker = () => sock.subscribes.findIndex((s) => "marker" in s.panels);
  await expect.poll(marker).toBeGreaterThan(-1);
  expect(marker()).toBe(asks.length);
  expect(confluenceAsks().at(-1)).toBe(asks[asks.length - 1]);
  expect(expiries.length).toBe(picked + 1);
  await expect(page.locator("#cmBody .cm-exp")).toHaveText("Expiry " + NEXT);
  expect(errs).toEqual([]);
});

test("a chosen expiry that has passed is said, never another expiry's matrix", async ({ page }) => {
  const asked = [];
  let afterItPassed = false;
  const sock = await mockPriceSocket(page, [], undefined, {
    confluence: (key, params) => {
      asked.push(params.expiry);
      return afterItPassed ? FX.front_passed : served(params.expiry);
    },
  });
  await openMatrix(page);
  await page.evaluate((e) => window.EdShell.setExpiry(e), FRONT);
  await expect.poll(() => asked[asked.length - 1]).toBe(FRONT);
  await expect(page.locator("#cmBody")).toContainText(served(FRONT).rows[0].strike_text);
  afterItPassed = true;
  const before = asked.length;
  sock.changed("confluence");
  await expect.poll(() => asked.length).toBe(before + 1);
  expect(asked[asked.length - 1]).toBe(FRONT);
  // the program's answer on Sunday for Friday's expiry: why, and no rows of the next one
  expect(FX.front_passed.available).toBe(false);
  await expect(page.locator("#cmBody")).toContainText(FX.front_passed.reason);
  await expect(page.locator("#cmRows tr")).toHaveCount(0);
});

// the regime card's value, as drawn
const regimeCell = (page) =>
  page.locator("#cmBody .stat", { hasText: "GAMMA REGIME" }).locator("strong");

test("the regime card says MRVL's regime in the served words and tone", async ({ page }) => {
  // MRVL's real answer: net GEX at the price is positive
  const body = served(FRONT);
  const card = body.cards.find((c) => c.label === "GAMMA REGIME");
  expect([card.value, card.tone]).toEqual(["Positive gamma", "pos"]);
  await mockPriceSocket(page, [], undefined, { confluence: body });
  await openMatrix(page);
  await expect(regimeCell(page)).toHaveText("Positive gamma");
  await expect(regimeCell(page)).toHaveClass(/pos/);
});

// INDUCED: MRVL's answer with each other word and tone the server serves on the card, then words
// the page has never held: the card draws the served words and picks none
for (const [words, tone] of [
  ["Negative gamma", "neg"],
  ["unavailable", null],
  ["as only the server says", null],
]) {
  test(`the regime card draws the served words ${words}`, async ({ page }) => {
    const body = served(FRONT);
    const cards = body.cards.map((c) =>
      c.label === "GAMMA REGIME" ? Object.assign({}, c, { value: words, tone: tone }) : c,
    );
    await mockPriceSocket(page, [], undefined, {
      confluence: Object.assign({}, body, { cards: cards }),
    });
    await openMatrix(page);
    await expect(regimeCell(page)).toHaveText(words);
  });
}

test("a look-back picked is asked for, and the served one is drawn on with its start", async ({
  page,
}) => {
  const asked = [];
  // the program's answer at each look-back asked: the served body, its choice marked on as the
  // program marks it (push.confluence._lookback), its start as served
  await mockPriceSocket(page, [], undefined, {
    confluence: (key, params) => {
      asked.push(params.lookback);
      const body = served(FRONT);
      const chosen = params.lookback || body.lookback.chosen;
      return Object.assign({}, body, {
        lookback: Object.assign({}, body.lookback, {
          chosen: chosen,
          choices: body.lookback.choices.map((c) => Object.assign({}, c, { on: c.key === chosen })),
        }),
      });
    },
  });
  await openMatrix(page);
  const picker = page.locator("#cmBody .cm-lookback");
  await expect(picker.locator("button.on")).toHaveText("5 min");
  await expect(picker.locator("small")).toHaveText(served(FRONT).lookback.start_text);
  await picker.getByRole("button", { name: "15 min" }).click();
  await expect.poll(() => asked[asked.length - 1]).toBe("15");
  await expect(picker.locator("button.on")).toHaveText("15 min");
});

test("the headline says the kind of move in the served words, untested", async ({ page }) => {
  const body = served(FRONT);
  await mockPriceSocket(page, [], undefined, { confluence: body });
  await openMatrix(page);
  await expect(page.locator("#cmBody .cm-kind")).toContainText(body.headline.text);
  await expect(page.locator("#cmBody .cm-kind")).toHaveClass(new RegExp(body.headline.tone));
  await expect(page.locator("#cmBody .cm-record")).toContainText("untested");
});
