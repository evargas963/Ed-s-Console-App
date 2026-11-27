/*
 * Every page's text is readable in both themes: WCAG 2.2's contrast minimum (1.4.3, level AA:
 * 4.5 to 1, 3 to 1 for large text), as axe-core's color-contrast rule measures it on each page the
 * shell lists (fixtures/pages.js). The operator's high-contrast order (no muted grays), held by the
 * standard tool. The page is opened with no program behind its socket, so each panel draws its
 * empty state.
 */
const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const { eachPage } = require("./fixtures/pages");

for (const theme of ["dark", "light"]) {
  test(`every page's text meets WCAG 2.2 AA contrast in the ${theme} theme`, async ({ page }) => {
    await page.goto("/");
    await page.evaluate((t) => window.EdTheme.setPref(t), theme);
    const found = [];
    await eachPage(page, async ({ ws, sub, view }) => {
      const { violations } = await new AxeBuilder({ page }).withRules(["color-contrast"]).analyze();
      for (const n of violations.flatMap((v) => v.nodes)) {
        const where = [ws, sub, view].filter(Boolean).join("/");
        found.push(`${where}: ${n.target.join(" ")}: ${n.any.map((a) => a.message).join("; ")}`);
      }
    });
    expect(found).toEqual([]);
  });
}
