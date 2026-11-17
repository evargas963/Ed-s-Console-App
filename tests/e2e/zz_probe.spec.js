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

test("probe: the Desk settled, and the fonts it has", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 950 });
  const seen = [];
  const bodies = { READOUT_LIVE, READOUT_AUCTION, READOUT_OFFLINE, READOUT_NO_BOOK, READOUT_EVERY_LINE };
  for (const [name, body] of Object.entries(bodies)) {
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
    await page.locator("#tdmCardLiq .liq-body > *").first().waitFor();
    const first = await page.evaluate(() => {
      const r = document.getElementById("tdmRoot");
      return r.scrollHeight + "/" + r.clientHeight;
    });
    await page.waitForTimeout(3000);
    const settled = await page.evaluate(() => {
      const r = document.getElementById("tdmRoot");
      const kids = [...r.children].map((c) => c.offsetHeight).join(",");
      const fonts = ["Arial Narrow", "Liberation Sans Narrow", "Segoe UI", "Arial"]
        .map((f) => f + "=" + document.fonts.check("12px '" + f + "'"))
        .join(" ");
      return r.scrollHeight + "/" + r.clientHeight + " kids " + kids + " | " + fonts;
    });
    seen.push("PROBE " + name + " first " + first + " settled " + settled);
  }
  throw new Error(seen.join("\n"));
});
