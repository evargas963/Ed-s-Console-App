/**
 * RC-304 — the provenance of a FORCES row is the DATA that row summed, not the payload it
 * arrived in.
 *
 * /api/forces answers with one object built from two banked captures, and the three rows it
 * feeds do not share a source:
 *
 *   ΔOI    differences open interest between the OLDER capture (older_et_date) and the NEWER
 *          one (newer_et_date) — genuinely a two-date span.
 *   DEX    sums net_dex_dollars on the NEWER capture only.
 *   CHARM  sums dealer-signed net_charm on the NEWER capture only, over whichever book that
 *          capture held — which is why the server derives `charm_book_scope` (RC-288) by
 *          counting the distinct expiries it actually summed.
 *
 * chart.html labelled all three `banked <older>→<newer>`, which advertised a two-date span
 * behind two single-date numbers and never showed the book scope at all. Charm printed beside
 * whole-book GEX with nothing to say whether it covered the whole book or one expiry.
 *
 * Absence is reported as absence (RC-274/RC-301): a missing date yields "date unknown", never
 * a confident span, and a served `charm_error` is stated rather than hidden behind a label
 * that implies the number simply has not arrived.
 *
 * Exposed as globalThis.EdForcesProvenance, the convention static/js/l1_sse_guards.js set.
 */
(function (g) {
  'use strict';

  function _d(v) {
    if (v == null) return '';
    const s = String(v).trim();
    return s ? s.slice(0, 10) : '';
  }

  /**
   * Source label for one FORCES row.
   *
   * @param {object|null} fz   the /api/forces payload
   * @param {string} row       'doi' | 'dex' | 'charm'
   * @returns {string}         what this row's numbers were summed over
   */
  function forcesRowSource(fz, row) {
    if (!fz || !fz.available) {
      return fz && fz.reason ? String(fz.reason).slice(0, 60) : 'banked chains — loading';
    }
    const newer = _d(fz.newer_et_date), older = _d(fz.older_et_date);

    if (row === 'doi') {
      // The only row that spans both captures.
      return (older && newer)
        ? `banked ${older}→${newer}`
        : 'banked pair — date unknown';
    }

    const one = newer ? `banked ${newer}` : 'banked — date unknown';
    if (row !== 'charm') return one;

    // The charm row carries the book it was summed over, and says so when it failed.
    if (fz.charm_error) return `${one} · charm failed: ${String(fz.charm_error).slice(0, 48)}`;
    if (fz.charm_below == null && fz.charm_above == null) return `${one} · charm not served`;
    const scope = fz.charm_book_scope == null ? '' : String(fz.charm_book_scope).trim();
    return scope ? `${one} · ${scope}` : `${one} · book scope unknown`;
  }

  g.EdForcesProvenance = { forcesRowSource: forcesRowSource };
})(typeof globalThis !== 'undefined' ? globalThis : this);
