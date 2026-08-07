/*
 * Synthetic reference only.
 * Not production.
 * Not approved visual final.
 * Companion to reports/exposure_overlay_chart_direction_v1.md
 *
 * Operator is not a fan of this look - encodings are the deliverable, not this aesthetic as final UI.
 */

import React, { useMemo, useState } from "react";

/* ------------------------------------------------------------------ *
 * On-chart dealer exposure overlay — visual reference build
 * Synthetic SPX 0DTE data. No live feed. Encodings are the deliverable.
 * ------------------------------------------------------------------ */

const C = {
  bg: "#0A0C10",
  panel: "#101419",
  grid: "#1A2029",
  gridSoft: "#141920",
  pos: "#F5B301",      // positive dealer gamma (calls)
  posDim: "#7A5A02",
  neg: "#A855F7",      // negative dealer gamma (puts)
  negDim: "#4C2870",
  king: "#22D3EE",     // largest |GEX| — structural gravity
  flip: "#E2E8F0",     // gamma flip / HVL
  air: "#2E2140",      // air pocket
  wickUp: "#D6DEE7",
  wickDn: "#5C6672",
  text: "#E6EBF0",
  dim: "#7C8794",
  faint: "#3A434E",
};

const W = 1000, H = 560;
const PLOT = { x0: 56, x1: 806, y0: 28, y1: 494 };
const LADDER = { x0: 822, x1: 986 };

/* ---------------- synthetic data ---------------- */

function lcg(seed) {
  let s = seed;
  return () => ((s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296);
}

const STRIKES = [
  { k: 6470, gex: 8 }, { k: 6465, gex: 14 }, { k: 6460, gex: 31 },
  { k: 6455, gex: 62 }, { k: 6450, gex: 192 }, { k: 6445, gex: 71 },
  { k: 6440, gex: 44 }, { k: 6435, gex: 21 }, { k: 6430, gex: 9 },
  { k: 6425, gex: -11 }, { k: 6420, gex: -34 }, { k: 6415, gex: -58 },
  { k: 6410, gex: -96 }, { k: 6405, gex: -134 }, { k: 6400, gex: -171 },
  { k: 6395, gex: -88 }, { k: 6390, gex: -47 }, { k: 6385, gex: -22 },
  { k: 6380, gex: -9 },
];

const FLIP = 6432;      // HVL / gamma flip
const SPOT = 6440.75;

const EVENTS = [
  { i: 7,  k: 6450, usd: 38.32 },
  { i: 13, k: 6400, usd: -30.51 },
  { i: 21, k: 6445, usd: 22.83 },
  { i: 29, k: 6410, usd: -17.40 },
  { i: 37, k: 6455, usd: 12.64 },
  { i: 46, k: 6425, usd: -9.12 },
  { i: 53, k: 6450, usd: 26.70 },
];

const ANCHORS = [[0, 6398], [10, 6404], [20, 6417], [30, 6430], [40, 6449], [48, 6453], [54, 6443], [59, 6441]];
const N = 60;

function buildCandles() {
  const rnd = lcg(20260802);
  const mid = [];
  for (let i = 0; i < N; i++) {
    let a = ANCHORS[0], b = ANCHORS[ANCHORS.length - 1];
    for (let j = 0; j < ANCHORS.length - 1; j++) {
      if (i >= ANCHORS[j][0] && i <= ANCHORS[j + 1][0]) { a = ANCHORS[j]; b = ANCHORS[j + 1]; break; }
    }
    const t = (i - a[0]) / Math.max(1, b[0] - a[0]);
    mid.push(a[1] + (b[1] - a[1]) * t + (rnd() - 0.5) * 3.4);
  }
  return mid.map((m, i) => {
    const o = i === 0 ? m - 1 : mid[i - 1];
    const c = m;
    const pad = 0.9 + rnd() * 2.6;
    return { i, o, c, h: Math.max(o, c) + pad, l: Math.min(o, c) - pad };
  });
}

/* ---------------- derived structure ---------------- */

function deriveStructure(strikes) {
  const maxAbs = Math.max(...strikes.map((s) => Math.abs(s.gex)));
  const king = strikes.reduce((a, b) => (Math.abs(b.gex) > Math.abs(a.gex) ? b : a));
  const callWall = strikes.filter((s) => s.gex > 0).reduce((a, b) => (b.gex > a.gex ? b : a));
  const putWall = strikes.filter((s) => s.gex < 0).reduce((a, b) => (b.gex < a.gex ? b : a));

  // air pockets: runs of strikes with |gex| under 15% of peak
  const thr = maxAbs * 0.15;
  const pockets = [];
  let run = null;
  [...strikes].sort((a, b) => a.k - b.k).forEach((s) => {
    if (Math.abs(s.gex) < thr) {
      if (!run) run = { lo: s.k, hi: s.k };
      else run.hi = s.k;
    } else if (run) { pockets.push(run); run = null; }
  });
  if (run) pockets.push(run);

  // gatekeeper: strike adjacent to the sign change nearest spot
  const sorted = [...strikes].sort((a, b) => a.k - b.k);
  let gate = null;
  for (let i = 1; i < sorted.length; i++) {
    if (Math.sign(sorted[i].gex) !== Math.sign(sorted[i - 1].gex)) {
      gate = Math.abs(sorted[i].gex) > Math.abs(sorted[i - 1].gex) ? sorted[i] : sorted[i - 1];
    }
  }
  const net = strikes.reduce((a, s) => a + s.gex, 0);
  return { maxAbs, king, callWall, putWall, pockets, gate, net };
}

/* ---------------- component ---------------- */

export default function ExposureOverlayChart() {
  const [show, setShow] = useState({
    walls: true, bubbles: true, pockets: true, flip: true, ladder: true,
  });
  const [hover, setHover] = useState(null);

  const candles = useMemo(buildCandles, []);
  const S = useMemo(() => deriveStructure(STRIKES), []);

  const lo = 6376, hi = 6474;
  const y = (p) => PLOT.y1 - ((p - lo) / (hi - lo)) * (PLOT.y1 - PLOT.y0);
  const x = (i) => PLOT.x0 + (i / (N - 1)) * (PLOT.x1 - PLOT.x0);
  const cw = (PLOT.x1 - PLOT.x0) / N * 0.62;

  const maxUsd = Math.max(...EVENTS.map((e) => Math.abs(e.usd)));
  const rOf = (u) => 9 + 20 * Math.sqrt(Math.abs(u) / maxUsd);
  const bandOf = (g) => 2.5 + 13 * (Math.abs(g) / S.maxAbs);

  const regimePos = SPOT > FLIP;
  const toggle = (k) => setShow((s) => ({ ...s, [k]: !s[k] }));

  const chips = [
    ["walls", "Exposure walls"], ["bubbles", "Flow bubbles"],
    ["pockets", "Air pockets"], ["flip", "Gamma flip"], ["ladder", "Strike ladder"],
  ];

  return (
    <div className="w-full min-h-screen p-4 sm:p-6" style={{ background: C.bg }}>
      <div className="max-w-6xl mx-auto">

        {/* header */}
        <div className="flex flex-wrap items-end justify-between gap-4 mb-4">
          <div>
            <div className="flex items-baseline gap-3">
              <h1 className="text-2xl font-semibold tracking-tight" style={{ color: C.text }}>SPXW</h1>
              <span className="font-mono text-2xl tabular-nums" style={{ color: C.text }}>{SPOT.toFixed(2)}</span>
              <span className="font-mono text-sm" style={{ color: C.pos }}>+18.40</span>
            </div>
            <p className="mt-1 text-xs tracking-wide uppercase" style={{ color: C.dim }}>
              0DTE dealer exposure · synthetic reference data
            </p>
          </div>

          <div className="flex items-center gap-2">
            <div className="px-3 py-1.5 rounded-md border font-mono text-xs"
              style={{ borderColor: regimePos ? C.posDim : C.negDim, color: regimePos ? C.pos : C.neg, background: C.panel }}>
              {regimePos ? "POSITIVE GAMMA" : "NEGATIVE GAMMA"}
            </div>
            <div className="px-3 py-1.5 rounded-md border font-mono text-xs"
              style={{ borderColor: C.grid, color: C.dim, background: C.panel }}>
              NET GEX <span style={{ color: S.net >= 0 ? C.pos : C.neg }}>{S.net >= 0 ? "+" : ""}{S.net}M</span>
            </div>
          </div>
        </div>

        {/* chart */}
        <div className="rounded-lg border overflow-hidden" style={{ borderColor: C.grid, background: C.panel }}>
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto block" role="img"
            aria-label="Intraday price chart with dealer gamma exposure overlays">

            <defs>
              <pattern id="hatch" width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
                <line x1="0" y1="0" x2="0" y2="7" stroke={C.air} strokeWidth="3" />
              </pattern>
              <linearGradient id="kingGlow" x1="0" x2="1">
                <stop offset="0%" stopColor={C.king} stopOpacity="0" />
                <stop offset="18%" stopColor={C.king} stopOpacity="0.55" />
                <stop offset="100%" stopColor={C.king} stopOpacity="0.12" />
              </linearGradient>
            </defs>

            <rect width={W} height={H} fill={C.bg} />

            {/* price gridlines */}
            {[6380, 6400, 6420, 6440, 6460].map((p) => (
              <g key={p}>
                <line x1={PLOT.x0} x2={PLOT.x1} y1={y(p)} y2={y(p)} stroke={C.gridSoft} strokeWidth="1" />
                <text x={PLOT.x0 - 10} y={y(p) + 4} textAnchor="end"
                  className="font-mono" fontSize="11" fill={C.faint}>{p}</text>
              </g>
            ))}

            {/* LAYER 1 — air pockets */}
            {show.pockets && S.pockets.map((p, i) => (
              <g key={i}>
                <rect x={PLOT.x0} y={y(p.hi + 2.5)} width={PLOT.x1 - PLOT.x0}
                  height={Math.max(6, y(p.lo - 2.5) - y(p.hi + 2.5))} fill="url(#hatch)" opacity="0.5" />
                <text x={PLOT.x0 + 8} y={y((p.hi + p.lo) / 2) + 4} fontSize="9.5"
                  className="font-mono uppercase tracking-widest" fill={C.neg} opacity="0.75">air pocket</text>
              </g>
            ))}

            {/* LAYER 2 — exposure walls, thickness encodes magnitude */}
            {show.walls && STRIKES.map((s) => {
              const isKing = s.k === S.king.k;
              const h = bandOf(s.gex);
              const col = s.gex >= 0 ? C.pos : C.neg;
              if (Math.abs(s.gex) < S.maxAbs * 0.12 && !isKing) return null;
              return (
                <g key={s.k}>
                  {isKing && (
                    <rect x={PLOT.x0} y={y(s.k) - h / 2 - 5} width={PLOT.x1 - PLOT.x0} height={h + 10}
                      fill="url(#kingGlow)" opacity="0.5" />
                  )}
                  <rect x={PLOT.x0} y={y(s.k) - h / 2} width={PLOT.x1 - PLOT.x0} height={h}
                    fill={col} opacity={isKing ? 0.62 : 0.3} rx={h / 2} />
                </g>
              );
            })}

            {/* wall labels */}
            {show.walls && [
              { s: S.callWall, t: "CALL WALL", c: C.pos },
              { s: S.putWall, t: "PUT WALL", c: C.neg },
              { s: S.gate, t: "GATEKEEPER", c: C.dim },
            ].filter(Boolean).map(({ s, t, c }) => (
              <text key={t} x={PLOT.x1 - 8} y={y(s.k) - 7} textAnchor="end" fontSize="9.5"
                className="font-mono tracking-widest" fill={c} opacity="0.85">{t} {s.k}</text>
            ))}

            {/* LAYER 3 — gamma flip */}
            {show.flip && (
              <g>
                <line x1={PLOT.x0} x2={PLOT.x1} y1={y(FLIP)} y2={y(FLIP)}
                  stroke={C.flip} strokeWidth="1.25" strokeDasharray="2 6" opacity="0.7" />
                <text x={PLOT.x0 + 8} y={y(FLIP) - 7} fontSize="9.5"
                  className="font-mono tracking-widest" fill={C.flip} opacity="0.8">GAMMA FLIP {FLIP}</text>
              </g>
            )}

            {/* LAYER 4 — candles, deliberately desaturated */}
            {candles.map((d) => {
              const up = d.c >= d.o;
              const col = up ? C.wickUp : C.wickDn;
              const top = y(Math.max(d.o, d.c));
              const bot = y(Math.min(d.o, d.c));
              return (
                <g key={d.i} opacity="0.92">
                  <line x1={x(d.i)} x2={x(d.i)} y1={y(d.h)} y2={y(d.l)} stroke={col} strokeWidth="1" />
                  <rect x={x(d.i) - cw / 2} y={top} width={cw} height={Math.max(1, bot - top)}
                    fill={up ? "none" : col} stroke={col} strokeWidth="1.1" />
                </g>
              );
            })}

            {/* LAYER 5 — flow bubbles */}
            {show.bubbles && EVENTS.map((e, idx) => {
              const col = e.usd >= 0 ? C.pos : C.neg;
              const r = rOf(e.usd);
              const cx = x(e.i), cy = y(e.k);
              const anchorY = y(candles[e.i].c);
              const active = hover === idx;
              return (
                <g key={idx} onMouseEnter={() => setHover(idx)} onMouseLeave={() => setHover(null)}
                  style={{ cursor: "pointer" }}>
                  <line x1={cx} x2={cx} y1={cy} y2={anchorY} stroke={col} strokeWidth="1" opacity="0.4"
                    strokeDasharray="1 3" />
                  <circle cx={cx} cy={cy} r={r} fill={col} opacity={active ? 0.34 : 0.19} />
                  <circle cx={cx} cy={cy} r={r} fill="none" stroke={col} strokeWidth={active ? 2 : 1.25}
                    opacity={active ? 1 : 0.8} />
                  <text x={cx} y={cy + 4} textAnchor="middle" fontSize="11.5"
                    className="font-mono tabular-nums" fill={col} fontWeight="600">
                    ${Math.abs(e.usd).toFixed(1)}M
                  </text>
                </g>
              );
            })}

            {/* spot marker */}
            <line x1={PLOT.x0} x2={PLOT.x1} y1={y(SPOT)} y2={y(SPOT)} stroke={C.king} strokeWidth="0.75" opacity="0.4" />
            <rect x={PLOT.x1 - 62} y={y(SPOT) - 9} width="60" height="18" rx="3" fill={C.king} />
            <text x={PLOT.x1 - 32} y={y(SPOT) + 4} textAnchor="middle" fontSize="11"
              className="font-mono tabular-nums" fill={C.bg} fontWeight="700">{SPOT.toFixed(2)}</text>

            {/* LAYER 6 — strike ladder, shares the price axis */}
            {show.ladder && (
              <g>
                <line x1={LADDER.x0 - 10} x2={LADDER.x0 - 10} y1={PLOT.y0} y2={PLOT.y1}
                  stroke={C.grid} strokeWidth="1" />
                <text x={LADDER.x0} y={PLOT.y0 - 8} fontSize="9.5"
                  className="font-mono tracking-widest" fill={C.dim}>NET GEX BY STRIKE →</text>
                {STRIKES.map((s) => {
                  const col = s.gex >= 0 ? C.pos : C.neg;
                  const w = (Math.abs(s.gex) / S.maxAbs) * (LADDER.x1 - LADDER.x0 - 46);
                  const isKing = s.k === S.king.k;
                  return (
                    <g key={s.k}>
                      <rect x={LADDER.x0} y={y(s.k) - 5} width={Math.max(1.5, w)} height="10"
                        fill={col} opacity={isKing ? 0.95 : 0.55} rx="1.5" />
                      <text x={LADDER.x0 + Math.max(1.5, w) + 6} y={y(s.k) + 4} fontSize="9.5"
                        className="font-mono tabular-nums" fill={isKing ? C.king : C.faint}>
                        {s.gex > 0 ? "+" : ""}{s.gex}
                      </text>
                      {isKing && (
                        <circle cx={LADDER.x0 - 5} cy={y(s.k)} r="2.5" fill={C.king}
                          className="motion-reduce:animate-none animate-pulse" />
                      )}
                    </g>
                  );
                })}
              </g>
            )}

            {/* king node callout */}
            <g>
              <text x={PLOT.x0 + 8} y={y(S.king.k) - 12} fontSize="10"
                className="font-mono tracking-widest" fill={C.king} fontWeight="700">
                ◆ KING NODE {S.king.k} · {S.king.gex > 0 ? "+" : ""}{S.king.gex}M
              </text>
            </g>

            {/* tooltip */}
            {hover !== null && (() => {
              const e = EVENTS[hover];
              const tx = Math.min(x(e.i) + 22, PLOT.x1 - 190);
              const ty = Math.max(y(e.k) - 58, PLOT.y0 + 4);
              const col = e.usd >= 0 ? C.pos : C.neg;
              return (
                <g pointerEvents="none">
                  <rect x={tx} y={ty} width="182" height="54" rx="4" fill={C.panel}
                    stroke={C.grid} strokeWidth="1" />
                  <text x={tx + 10} y={ty + 18} fontSize="10.5" className="font-mono" fill={C.text}>
                    Strike {e.k} · {e.usd >= 0 ? "call" : "put"} side
                  </text>
                  <text x={tx + 10} y={ty + 34} fontSize="10.5" className="font-mono" fill={col}>
                    Δ exposure {e.usd >= 0 ? "+" : "−"}${Math.abs(e.usd).toFixed(2)}M
                  </text>
                  <text x={tx + 10} y={ty + 48} fontSize="9.5" className="font-mono" fill={C.dim}>
                    {e.usd >= 0 ? "dampening · hedges fade moves" : "amplifying · hedges chase moves"}
                  </text>
                </g>
              );
            })()}

            {/* session close boundary */}
            <line x1={x(N - 1) + 14} x2={x(N - 1) + 14} y1={PLOT.y0} y2={PLOT.y1}
              stroke={C.faint} strokeWidth="1" strokeDasharray="4 5" />

            {/* time axis */}
            {[[0, "09:30"], [15, "10:45"], [30, "12:00"], [45, "13:15"], [59, "14:25"]].map(([i, t]) => (
              <text key={t} x={x(i)} y={PLOT.y1 + 20} textAnchor="middle" fontSize="10"
                className="font-mono" fill={C.faint}>{t}</text>
            ))}
          </svg>

          {/* toggles */}
          <div className="flex flex-wrap gap-2 px-4 py-3 border-t" style={{ borderColor: C.grid }}>
            {chips.map(([k, label]) => (
              <button key={k} onClick={() => toggle(k)}
                className="px-3 py-1.5 rounded text-xs font-mono tracking-wide border transition-colors focus:outline-none focus-visible:ring-2"
                style={{
                  borderColor: show[k] ? C.grid : C.gridSoft,
                  background: show[k] ? "#181E26" : "transparent",
                  color: show[k] ? C.text : C.faint,
                }}>
                {show[k] ? "●" : "○"} {label}
              </button>
            ))}
          </div>
        </div>

        {/* legend */}
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[
            { c: C.pos, t: "Positive dealer gamma", d: "Hedges oppose the move. Pins, fades, mean reversion." },
            { c: C.neg, t: "Negative dealer gamma", d: "Hedges chase the move. Breakouts extend, breakdowns deepen." },
            { c: C.king, t: "King node", d: "Largest |GEX| on the map. Primary reversion target into the close." },
          ].map((l) => (
            <div key={l.t} className="rounded border p-3" style={{ borderColor: C.grid, background: C.panel }}>
              <div className="flex items-center gap-2">
                <span className="inline-block w-3 h-3 rounded-sm" style={{ background: l.c }} />
                <span className="text-xs font-semibold" style={{ color: C.text }}>{l.t}</span>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed" style={{ color: C.dim }}>{l.d}</p>
            </div>
          ))}
        </div>

        <p className="mt-4 text-xs" style={{ color: C.faint }}>
          Synthetic data for layout reference. Sign convention: calls positive, puts negative (dealer view).
        </p>
      </div>
    </div>
  );
}
