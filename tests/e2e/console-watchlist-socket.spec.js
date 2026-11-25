// @ts-check
// The watchlist rail reads the list the program's socket carries on every beat (/ws `feed`: the
// daemon's status, its `watchlist`; live_ui.LiveUiServer.beat_loop), and asks the console for no
// list. STAND-INS: the program's socket, its beats carrying the watchlist alone (no rows), and the
// console's watchlist routes (fixtures/watchlist.js).
const { test, expect } = require("@playwright/test");
const { routeWatchlist, beatNow } = require("./fixtures/watchlist");
const { watchRequests, holdClock } = require("./fixtures/settled");

// one beat as the program sends it, the daemon's status reduced to its time, its watchlist and
// the session, its code and its word (Unknown: Schwab's /markets answer not held;
// time_et.SESSION_WORDS) (null: no status); `ts` on the program's clock, now unless given
function feed(list, ts = Date.now() / 1000, session = "Unknown", word = "UNKNOWN") {
  return JSON.stringify({
    type: "feed",
    feed: list === null ? null : { ts: ts, watchlist: list, session: session, session_word: word },
  });
}

// Every frame sent on `socket` before this one has been taken by the page: a beat with no status,
// sent last, is answered on the page by its notice (the page's clock held, so no timer of the
// page replaces or clears it).
async function taken(page, socket) {
  socket.send(feed(null));
  await expect(page.locator("#wlFeed")).toHaveText("the capture daemon is not reporting");
}

test("the rail fills from the first beat on the socket, and nothing asks for the list", async ({
  page,
}) => {
  const requests = watchRequests(page);
  const gets = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/watchlist") && r.method() === "GET") gets.push(r.url());
  });
  await page.routeWebSocket(/\/ws$/, (ws) => ws.send(feed(["SPY", "QQQ"])));
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "QQQ"]);
  await requests.settled();
  expect(gets).toEqual([]);
});

test("the header session follows each beat, while quotes keep arriving between them", async ({
  page,
}) => {
  let socket;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    socket = ws;
    ws.send(feed(["SPY"], 1000, "Closed", "CLOSED"));
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#hSession")).toHaveText("CLOSED");
  for (let i = 0; i < 5; i++) socket.send(JSON.stringify({ type: "quotes", rows: [] }));
  // Schwab's pre-market window opened
  socket.send(feed(["SPY"], 1001, "Pre-Market", "PRE-MARKET"));
  await expect(page.locator("#hSession")).toHaveText("PRE-MARKET");
  await expect(page.locator("#hSession")).toHaveClass(/pre/);
  socket.send(feed(["SPY"], 1002, "RTH", "REGULAR"));
  await expect(page.locator("#hSession")).toHaveText("REGULAR");
  // the word is the program's, never the page's: INDUCED, the beat words it otherwise
  socket.send(feed(["SPY"], 1003, "RTH", "SERVED REGULAR"));
  await expect(page.locator("#hSession")).toHaveText("SERVED REGULAR");
  await expect(page.locator("#hSession")).toHaveClass(/rth/);
});

test("the header clock is the beat time the program sends, drawn as sent", async ({ page }) => {
  let socket;
  // capture.Daemon.status at ts 1790380803.232: time_et.ct_time and time_et.ct_day
  const beat = {
    ts: 1790380803.232,
    clock_ct: "19:00:03 CT",
    day_ct: "Fri, Sep 25",
    watchlist: ["SPY"],
    session: "Closed",
    session_word: "CLOSED",
  };
  await page.routeWebSocket(/\/ws$/, (ws) => {
    socket = ws;
    ws.send(JSON.stringify({ type: "feed", feed: beat }));
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#hClock")).toHaveText("19:00:03 CT");
  await expect(page.locator("#hClockDate")).toHaveText("Fri, Sep 25");
  // a status without its clock words: the header says "-", never a time of the page's own
  socket.send(
    JSON.stringify({
      type: "feed",
      feed: { ts: 1790380804, watchlist: ["SPY"], session: "Closed", session_word: "CLOSED" },
    }),
  );
  await expect(page.locator("#hClock")).toHaveText("-");
});

test('before a beat has carried a list, the rail reads "-", never an empty list', async ({
  page,
}) => {
  await holdClock(page);
  await page.routeWebSocket(/\/ws$/, () => {}); // open, no beat yet
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".wl-empty")).toHaveText("-");
  await page.clock.runFor(3000); // every page timer due in 3 s has run
  await expect(page.locator(".wl-empty")).toHaveText("-");
  await expect(page.locator(".wl-row")).toHaveCount(0);
});

test("a change the daemon makes reaches the rail with the next beat; an add here draws from its answer", async ({
  page,
}) => {
  const list = await routeWatchlist(page, ["SPY"]);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY"]);
  list.push("AMD"); // added on another page: the daemon's list
  beatNow(page); // the program's next beat carries it
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "AMD"], { timeout: 2500 });
  list.splice(0, 1); // SPY removed on another page
  beatNow(page);
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["AMD"], { timeout: 2500 });
  await page.evaluate(() => window.EdShell.addSymbol("MU"));
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["AMD", "MU"]);
});

test("a beat built before an add, arriving after its answer, does not take the added ticker away", async ({
  page,
}) => {
  // the program's clock: the add's record at 1002; a beat built at 1001 still carries the old list
  let socket;
  await holdClock(page);
  await page.routeWebSocket(/\/ws$/, (ws) => {
    socket = ws;
    ws.send(feed(["SPY"], 1000));
  });
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        op: "added",
        ticker: "AMD",
        tickers: ["SPY", "AMD"],
        ts: 1002,
        status: 200,
        answer: {},
        text: "AMD is added to the watchlist",
      }),
    }),
  );
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY"]);
  await page.evaluate(() => window.EdShell.addSymbol("AMD"));
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "AMD"]);
  socket.send(feed(["SPY"], 1001)); // late: built before the add
  await taken(page, socket);
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "AMD"]);
  socket.send(feed(["SPY", "AMD", "MU"], 1003)); // built after it: taken
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "AMD", "MU"]);
});

test("a beat with no status keeps the list drawn and says the daemon is not reporting", async ({
  page,
}) => {
  await page.routeWebSocket(/\/ws$/, (ws) => {
    ws.send(feed(["SPY", "QQQ"]));
    const timer = setInterval(() => ws.send(feed(null)), 1000); // every beat while the status fails
    timer.unref();
    ws.onClose(() => clearInterval(timer));
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator("#wlFeed")).toHaveText("the capture daemon is not reporting");
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "QQQ"]);
});

// The message line is the answer to the operator's own add; the daemon's state has its own line.
// A beat with no status, taken just after Schwab refuses a ticker, does not write over the answer,
// and a beat with a status again clears the state line. STAND-IN: the console's answer to the add
// is Schwab's for ZQZQZ on 2026-10-07 (tests/fixtures/real_schwab_quotes_watchlist_check_2026_10_07.json).
test("the answer to an add stands when a beat then carries no status", async ({ page }) => {
  let socket;
  await holdClock(page); // the page's timers run when the test moves its time: nothing self-clears
  await page.routeWebSocket(/\/ws$/, (ws) => {
    socket = ws;
    ws.send(feed(["SPY", "QQQ"]));
  });
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: false,
        op: "invalid",
        ticker: "ZQZQZ",
        tickers: ["SPY", "QQQ"],
        ts: Date.now() / 1000,
        status: 200,
        answer: { errors: { invalidSymbols: ["ZQZQZ"] } },
        text: 'ZQZQZ is not added: Schwab does not quote it ({"errors": {"invalidSymbols": ["ZQZQZ"]}})',
      }),
    }),
  );
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "QQQ"]);
  await page.evaluate(() => window.EdShell.addSymbol("ZQZQZ"));
  const said =
    'ZQZQZ is not added: Schwab does not quote it ({"errors": {"invalidSymbols": ["ZQZQZ"]}})';
  await expect(page.locator("#wlMsg")).toHaveText(said);
  await taken(page, socket); // a beat with no status, after the answer
  await expect(page.locator("#wlMsg")).toHaveText(said);
  socket.send(feed(["SPY", "QQQ"])); // the daemon reports again
  await expect(page.locator("#wlFeed")).toHaveText("");
  await expect(page.locator("#wlMsg")).toHaveText(said);
});

// A ticker already listed is the daemon's to say (capture.ON_LIST, WATCHLIST_TEXT): the page asks,
// draws the answer as sent and selects the ticker; it never words it itself. INDUCED: the
// answer's sentence is worded otherwise, so a page word of its own would show.
test("adding a ticker already listed draws the daemon's answer and selects it", async ({
  page,
}) => {
  const asked = [];
  const said = "QQQ is already on the watchlist (the daemon's sentence)";
  await page.routeWebSocket(/\/ws$/, (ws) => ws.send(feed(["SPY", "QQQ"])));
  await page.route("**/api/watchlist", (route) => {
    asked.push(route.request().postDataJSON().ticker);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: false,
        op: "already on the list",
        ticker: "QQQ",
        tickers: ["SPY", "QQQ"],
        ts: Date.now() / 1000,
        status: null,
        answer: null,
        text: said,
      }),
    });
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "QQQ"]);
  await page.evaluate(() => window.EdShell.addSymbol("qqq"));
  await expect(page.locator("#wlMsg")).toHaveText(said);
  expect(asked).toEqual(["QQQ"]);
  await expect.poll(() => page.evaluate(() => window.EdShell.getState().ticker)).toBe("QQQ");
});

// Each answer's served sentence is drawn as sent: the daemon's record (capture.WATCHLIST_TEXT) and
// the console's own when the daemon is away (server._watchlist_change, its 503 as it answers with
// no daemon). INDUCED: an answer that is not the program's JSON (a 500 page from something between
// the page and the program) says its HTTP status.
test("the served sentence of each answer is drawn; an answer that is not the program's says its HTTP status", async ({
  page,
}) => {
  await holdClock(page); // nothing self-clears
  // the program's clock: the beat at 1000, the removal's record at 1001
  await page.routeWebSocket(/\/ws$/, (ws) => ws.send(feed(["SPY", "QQQ"], 1000)));
  const answers = [
    {
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        op: "removed",
        ticker: "QQQ",
        tickers: ["SPY"],
        ts: 1001,
        status: null,
        answer: null,
        text: "QQQ is removed from the watchlist",
      }),
    },
    {
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        ok: false,
        text: "TSLA is not added: no capture daemon runs in this program",
      }),
    },
    { status: 500, contentType: "text/html", body: "<html><body>Internal error</body></html>" },
    { status: 502, contentType: "text/html", body: "<html><body>Bad gateway</body></html>" },
  ];
  await page.route("**/api/watchlist**", (route) => route.fulfill(answers.shift()));
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "QQQ"]);
  await page.locator('[data-rm="QQQ"]').click();
  await expect(page.locator("#wlMsg")).toHaveText("QQQ is removed from the watchlist");
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY"]);
  await page.evaluate(() => window.EdShell.addSymbol("TSLA"));
  await expect(page.locator("#wlMsg")).toHaveText(
    "TSLA is not added: no capture daemon runs in this program",
  );
  await page.evaluate(() => window.EdShell.addSymbol("TSLA"));
  await expect(page.locator("#wlMsg")).toHaveText("TSLA is not added: HTTP 500");
  await page.locator('[data-rm="SPY"]').click();
  await expect(page.locator("#wlMsg")).toHaveText("SPY is not removed: HTTP 502");
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY"]);
});

test("the socket drops: the rail stands marked; it returns: the new connection's beat redraws it", async ({
  page,
}) => {
  let connections = 0;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    connections += 1;
    if (connections === 1) {
      ws.send(feed(["SPY", "QQQ"]));
      setTimeout(() => ws.close(), 500); // the program goes away
    } else {
      setTimeout(() => ws.send(feed(["SPY", "IWM"])), 4000); // back, its first beat later
    }
  });
  await page.addInitScript(() => {
    localStorage.setItem("ed_ticker", "SPY");
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "QQQ"]);
  await expect.poll(() => connections).toBe(2);
  await expect(page.locator("#watchlist")).toHaveClass(/wl-degraded/);
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "QQQ"]);
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "IWM"], { timeout: 6000 });
});

test("the same list on every beat leaves the rail as drawn (no redraw, no flicker)", async ({
  page,
}) => {
  let socket;
  await holdClock(page);
  await page.routeWebSocket(/\/ws$/, (ws) => {
    socket = ws;
    ws.send(feed(["SPY", "QQQ"]));
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".wl-row .wl-sym")).toHaveText(["SPY", "QQQ"]);
  await page.evaluate(() => {
    document.querySelector(".wl-row").dataset.drawn = "first";
  });
  for (let beat = 0; beat < 7; beat += 1) socket.send(feed(["SPY", "QQQ"])); // seven beats, the same list
  await taken(page, socket);
  await expect(page.locator(".wl-row").first()).toHaveAttribute("data-drawn", "first");
});
