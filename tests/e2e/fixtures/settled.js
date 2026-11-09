// The page's requests, watched from the test, so a check that something did NOT happen waits for the
// page's own work to run out instead of a guessed time: every request answered or cut short, and two
// tasks of the page run after that with no new request, so each answer's own work (its draw, a read
// it starts) has run. A server push stream (EventSource) stays open by design and is not counted.
// The tasks are MessageChannel messages, which page.clock does not hold, so this works with the
// page's clock paused too.
const { expect } = require('@playwright/test');

function watchRequests(page) {
  const open = new Set();
  const made = [];
  page.on('request', (r) => {
    if (r.resourceType() === 'eventsource') return;
    made.push(r);
    open.add(r);
  });
  page.on('requestfinished', (r) => open.delete(r));
  page.on('requestfailed', (r) => open.delete(r));
  const pageTask = () => page.evaluate(() => new Promise((resolve) => {
    const c = new MessageChannel();
    c.port1.onmessage = () => resolve(null);
    c.port2.postMessage(null);
  }));
  return {
    // `only`: the requests waited for (all of them unless a test holds one it never answers)
    async settled(only = () => true) {
      const outstanding = () => [...open].filter(only).length;
      const count = () => made.filter(only).length;
      for (let quiet = 0; quiet < 2;) {
        await expect.poll(outstanding).toBe(0);
        const before = count();
        await pageTask();
        quiet = count() === before && outstanding() === 0 ? quiet + 1 : 0;
      }
    },
  };
}

module.exports = { watchRequests };
