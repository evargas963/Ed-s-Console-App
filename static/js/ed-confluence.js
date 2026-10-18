/* Trade Desk / Confluence Matrix. Draws /api/confluence. Computes nothing. */
(function () {
  'use strict';

  var expiry = null;
  var selectedStrike = null;

  function state() {
    if (!window.EdShell) return null;
    return window.EdShell.getState();
  }

  function text(value) {
    if (value == null) return '—';
    if (value === '') return '—';
    return String(value);
  }

  function loadImpl(signal) {
    var st = state();
    if (!st || st.workspace !== 'trade-desk' || st.subview !== 'confluence') return;
    var tk = st.key || st.ticker;
    var box = document.getElementById('cmBody');
    var who = document.getElementById('cmTicker');
    if (!box) return;
    if (who) who.textContent = st.display || tk || '—';
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

  function draw(body) {
    var box = document.getElementById('cmBody');
    var time = document.getElementById('cmTime');
    var preset = document.getElementById('cmPreset');
    var exp = document.getElementById('cmExp');
    if (!box) return;
    if (expiry == null && body.expiry) expiry = body.expiry;
    if (time) time.textContent = body.chain_as_of_time_ct == null ? '' : body.chain_as_of_time_ct;
    if (preset) {
      preset.textContent = body.preset ? (body.preset + ' · ceiling ' + body.ceiling) : '';
    }
    var expiries = Array.isArray(body.expiries) ? body.expiries : [];
    if (exp) {
      exp.innerHTML = '';
      expiries.forEach(function (e) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'cm-exp-b' + (e.expiry === body.expiry ? ' on' : '');
        b.textContent = e.expiry + (e.dte == null ? '' : ' · ' + e.dte);
        b.addEventListener('click', function () { expiry = e.expiry; selectedStrike = null; load(); });
        exp.appendChild(b);
      });
    }
    if (!body.available) {
      box.innerHTML = '<div class="placeholder"><div class="sm">' + text(body.reason) + '</div></div>';
      return;
    }
    var weights = body.weights_in_score == null ? {} : body.weights_in_score;
    var notes = [];
    if (body.thin) notes.push('Thin book: fewer than 10 strikes.');
    var flat = Array.isArray(body.flat_factors) ? body.flat_factors : [];
    if (flat.length) notes.push(flat.join(', ') + ' does not vary, so it adds nothing.');
    var slopes = Array.isArray(body.slopes) ? body.slopes : [];
    var head = '<div class="cm-weights">' + Object.keys(weights).map(function (k) {
      return k + ' ' + weights[k];
    }).join(' · ') + '</div>';
    if (notes.length) head += '<div class="cm-weights">' + notes.join(' ') + '</div>';
    if (slopes.length) {
      head += '<div class="cm-weights">slope ' + slopes.map(function (s) {
        return s.label + ' ' + s.text;
      }).join(' · ') + '</div>';
    }
    var cols = ['Strike', 'Δ', 'Score', 'Net', 'Gross', 'OI', 'P/C', 'ΔGEX', 'Vol', 'P/C vol', 'Vol/OI', 'Flow', 'DEX', 'Vanna', 'IV', 'Charm', ''];
    var keys = ['strike', 'distance_text', 'score_text', 'net_gex_text', 'gross_text', 'oi_text', 'pc_gex_text', 'dgex_text', 'volume_text', 'pc_vol_text', 'vol_oi_text', 'flow_text', 'dex_text', 'vanna_text', 'iv_text', 'charm_text', 'markers'];
    var html = head + '<div class="cm-scroll"><table class="cm"><thead><tr>';
    cols.forEach(function (c) { html += '<th>' + c + '</th>'; });
    html += '</tr></thead><tbody>';
    var rows = Array.isArray(body.rows) ? body.rows : [];
    var kept = null;
    rows.forEach(function (row, i) {
      if (row.strike === selectedStrike) kept = row;
      html += '<tr data-i="' + i + '"' + (row.strike === selectedStrike ? ' class="on"' : '') + '>';
      keys.forEach(function (k) {
        var marks = Array.isArray(row.markers) ? row.markers : [];
        var shown = k === 'strike' ? text(row.strike) : (k === 'markers' ? marks.join(' ') : text(row[k]));
        var heat = (k === 'score_text' && row.heat_background) ? ' style="background:' + row.heat_background + '"' : '';
        html += '<td' + heat + '>' + shown + '</td>';
      });
      html += '</tr>';
      if (row.spot_line) {
        html += '<tr class="cm-spot"><td colspan="' + cols.length + '">spot ' + text(body.spot) + '</td></tr>';
      }
    });
    html += '</tbody></table></div><div class="cm-detail" id="cmDetail"></div>';
    var off = Array.isArray(body.offscreen) ? body.offscreen : [];
    if (off.length) {
      html += '<div class="cm-off">' + off.map(function (m) { return m.label + ' ' + m.price; }).join(' · ') + '</div>';
    }
    box.innerHTML = html;
    function showDetail(row) {
      var detail = document.getElementById('cmDetail');
      if (!detail || !row) return;
      var missing = Array.isArray(row.missing) ? row.missing : [];
      var parts = Array.isArray(row.contributions) ? row.contributions : [];
      var factors = Array.isArray(row.factors) ? row.factors : [];
      if (row.score == null) {
        detail.textContent = missing.join(', ');
        return;
      }
      var why = parts.map(function (p) { return p.label + ' ' + p.text; }).join(' · ');
      var lines = factors.map(function (p) {
        return p.label + ' ' + p.text + '  raw ' + text(p.raw_text) + '  norm ' + text(p.normalized_text) + '  weight ' + text(p.weight_text);
      });
      detail.textContent = why + '\n' + lines.join('\n');
    }
    box.querySelectorAll('tbody tr[data-i]').forEach(function (tr) {
      tr.addEventListener('click', function () {
        var row = rows[Number(tr.getAttribute('data-i'))];
        if (!row) return;
        selectedStrike = row.strike;
        box.querySelectorAll('tbody tr[data-i]').forEach(function (other) { other.classList.remove('on'); });
        tr.classList.add('on');
        showDetail(row);
      });
    });
    if (kept) showDetail(kept);
  }

  document.addEventListener('ed:view', function () { selectedStrike = null; load(); });
  document.addEventListener('ed:ticker', function () { expiry = null; selectedStrike = null; load(); });
  // The priced book is republished as `levels`. A new chain publishes that too.
  document.addEventListener('ed:changed', function (e) {
    var kind = e.detail && e.detail.kind;
    if (kind === 'levels' || kind === 'chain') load();
  });
})();
