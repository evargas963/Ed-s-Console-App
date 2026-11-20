/*
 * The header says whether Schwab accepts the daemon's sign-in, as the daemon's heartbeat serves
 * it (capture.sign_in_line): REFUSED and what to run, with Schwab's own reason on hover, then
 * accepted once a new sign-in is taken. The lines are the daemon's own
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
  await expect(cell).toHaveText(LINES.refused.line);
  await expect(cell).toHaveAttribute("title", LINES.refused.why);
  await expect(cell).toHaveClass(/\bneg\b/);
  beat(LINES.accepted);
  await expect(cell).toHaveText("accepted");
  await expect(cell).not.toHaveClass(/\bneg\b/);
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
  await expect(page.locator("#hLeftOut")).toHaveAttribute("title", line.why);
  await expect(page.locator("#hLeftOut")).toHaveClass(/\bneg\b/);
  beat(null);
  await expect(kv).toBeHidden();
  expect(errs).toEqual([]);
});
