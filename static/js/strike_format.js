/* THE strike display authority for every browser surface. ONE PRODUCER, many consumers.
 *
 * # ui-mockup-ok: non-redesign FIDELITY BUG FIX (2026-08-26). Changes no layout, encoding or
 * interaction — only what a strike-valued label SAYS.
 *
 * WHY THIS FILE EXISTS RATHER THAN A HELPER PER PAGE. The defect it fixes was a formatting rule
 * duplicated per surface and wrong in different ways on each:
 *     chart.html    fmt(k, 0)                       -> 322.5 printed "323"
 *     exposure.html fmt(k, 0)                       -> 322.5 printed "323"
 *     index.html    r.k.toFixed(1)                  -> 17.25 printed "17.3"
 *     chart.html:1634 fmt(r[0], isInt ? 0 : 2)      -> correct, and alone in being correct
 * Four surfaces, four rules, one of them right. Fixing them in place would have produced four
 * CORRECT rules that could drift apart again on the next edit. A displayed strike is one
 * computation, so it gets one producer.
 *
 * WHAT WAS WRONG. toFixed(0) ROUNDS. Per ECMA-262 it picks the larger n on a tie, so a real 322.5
 * strike does not lose a decimal — it becomes 323, a price at which no contract trades. Two
 * distinct harms follow:
 *   FABRICATION  — the console names a level the operator cannot act on. This reached the
 *                  CALL WALL / PUT WALL chips and the NET GEX PEAK banner, not just axis ticks.
 *   COLLISION    — on a 0.5 ladder two adjacent real strikes print the SAME label (22.5 and 23.0
 *                  both render "23"), so a strike disappears from the display entirely.
 *
 * WHY IT SURVIVED. SPY, QQQ and IWM trade whole-dollar ladders, so on the three tickers everyone
 * watches the rounding is invisible. Measured live 2026-08-26: TSLA/AAPL/META/NVDA trade a 2.5
 * ladder; XRT/CDE/CIFR/SMCI/KRE/PCG a 0.5 one. The bug was CORE-TICKER-SHAPED — right on the
 * anchors, wrong on everything else.
 *
 * THE RULE, carrying no instrument knowledge: show exactly the decimals this number needs.
 *     320 -> "320"      322.5 -> "322.5"      17.25 -> "17.25"      1.125 -> "1.125"
 * No increment, tick size, roster or core-ticker assumption, so an optionable symbol this console
 * has never seen formats correctly with no prior knowledge of it.
 *
 * SERVER COUNTERPART: instrument_identity.format_strike_for_display (Python). The two must agree;
 * tests/test_ui_strike_label_fidelity_v1.py asserts they produce identical output.
 */
(function (root) {
  'use strict';

  // Strike prices are exact binary fractions in practice (.5, .25, .125), and four decimals is
  // well beyond any listed increment. Trailing zeros are trimmed so a whole-dollar strike reads
  // "320" rather than "320.0000" — the display should look like the ladder, not like a float.
  var STRIKE_DECIMALS = 4;

  function fmtStrike(k) {
    if (k === null || k === undefined || k === '') return '—';
    var n = Number(k);
    if (!isFinite(n)) return '—';
    var s = n.toFixed(STRIKE_DECIMALS);
    if (s.indexOf('.') < 0) return s;
    return s.replace(/0+$/, '').replace(/\.$/, '');
  }

  // Already loaded (a page may include this once per bundle) — do not redefine, so there is
  // exactly one function object and no chance of two behaviours in one document.
  if (typeof root.fmtStrike === 'function') return;

  root.fmtStrike = fmtStrike;
  root.EdStrikeFormat = { fmtStrike: fmtStrike, decimals: STRIKE_DECIMALS };
})(typeof window !== 'undefined' ? window : globalThis);
