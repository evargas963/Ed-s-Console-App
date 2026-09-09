/* Ed Console — Options/Gamma Chart view (RC-UI-1). PRESENTATION ONLY.
   Two modes on the same canonical inputs, spatially aligned to the price axis:
     A. Price + GEX Profile  — price line (/api/bars1m) beside a signed per-strike GEX
        profile (/api/terrain/strikes), with spot/flip/call-wall/put-wall overlays (/api/terrain).
     B. GEX Dot Map          — per-strike dots: colour=sign, size=|$ magnitude|, label=$ value.
   All numbers come from canonical endpoints; this module maps value->pixel (visualisation) and
   formats text. It computes NO exposure/levels semantics. */
(function () {
  'use strict';

  var usd = (window.EdGamma && window.EdGamma.formatUsd) || function (n) {
    if (n == null || isNaN(n)) return ''; var a = Math.abs(n), s = n < 0 ? '-' : '';
    if (a >= 1e9) return s + '$' + (a / 1e9).toFixed(1) + 'B';
    if (a >= 1e6) return s + '$' + (a / 1e6).toFixed(1) + 'M';
    if (a >= 1e3) return s + '$' + (a / 1e3).toFixed(1) + 'K'; return s + '$' + a.toFixed(0);
  };
  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c];});}
  function ctTime(sec){try{return new Date(sec*1000).toLocaleTimeString('en-US',{hour12:false,hour:'2-digit',minute:'2-digit',timeZone:'America/Chicago'});}catch(e){return'';}}
  function isChart(){var s=(window.EdShell&&window.EdShell.getState())||{};return s.workspace==='options'&&s.subview==='gamma'&&s.view==='chart';}
  function ticker(){return((window.EdShell&&window.EdShell.getState())||{}).ticker||'SPY';}

  var _mode = 'profile', _gen = 0;
  var COL = { pos: 'var(--ed-pos)', neg: 'var(--ed-neg)', spot: 'var(--ed-ink)', flip: 'var(--ed-accent)',
    call: 'var(--ed-neg)', put: 'var(--ed-pos)', axis: 'var(--ed-edge)', ink3: 'var(--ed-ink-3)' };

  function load() {
    var host = document.getElementById('chartBody');
    if (!host || !isChart()) return;
    var g = ++_gen, tk = ticker();
    host.setAttribute('aria-busy', 'true');
    Promise.all([
      fetch('/api/bars1m?ticker=' + encodeURIComponent(tk) + '&limit=180', { cache: 'no-store' }).then(okJson).catch(nullp),
      fetch('/api/terrain/strikes?ticker=' + encodeURIComponent(tk), { cache: 'no-store' }).then(okJson).catch(nullp),
      fetch('/api/terrain?ticker=' + encodeURIComponent(tk), { cache: 'no-store' }).then(okJson).catch(nullp),
    ]).then(function (res) {
      if (g !== _gen) return;
      render(host, res[0], res[1], res[2]);
    });
  }
  function okJson(r){ if(!r.ok) throw new Error(r.status); return r.json(); }
  function nullp(){ return null; }

  function render(host, barsData, strikesData, terrain) {
    var bars = (barsData && barsData.bars) || [];
    var srows = (strikesData && strikesData.today && strikesData.today.all) || [];
    var spot = Number((terrain && terrain.spot) != null ? terrain.spot : (strikesData && strikesData.spot));
    if (!bars.length && !srows.length) {
      host.innerHTML = '<div class="placeholder"><div class="sm">' +
        (barsData || strikesData ? 'no bars / per-strike gamma for this symbol' : 'no console serving /api/bars1m + /api/terrain/strikes') + '</div></div>';
      return;
    }
    // price domain over bars + strikes window (±4% of spot)
    var lo = Infinity, hi = -Infinity;
    bars.forEach(function (b) { if (b.l != null) lo = Math.min(lo, b.l); if (b.h != null) hi = Math.max(hi, b.h); });
    var win = srows.filter(function (r) { return isFinite(spot) ? Math.abs(r[0] - spot) <= spot * 0.04 : true; });
    win.forEach(function (r) { lo = Math.min(lo, r[0]); hi = Math.max(hi, r[0]); });
    if (!isFinite(lo) || !isFinite(hi) || lo === hi) { lo = (spot || 100) * 0.98; hi = (spot || 100) * 1.02; }
    var pad = (hi - lo) * 0.04; lo -= pad; hi += pad;

    var legend = '<div class="chart-legend">' +
      '<span><span class="sw" style="background:var(--ed-pos)"></span>+GEX</span>' +
      '<span><span class="sw" style="background:var(--ed-neg)"></span>−GEX</span>' +
      '<span><span class="sw" style="background:var(--ed-ink)"></span>spot ' + (isFinite(spot) ? spot.toFixed(2) : '—') + '</span>' +
      '<span><span class="sw" style="background:var(--ed-accent)"></span>flip</span></div>';
    var svg = (_mode === 'profile')
      ? profileSvg(bars, win, spot, terrain, lo, hi)
      : dotSvg(win, spot, terrain, lo, hi);
    host.innerHTML = legend + svg;
  }

  var W = 1000, H = 540, T = 12, B = 24, L = 52, R = 10;
  function yOf(p, lo, hi) { return T + (1 - (p - lo) / (hi - lo)) * (H - T - B); }

  function levelLines(terrain, lo, hi, x1, x2) {
    if (!terrain) return '';
    var out = '';
    function line(v, color, label, dash) {
      if (v == null || isNaN(v) || v < lo || v > hi) return;
      var y = yOf(v, lo, hi).toFixed(1);
      out += '<line x1="' + x1 + '" x2="' + x2 + '" y1="' + y + '" y2="' + y + '" stroke="' + color +
        '" stroke-width="1"' + (dash ? ' stroke-dasharray="4 3"' : '') + ' opacity="0.85"/>' +
        '<text x="' + (x2 - 3) + '" y="' + (y - 3) + '" text-anchor="end" font-size="10" fill="' + color + '">' + esc(label) + '</text>';
    }
    line(terrain.gamma_flip, COL.flip, 'flip ' + fmt(terrain.gamma_flip), true);
    line(terrain.call_wall, COL.call, 'call wall ' + fmt(terrain.call_wall), false);
    line(terrain.put_wall, COL.put, 'put wall ' + fmt(terrain.put_wall), false);
    return out;
  }
  function fmt(v){ return (v==null||isNaN(v))?'':Number(v).toFixed(2); }

  function priceAxis(lo, hi) {
    var out = '', n = 5;
    for (var i = 0; i <= n; i++) {
      var p = lo + (hi - lo) * i / n, y = yOf(p, lo, hi).toFixed(1);
      out += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '" stroke="' + COL.axis + '" stroke-width="0.5" opacity="0.5"/>' +
        '<text x="' + (L - 5) + '" y="' + (Number(y) + 3) + '" text-anchor="end" font-size="9">' + p.toFixed(2) + '</text>';
    }
    return out;
  }

  function profileSvg(bars, win, spot, terrain, lo, hi) {
    var xSplit = Math.round(W * 0.60);
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="chart-svg" preserveAspectRatio="none" role="img" aria-label="Price and GEX profile">';
    s += priceAxis(lo, hi);
    // price line (closes) in the left region
    if (bars.length) {
      var x0 = L, x1 = xSplit - 10, n = bars.length;
      var pts = bars.map(function (b, i) {
        var x = x0 + (n === 1 ? 0 : i / (n - 1) * (x1 - x0));
        return x.toFixed(1) + ',' + yOf(b.c, lo, hi).toFixed(1);
      }).join(' ');
      s += '<polyline points="' + pts + '" fill="none" stroke="var(--ed-ink-2)" stroke-width="1.2"/>';
      // time ticks
      [0, Math.floor(n / 2), n - 1].forEach(function (i) {
        if (!bars[i]) return; var x = (x0 + (n === 1 ? 0 : i / (n - 1) * (x1 - x0)));
        s += '<text x="' + x.toFixed(1) + '" y="' + (H - 8) + '" text-anchor="middle" font-size="9">' + ctTime(bars[i].t) + '</text>';
      });
    }
    // GEX profile in the right region, signed bars from a zero axis
    var maxAbs = win.reduce(function (m, r) { return Math.max(m, Math.abs(Number(r[1]) || 0)); }, 0) || 1;
    var cx = xSplit + 8, right = W - R - 4, halfW = (right - cx);
    s += '<line x1="' + cx + '" x2="' + cx + '" y1="' + T + '" y2="' + (H - B) + '" stroke="' + COL.axis + '" stroke-width="1"/>';
    win.forEach(function (r) {
      var k = r[0], v = Number(r[1]) || 0, w = Math.abs(v) / maxAbs * halfW;
      var y = yOf(k, lo, hi), pos = v >= 0;
      s += '<rect x="' + (pos ? cx : cx - w).toFixed(1) + '" y="' + (y - 3).toFixed(1) + '" width="' + w.toFixed(1) +
        '" height="6" fill="' + (pos ? COL.pos : COL.neg) + '" opacity="0.85"/>';
    });
    // biggest-magnitude label
    var top = win.slice().sort(function (a, b) { return Math.abs(b[1]) - Math.abs(a[1]); })[0];
    if (top) { var yt = yOf(top[0], lo, hi); s += '<text x="' + (cx + 4) + '" y="' + (yt - 5).toFixed(1) + '" font-size="10" fill="var(--ed-ink-2)">' + esc(usd(top[1])) + '</text>'; }
    // overlays
    s += levelLines(terrain, lo, hi, L, W - R);
    if (isFinite(spot)) {
      var ys = yOf(spot, lo, hi).toFixed(1);
      s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + ys + '" y2="' + ys + '" stroke="' + COL.spot + '" stroke-width="1.2" stroke-dasharray="2 2"/>' +
        '<text x="' + (L + 3) + '" y="' + (Number(ys) - 3) + '" font-size="10" fill="' + COL.spot + '">spot ' + spot.toFixed(2) + '</text>';
    }
    return s + '</svg>';
  }

  function dotSvg(win, spot, terrain, lo, hi) {
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="chart-svg" preserveAspectRatio="none" role="img" aria-label="GEX dot map">';
    s += priceAxis(lo, hi);
    var cx = Math.round(W * 0.5);
    var maxAbs = win.reduce(function (m, r) { return Math.max(m, Math.abs(Number(r[1]) || 0)); }, 0) || 1;
    s += '<line x1="' + cx + '" x2="' + cx + '" y1="' + T + '" y2="' + (H - B) + '" stroke="' + COL.axis + '" stroke-width="0.5" opacity="0.4"/>';
    win.forEach(function (r) {
      var k = r[0], v = Number(r[1]) || 0, y = yOf(k, lo, hi);
      var rad = 3 + Math.sqrt(Math.abs(v) / maxAbs) * 22;
      var pos = v >= 0, x = cx + (pos ? 1 : -1) * (rad + 10);
      s += '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + rad.toFixed(1) +
        '" fill="' + (pos ? COL.pos : COL.neg) + '" opacity="0.55" stroke="' + (pos ? COL.pos : COL.neg) + '"/>' +
        '<text x="' + (pos ? x + rad + 4 : x - rad - 4).toFixed(1) + '" y="' + (y + 3).toFixed(1) + '" text-anchor="' + (pos ? 'start' : 'end') +
        '" font-size="9" fill="var(--ed-ink-2)">' + esc(usd(v)) + '</text>';
    });
    s += levelLines(terrain, lo, hi, L, W - R);
    if (isFinite(spot)) {
      var ys = yOf(spot, lo, hi).toFixed(1);
      s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + ys + '" y2="' + ys + '" stroke="' + COL.spot + '" stroke-width="1.2" stroke-dasharray="2 2"/>' +
        '<text x="' + (L + 3) + '" y="' + (Number(ys) - 3) + '" font-size="10" fill="' + COL.spot + '">spot ' + spot.toFixed(2) + '</text>';
    }
    return s + '</svg>';
  }

  // mode toggle (buttons live in #chartModes; shown only on the Chart view)
  function bindModes() {
    var host = document.getElementById('chartModes');
    if (!host) return;
    host.querySelectorAll('.cmode').forEach(function (b) {
      b.addEventListener('click', function () {
        _mode = b.getAttribute('data-cmode');
        host.querySelectorAll('.cmode').forEach(function (x) { x.classList.toggle('on', x === b); });
        load();
      });
    });
  }

  document.addEventListener('ed:view', load);
  document.addEventListener('ed:ticker', load);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { bindModes(); load(); });
  else { bindModes(); load(); }
})();
