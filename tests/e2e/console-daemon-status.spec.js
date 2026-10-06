// The header's Schwab and Record: the capture daemon's own lines, from its heartbeat on the price
// socket, drawn as served (capture.Daemon._schwab_line; tests/test_data_path_startup_v1.py holds
// the daemon's real line for a refused client). The daemon's socket is stood in for here.
const { test, expect } = require('@playwright/test');

const NOT_CONNECTED = 'NOT CONNECTED since Tue 10/06 04:05 PM CT';
const WHY = 'ConnectionError: no Schwab client (Token file not found: C:\\runtime\\schwab_token.json.)';

test('the header shows why Schwab is not connected, as the daemon says it', async ({ page }) => {
  await page.addInitScript(() => { try { localStorage.setItem('ed_ticker', 'SPY'); } catch (e) {} });
  await page.routeWebSocket(/:1\/$/, (ws) => {
    ws.onMessage((m) => {
      let req; try { req = JSON.parse(String(m)); } catch (e) { return; }
      if (!req || req.op !== 'subscribe') return;
      ws.send(JSON.stringify({ type: 'symbols', symbols: [{ requested: 'SPY', key: 'SPY', display: 'SPY' }] }));
      ws.send(JSON.stringify({ type: 'feed', rows: [], feed: {
        ts: Date.now() / 1000, schwab_socket_open: false, writer: null,
        schwab: { line: NOT_CONNECTED, cls: 'neg', why: WHY } } }));
    });
  });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#hSchwab')).toHaveText(NOT_CONNECTED);
  await expect(page.locator('#hSchwab')).toHaveClass('v neg');
  await expect(page.locator('#hSchwab')).toHaveAttribute('title', WHY);
  await expect(page.locator('#hRecord')).toHaveText('—');
});
