/*
 * The Trade Desk's Liquidity card draws the route's served readout (/api/order-flow/microstructure
 * `readout`) for SPY's real 2026-11-02 books; it computes nothing. Any page error fails the test.
 * Its own spec file: Playwright runs spec files side by side and a file's tests in order.
 */
const { test, expect } = require('@playwright/test');
const {
  READOUT_LIVE, READOUT_OFFLINE, READOUT_NO_BOOK, READOUT_AUCTION, READOUT_EVERY_LINE, LIVE_COMP, intercept, watchErrors,
} = require('./fixtures/trade_desk');

test.describe('Desk: the Liquidity card draws the served order-imbalance readout', () => {
  async function openDesk(page, body, keep) {
    await intercept(page);
    await page.route('**/api/order-flow/microstructure**', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(body) }));
    await page.addInitScript((k) => { try { localStorage.setItem('ed_ticker', 'SPY'); localStorage.setItem('ed_ws', 'trade-desk');
      localStorage.setItem('ed_sub', 'desk'); localStorage.setItem('ed_book_venue', 'NYSE_BOOK');
      if (!k) { localStorage.removeItem('ed.desk.liqvenue'); localStorage.removeItem('ed.desk.liqview'); } } catch (e) {} }, keep);
    await page.goto('/', { waitUntil: 'domcontentloaded' });
  }
  const card = (page) => page.locator('#tdmCardLiq');
  const left = (pct) => (50 + pct * 0.45) + '%';

  test('on the operator\'s 1920×950 window every card shows whole, the Desk does not scroll, and the sentence is high contrast', async ({ page }) => {
    const errs = watchErrors(page);
    // the operator's window (Edge maximized on 1920×1080), then a smaller laptop window, where the Desk may scroll
    for (const [width, height] of [[1920, 950], [1366, 650]]) {
      await page.setViewportSize({ width, height });
      for (const body of [READOUT_LIVE, READOUT_AUCTION, READOUT_OFFLINE, READOUT_NO_BOOK, READOUT_EVERY_LINE]) {
        await openDesk(page, body);
        await expect(card(page).locator('.liq-body > *').first()).toBeVisible();
        const cut = await page.evaluate((whole) => {
          const out = [];
          const root = document.getElementById('tdmRoot');
          if (whole && root.scrollHeight > root.clientHeight) out.push('the Desk scrolls: ' + root.scrollHeight + ' > ' + root.clientHeight);
          // no part of the Desk is squeezed below its content: the map, the cards, the strip, the footer
          [...root.children, document.querySelector('#tdmRoot .tdm-map')].forEach((p) => {
            if (p.offsetHeight && p.scrollHeight > p.clientHeight + 1) out.push((p.id || p.className) + ' is squeezed: ' + p.scrollHeight + ' > ' + p.clientHeight);
          });
          const map = document.querySelector('#tdmRoot .tdm-main');
          if (map && map.getBoundingClientRect().height < 380) out.push('the market map is under 380 px: ' + map.getBoundingClientRect().height);
          document.querySelectorAll('#tdmCards > .tdm-card').forEach((c) => {
            // the card hides what passes its edge (overflow: hidden)
            const box = c.getBoundingClientRect(), bottom = box.bottom + 0.5, right = box.right + 0.5;
            c.querySelectorAll('*').forEach((e) => {
              const r = e.getBoundingClientRect();
              if (!r.width || !r.height) return;
              if (r.bottom > bottom || r.right > right) out.push(c.id + ': ' + e.tagName + ' "' + e.textContent.slice(0, 40) + '" runs past the card by ' + Math.round(Math.max(r.bottom - bottom, r.right - right)) + 'px');
              const s = getComputedStyle(e);
              if (/hidden|clip/.test(s.overflowX + s.overflowY) &&
                  (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1)) {
                out.push(c.id + ': ' + e.tagName + '.' + e.className + ' "' + e.textContent.slice(0, 40) + '" is clipped');
              }
            });
          });
          return out;
        }, width === 1920);
        expect(cut, width + '×' + height + ' ' + JSON.stringify(cut)).toEqual([]);
      }
    }
    // every line the card can add, at once, shows on it
    await page.setViewportSize({ width: 1920, height: 950 });
    await openDesk(page, READOUT_EVERY_LINE);
    const all = READOUT_EVERY_LINE.readout, every = all.venues.COMPOSITE;
    for (const t of ['BOOK CROSSED', 'BOOK ' + every.feed_label, all.auction_text, every.dedup_partial_text, every.not_live_text]) {
      await expect(card(page).locator('.liq-body')).toContainText(t);
    }
    await openDesk(page, READOUT_LIVE);
    const look = await card(page).locator('.liq-sent').evaluate((e) => {
      const s = getComputedStyle(e), probe = document.createElement('i');
      probe.style.color = 'var(--ed-ink)';   // the brightest ink the console has
      document.body.appendChild(probe);
      const ink = getComputedStyle(probe).color;
      probe.remove();
      return { color: s.color, weight: s.fontWeight, ink };
    });
    expect(look.color).toBe(look.ink);
    expect(look.weight).toBe('700');
    expect(errs).toEqual([]);
  });

  test('the default view is the composite, weighted: every element in order, from the served values', async ({ page }) => {
    const errs = watchErrors(page);
    await openDesk(page, READOUT_LIVE);
    const w = LIVE_COMP.views.weighted;
    await expect(card(page).locator('[data-liqvenue="COMPOSITE"]')).toHaveClass(/on/);
    await expect(card(page).locator('[data-liqview="weighted"]')).toHaveClass(/on/);
    await expect(card(page).locator('.liq-depth')).toContainText('price levels per side, not timeframes');
    await expect(card(page).locator('.tdm-src')).toHaveText('Schwab NYSE_BOOK + NASDAQ_BOOK · composite, newest quote of each exchange');
    // the whole source line shows, wrapped, never cut off
    expect(await card(page).locator('.tdm-src').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    const text = await card(page).locator('.liq-body').innerText();
    const span = (k, side) => '$' + READOUT_LIVE.readout.venues[k].views.weighted['span_' + side + '_text'];
    const order = ['price levels per side, not timeframes', 'WEIGHTED TOP-5 HEADLINE', w.side_word, w.pct_text,
      'Bids', w.bid_text, 'Asks', w.ask_text,
      w.sentence, 'Difference: ' + w.difference_text + ' shares · Total depth: ' + w.total_text + ' shares',
      'VENUES', 'AT THE TOUCH', LIVE_COMP.touch_text,
      'LEAN', w.held_text, w.flips_word + ' · ' + w.flips_2m + ' flips in 2 min',
      'Green NYSE · Red Nasdaq · Gold Composite · White ring marks the selected venue',
      'Top-5 spans, bid / ask: NYSE ' + span('NYSE_BOOK', 'bid') + ' / ' + span('NYSE_BOOK', 'ask') +
        ' · Nasdaq ' + span('NASDAQ_BOOK', 'bid') + ' / ' + span('NASDAQ_BOOK', 'ask'),
      'NYSE + Nasdaq only — not the whole market · Book ' + LIVE_COMP.book_time_ct];
    let at = -1;
    for (const s of order) { const i = text.indexOf(s, at + 1); expect(i, s).toBeGreaterThan(at); at = i; }
    await expect(card(page).locator('.liq-live')).toHaveText(w.live_text + ' live');
    // the served flag: NYSE and Nasdaq lean opposite ways at this depth
    expect(READOUT_LIVE.readout.disagree.weighted).toBe(true);
    await expect(card(page).locator('.liq-body')).toContainText('VENUES DISAGREE');
    // no predicted price move, no balance scale, no demo or not-live control
    await expect(card(page)).not.toContainText(/ticks|price goes/i);
    await expect(card(page).locator('button')).toHaveCount(8);
    expect(errs).toEqual([]);
  });

  test('the venue dots and the touch marker sit at 50% + pct × 0.45, the selected venue ringed', async ({ page }) => {
    const errs = watchErrors(page);
    await openDesk(page, READOUT_LIVE);
    for (const k of ['NYSE_BOOK', 'NASDAQ_BOOK', 'COMPOSITE']) {
      const dot = card(page).locator('.liq-dot.' + k);
      await expect(dot).toHaveAttribute('style', 'left:' + left(READOUT_LIVE.readout.venues[k].views.weighted.pct));
    }
    await expect(card(page).locator('.liq-dot.sel')).toHaveCount(1);
    await expect(card(page).locator('.liq-dot.COMPOSITE')).toHaveClass(/sel/);
    await expect(card(page).locator('.liq-gauge i')).toHaveAttribute('style', 'left:' + left(LIVE_COMP.touch_pct));
    expect(errs).toEqual([]);
  });

  test('a depth switch redraws headline, bars, sentence and dots from that depth; a venue switch from that venue', async ({ page }) => {
    const errs = watchErrors(page);
    await openDesk(page, READOUT_LIVE);
    await expect(card(page).locator('[data-liqview="3"]')).toBeVisible();
    await card(page).locator('[data-liqview="3"]').click();
    const v3 = LIVE_COMP.views['3'];
    await expect(card(page).locator('.liq-body')).toContainText('TOP 3 HEADLINE');
    await expect(card(page).locator('.liq-pct')).toHaveText(v3.pct_text);
    await expect(card(page).locator('.liq-sent')).toHaveText(v3.sentence);
    await expect(card(page).locator('.liq-body')).toContainText('Difference: ' + v3.difference_text + ' shares');
    await expect(card(page).locator('.liq-dot.NASDAQ_BOOK')).toHaveAttribute('style', 'left:' + left(READOUT_LIVE.readout.venues.NASDAQ_BOOK.views['3'].pct));
    await expect(card(page).locator('.liq-body')).toContainText(READOUT_LIVE.readout.disagree['3'] ? 'VENUES DISAGREE' : 'VENUES');
    // the touch stays the venue's top 1 whatever the depth
    await expect(card(page).locator('.liq-gauge i')).toHaveAttribute('style', 'left:' + left(LIVE_COMP.touch_pct));
    await card(page).locator('.bookvenue [data-venue="NYSE_BOOK"]').click();
    const n = READOUT_LIVE.readout.venues.NYSE_BOOK;
    await expect(card(page).locator('.tdm-src')).toHaveText('Schwab NYSE_BOOK · live book');
    await expect(card(page).locator('.liq-pct')).toHaveText(n.views['3'].pct_text);
    await expect(card(page).locator('.liq-dot.NYSE_BOOK')).toHaveClass(/sel/);
    await expect(card(page).locator('.liq-lbl b').first()).toHaveText(n.touch_text);
    expect(errs).toEqual([]);
  });

  test('the composite is one read of one venue: no second book request', async ({ page }) => {
    const reads = [];
    page.on('request', (r) => { if (r.url().includes('/api/order-flow/microstructure')) reads.push(r.url()); });
    await openDesk(page, READOUT_LIVE);
    await expect(card(page).locator('.liq-pct')).toHaveText(LIVE_COMP.views.weighted.pct_text);
    await page.waitForTimeout(500);
    expect(reads.length).toBe(1);
    expect(reads[0]).toContain('venue=NYSE_BOOK');
  });

  test('a book that stopped keeps its last numbers greyed, with its time and the card\'s not-live words', async ({ page }) => {
    const errs = watchErrors(page);
    await openDesk(page, READOUT_OFFLINE);
    const c = READOUT_OFFLINE.readout.venues.COMPOSITE;
    await expect(card(page).locator('.liq-body')).toHaveClass(/stale/);
    await expect(card(page).locator('.liq-body')).toContainText('BOOK OFFLINE');
    await expect(card(page).locator('.liq-body')).toContainText(c.not_live_text);
    await expect(card(page).locator('.tdm-src')).toHaveText('Schwab NYSE_BOOK + NASDAQ_BOOK · composite, newest quote of each exchange · book ' + c.book_time_ct + ' · ' + c.book_age_text + ' old · not live');
    await expect(card(page).locator('.liq-pct')).toHaveText(c.views.weighted.pct_text);
    expect(errs).toEqual([]);
  });

  test('no book: NO BOOK in plain words, no number, the cause on the source line', async ({ page }) => {
    const errs = watchErrors(page);
    await openDesk(page, READOUT_NO_BOOK);
    await expect(card(page).locator('.liq-body')).toContainText('NO BOOK');
    await expect(card(page).locator('.liq-body')).toContainText('No book for this symbol right now');
    await expect(card(page).locator('.tdm-src')).toContainText('no book for this symbol right now');
    await expect(card(page).locator('.liq-body')).not.toContainText('%');
    expect(errs).toEqual([]);
  });

  test('inside the closing auction the number stands and the auction line is added', async ({ page }) => {
    const errs = watchErrors(page);
    await openDesk(page, READOUT_AUCTION);
    const c = READOUT_AUCTION.readout.venues.COMPOSITE;
    await expect(card(page).locator('.liq-body')).toContainText(READOUT_AUCTION.readout.auction_text);
    await expect(card(page).locator('.liq-pct')).toHaveText(c.views.weighted.pct_text);
    // the line sits after the sentence box, before the venues
    const text = await card(page).locator('.liq-body').innerText();
    expect(text.indexOf(READOUT_AUCTION.readout.auction_text)).toBeGreaterThan(text.indexOf(await card(page).locator('.liq-sent').innerText()));
    expect(text.indexOf(READOUT_AUCTION.readout.auction_text)).toBeLessThan(text.indexOf('VENUES'));
    expect(errs).toEqual([]);
  });

  test('a crossed book flags it, keeps its number and totals, and withholds the sentence', async ({ page }) => {
    const errs = watchErrors(page);
    await openDesk(page, READOUT_AUCTION);
    const c = READOUT_AUCTION.readout.venues.COMPOSITE;
    expect(c.touch_flag).toBe('BOOK CROSSED');
    await expect(card(page).locator('.liq-body')).toContainText('BOOK CROSSED');
    await expect(card(page).locator('.liq-pct')).toHaveText(c.views.weighted.pct_text);
    await expect(card(page).locator('.liq-body')).toContainText(c.views.weighted.ask_text);
    await expect(card(page).locator('.liq-sent')).toHaveText('Book crossed — bid and ask overlap, no balancing sentence.');
    expect(errs).toEqual([]);
  });

  test('the headline opens the detail panel with the served words; Close shuts it', async ({ page }) => {
    const errs = watchErrors(page);
    await openDesk(page, READOUT_LIVE);
    const d = READOUT_LIVE.readout.detail;
    await expect(card(page).locator('.liq-detail')).toHaveCount(0);
    await expect(card(page).locator('.liq-hl')).toBeVisible();
    await card(page).locator('.liq-hl').click();
    const panel = card(page).locator('.liq-detail');
    for (const t of [d.weights, d.zones, d.construction, d.spans, d.books]) {
      await expect(panel).toContainText(t);
    }
    await panel.locator('[data-liqclose]').click();
    await expect(card(page).locator('.liq-detail')).toHaveCount(0);
    expect(errs).toEqual([]);
  });

  test('the card paints at most once a second, reads on each push, and never polls', async ({ page }) => {
    const errs = watchErrors(page);
    const reads = [];
    page.on('request', (r) => { if (r.url().includes('/api/order-flow/microstructure')) reads.push(r.url()); });
    await openDesk(page, READOUT_LIVE);
    await expect(card(page).locator('.liq-pct')).toHaveText(LIVE_COMP.views.weighted.pct_text);
    await page.waitForTimeout(1200);
    const before = await page.evaluate(() => window.EdTradeDeskMap.state().liqPaints);
    const n0 = reads.length;
    await page.evaluate(() => { for (let i = 0; i < 5; i++) document.dispatchEvent(new CustomEvent('ed:changed', { detail: { kind: 'flow' } })); });
    await expect.poll(() => reads.length).toBe(n0 + 5);
    await page.waitForTimeout(400);
    // five answers inside a second: one paint now, at most one more when the second is up
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().liqPaints)).toBeLessThanOrEqual(before + 1);
    await page.waitForTimeout(1000);
    expect(await page.evaluate(() => window.EdTradeDeskMap.state().liqPaints)).toBeLessThanOrEqual(before + 2);
    const n1 = reads.length;
    await page.waitForTimeout(2500);
    expect(reads.length).toBe(n1);   // no push, no read
    expect(errs).toEqual([]);
  });
});
