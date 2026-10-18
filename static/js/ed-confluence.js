/* Trade Desk / Confluence Matrix. Draws /api/confluence. Computes nothing financial.
   Pill positions are display geometry between the served strikes. */
(function () {
  'use strict';

  var expiry = null;
  var selectedStrike = null;
  var pinned = null;
  var lastRows = [];
  var lastLevels = [];
  var lastSpot = null;
  var lastSpotText = null;
  var lastBody = null;
  var bound = false;

  var HEADS = [
    ['Price / session', 'exact price', 'Session reference levels. POC keeps its est mark.', false],
    ['Options levels', 'chain + same-day', 'Chain levels and the same-day levels, each at its own price.', false],
    ['Strike', '', 'Listed strike.', false],
    ['Δ spot', 'points', 'Strike minus the chain spot. Blue marks the one-day expected move.', false],
    ['Composite', '', 'The score for this strike, up to the preset ceiling.', true],
    ['Net GEX', '$M / 1%', 'Net gamma exposure in millions of dollars per 1% move.', false],
    ['OI', 'contracts', 'Open interest in contracts. Green intensity shows size.', false],
    ['P/C GEX', 'ratio', 'Put gamma divided by call gamma. Above 1 is put-heavy.', false],
    ['Gross GEX', '$M / 1%', 'Call gamma plus put gamma, in millions per 1% move. Green shows size.', true],
    ['ΔGEX', '$M / 1%', 'No change in gamma is produced.', false],
    ['Opt Vol', 'contracts', 'Options volume this session, in contracts. Green intensity shows size.', false],
    ['P/C vol', 'ratio', 'Put volume divided by call volume. Above 1 is put-heavy.', false],
    ['Vol/OI', 'ratio', 'Options volume divided by open interest.', false],
    ['Flow', 'signed $M', 'No signed flow is produced.', true],
    ['DEX', '$M', 'Delta exposure in millions of dollars.', false],
    ['Vanna', '$M / vol pt', 'Vanna in dollars per volatility point.', false],
    ['IV', '%', 'Implied volatility for the strike.', false],
    ['Charm', 'k shares/day', 'Charm in thousands of delta-shares per day.', false]
  ];

  function state() {
    if (!window.EdShell) return null;
    return window.EdShell.getState();
  }

  function text(value) {
    if (value == null) return '—';
    if (value === '') return '—';
    return String(value);
  }

  function esc(value) {
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  }

  function loadImpl(signal) {
    var st = state();
    if (!st || st.workspace !== 'trade-desk' || st.subview !== 'confluence') return;
    var tk = st.key || st.ticker;
    var box = document.getElementById('cmBody');
    if (!box) return;
    if (!tk) {
      box.innerHTML = '<div class="placeholder"><div class="sm">Pick a ticker.</div></div>';
      return;
    }
    var url = '/api/confluence?ticker=' + encodeURIComponent(tk);
    if (expiry) url += '&expiry=' + encodeURIComponent(expiry);
    return fetch(url, { cache: 'no-store', signal: signal }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    }).then(draw).catch(function (e) {
      if (e && e.name === 'AbortError') return;
      box.innerHTML = '<div class="placeholder"><div class="sm">The matrix request failed.</div></div>';
    });
  }

  var _loader = window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(signal); });

  function load() {
    var st = state();
    if (!st || st.workspace !== 'trade-desk' || st.subview !== 'confluence') return;
    var tk = st.key || st.ticker;
    _loader.trigger((tk == null ? '' : tk) + '|' + (expiry == null ? '' : expiry));
  }

  function anchorY(price, rows) {
    var n = rows.length;
    var height = n * 52;
    if (!n) return 0;
    var i;
    for (i = 0; i < n - 1; i++) {
      var hi = rows[i].strike;
      var lo = rows[i + 1].strike;
      if (price <= hi && price >= lo) {
        var span = hi - lo;
        var frac = span === 0 ? 0 : (hi - price) / span;
        return 26 + i * 52 + frac * 52;
      }
    }
    if (price >= rows[0].strike) return 26;
    return height - 26;
  }

  function rails(rows, levels) {
    var n = rows.length;
    var height = n * 52;
    if (!n) return '';
    var hi = rows[0].strike;
    var lo = rows[n - 1].strike;
    var inside = levels.filter(function (lv) { return lv.price <= hi && lv.price >= lo; });
    var seen = {};
    var prices = [];
    inside.forEach(function (lv) {
      if (!seen[lv.price_text]) {
        seen[lv.price_text] = lv.price;
        prices.push(lv);
      }
    });
    var svg = '<svg viewBox="0 0 276 ' + height + '" width="276" height="' + height + '" aria-label="Price levels">';
    prices.forEach(function (lv) {
      var start = inside.some(function (o) { return o.price_text === lv.price_text && o.lane === 'session'; }) ? 8 : 146;
      svg += '<path class="price-line" data-price="' + esc(lv.price_text) + '" d="M' + start + ' ' + anchorY(lv.price, rows) + ' H290" stroke="#718198" opacity=".7"/>';
    });
    ['session', 'options'].forEach(function (lane, laneIndex) {
      var group = inside.filter(function (o) { return o.lane === lane; });
      group.sort(function (a, b) { return b.price - a.price; });
      var pos = group.map(function (o) {
        var y = anchorY(o.price, rows);
        if (y < 12) return 12;
        if (y > height - 12) return height - 12;
        return y;
      });
      var i;
      for (i = 1; i < pos.length; i++) {
        if (pos[i] < pos[i - 1] + 25) pos[i] = pos[i - 1] + 25;
      }
      if (pos.length && pos[pos.length - 1] > height - 12) {
        pos[pos.length - 1] = height - 12;
        for (i = pos.length - 2; i >= 0; i--) {
          if (pos[i] > pos[i + 1] - 25) pos[i] = pos[i + 1] - 25;
        }
      }
      group.forEach(function (lv, index) {
        var x = laneIndex * 138 + 7;
        var anchor = anchorY(lv.price, rows);
        var label = pos[index];
        var connector = Math.abs(label - anchor) > 0.1
          ? '<path d="M' + (x + 120) + ' ' + label + ' L' + (x + 126) + ' ' + anchor + '" fill="none" stroke="#8b9db5"/>'
          : '';
        svg += '<g class="level-pill" role="button" tabindex="0" data-price="' + esc(lv.price_text) + '" aria-label="' + esc(lv.title + ' ' + lv.price_text) + '"><title>' + esc(lv.title + ': ' + lv.price_text) + '</title>' + connector + '<rect x="' + x + '" y="' + (label - 10) + '" width="120" height="20" rx="3" fill="#111b29" stroke="#56677f"/><text x="' + (x + 60) + '" y="' + (label + 4) + '" text-anchor="middle" fill="white" font-size="10" font-weight="700">' + esc(lv.abbrev + ' ' + lv.price_text) + '</text></g>';
      });
    });
    return svg + '</svg>';
  }

  function offButtons(rows, levels, side) {
    if (!rows.length) return '';
    var hi = rows[0].strike;
    var lo = rows[rows.length - 1].strike;
    var list = levels.filter(function (lv) {
      return side === 'above' ? lv.price > hi : lv.price < lo;
    });
    return list.map(function (lv) {
      var prefix = side === 'above' ? '↑ ' : '↓ ';
      return '<button type="button" data-price="' + esc(lv.price_text) + '" title="' + esc(lv.title + ' · outside visible strike range') + '">' + esc(prefix + lv.abbrev + ' ' + lv.price_text) + '</button>';
    }).join('');
  }

  function heatCell(shown, style, reason, edge) {
    var missing = shown == null || shown === '';
    var cls = (edge ? 'edge ' : '') + (missing ? 'missing' : '');
    var title = missing && reason ? ' title="' + esc(reason) + '"' : '';
    var paint = !missing && style ? ' style="' + esc(style) + '"' : '';
    return '<td class="' + cls + '"' + title + paint + '>' + (missing ? '—' : esc(shown)) + '</td>';
  }

  function showDetail(row) {
    var detail = document.getElementById('cmDetail');
    if (!detail) return;
    if (!row) {
      detail.innerHTML = '<div class="eyebrow">Selected strike</div><p>Click a strike for its numbers.</p>';
      return;
    }
    var missing = Array.isArray(row.missing) ? row.missing : [];
    var parts = Array.isArray(row.contributions) ? row.contributions : [];
    var factors = Array.isArray(row.factors) ? row.factors : [];
    var ceiling = lastBody && lastBody.ceiling != null ? lastBody.ceiling : null;
    var scoreLine = row.score == null
      ? text(missing.join(', '))
      : text(row.score_text) + ' / ' + text(ceiling);
    var facts = [
      ['Net GEX', row.net_gex_text, row.net_reason, '$ per 1% move'],
      ['Open interest', row.oi_text, row.oi_reason, 'contracts'],
      ['Options Volume', row.volume_text, row.volume_reason, 'session contracts'],
      ['IV', row.iv_text, row.iv_reason, 'implied volatility'],
      ['Flow', row.flow_text, row.flow_reason, 'premium dollars'],
      ['Charm', row.charm_text, row.charm_reason, 'delta-shares / day']
    ];
    var cards = facts.map(function (f) {
      var missingValue = f[1] == null || f[1] === '';
      var caption = missingValue && f[2] ? f[2] : f[3];
      return '<div class="card"><label>' + esc(f[0]) + '</label><b>' + (missingValue ? '—' : esc(f[1])) + '</b><span>' + esc(caption) + '</span></div>';
    }).join('');
    var why = parts.map(function (p) { return p.label + ' ' + p.text; }).join(' · ');
    var lines = factors.map(function (p) {
      return p.label + ' ' + p.text + '  raw ' + text(p.raw_text) + '  norm ' + text(p.normalized_text) + '  weight ' + text(p.weight_text);
    });
    var note = why;
    if (lines.length) note += (note ? '\n' : '') + lines.join('\n');
    if (missing.length && row.score == null) note += (note ? '\n' : '') + missing.join(', ');
    detail.innerHTML = '<div class="eyebrow">Selected strike</div><h2>' + esc(text(row.strike_text) + ' · ' + text(row.distance_text) + ' points from spot') + '</h2><p>Composite ' + esc(scoreLine) + '</p><div class="cards">' + cards + '</div>' + (note ? '<p class="note">' + esc(note) + '</p>' : '');
  }

  function highlight(priceText) {
    var box = document.getElementById('cmBody');
    if (!box) return;
    box.querySelectorAll('[data-price]').forEach(function (el) {
      var on = priceText != null && el.getAttribute('data-price') === priceText;
      el.classList.toggle('lit', on);
      el.classList.toggle('pinned', on);
    });
    var read = document.getElementById('cmRead');
    if (!read) return;
    if (priceText == null) {
      read.textContent = 'Hover or focus a level; click to pin its line. Escape clears the selection.';
      return;
    }
    var names = lastLevels.filter(function (lv) { return lv.price_text === priceText; }).map(function (lv) { return lv.title; });
    var line = names.join(' + ') + ' · ' + priceText;
    if (pinned === priceText) line += ' · PINNED';
    read.textContent = line;
  }

  function position() {
    var line = document.getElementById('spotline');
    var tbody = document.getElementById('cmRows');
    if (!line || !tbody) return;
    var trs = tbody.querySelectorAll('tr');
    var wrap = tbody.closest('.matrix-wrap');
    if (!trs.length || lastSpot == null || !wrap) {
      line.style.display = 'none';
      return;
    }
    var points = [];
    var i;
    for (i = 0; i < trs.length; i++) {
      var rect = trs[i].getBoundingClientRect();
      var wrapRect = wrap.getBoundingClientRect();
      points.push({ price: lastRows[i].strike, y: rect.top - wrapRect.top + rect.height / 2 });
    }
    var top = null;
    if (points.length === 1 && points[0].price === lastSpot) top = points[0].y;
    for (i = 0; i < points.length - 1; i++) {
      if (lastSpot <= points[i].price && lastSpot >= points[i + 1].price) {
        var span = points[i].price - points[i + 1].price;
        var frac = span === 0 ? 0 : (points[i].price - lastSpot) / span;
        top = points[i].y + frac * (points[i + 1].y - points[i].y);
        break;
      }
    }
    if (top == null) {
      line.style.display = 'none';
      return;
    }
    line.style.display = '';
    line.style.top = top + 'px';
    line.innerHTML = '<span>SPOT ' + esc(text(lastSpotText)) + '</span>';
  }

  function onClick(e) {
    var box = document.getElementById('cmBody');
    if (!box || !box.contains(e.target)) return;
    var level = e.target.closest('[data-price]');
    if (level) {
      var priceText = level.getAttribute('data-price');
      pinned = pinned === priceText ? null : priceText;
      highlight(pinned);
      return;
    }
    var row = e.target.closest('tr[data-i]');
    if (!row || e.target.closest('.rail')) return;
    var picked = lastRows[Number(row.getAttribute('data-i'))];
    if (!picked) return;
    selectedStrike = picked.strike;
    box.querySelectorAll('tr[data-i]').forEach(function (other) {
      other.classList.toggle('selected', other === row);
    });
    showDetail(picked);
  }

  function bind() {
    if (bound) return;
    var box = document.getElementById('cmBody');
    if (!box) return;
    bound = true;
    box.addEventListener('click', onClick);
    box.addEventListener('mouseover', function (e) {
      var level = e.target.closest('[data-price]');
      if (level && box.contains(level)) highlight(level.getAttribute('data-price'));
    });
    box.addEventListener('mouseout', function (e) {
      var level = e.target.closest('[data-price]');
      if (!level || !box.contains(level)) return;
      if (e.relatedTarget && level.contains(e.relatedTarget)) return;
      highlight(pinned);
    });
    box.addEventListener('focusin', function (e) {
      var level = e.target.closest('[data-price]');
      if (level) highlight(level.getAttribute('data-price'));
    });
    box.addEventListener('focusout', function () { highlight(pinned); });
    box.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        pinned = null;
        highlight(null);
        return;
      }
      var pill = e.target.closest('.level-pill');
      var row = e.target.closest('tr[data-i]');
      if ((e.key === 'Enter' || e.key === ' ') && (pill || row)) {
        e.preventDefault();
        onClick(e);
      }
    });
    window.addEventListener('resize', function () { position(); });
  }

  function draw(body) {
    var box = document.getElementById('cmBody');
    if (!box) return;
    bind();
    lastBody = body;
    var names = Array.isArray(body.expiries) ? body.expiries : [];
    var held = false;
    names.forEach(function (e) { if (e.expiry === expiry) held = true; });
    if (body.expiry && (expiry == null || !held)) expiry = body.expiry;
    var pick = '';
    if (names.length) {
      pick = '<label class="expiry-pick">Expiry<select id="cmExp">';
      names.forEach(function (e) {
        pick += '<option value="' + esc(e.expiry) + '"' + (e.expiry === expiry ? ' selected' : '') + '>' + esc(e.label) + '</option>';
      });
      pick += '</select></label>';
    }
    var rows = Array.isArray(body.rows) ? body.rows : [];
    var levels = Array.isArray(body.levels) ? body.levels : [];
    lastRows = rows;
    lastLevels = levels;
    lastSpot = typeof body.spot === 'number' ? body.spot : null;
    lastSpotText = body.spot_text;
    if (!rows.some(function (r) { return r.strike === selectedStrike; })) {
      var fallback = null;
      rows.forEach(function (r) { if (r.spot_line && fallback == null) fallback = r; });
      if (fallback == null && rows.length) fallback = rows[0];
      selectedStrike = fallback == null ? null : fallback.strike;
    }
    var summary = [
      ['SPOT', body.spot_text, ''],
      ['GAMMA REGIME · CHAIN', body.regime_text, ''],
      ['MODELED FLIP · CHAIN', body.flip_text, body.expiry ? body.expiry : ''],
      ['EXPECTED MOVE · CHAIN', body.move_text, body.move_text ? 'one day' : ''],
      ['0DTE PIN · MODELED', body.pin_text, body.pin_text ? 'same-day' : '']
    ].map(function (cell) {
      var small = cell[2] ? '<small>' + esc(cell[2]) + '</small>' : '';
      return '<div class="stat"><label>' + esc(cell[0]) + '</label><strong>' + esc(text(cell[1])) + '</strong>' + small + '</div>';
    }).join('');
    var status = body.available
      ? (body.chain_as_of_time_ct ? 'Chain as of ' + body.chain_as_of_time_ct : 'The chain time was not sent.')
      : text(body.reason);
    var heads = '<tr><th class="group edge" colspan="5">Price context</th><th class="group edge" colspan="4">Positioning</th><th class="group edge" colspan="5">Activity</th><th class="group" colspan="4">Sensitivity</th></tr><tr>';
    HEADS.forEach(function (col, index) {
      var secondary = '<small>' + esc(col[1]) + '</small>';
      if (index === 4) {
        secondary = '<small>0–100</small>';
        if (body.preset) secondary += '<small>' + esc(body.preset) + '</small>';
      }
      heads += '<th tabindex="0" title="' + esc(col[2]) + '"' + (col[3] ? ' class="edge"' : '') + '>' + esc(col[0]) + secondary + '</th>';
    });
    heads += '</tr>';
    var bodyRows = '';
    var low = typeof body.move_low === 'number' ? body.move_low : null;
    var high = typeof body.move_high === 'number' ? body.move_high : null;
    rows.forEach(function (row, i) {
      var inside = low != null && high != null && row.strike >= low && row.strike <= high;
      var scoreShown = row.score_text == null
        ? ''
        : '<button type="button" class="score" aria-label="Inspect strike ' + esc(text(row.strike_text)) + '">' + esc(row.score_text) + ' ›</button>';
      var scoreReason = Array.isArray(row.missing) ? row.missing.join(', ') : '';
      bodyRows += '<tr tabindex="0" class="data-row' + (row.strike === selectedStrike ? ' selected' : '') + '" data-i="' + i + '">';
      if (i === 0) {
        bodyRows += '<td class="rail edge" colspan="2" rowspan="' + rows.length + '">' + rails(rows, levels) + '</td>';
      }
      bodyRows += '<td class="strike">' + esc(text(row.strike_text)) + '</td>';
      bodyRows += '<td class="' + (inside ? 'inside' : '') + '">' + esc(text(row.distance_text)) + '</td>';
      if (row.score_text == null) {
        bodyRows += '<td class="edge missing" title="' + esc(scoreReason) + '">—</td>';
      } else {
        var paint = row.heat_background ? ' style="' + esc(row.heat_background) + '"' : '';
        bodyRows += '<td class="edge"' + paint + '>' + scoreShown + '</td>';
      }
      bodyRows += heatCell(row.net_gex_text, row.net_style, row.net_reason, false);
      bodyRows += heatCell(row.oi_text, row.oi_style, row.oi_reason, false);
      bodyRows += heatCell(row.pc_gex_text, row.pc_gex_style, row.pc_gex_reason, false);
      bodyRows += heatCell(row.gross_text, row.gross_style, row.gross_reason, true);
      bodyRows += heatCell(row.dgex_text, null, row.dgex_reason, false);
      bodyRows += heatCell(row.volume_text, row.volume_style, row.volume_reason, false);
      bodyRows += heatCell(row.pc_vol_text, row.pc_vol_style, row.pc_vol_reason, false);
      bodyRows += heatCell(row.vol_oi_text, row.vol_oi_style, row.vol_oi_reason, false);
      bodyRows += heatCell(row.flow_text, null, row.flow_reason, true);
      bodyRows += heatCell(row.dex_text, row.dex_style, row.dex_reason, false);
      bodyRows += heatCell(row.vanna_text, row.vanna_style, row.vanna_reason, false);
      bodyRows += heatCell(row.iv_text, row.iv_style, row.iv_reason, false);
      bodyRows += heatCell(row.charm_text, row.charm_style, row.charm_reason, false);
      bodyRows += '</tr>';
    });
    var notes = Array.isArray(body.notes) ? body.notes : [];
    var table = rows.length
      ? '<div class="frame" id="cmFrame"><div class="matrix-wrap"><table><colgroup><col style="width:138px"><col style="width:138px"><col style="width:74px"><col style="width:58px"><col style="width:75px"><col span="13"></colgroup><thead>' + heads + '</thead><tbody id="cmRows">' + bodyRows + '</tbody></table><div id="spotline"></div></div></div>'
      : '<div class="status">' + esc(text(body.reason)) + '</div>';
    var kept = null;
    rows.forEach(function (row) { if (row.strike === selectedStrike) kept = row; });
    box.innerHTML = '<div class="cm-page"><div class="top"><div><h1>Confluence matrix</h1><p>Hover a level to trace its price · Click to pin it · Click any strike for details.</p></div>' + pick + '</div><div class="summary">' + summary + '</div><div class="status">' + esc(status) + '</div><div class="offscreen" id="cmAbove">' + offButtons(rows, levels, 'above') + '</div>' + table + '<div class="offscreen" id="cmBelow">' + offButtons(rows, levels, 'below') + '</div><div class="levelread" id="cmRead">Hover or focus a level; click to pin its line. Escape clears the selection.</div><div class="legend"><span><i class="scale"></i> Red − / green + · brighter = larger magnitude within each column.</span><span>OI, Opt Vol, Gross GEX, IV and composite: green intensity = size only. P/C: red put-heavy / green call-heavy.</span></div><div class="detail" id="cmDetail"></div>' + (notes.length ? '<p class="foot">' + esc(notes.join(' ')) + '</p>' : '') + '</div>';
    var sel = document.getElementById('cmExp');
    if (sel) {
      sel.addEventListener('change', function () {
        if (sel.value === expiry) return;
        expiry = sel.value;
        selectedStrike = null;
        pinned = null;
        load();
      });
    }
    showDetail(kept);
    highlight(pinned);
    requestAnimationFrame(position);
  }

  document.addEventListener('ed:view', function () { selectedStrike = null; load(); });
  document.addEventListener('ed:ticker', function () { expiry = null; selectedStrike = null; pinned = null; load(); });
  document.addEventListener('ed:changed', function (e) {
    var kind = e.detail && e.detail.kind;
    if (kind === 'levels' || kind === 'chain') load();
  });
})();
