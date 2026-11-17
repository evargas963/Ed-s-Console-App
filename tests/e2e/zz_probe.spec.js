const { test } = require("@playwright/test");
const {
  READOUT_LIVE,
  READOUT_OFFLINE,
  READOUT_NO_BOOK,
  READOUT_AUCTION,
  READOUT_EVERY_LINE,
  intercept,
  deskPanels,
} = require("./fixtures/trade_desk");

test("probe: the Desk's height while it fills", async ({ page }) => {
  const cdp = await page.context().newCDPSession(page);
  await page.setViewportSize({ width: 1920, height: 950 });
  const bodies = { READOUT_LIVE, READOUT_AUCTION, READOUT_OFFLINE, READOUT_NO_BOOK, READOUT_EVERY_LINE };
  for (const rate of [1, 6])
  for (const [name, body] of Object.entries(bodies)) {
    await cdp.send("Emulation.setCPUThrottlingRate", { rate });
    await intercept(page);
    deskPanels().book = body;
    await page.addInitScript(() => {
      localStorage.setItem("ed_ticker", "SPY");
      localStorage.setItem("ed_ws", "trade-desk");
      localStorage.setItem("ed_sub", "desk");
      localStorage.setItem("ed_book_venue", "NYSE_BOOK");
      localStorage.removeItem("ed.desk.liqvenue");
      localStorage.removeItem("ed.desk.liqview");
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const seen = await page.evaluate(
      () =>
        new Promise((done) => {
          const out = [];
          const t0 = performance.now();
          const tick = () => {
            const root = document.getElementById("tdmRoot");
            if (root && root.scrollHeight > root.clientHeight) {
              out.push({
                t: Math.round(performance.now() - t0),
                over: root.scrollHeight + ">" + root.clientHeight,
                kids: [...root.children].map(
                  (c) => (c.id || c.className).slice(0, 20) + ":" + c.offsetHeight,
                ),
              });
            }
            if (performance.now() - t0 < 4000) setTimeout(tick, 25);
            else done(out);
          };
          tick();
        }),
    );
    console.log("PROBE", rate, name, seen.length, JSON.stringify(seen.slice(0, 3)), JSON.stringify(seen.slice(-1)));
  }
});
