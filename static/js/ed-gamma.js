/* Ed Console — Options/Gamma heatmap view (RC-UI-1). PRESENTATION ONLY.
   Consumes GET /api/options/gamma-surface (canonical projection of compute_exposures_by_strike)
   and renders the strike × expiry grid. This module performs NO exposure math: it positions
   cells, formats the signed dollar value verbatim, maps sign->colour, and derives visual shade
   from the ABSOLUTE DISPLAYED magnitude only. The number shown equals the API value after
   formatting. Pure helpers are exposed on globalThis.EdGamma for node tests (invariants D/E). */
(function () {
  'use strict';

  // ---- pure formatter: compact signed USD ($958.6K, $7.6M, -$264.5K) ----
  function formatUsd(n) {
    if (n === null || n === undefined || isNaN(n)) return '';
    var v = Number(n), a = Math.abs(v), sign = v < 0 ? '-' : '';
    var s;
    if (a >= 1e9) s = (a / 1e9).toFixed(1) + 'B';
    else if (a >= 1e6) s = (a / 1e6).toFixed(1) + 'M';
    else if (a >= 1e3) s = (a / 1e3).toFixed(1) + 'K';
    else s = a.toFixed(0);
    return sign + '$' + s;
  }

  // ---- compact CONTRACT COUNT (1.0K, 23.1K) — no $ sign: Open Interest and Volume are
  // contract counts, not dollars, and formatting them through formatUsd (operator
  // field-inventory audit, 2026-09-13 — reproduced live: the Open Interest heatmap showed
  // "$1.0K" for 1,206 contracts) misrepresents the unit, not just the label. ----
  function formatCount(n) {
    if (n === null || n === undefined || isNaN(n)) return '';
    var v = Number(n), a = Math.abs(v), sign = v < 0 ? '-' : '';
    var s;
    if (a >= 1e9) s = (a / 1e9).toFixed(1) + 'B';
    else if (a >= 1e6) s = (a / 1e6).toFixed(1) + 'M';
    else if (a >= 1e3) s = (a / 1e3).toFixed(1) + 'K';
    else s = a.toFixed(0);
    return sign + s;
  }
  function formatMeasureValue(n, measure) {
    return (measure === 'oi' || measure === 'volume') ? formatCount(n) : formatUsd(n);
  }

  // ---- theme-aware colour: sign -> green/red, |value|/maxAbs -> intensity, ~0 -> recede.
  //      Fills are SOLID, interpolated from the active theme's heat tokens (zero -> pos/neg), so a
  //      cell reads correctly on ANY background — never dark-mode rgba re-used over a light canvas.
  //      Text contrast is picked from the resulting fill's luminance, so it is legible in both themes. ----
  var DEFAULT_HEAT = { pos: [35, 192, 107], neg: [229, 72, 77], zero: [18, 26, 37] };  // dark defaults (node/test)
  function _hex(h) {
    h = String(h || '').trim(); if (h.charAt(0) === '#') h = h.slice(1);
    if (h.length === 3) h = h.charAt(0) + h.charAt(0) + h.charAt(1) + h.charAt(1) + h.charAt(2) + h.charAt(2);
    if (h.length < 6) return null;
    var n = parseInt(h.slice(0, 6), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function _mix(a, b, t) { return [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t), Math.round(a[2] + (b[2] - a[2]) * t)]; }
  function _rgb(c) { return 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')'; }
  function _lum(c) { return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]; }
  function cellStyle(n, maxAbs, colors) {
    colors = colors || DEFAULT_HEAT;
    if (n === null || n === undefined || isNaN(n)) return { bg: 'transparent', fg: 'var(--ed-ink-4)', empty: true };
    var v = Number(n);
    if (Math.abs(v) < 1) return { bg: _rgb(colors.zero), fg: 'var(--ed-ink-3)', empty: false };
    var t = maxAbs > 0 ? Math.min(1, Math.abs(v) / maxAbs) : 0;
    var intensity = Math.pow(t, 0.34);   // cube-root-ish so small-but-real cells stay visible
    var mixed = _mix(colors.zero, (v > 0 ? colors.pos : colors.neg), intensity);
    var fg = _lum(mixed) < 140 ? '#f4f7fb' : '#0a0e17';
    return { bg: _rgb(mixed), fg: fg, empty: false, sign: (v > 0 ? 1 : -1) };
  }
  function readHeatColors() {   // the active theme's heat palette (falls back to dark defaults)
    try {
      var cs = getComputedStyle(document.documentElement);
      var p = _hex(cs.getPropertyValue('--ed-heat-pos')), ng = _hex(cs.getPropertyValue('--ed-heat-neg')), z = _hex(cs.getPropertyValue('--ed-heat-zero'));
      if (p && ng && z) return { pos: p, neg: ng, zero: z };
    } catch (e) {}
    return DEFAULT_HEAT;
  }

  // The real vendor OSI symbols backing a set of VISIBLE (strike-row, expiry-column)
  // cells -- read straight off the surface's own per-cell `contracts` field (server.py's
  // project_gamma_surface), never invented or reconstructed here. Returns ONE ENTRY PER
  // COLUMN (not a flattened symbol list) so a caller enforcing a request-size ceiling can cap
  // by dropping whole trailing COLUMNS, never by slicing partway through one -- a flat cutoff
  // over an interleaved column-major list can otherwise exclude one column's contracts for a
  // strike while keeping the other column's contracts for that SAME strike (independent-
  // review finding, 2026-09-13, REPRODUCED: at 244 visible contracts a plain 240-slice cut
  // through the last row's second column instead of dropping a whole column cleanly).
  //
  // `rows` (a SEVENTH independent review, 2026-09-13, REPRODUCED) groups each column's own
  // symbols by STRIKE ROW, in the same order `symbols` lists them -- a caller that must
  // PARTIALLY cover an over-budget column (never splitting one strike's own call+put pair)
  // can slice by whole rows from this list, which `symbols` alone (already flattened) cannot
  // safely support.
  function _heatmapVisibleContractsByColumn(cells, rowSel, cols) {
    return cols.map(function (j) {
      var seen = {}, symbols = [], rows = [];
      rowSel.idx.forEach(function (i) {
        var row = cells[i]; if (!row) return;
        var c = (row.contracts || [])[j];
        if (!c) return;
        var rowSyms = [];
        [c.call, c.put].forEach(function (sym) {
          if (sym && !seen[sym]) { seen[sym] = true; symbols.push(sym); rowSyms.push(sym); }
        });
        if (rowSyms.length) rows.push(rowSyms);
      });
      return { col: j, symbols: symbols, rows: rows };
    });
  }
  function _heatmapVisibleContracts(cells, rowSel, cols) {
    var seen = {}, out = [];
    _heatmapVisibleContractsByColumn(cells, rowSel, cols).forEach(function (entry) {
      entry.symbols.forEach(function (sym) { if (!seen[sym]) { seen[sym] = true; out.push(sym); } });
    });
    return out;
  }

  function nearestStrikeIndex(strikes, spot) {
    var best = -1, bd = Infinity;
    for (var i = 0; i < strikes.length; i++) {
      var d = Math.abs(strikes[i] - spot);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }

  // Operator field-inventory audit (2026-09-13): the ONE canonical strike x expiry
  // projection (server.py project_gamma_surface) carries dex/oi/volume per cell alongside
  // gex, computed by the SAME faucet every gex cell already comes from -- no second
  // computation. This is the ONE place that picks which of those a render actually reads,
  // so every consumer (maxAbs, the cell loop, the just-updated flash map) agrees on the
  // same measure the operator selected, never a mix of measures across the same render.
  // oi/volume are {call, put} per cell (unlike gex/dex, which are signed dealer-net
  // dollars) -- summed to a magnitude (call + put) for heatmap coloring, since OI/volume
  // concentration, not a net dealer sign, is the question those two measures answer.
  function _measureRow(row, measure) {
    if (measure === 'oi' || measure === 'volume') {
      return (row[measure] || []).map(function (cp) {
        if (!cp) return null;
        var c = cp.call, p = cp.put;
        return (c == null && p == null) ? null : (c || 0) + (p || 0);
      });
    }
    return row[measure] || row.gex || [];
  }

  // The per-(strike, expiry) value a PRIOR rendered surface reported, for the
  // just-updated flash below -- {} (nothing "changed") on the very first render, when
  // there is no real prior state to compare against.
  function _priorValueMap(priorSurface, measure) {
    var map = {};
    if (!priorSurface) return map;
    var priorExps = priorSurface.expirations || [], priorCells = priorSurface.cells || [];
    priorCells.forEach(function (row) {
      _measureRow(row, measure).forEach(function (v, j) {
        var e = priorExps[j];
        if (e) map[row.strike + '|' + e.expiry] = v;
      });
    });
    return map;
  }

  // ---- render the grid from a canonical surface payload (no math) ----
  function renderSurface(host, surface) {
    // Independent-review finding (2026-09-12, state-authority review): "actual Schwab
    // updates visibly change the appropriate values and colors" -- a full unconditional
    // table rebuild on every update changes the DOM correctly but gives a trader no cue
    // WHICH cell just moved; on a busy grid a real, correct update can go unnoticed.
    // Captured here, before `_lastSurface` below is overwritten with the incoming
    // surface, so the diff below compares against what was actually on screen a moment
    // ago, not the surface currently being rendered.
    var _priorSurfaceForFlash = _lastSurface;
    if (!surface || surface.available === false) {
      // Independent-review finding (2026-09-13), REPRODUCED: an unavailable result (no
      // chain, delisted, not on board) never cleared the heatmap's own streamed-contract
      // demand, so a ticker that stops being available kept the LAST successful render's
      // contracts subscribed indefinitely. Every exit from this function states demand,
      // including "none" -- same discipline Strike Detail's renderStrike already applies.
      if (window.EdStream && window.EdStream.setAdditionalContracts) {
        window.EdStream.setAdditionalContracts([], 'heatmap');
      }
      ++_demandGen; _demandStateByCol = {}; _demandSymbolsByCol = {};   // invalidate any in-flight confirm/reject from a prior available render
      // Independent-review finding (2026-09-13), REPRODUCED ("unavailable heatmap
      // lifecycle"): _lastSurface/_lastRevision used to survive an unavailable result
      // untouched (this branch returned before either was ever assigned), so a LATER
      // presentation-only event -- ed:theme, or the "else load()" branches missing entirely
      // -- reused the LAST AVAILABLE surface as if it were still current: ed:theme's
      // `if (h && _lastSurface) renderSurface(h, _lastSurface)` repainted the stale data as
      // available AND reissued its streamed-contract demand, resurrecting exactly the
      // subscription this branch just cleared. Fixed by invalidating the cache here too --
      // a presentation-only re-render has nothing left to reuse and correctly falls back to
      // a fresh load() instead of resurrecting stale state.
      _lastSurface = null; _lastRevision = null;
      // #1-A: even with no surface to draw, disclose the collection status honestly — a requested
      // symbol that is NOT on the board must read "not currently active for this symbol", never a
      // promised refresh. buildBanner is the ONE place that wording lives (warming/requested/board).
      var b = surface ? buildBanner(surface) : '';
      host.innerHTML = b + '<div class="placeholder"><div class="big">Gamma surface unavailable</div>' +
        '<div class="sm">' + escapeHtml((surface && surface.reason) || 'no console / no banked wide chain for this symbol') +
        '</div></div>';
      return;
    }
    var exps = surface.expirations || [], strikes = surface.strikes || [], cells = surface.cells || [];
    var spot = Number(surface.spot);
    var ES = window.EdShell;
    // #5: expiry filter (from the canonical /api/expiries dropdown) is PRESENTATION — it selects which
    // already-computed expiry column(s) to show; it never recomputes a value.
    var expFilter = (ES && ES.getExpiry) ? ES.getExpiry() : null;
    var scope = (ES && ES.getScope) ? ES.getScope() : 'auto';
    // Operator field-inventory audit (2026-09-13): which of the SAME surface's own
    // gex/dex/oi/volume fields this render presents -- see _measureRow's own comment.
    var measure = (ES && ES.getMeasure) ? ES.getMeasure() : 'gex';
    // VIEWPORT (real-data repair 2026-09-10): the canonical surface is served complete (the live SPY
    // reference is 116 strikes x 16 expirations) and the heatmap used to draw ALL of it, collapsing
    // the approved ~11-row workstation into an unreadable dump. The display now SELECTS a viewport:
    //   rows    = the ONE shell scope policy (EdShell.scopeSelect: Auto 11 strikes around spot,
    //             Wider 23, All available = every canonical strike, scrolled at the same row height);
    //   columns = the expiry filter's column, else in Auto the nearest UNEXPIRED expirations that fit
    //             legibly (server-stamped `expired`; a prior session's 0DTE is never shown as current
    //             structure), else every canonical column with expired ones labelled EXPIRED.
    // Selection only: every cell value is the API value; nothing is dropped from the payload, and the
    // counts (canonical vs shown) are disclosed in the header and the scope note.
    var rowSel = (ES && ES.scopeSelect) ? ES.scopeSelect(strikes, spot)
      : { idx: strikes.map(function (_s, i) { return i; }), shown: strikes.length, total: strikes.length };
    var allCols = exps.map(function (_e, ix) { return ix; });
    var unexpired = allCols.filter(function (ix) { return exps[ix].expired !== true; });
    var viewCols, expiredHidden = 0, filterMissing = false;
    if (expFilter) {
      viewCols = allCols.filter(function (ix) { return exps[ix].expiry === expFilter; });
      filterMissing = !viewCols.length;
    } else if (scope === 'auto') {
      var pool = unexpired.length ? unexpired : allCols;      // nothing unexpired: show what exists, labelled
      viewCols = pool.slice(0, autoColCount(host));
      expiredHidden = allCols.length - unexpired.length;
    } else if (scope === 'wider') {
      // twice the Auto column budget: nearest unexpired first, then expired (labelled); the grid scrolls
      var expiredCols = allCols.filter(function (ix) { return exps[ix].expired === true; });
      viewCols = unexpired.concat(expiredCols).slice(0, 2 * autoColCount(host)).sort(function (a, b) { return a - b; });
    } else {
      viewCols = allCols;                                       // every canonical column, scrolled at legible width
    }
    // Independent-review finding (2026-09-13), REPRODUCED, then a FOURTH review overturned the
    // first fix: falling back to `viewCols = allCols` avoided a blank grid, but the operator's
    // own requirement is that a selected expiry absent from the surface reads UNAVAILABLE for
    // THAT expiry, with its streaming demand cleared -- not silently substituted with every
    // other expiry's data (and, worse, that substitute set kept demanding streamed contracts
    // for expiries the operator never asked to watch). Fixed at the root: this state now
    // renders an honest "not available" placeholder instead of the grid, and clears demand
    // exactly like the surface.available===false branch above does, so nothing is ever
    // streamed for an expiry the operator did not select. Recovery is automatic: the next
    // surface poll that DOES include the requested expiry takes the normal path below (the
    // `_lastRevision` cache key is bumped by `filterMissing` requesting its own render skip
    // below, so a real column set arriving next paints immediately).
    if (filterMissing) {
      if (window.EdStream && window.EdStream.setAdditionalContracts) {
        ++_demandGen;
        window.EdStream.setAdditionalContracts([], 'heatmap');
      }
      _demandStateByCol = {}; _demandSymbolsByCol = {};
      _lastSurface = surface;
      _lastRevision = 'filter-missing:' + expFilter;   // never matches a real column set's rev
      host.innerHTML = '<div class="placeholder"><div class="big">Expiry ' + escapeHtml(expFilter) +
        ' unavailable</div><div class="sm">not present in this surface (' + exps.length +
        ' expiration' + (exps.length === 1 ? '' : 's') + ' available) — choose another expiry, ' +
        'or All Expirations, from the dropdown above</div></div>';
      return;
    }
    // C: emphasise the nearest UNEXPIRED expiry (front) column — presentation only, no predictive meaning
    var frontCol = -1, minDte = Infinity;
    exps.forEach(function (e, ix) { if (e.expired !== true && e.dte != null && e.dte < minDte) { minDte = e.dte; frontCol = ix; } });
    // Live-heatmap coverage (state-authority review, 2026-09-12): every OTHER cell on this
    // grid only ever refreshed on the ~60s wide-chain REST cycle -- nothing had ever asked
    // the streaming layer to keep the cells the operator is ACTUALLY LOOKING AT fresh
    // sub-second, only whatever one strike Strike Detail happened to have separately
    // selected. Each surface cell now carries its own vendor OSI symbols (server.py's
    // project_gamma_surface), so the heatmap can declare its OWN demand through the same
    // single-owner endpoint EdStream already owns (setAdditionalContracts's ownerKey,
    // 'heatmap' -- coexists with Strike Detail's own 'default'-owner demand, unioned).
    // Deliberately bounded to the DEFAULT ("auto") scope's visible strikes and only the
    // FRONT (nearest-unexpired) expiry column -- the column traders actually watch
    // tick-to-tick, and a contract count (<= MAX_AUTO_COLS strikes x 2 sides) already
    // within this session's own measured-safe replay-loop budget. "Wider"/"All available"
    // are an explicit operator zoom-out to the full book and stay REST-cadence only, same
    // as before -- the full-book vendor-side subscription capacity remains a separate,
    // NOT_PROVEN, operator-authorized question this does not silently reopen.
    //
    // Independent-review findings (2026-09-13), BOTH REPRODUCED, fixed together here:
    // (a) "demand can target a different expiry from the displayed cells" -- this always
    //     demanded the FRONT column regardless of an explicit single-expiry filter, so
    //     picking (e.g.) Sept 25 while the nearer Sept 18 was still the computed "front"
    //     kept streaming Sept 18's contracts while Sept 25's cells sat on the REST cadence.
    //     Fixed: when an explicit expFilter is active, viewCols IS that one column
    //     regardless of scope (see the branch above) -- the same bounded single-column
    //     cost the front-column policy already allows -- so demand now follows viewCols,
    //     not always "front", whenever a filter narrows the view.
    // (b) "demand stays cleared after leaving and returning to an unchanged surface" --
    //     this call used to live INSIDE the full-table-rebuild branch below, gated by the
    //     `rev === _lastRevision` fast-path (module state that outlives a leave/return
    //     cycle). Leaving the heatmap explicitly clears demand (see load()); returning to
    //     an otherwise-unchanged surface then hit the fast path and never re-declared it.
    //     Fixed by moving this out of the fast-path gate entirely -- it now runs on EVERY
    //     render, full rebuild or not (setAdditionalContracts is dedup-safe to call
    //     repeatedly with the same set, by the same design panels.js already documents).
    // Computed unconditionally (not just when EdStream exists) -- the column-header
    // coverage disclosure below reads `demandCols` regardless of whether anything is
    // actually listening for the demand notification (e.g. the node test harness, which
    // renders this exact function with no `window`/EdStream at all).
    // Independent-review finding (2026-09-13, operator-directed): Wider/All used to demand
    // ZERO contracts unconditionally -- a silent narrowing of the coverage objective that
    // the operator explicitly rejected as unjustified ("vendor-capacity uncertainty does
    // not explain away that application behavior"). Wider/All now demand exactly the
    // columns they DISPLAY (viewCols), the same rule an explicit expiry filter already
    // used. Auto's own measured, capacity-safe front-column-only policy (round 6's
    // deliberately bounded DEFAULT-scope budget) is unchanged -- it was never the
    // complaint, and nothing here reopens it.
    var demandCols = expFilter ? viewCols : (scope === 'auto' && frontCol >= 0 ? [frontCol] : viewCols);
    // Independent-review finding (2026-09-13), REPRODUCED: the column-header tooltip
    // claimed "sub-second streaming updates active for this column" the instant a column
    // was in `demandCols` -- but `demandCols` only names what THIS module ASKED for; the
    // single-owner streaming-control endpoint can reject that ask (confirmed with a real
    // HTTP 503 in the reproduction) and contracts stayed empty while the tooltip kept
    // claiming active streaming. `setAdditionalContracts` already returns a promise
    // resolving to the server's own accepted/rejected verdict (ed-stream.js) -- this was
    // simply never read. Fixed: track REQUESTED vs CONFIRMED vs REJECTED per dispatch,
    // synchronously default new demand to "pending" (never "active") until the response
    // actually confirms it, and patch the live column title in place once it resolves
    // (applyDemandTitles) rather than claiming a fresh column has already streamed anything.
    // Deliberate, DISCLOSED safety ceiling on the number of symbols submitted in one
    // active-option-contracts request -- extending real coverage to Wider/All (above) means
    // a wide "All" configuration (many strikes x many expirations) could otherwise name
    // thousands of contracts in a single POST. The true vendor-side subscription capacity
    // at that scale has never been measured against live Schwab and remains its own
    // NOT_PROVEN question (round 6); this cap does not silently avoid that question -- it
    // states plainly what this client actually attempts and discloses (scope note below)
    // whenever the true displayed coverage exceeds it, rather than either fabricating full
    // coverage or silently submitting an unbounded request.
    //
    // A FOURTH independent review (2026-09-13), REPRODUCED: a flat `.slice(0, cap)` over the
    // flattened, column-interleaved symbol list cut mid-row at the boundary (244 visible
    // contracts, cap 240 -- the last row's second column lost both its contracts while every
    // OTHER cell in that same column stayed covered), yet the column header tooltip kept
    // claiming that column was fully "active" with no per-column distinction. Fixed: cap by
    // dropping whole trailing COLUMNS (in `demandCols`' own priority order) once the running
    // total would exceed the ceiling, never by slicing through one -- `_cappedCols` names
    // exactly which columns this excluded, so their own tooltip can honestly say so instead
    // of claiming the same coverage as a column that was never cut.
    //
    // A SEVENTH independent review (2026-09-13), REPRODUCED: that column-dropping cap zeroed
    // out a column ENTIRELY the instant it alone exceeded the ceiling -- concretely, a single
    // explicitly-selected expiry with 121 strikes (242 contracts) submitted ZERO streaming
    // demand, worse than useless for exactly the "I picked one expiry to watch" scenario an
    // operator cares about most. Fixed: the ONE column that first crosses the ceiling is now
    // given PARTIAL coverage -- as many WHOLE STRIKE ROWS (never one strike's call+put split
    // across the cut) as fit in the remaining budget -- rather than being dropped outright;
    // `_partialCols` names it distinctly from `_cappedCols` (a column excluded ENTIRELY,
    // which can still happen for a column AFTER the one that already consumed the remaining
    // budget) so its own tooltip discloses partial, not total, exclusion.
    var MAX_DEMAND_CONTRACTS = 240;
    var frontDemand = [], _cappedCols = {}, _partialCols = {}, _newSymbolsByCol = {};
    if (demandCols.length) {
      var byCol = _heatmapVisibleContractsByColumn(cells, rowSel, demandCols);
      var seen = {}, total = 0;
      for (var _bc = 0; _bc < byCol.length; _bc++) {
        var entry = byCol[_bc];
        // This column's own rows, filtered to symbols not already claimed by an EARLIER
        // column in this loop -- row grouping preserved, so a partial cut below can still
        // never split one strike's own call+put pair.
        var freshRows = entry.rows.map(function (r) { return r.filter(function (s) { return !seen[s]; }); })
                                   .filter(function (r) { return r.length > 0; });
        var freshCount = freshRows.reduce(function (n, r) { return n + r.length; }, 0);
        if (total + freshCount <= MAX_DEMAND_CONTRACTS) {
          freshRows.forEach(function (r) { r.forEach(function (s) { seen[s] = true; frontDemand.push(s); }); });
          total += freshCount;
          // The FULL symbol set for this column (both call and put, every visible row) --
          // not just the fresh/deduped subset -- so this column's own 'observed' check
          // below intersects against everything it actually covers.
          _newSymbolsByCol[entry.col] = entry.symbols;
          continue;
        }
        // Does not fully fit -- take as many WHOLE ROWS as remain in the budget.
        var remaining = MAX_DEMAND_CONTRACTS - total, taken = [];
        for (var _r = 0; _r < freshRows.length; _r++) {
          var r = freshRows[_r];
          if (r.length > remaining) break;
          r.forEach(function (s) { seen[s] = true; frontDemand.push(s); taken.push(s); });
          remaining -= r.length;
        }
        total = MAX_DEMAND_CONTRACTS - remaining;
        if (taken.length) {
          _partialCols[entry.col] = taken.length + '/' + entry.symbols.length;
          _newSymbolsByCol[entry.col] = taken;   // 'observed' evidence checked only against what was actually demanded
        } else {
          _cappedCols[entry.col] = true;
        }
      }
    }
    var demandCapped = Object.keys(_cappedCols).length > 0 || Object.keys(_partialCols).length > 0;
    var demandedCols = Object.keys(_newSymbolsByCol).map(Number);
    _demandSymbolsByCol = _newSymbolsByCol;
    if (window.EdStream && window.EdStream.setAdditionalContracts) {
      var myDemandGen = ++_demandGen;
      demandedCols.forEach(function (c) { _demandStateByCol[c] = frontDemand.length ? 'pending' : 'none'; });
      window.EdStream.setAdditionalContracts(frontDemand, 'heatmap').then(function (res) {
        if (myDemandGen !== _demandGen) return;   // superseded by a newer demand call
        if (!frontDemand.length) {
          demandedCols.forEach(function (c) { _demandStateByCol[c] = 'none'; });
          return;
        }
        // 'accepted' names a server-ACKed subscribe REQUEST -- real observed data, checked
        // per-column against the latest surface below (this render's, or any later one), is
        // what actually promotes THAT column to 'observed'. A SIXTH independent review
        // (2026-09-13): each column is judged against its OWN demanded symbols
        // (_colHasObservedEvidence), never a surface-wide count that a peer column's
        // evidence could satisfy on this column's behalf.
        var verdict = (res && (res.accepted || res.unchanged))
          ? 'accepted' : (res && res.pending) ? 'pending' : 'rejected';
        demandedCols.forEach(function (c) {
          _demandStateByCol[c] = (verdict === 'accepted' && _colHasObservedEvidence(c, _lastSurface))
            ? 'observed' : verdict;
        });
        applyDemandTitles(document.getElementById('heatBody'));
      });
    } else {
      demandedCols.forEach(function (c) { _demandStateByCol[c] = frontDemand.length ? 'pending' : 'none'; });
    }
    // Independent-review finding (2026-09-13), REPRODUCED: acceptance was treated as the
    // final word -- a demand accepted on an EARLIER render never got upgraded once a LATER,
    // routine refresh's surface finally carried real overlay evidence for it. Checked on
    // every render (not only the render that issued the request) so a demand that was merely
    // 'accepted' when first requested still becomes honestly 'observed' the moment evidence
    // for it actually arrives -- per column, per the SAME identity-bound check above.
    Object.keys(_demandStateByCol).forEach(function (c) {
      if (_demandStateByCol[c] === 'accepted' && _colHasObservedEvidence(Number(c), surface)) {
        _demandStateByCol[c] = 'observed';
      }
    });
    _lastSurface = surface;   // cached so a theme switch can re-render without a refetch
    // #1: skip the full table rebuild when the canonical surface REVISION (and the viewport choice)
    // is unchanged (only the age advances between terrain revisions). A theme switch clears
    // _lastRevision so the recolour still rebuilds.
    var rev = surfaceRevision(surface) + '|' + scope + '|' + viewCols.length + '|' + measure;
    if (rev === _lastRevision && host.querySelector('.heat')) {
      applyStatus(host, surface); applyStrikeHighlight(host);   // data unchanged: refresh status only
      return;
    }
    _lastRevision = rev;
    var heat = readHeatColors();
    // maxAbs over DISPLAYED cells — visual normalisation only, not a semantic value
    var maxAbs = 0;
    rowSel.idx.forEach(function (i) { var r = cells[i] || {}; var mr = _measureRow(r, measure); viewCols.forEach(function (j) { var v = mr[j]; if (v != null && Math.abs(v) > maxAbs) maxAbs = Math.abs(v); }); });

    var spotIdx = nearestStrikeIndex(strikes, spot);
    // freshness / source — fail stale visibly (RC-UI-1 live-source rewire)
    var live = surface.live !== false, stale = !!surface.stale;
    var banner = buildBanner(surface);   // status banners (warming/requested/stale/ref + narrowed)
    // B: a STALE / REFERENCE surface visually recedes (in addition to the banner)
    var recede = (!live || stale) ? ' recede' : '';
    var tbl = '<table class="heat"><thead><tr><th class="hcorner">Strike</th>';
    // Coverage disclosure (mandate: "coverage limitations must be visible... never silently
    // become a narrower definition of completion"): only the column(s) in `demandCols`
    // above actually receive sub-second streaming updates; every OTHER column -- including
    // every column when Wider/All is selected with no expiry filter -- still refreshes on
    // the ~60s REST cadence only. This states that distinction on the column itself rather
    // than leaving the visual col-front highlight to imply a meaning it never spelled out.
    var demandColSet = {}; demandCols.forEach(function (dc) { demandColSet[dc] = true; });
    viewCols.forEach(function (j) {
      var e = exps[j], expired = e.expired === true;
      // A column the cap excluded ENTIRELY (`_cappedCols`) was NEVER actually demanded,
      // whatever `demandColSet` says it was asked for. A PARTIALLY-covered column
      // (`_partialCols`) WAS genuinely demanded, just not for every strike -- its own
      // tooltip must say so distinctly from both a fully-excluded column and one the cap
      // never touched at all. Excluded from `streamed`/`.stream-demand` the same as a fully
      // capped column (not just `_cappedCols`): `applyDemandTitles` (a separate function
      // with no access to this render's own `_partialCols` closure) patches EVERY
      // `.stream-demand` th's title from the async accept/observed state the instant that
      // promise resolves -- REPRODUCED clobbering this column's static "PARTIALLY covered"
      // disclosure with a generic "subscription accepted" title the moment it fired, unless
      // this column is excluded from that class the same way a fully-capped one already is.
      var streamed = !!demandColSet[j] && !_cappedCols[j] && !_partialCols[j];
      var dte = expired ? 'EXPIRED' : (e.dte === 0) ? '0DTE' : (e.dte != null ? e.dte + 'DTE' : '');
      var title = expired
        ? 'this expiration has already expired — a prior-session column kept for reference, not current structure'
        : _cappedCols[j]
        ? 'streaming demand for this column was excluded by the ' + MAX_DEMAND_CONTRACTS + '-contract subscription-size safety limit — REST-cadence only'
        : _partialCols[j]
        ? 'streaming demand for this column was PARTIALLY covered (' + _partialCols[j] + ' contracts) by the ' +
          MAX_DEMAND_CONTRACTS + '-contract subscription-size safety limit — remaining strikes REST-cadence only'
        : demandTitle(streamed, j);
      tbl += '<th class="hexp' + (j === frontCol ? ' col-front' : '') + (expired ? ' expired' : '') + (streamed ? ' stream-demand' : '') + '"' +
        ' data-col="' + j + '" title="' + escapeHtml(title) + '"' +
        '><span class="d">' + escapeHtml((e.expiry || '').slice(5)) + '</span><span class="dte">' + dte + '</span></th>';
    });
    tbl += '</tr></thead><tbody>';
    // Just-updated flash (state-authority review, 2026-09-12): a cell whose value
    // genuinely differs from what THIS SAME (strike, expiry) showed a moment ago gets a
    // one-shot CSS highlight (see .hcell.flash-update in console.html) -- the ONLY signal
    // that separates "this table was rebuilt" from "this specific value just moved" on a
    // grid otherwise indistinguishable before and after a live tick. Never flashes on the
    // very first render (no real prior state exists yet to compare against).
    var priorValues = _priorValueMap(_priorSurfaceForFlash, measure);
    // Operator finding (2026-09-11): rowSel.idx is ascending-index order into the
    // ascending `strikes` array (scopeSelect's own contract — shared by GEX-by-Strike
    // and other consumers, so it stays ascending there). The heatmap specifically must
    // read like a real strike ladder: highest strike at the top, lowest at the bottom.
    // Reversed here, in the render loop only -- a presentation-only iteration order, not
    // a mutation of rowSel.idx (still ascending for maxAbs above and any other reader)
    // or of any row's own strike/expiry/gex/isSpot binding, which is looked up by index
    // `i` exactly as before.
    rowSel.idx.slice().reverse().forEach(function (i) {
      var row = cells[i] || { strike: strikes[i], gex: [] }, isSpot = (i === spotIdx);
      var mrow = _measureRow(row, measure);
      tbl += '<tr' + (isSpot ? ' class="spotrow"' : '') + '>' +
        '<th class="hstrike' + (isSpot ? ' spot' : '') + '">' + fmtStrike(row.strike) + '</th>';
      for (var jj = 0; jj < viewCols.length; jj++) {
        var j2 = viewCols[jj];
        // `data-gex` kept as the DOM attribute name for back-compat with existing tests/
        // tooling that read a heatmap cell's value -- it now holds whichever measure is
        // selected (gex/dex/oi/volume), not literally GEX specifically.
        var v = mrow[j2];
        var st = cellStyle(v, maxAbs, heat);
        var priorKey = row.strike + '|' + exps[j2].expiry;
        var justChanged = _priorSurfaceForFlash &&
          Object.prototype.hasOwnProperty.call(priorValues, priorKey) && priorValues[priorKey] !== v;
        tbl += '<td class="hcell' + (j2 === frontCol ? ' col-front' : '') + (exps[j2].expired === true ? ' expired' : '') +
          (justChanged ? ' flash-update' : '') +
          '" style="background:' + st.bg + ';color:' + st.fg + '" ' +
          'data-strike="' + row.strike + '" data-expiry="' + escapeHtml(exps[j2].expiry) + '" data-gex="' + (v == null ? '' : v) + '">' +
          (st.empty ? '' : formatMeasureValue(v, measure)) + '</td>';
      }
      tbl += '</tr>';
    });
    tbl += '</tbody></table>';
    // #3: the ONE disclosure line — how many canonical strikes / expirations are on screen vs clipped
    var cappedExps = Object.keys(_cappedCols).map(function (j) { return (exps[j] || {}).expiry; }).filter(Boolean);
    // A SEVENTH independent review (2026-09-13): a column given PARTIAL coverage (its own
    // strikes exceeded the remaining budget, so only a whole-row-aligned subset of it was
    // demanded) is named separately from one excluded ENTIRELY -- collapsing the two into one
    // "excluded" list would misreport a column that IS still genuinely streaming, in part.
    var partialExpsTxt = Object.keys(_partialCols).map(function (j) {
      return ((exps[j] || {}).expiry || '') + ' (' + _partialCols[j] + ' contracts)';
    }).filter(Boolean);
    var colsTxt = viewCols.length + ' of ' + exps.length + ' expirations' +
      (expiredHidden ? ' (' + expiredHidden + ' expired hidden in Auto)' : '') +
      (demandCapped ? ' · streaming demand capped at ' + MAX_DEMAND_CONTRACTS +
        ' contracts (subscription-size safety limit, untested at full scale)' +
        (cappedExps.length ? ' — excluded: ' + cappedExps.join(', ') : '') +
        (partialExpsTxt.length ? ' — partially covered: ' + partialExpsTxt.join(', ') : '') : '');
    var note = (ES && ES.scopeNote) ? ES.scopeNote({ total: strikes.length, shown: rowSel.shown, extra: colsTxt }) : '';
    // the grid fills the panel; a compact vertical magnitude legend sits at its right edge (the
    // dollar value is printed in every cell — shade = |GEX$|), matching the approved reference.
    // Measure-adaptive legend labels: gex/dex are signed dealer-net measures (call-side
    // high at top, put-side high at bottom, matching net_gex_1pct/net_dex_dollars' own
    // +call/-put sign convention); oi/volume are unsigned magnitudes (call+put), so the
    // legend reads "High"/"Low" concentration instead of a call/put polarity that does
    // not exist for those two measures.
    var MEASURE_LEGEND = {
      gex: ['High<br>Call<br>GEX', 'High<br>Put<br>GEX'],
      dex: ['High<br>Call<br>DEX', 'High<br>Put<br>DEX'],
      oi: ['High<br>Open<br>Interest', 'Low<br>Open<br>Interest'],
      volume: ['High<br>Volume', 'Low<br>Volume'],
    };
    var legendPair = MEASURE_LEGEND[measure] || MEASURE_LEGEND.gex;
    var vlegend = '<div class="heat-vlegend"><span class="bar"></span>' +
      '<span class="caps"><span class="t">' + legendPair[0] + '</span><span class="m">0</span>' +
      '<span class="b">' + legendPair[1] + '</span></span></div>';
    host.innerHTML = banner + note +
      '<div class="heat-host"><div class="heat-main"><div class="heat-wrap' + recede + '">' +
      tbl + '</div></div>' + vlegend + '</div>';

    // scroll spot into view; presentation-only cell selection -> strike detail
    var srow = host.querySelector('.spotrow');
    if (srow && srow.scrollIntoView) srow.scrollIntoView({ block: 'center' });
    host.querySelectorAll('.hcell').forEach(function (c) {
      c.addEventListener('click', function () {
        // A: route through the shared selection so every panel syncs to this strike
        if (window.EdShell) window.EdShell.setStrike(Number(c.getAttribute('data-strike')), c.getAttribute('data-expiry'));
      });
    });
    // default the shared selection to the spot strike on first load, so Strike Detail and the
    // GEX-by-strike highlight are populated on arrival (like the approved reference) instead of an
    // empty placeholder. Never overrides a selection the operator has already made.
    if (window.EdShell && window.EdShell.getState().selStrike == null && strikes.length && spotIdx >= 0) {
      var _fe = expFilter || (exps[frontCol >= 0 ? frontCol : 0] || {}).expiry || null;
      window.EdShell.setStrike(strikes[spotIdx], _fe);
    }
    applyStrikeHighlight(host);
    updateScope(surface);
  }

  function applyStrikeHighlight(host) {
    host = host || document.getElementById('heatBody'); if (!host) return;
    var sel = ((window.EdShell && window.EdShell.getState()) || {}).selStrike;
    host.querySelectorAll('.hcell.sel-strike').forEach(function (n) { n.classList.remove('sel-strike'); });
    if (sel == null) return;
    host.querySelectorAll('.hcell[data-strike="' + sel + '"]').forEach(function (n) { n.classList.add('sel-strike'); });
  }

  // Auto column budget: the nearest expirations that stay legible at the approved cell width. The
  // approved workstation shows ~11 columns at 1672px; a column narrower than MIN_COL_PX collapses
  // the header and the signed value, so the count is capped by width, never the other way round.
  var MIN_COL_PX = 84, MAX_AUTO_COLS = 11, MIN_AUTO_COLS = 3;
  function autoColCount(host) {
    var w = (host && host.clientWidth) || 0;
    if (!w) return MAX_AUTO_COLS;
    var avail = w - 70 /* strike column */ - 64 /* magnitude legend */;
    return Math.max(MIN_AUTO_COLS, Math.min(MAX_AUTO_COLS, Math.floor(avail / MIN_COL_PX)));
  }
  function fmtStrike(k) { return (Math.round(k * 100) / 100).toString(); }
  function escapeHtml(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }

  // ---- fetch + render, guarded (latest-wins) ----
  var _lastSurface = null, _lastRevision = null;
  // Streaming-demand confirmation state (2026-09-13) — see the demand-dispatch block in
  // renderSurface for why this exists: `demandCols` is only a REQUEST, not a guarantee.
  //
  // A FOURTH independent review (2026-09-13), REPRODUCED: 'confirmed' fired, and the tooltip
  // claimed "sub-second streaming updates ACTIVE", the instant `setAdditionalContracts`
  // resolved with the server's own subscribe-request ACK (res.accepted) -- a successful
  // control-plane POST, never checked against whether the producer has delivered even one
  // real observation for any contract in the set. 'accepted' now names exactly that (a
  // request the server acknowledged) and stays the ceiling until a LATER surface poll's own
  // `stream_overlay_contracts` count (server.py: how many contracts THIS surface actually
  // carries a genuinely-overlaid streamed field for -- real evidence, not a request outcome)
  // is greater than zero while this demand is still live -- only then does the state become
  // 'observed', and only then does the tooltip claim streaming is actually active.
  // A SIXTH independent review (2026-09-13), REPRODUCED: `_demandState` was ONE global
  // string shared by every demanded column -- the instant `stream_overlay_contracts` (a
  // single surface-wide COUNT) went nonzero for ANY reason, EVERY currently-'accepted'
  // column was promoted to 'observed' together, even a column for a completely different
  // expiry than whatever actually got freshened. Concretely reproduced: two accepted
  // columns A and B; only B's contract genuinely streams; A's own tooltip still claimed
  // "sub-second streaming updates observed" with zero real evidence for A specifically.
  // Fixed: state and the demanded symbol set are now BOTH keyed by column, and promotion
  // to 'observed' requires THIS column's own demanded symbols to intersect the surface's
  // `stream_overlay_symbols` (server.py's _overlaid_symbols) -- real, identity-bound
  // evidence for that specific column, never a peer column's.
  var _demandGen = 0;
  var _demandStateByCol = {};      // col index -> 'pending' | 'accepted' | 'observed' | 'rejected'
  var _demandSymbolsByCol = {};    // col index -> the vendor symbols demanded for that column
  function _colHasObservedEvidence(col, surface) {
    var syms = _demandSymbolsByCol[col] || [];
    if (!syms.length || !surface) return false;
    var overlaid = surface.stream_overlay_symbols || [];
    for (var i = 0; i < overlaid.length; i++) {
      if (syms.indexOf(overlaid[i]) !== -1) return true;
    }
    return false;
  }
  function demandTitle(streamed, col) {
    if (!streamed) return 'REST-cadence only (refreshes ~60s) — not sub-second streamed; Auto shows one streamed column at a time';
    var st = _demandStateByCol[col];
    if (st === 'observed') return 'sub-second streaming updates observed for this column';
    if (st === 'accepted') return 'streaming subscription accepted for this column — awaiting the first observed update';
    if (st === 'rejected') return 'streaming subscription for this column was NOT accepted by the server — falling back to REST-cadence only';
    return 'streaming subscription requested for this column — awaiting confirmation';   // 'pending' or transiently unset
  }
  // Patches the demanded column(s)' tooltip in place once the confirm/reject response
  // lands, WITHOUT a full table rebuild -- the demand promise can resolve well after
  // renderSurface has already returned, possibly across several unrelated re-renders.
  function applyDemandTitles(host) {
    if (!host) return;
    var ths = host.querySelectorAll('.heat thead th.hexp.stream-demand');
    for (var i = 0; i < ths.length; i++) {
      if (ths[i].classList.contains('expired')) continue;
      ths[i].setAttribute('title', demandTitle(true, Number(ths[i].getAttribute('data-col'))));
    }
  }

  // server-owned revision identity — the cells are identical while these are unchanged, so we can
  // skip the full table rebuild. Not a semantic client fingerprint of the data; just the canonical
  // as-of / source / basis / freshness fields the server already stamps.
  function surfaceRevision(s) {
    // DATA revision only — decides whether the expensive TABLE rebuilds. Status (live/stale/warming/
    // age) is deliberately NOT here; it is refreshed every time via applyStatus. et_date discriminates
    // banked captures (whose chain/spot as-of are null) so a new morning capture cannot reuse the grid.
    if (!s || s.available === false) return 'unavailable|' + (s && s.source);
    // ticker + expiry filter are part of WHICH cells are shown: a symbol change or an expiry-column
    // change must always rebuild the grid, never reuse a prior symbol's/expiry's table.
    var expFilter = (window.EdShell && window.EdShell.getExpiry) ? window.EdShell.getExpiry() : null;
    // Independent-review finding (2026-09-12), REPRODUCED: a streamed update can change cell
    // VALUES (server.py's eager refresh_gamma_surface_from_stream) without touching
    // chain_as_of_ts_utc/spot_as_of_ts_utc at all — those are stamped only by the ~60s REST
    // cycle. With only REST-only fields in this key, a genuinely new surface hashed identical
    // to the old one and the table silently kept showing stale cells. surface_seq is a
    // server-owned counter bumped on EVERY publication, REST or streamed (server.py's
    // _next_gamma_surface_seq) — its inclusion is what makes a streamed-only change visible.
    return [s.ticker || s.symbol, s.source, s.chain_as_of_ts_utc, s.spot_as_of_ts_utc, s.chain_basis, s.et_date, expFilter, s.surface_seq].join('|');
  }
  // lightweight STATUS: banner (warming/requested/stale/reference/degraded) + recede dimming + scope
  // age — always refreshed, even when the DATA revision is unchanged, so nothing is left frozen.
  function buildBanner(surface) {
    var live = surface.live !== false, stale = !!surface.stale, out = '';
    if (!live || stale) {
      var warming = !live && surface.warming === true;
      var requested = !live && !warming && surface.requested === true;
      // #1-A: distinguish "on the board, a refresh is coming" from "not on the board, nothing is
      // collecting this symbol". Only the former may promise a next refresh.
      var onBoard = surface.on_board === true;
      var notCollecting = requested && !onBoard;
      // WHAT is on screen (identity, server-stamped): a banked reference from a PRIOR session is named
      // as such — a 2026-09-09 morning chain viewed on 2026-09-10 is never dressed as today's structure.
      var prior = surface.prior_session === true;
      var refLabel = !live ? ((prior ? 'PRIOR SESSION REFERENCE' : 'MORNING REFERENCE') +
        (surface.et_date ? ' · ' + escapeHtml(surface.et_date) : '')) : '';
      // WHERE the live surface stands (state)
      var stateLabel = warming ? 'LIVE SURFACE WARMING'
        : notCollecting ? 'NOT COLLECTING'
        : requested ? 'LIVE SURFACE REQUESTED'
        : (live ? 'STALE' : '');
      // identity class first (a reference surface always reads as REFERENCE), live-state class beside it
      var cls = (!live ? 'ref ' : '') + (warming ? 'warming'
        : (requested && !notCollecting) ? 'warming'
        : (live ? 'stale' : ''));
      // CONCISE primary line; the full reason is disclosed in the tooltip (title) — never a paragraph
      // that consumes the analytical panel.
      var brief = !live
        ? (prior ? 'banked chain from a prior session — not this session, not intraday' : 'banked morning chain — not intraday')
        : 'live surface is stale';
      var detail = surface.degraded
        || (notCollecting ? 'live terrain collection is not currently active for this symbol'
          : requested ? 'awaiting next eligible terrain refresh' : brief);
      var text = [refLabel, stateLabel].filter(Boolean).join(' — ') + ' · ' + brief +
        (notCollecting ? ' · collection is not currently active for this symbol' : '');
      out += '<div class="heat-banner ' + cls + '" title="' + escapeHtml(detail) + '"><span class="hb-main">' + text +
        '</span><span class="hb-more" aria-label="details">details</span></div>';
    }
    if (live && surface.chain_basis && surface.chain_basis !== 'full') {
      out += '<div class="heat-banner degraded">NARROWED — live chain basis "' + escapeHtml(surface.chain_basis) +
        '" (reduced expiry window under load), not the usual full basis</div>';
    }
    return out;
  }
  function applyStatus(host, surface) {   // refresh status WITHOUT rebuilding the table
    Array.prototype.slice.call(host.querySelectorAll('.heat-banner')).forEach(function (n) { n.remove(); });
    var b = buildBanner(surface);
    if (b) host.insertAdjacentHTML('afterbegin', b);
    var wrap = host.querySelector('.heat-wrap');
    if (wrap) wrap.classList.toggle('recede', surface.live === false || !!surface.stale);
    updateScope(surface);
  }
  function updateScope(surface) {   // lightweight: only the age/scope tag in the panel header
    var strikes = surface.strikes || [], exps = surface.expirations || [], spot = Number(surface.spot);
    var srcLabel = surface.source === 'terrain_live_cache' ? (surface.complete === false ? 'LIVE·window' : 'LIVE')
      : surface.source === 'banked_morning_reference' ? 'REF·morning' : (surface.source || '');
    var age = surface.age_sec != null ? ' ' + Math.round(surface.age_sec) + 's' : '';
    var basis = (surface.coverage && surface.coverage.chain_basis) ? ' ' + surface.coverage.chain_basis : '';
    var el = document.getElementById('heatScope');
    if (el) {
      var shownRows = document.querySelectorAll('#heatBody .heat tbody tr').length;
      var shownCols = document.querySelectorAll('#heatBody .heat thead .hexp').length;
      var shown = (shownRows && shownCols) ? ' · ' + shownRows + '×' + shownCols + ' shown' : '';
      el.textContent = strikes.length + '×' + exps.length + ' canonical' + shown + ' · spot ' + (isFinite(spot) ? spot.toFixed(2) : '—') + ' · ' + srcLabel + age + basis;
      el.title = (surface.coverage && surface.coverage.note) || '';
    }
  }
  // ROOT-CAUSE FIX (2026-09-13, controlled reproduction confirmed): server.py pushes a
  // `gamma_surface_seq` SSE event on EVERY streamed publish (ed-core.js dispatches it as
  // `ed:refresh{slow:true, pushed:true}`) -- unboundedly frequent, not the 12s slow-poll
  // cadence this handler was written against. The old guard bumped `_gen` on every call and
  // only applied a response whose generation still matched on arrival: correct for
  // invalidating a stale ticker/view, but fatal once pushes arrive faster than the ~fetch
  // round trip -- a newer call always bumps `_gen` before the older fetch can land, so NO
  // response's generation ever survives, and the heatmap freezes until pushes stop (measured:
  // 500ms triggers vs a 750ms round trip left cells at their starting value while incoming
  // values advanced far past it). Fixed with EdL1SseGuards.makeCoalescedLoader: at most one
  // fetch in flight, a trigger that arrives mid-flight coalesces into exactly one trailing
  // re-run (never dropped, never piled up) -- so the table converges to the latest surface as
  // fast as the round trip allows, continuously, not only once traffic goes quiet. Context
  // invalidation (ticker/view changed while the fetch was in flight) is now `stillCurrent()`,
  // checked at resolution time instead of inferred from a counter.
  // Operator field-inventory audit (2026-09-13): dex/oi are the SAME heatmap pane gamma
  // renders (see state.measure / MEASURE_BY_SUBVIEW in ed-core.js), reached via a
  // DIFFERENT subview id -- every "am I still looking at the heatmap" check in this file
  // must recognize all three, or switching to Delta/DEX or Open Interest looks like
  // "left the heatmap" to this module: `load()`'s own guard bailed out treating it as a
  // navigate-away (clearing streamed-contract demand and never calling renderSurface at
  // all), leaving the OLD measure's numbers on screen under the NEW measure's title --
  // reproduced live: the Open Interest tab showed DEX's own dollar values unchanged.
  function _isGammaFamilySubview(sv) { return sv === 'gamma' || sv === 'dex' || sv === 'oi'; }
  function stillCurrent(ticker) {
    var s = (window.EdShell && window.EdShell.getState()) || {};
    return s.workspace === 'options' && _isGammaFamilySubview(s.subview) && s.view === 'heatmap' && (s.ticker || 'SPY') === ticker;
  }
  // Only the actual network fetch is coalesced. The "leaving the heatmap" cleanup below is
  // synchronous and state-authority-visible (it releases streamed-contract demand) -- it must
  // run the INSTANT the view changes, every time load() is called, never deferred behind a
  // stale/hung fetch the coalescing loader happens to still be waiting on (state-authority
  // review, 2026-09-13: reproduced exactly this way in ed-gamma-flow.js's analogous "clear
  // intent" branch — see that file's stillFlow fix for the identical class of bug).
  // ROUND 8 (2026-09-13, independent-review finding, REPRODUCED): the round-7 coalescing
  // loader merged EVERY trigger into the same in-flight slot, so a held/slow fetch for an
  // ABANDONED ticker blocked the newly-selected ticker from ever loading. Fixed by keying
  // the loader on ticker (makeCoalescedLoader now aborts+restarts immediately on a key
  // change instead of waiting) and passing the fetch its AbortSignal.
  function loadImpl(ticker, signal) {
    var host = document.getElementById('heatBody');
    if (!host || !stillCurrent(ticker)) return;
    host.setAttribute('aria-busy', 'true');
    return fetch('/api/options/gamma-surface?ticker=' + encodeURIComponent(ticker), { cache: 'no-store', signal: signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (stillCurrent(ticker)) renderSurface(host, d); })
      .catch(function (e) {
        if (e && e.name === 'AbortError') return;   // superseded by a newer ticker -- that load renders instead
        if (stillCurrent(ticker)) renderSurface(host, { available: false, reason: 'no console serving /api/options/gamma-surface' });
      });
  }
  var _pendingTicker = null;
  var _loader = (typeof window !== 'undefined' && window.EdL1SseGuards && window.EdL1SseGuards.makeCoalescedLoader)
    ? window.EdL1SseGuards.makeCoalescedLoader(function (signal) { return loadImpl(_pendingTicker, signal); })
    : { trigger: function () { loadImpl(_pendingTicker); }, reset: function () {} };
  function load() {
    var host = document.getElementById('heatBody');
    if (!host) return;
    var st = (window.EdShell && window.EdShell.getState()) || {};
    if (st.workspace !== 'options' || !_isGammaFamilySubview(st.subview) || st.view !== 'heatmap') {
      // Leaving the heatmap: its own streamed-contract demand (see renderSurface) must not
      // keep the last-viewed ticker's contracts subscribed forever once nobody is looking.
      // Runs immediately -- never coalesced behind an in-flight/hung surface fetch.
      if (window.EdStream && window.EdStream.setAdditionalContracts) {
        window.EdStream.setAdditionalContracts([], 'heatmap');
      }
      ++_demandGen; _demandStateByCol = {}; _demandSymbolsByCol = {};   // invalidate any in-flight confirm/reject from the view just left
      return;
    }
    _pendingTicker = st.ticker || 'SPY';
    _loader.trigger(_pendingTicker);
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('ed:ticker', load);
    document.addEventListener('ed:view', load);
    document.addEventListener('ed:refresh', function (e) { if (e.detail && e.detail.slow) load(); });
    document.addEventListener('ed:strike', function () { applyStrikeHighlight(); });   // A: cross-panel sync
    document.addEventListener('ed:theme', function () {   // recolour: force a rebuild (revision is unchanged but the palette changed)
      var h = document.getElementById('heatBody'); if (h && _lastSurface) { _lastRevision = null; renderSurface(h, _lastSurface); }
    });
    document.addEventListener('ed:expiry', function () {   // #5: re-window columns to the selected expiry (client-side; same canonical surface)
      var h = document.getElementById('heatBody'); if (!h) return; _lastRevision = null;
      if (_lastSurface) renderSurface(h, _lastSurface); else load();
    });
    document.addEventListener('ed:scope', function () {    // #3: Auto / Wider / All available re-selects the viewport (same canonical surface)
      var h = document.getElementById('heatBody'); if (!h) return; _lastRevision = null;
      if (_lastSurface) renderSurface(h, _lastSurface); else load();
    });
    // A direct #measureSel change (not a subview switch, which already re-renders via
    // ed:view) -- the SAME already-fetched surface, presenting a different one of its own
    // gex/dex/oi/volume fields (see _measureRow's own comment). No refetch needed.
    document.addEventListener('ed:measure', function () {
      var h = document.getElementById('heatBody'); if (!h) return; _lastRevision = null;
      if (_lastSurface) renderSurface(h, _lastSurface); else load();
    });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
  }

  var _root = (typeof window !== 'undefined') ? window : (typeof globalThis !== 'undefined' ? globalThis : this);
  _root.EdGamma = { formatUsd: formatUsd, cellStyle: cellStyle, nearestStrikeIndex: nearestStrikeIndex, renderSurface: renderSurface };
})();
