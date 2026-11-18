// The AI Analyst drawer, closed, takes no focus: its buttons are out of the tab order and the
// accessibility tree (HTML's `inert`). aria-hidden alone hid it from a screen reader while Tab
// still reached its five buttons (html-validate hidden-focusable).
const { test, expect } = require("@playwright/test");

test.use({ storageState: { cookies: [], origins: [] } });

async function focused(page) {
  return page.evaluate(() => document.activeElement && document.activeElement.className);
}

test("the closed drawer's buttons take no focus; open, they do; closed again, they do not", async ({
  page,
}) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const drawer = page.locator("#aidrawer");
  const question = page.locator("#aidrawer .aid-q").first();
  await expect(drawer).toHaveJSProperty("inert", true);
  await question.focus();
  expect(await focused(page)).not.toBe("aid-q");

  await page.locator("#aiOpen").click();
  await expect(drawer).toHaveJSProperty("inert", false);
  await question.focus();
  expect(await focused(page)).toBe("aid-q");

  await page.locator("#aiClose").click();
  await expect(drawer).toHaveJSProperty("inert", true);
  await question.focus();
  expect(await focused(page)).not.toBe("aid-q");
});
