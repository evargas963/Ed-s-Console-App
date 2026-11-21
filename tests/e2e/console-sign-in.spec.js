/*
 * The header says whether Schwab accepts the daemon's sign-in, as the daemon's heartbeat serves
 * it (capture.sign_in_line): REFUSED in its cell with Schwab's own reason on hover, and what to
 * run with that reason on row 2's alert line; then accepted once a new sign-in is taken, and the
 * alert gone. The lines are the daemon's own
 * (tests/e2e/fixtures/sign_in_lines.json, held by tests/test_data_path_sign_in_v1.py; the
 * refusal is production's of 2026-11-19 13:00:13 CT). Any page error fails the test.
 */
const { test, expect } = require("@playwright/test");
const LINES = require("./fixtures/sign_in_lines.json");

test("the header shows Schwab's refusal of the sign-in, then its acceptance", async ({ page }) => {
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  let program = null;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    program = ws;
  });
  const beat = (signIn) =>
    program.send(
      JSON.stringify({
        type: "feed",
        feed: { ts: Date.now() / 1000, watchlist: [], session: "Unknown", sign_in: signIn },
      }),
    );
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(() => program !== null).toBe(true);
  const cell = page.locator("#hSignIn");
  beat(LINES.refused);
  await expect(cell).toHaveText(LINES.refused.word);
  await expect(cell).toHaveAttribute("title", LINES.refused.why);
  await expect(cell).toHaveClass(/\bneg\b/);
  // what to run, and why, on the alert line, where the news was
  await expect(page.locator("#hLineLabel")).toHaveText("Alert");
  await expect(page.locator("#hTape .htrack > .hni .g")).toHaveText("Schwab sign-in");
  await expect(page.locator("#hTape .htrack > .hni .h")).toHaveText(
    LINES.refused.line + " · " + LINES.refused.why,
  );
  beat(LINES.accepted);
  await expect(cell).toHaveText("accepted");
  await expect(cell).not.toHaveClass(/\bneg\b/);
  await expect(page.locator("#hLineLabel")).toHaveText("News");
  await expect(page.locator("#hTape .hni")).toHaveCount(0);
  expect(errs).toEqual([]);
});

// What the program left out since it started (live_ui.left_out_line, its lines held by
// tests/test_data_path_silent_price_v1.py): shown while the beat serves one, not shown when the
// beat serves none (operator 2026-11-20). INDUCED: the counts are the test's.
test("the header shows what the program left out, and nothing when nothing was", async ({
  page,
}) => {
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  let program = null;
  await page.routeWebSocket(/\/ws$/, (ws) => {
    program = ws;
  });
  const beat = (leftOut) =>
    program.send(
      JSON.stringify({
        type: "feed",
        feed: { ts: Date.now() / 1000, watchlist: [], session: "Unknown", left_out: leftOut },
      }),
    );
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect.poll(() => program !== null).toBe(true);
  const kv = page.locator("#hLeftOutKv");
  beat(null);
  await expect(kv).toBeHidden();
  const line = {
    line: "3 records not applied · 1 page frames refused",
    why: "counted since the program started; each is in the daemon's log with what arrived",
    cls: "neg",
  };
  beat(line);
  await expect(kv).toBeVisible();
  await expect(page.locator("#hLeftOut")).toHaveText(line.line);
  // the title says the line too: a window with no room for it draws the cell's dot alone
  await expect(page.locator("#hLeftOut")).toHaveAttribute("title", line.line + " · " + line.why);
  await expect(page.locator("#hLeftOut")).toHaveClass(/\bneg\b/);
  beat(null);
  await expect(kv).toBeHidden();
  expect(errs).toEqual([]);
});
