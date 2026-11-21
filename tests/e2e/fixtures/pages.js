// Every page the shell lists, opened in turn by its own controls: each workspace as it opens,
// then each of its sub-views and each view of that. `visit({ ws, sub, view })` runs at each stop;
// `sub` and `view` are null where there is none (a workspace as it opens; a sub-view with no
// view bar). Returns the workspaces walked.
async function eachPage(page, visit) {
  const workspaces = await page
    .locator(".navitem[data-ws]")
    .evaluateAll((ns) => ns.map((n) => n.dataset.ws));
  for (const ws of workspaces) {
    await page.locator(`.navitem[data-ws="${ws}"]`).click();
    await visit({ ws, sub: null, view: null });
    for (const sub of await page
      .locator("#subnav button[data-sub]:not(.na)")
      .evaluateAll((bs) => bs.map((b) => b.dataset.sub))) {
      await page.locator(`#subnav button[data-sub="${sub}"]`).click();
      const views = await page
        .locator("#viewbar .vtab:not(.na)")
        .evaluateAll((bs) => bs.map((b) => b.dataset.view));
      for (const view of views.length ? views : [null]) {
        if (view) await page.locator(`#viewbar .vtab[data-view="${view}"]`).click();
        await visit({ ws, sub, view });
      }
    }
  }
  return workspaces;
}

module.exports = { eachPage };
