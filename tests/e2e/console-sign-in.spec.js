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
