/**
 * The oven's control panel, down its right side, as measured on Breville's close-up: the display
 * at the top; the small CONFIRM dial with its orange ring beside START|STOP with its red one; the
 * TEMP and TIME dials; and the buttons down the right (light, convection, a bit more, frozen food,
 * favorite). The dials are spun metal: each mirrors the studio round its centre, so its light
 * turns with the angle, as measured; their polished rims and the grooves they sit in likewise.
 */
import { nothing, svg, type SVGTemplateResult } from "lit";
import { softFilter, spunDisc, type Ring } from "../materials";
import type { OvenState } from "../types";
import { display, lcdDefs } from "./lcd";
import { PANEL, type Finish } from "./measured";

const FONT = "'Arial Narrow', 'Roboto Condensed', 'Helvetica Neue', Arial, sans-serif";

export function panelDefs(uid: string, black: boolean, state: OvenState): SVGTemplateResult {
  return svg`
    ${lcdDefs(uid, black, state.lcd)}
    ${softFilter(`${uid}-spun`, 0.014)}
    <filter id=${`${uid}-sink`} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="0.9"></feGaussianBlur></filter>
    <filter id=${`${uid}-ring-glow`} x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="1.6"></feGaussianBlur></filter>
    <radialGradient id=${`${uid}-turned`} cx="0.5" cy="0.5" r="0.035" spreadMethod="repeat">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.05"></stop>
      <stop offset="0.5" stop-color="#000000" stop-opacity="0.05"></stop>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0.05"></stop>
    </radialGradient>
  `;
}

/** A disc of spun metal, smoothed. */
function spun(uid: string, cx: number, cy: number, r: number, ring: Ring, steps = 72): SVGTemplateResult {
  return svg`<g filter=${`url(#${uid}-spun)`}>${spunDisc(cx, cy, r, ring, steps)}</g>`;
}

/** A dial: the groove it sits in, its polished rim, and its spun face. */
function dial(uid: string, cx: number, cy: number, r: number, finish: Finish): SVGTemplateResult {
  return svg`
    <circle cx=${cx} cy=${cy + r * 0.06} r=${r * 0.99} fill="#000000" opacity="0.32" filter=${`url(#${uid}-sink)`}></circle>
    ${spun(uid, cx, cy, r * 0.965, finish.dialGroove, 48)}
    ${spun(uid, cx, cy, r * 0.885, finish.dialRim)}
    ${spun(uid, cx, cy, r * 0.765, finish.dialCap)}
    <circle cx=${cx} cy=${cy} r=${r * 0.765} fill=${`url(#${uid}-turned)`}></circle>
    <circle cx=${cx} cy=${cy} r=${r * 0.765} fill="none" stroke="#000000" stroke-opacity="0.28" stroke-width=${r * 0.014}></circle>
    <circle cx=${cx} cy=${cy} r=${r * 0.878} fill="none" stroke="#ffffff" stroke-opacity="0.4" stroke-width=${r * 0.012}></circle>
    <circle cx=${cx} cy=${cy} r=${r * 0.965} fill="none" stroke="#000000" stroke-opacity="0.35" stroke-width=${r * 0.016}></circle>
  `;
}

/** A light ring round a button: glowing when lit, else smoky. */
function lightRing(uid: string, cx: number, cy: number, inner: number, outer: number, color: "orange" | "red", lit: boolean, pulse: boolean): SVGTemplateResult {
  const tones = color === "red"
    ? { core: "#ff4a3f", body: "#d1242a", edge: "#7d1216", glow: "#ff2a1f" }
    : { core: "#ffb070", body: "#ea6a3c", edge: "#9c3b26", glow: "#ff7a3a" };
  const mid = (inner + outer) / 2;
  const width = outer - inner;
  if (!lit) {
    return svg`
      <circle cx=${cx} cy=${cy} r=${mid} fill="none" stroke="#2c2a29" stroke-opacity="0.75" stroke-width=${width}></circle>
      <circle cx=${cx} cy=${cy} r=${inner + width * 0.3} fill="none" stroke="#ffffff" stroke-opacity="0.18" stroke-width=${width * 0.25}></circle>
    `;
  }
  return svg`<g class=${pulse ? `${uid}-pulse` : ""}>
    <circle cx=${cx} cy=${cy} r=${mid} fill="none" stroke=${tones.glow} stroke-opacity="0.55" stroke-width=${width * 2.2}
      filter=${`url(#${uid}-ring-glow)`}></circle>
    <circle cx=${cx} cy=${cy} r=${mid} fill="none" stroke=${tones.edge} stroke-width=${width}></circle>
    <circle cx=${cx} cy=${cy} r=${mid} fill="none" stroke=${tones.body} stroke-width=${width * 0.72}></circle>
    <circle cx=${cx} cy=${cy} r=${mid - width * 0.08} fill="none" stroke=${tones.core} stroke-width=${width * 0.3}></circle>
  </g>`;
}

/** CONFIRM: a small spun dial ringed in orange, inside a polished rim. */
function confirm(uid: string, finish: Finish, lit: boolean): SVGTemplateResult {
  const { cx, cy, r } = PANEL.confirm;
  return svg`
    <circle cx=${cx} cy=${cy + r * 0.07} r=${r} fill="#000000" opacity="0.35" filter=${`url(#${uid}-sink)`}></circle>
    ${spun(uid, cx, cy, r * 0.97, finish.dialGroove, 36)}
    ${spun(uid, cx, cy, r * 0.88, finish.dialRim, 48)}
    ${lightRing(uid, cx, cy, r * 0.62, r * 0.74, "orange", lit, false)}
    ${spun(uid, cx, cy, r * 0.62, finish.dialCap, 48)}
    <circle cx=${cx} cy=${cy} r=${r * 0.62} fill="none" stroke="#000000" stroke-opacity="0.3" stroke-width="0.25"></circle>
  `;
}

/** START|STOP: a spun button ringed in red at its edge. */
function start(uid: string, finish: Finish, lit: boolean, pulse: boolean): SVGTemplateResult {
  const { cx, cy, r } = PANEL.start;
  return svg`
    <circle cx=${cx} cy=${cy + r * 0.06} r=${r} fill="#000000" opacity="0.32" filter=${`url(#${uid}-sink)`}></circle>
    ${lit ? nothing : spun(uid, cx, cy, r * 0.97, finish.dialRim, 48)}
    ${lightRing(uid, cx, cy, r * 0.8, r * 0.97, "red", lit, pulse)}
    ${spun(uid, cx, cy, r * 0.8, finish.dialCap, 48)}
    <circle cx=${cx} cy=${cy} r=${r * 0.8} fill="none" stroke="#000000" stroke-opacity="0.3" stroke-width="0.3"></circle>
    <circle cx=${cx} cy=${cy} r=${r * 0.985} fill="none" stroke="#000000" stroke-opacity="0.4" stroke-width="0.4"></circle>
  `;
}

function icon(kind: string, cx: number, cy: number, ink: string): SVGTemplateResult {
  const line = { fill: "none", stroke: ink, "stroke-width": 0.42, "stroke-linecap": "round", "stroke-linejoin": "round" } as const;
  switch (kind) {
    case "light":
      return svg`<g fill=${line.fill} stroke=${ink} stroke-width=${line["stroke-width"]} stroke-linecap="round">
        <path d=${`M${cx - 1.1},${cy + 0.9} C${cx - 2.2},${cy - 0.1} ${cx - 2.1},${cy - 2.6} ${cx},${cy - 2.6} C${cx + 2.1},${cy - 2.6} ${cx + 2.2},${cy - 0.1} ${cx + 1.1},${cy + 0.9} Z`}></path>
        <path d=${`M${cx - 0.9},${cy + 1.6} h1.8 M${cx - 0.7},${cy + 2.3} h1.4`}></path>
      </g>`;
    case "fan":
      return svg`<g fill=${ink}>${[0, 120, 240].map(
        (angle) => svg`<path d=${`M${cx},${cy} c0.3,-1.2 1.9,-2 2.3,-0.9 c0.3,0.9 -0.9,1.4 -2.3,0.9Z`} transform=${`rotate(${angle} ${cx} ${cy})`}></path>`,
      )}<circle cx=${cx} cy=${cy} r="0.45"></circle></g>`;
    case "more":
      return svg`<g fill="none" stroke=${ink} stroke-width=${line["stroke-width"]} stroke-linecap="round">
        <path d=${`M${cx + 1.9},${cy - 0.6} A2.2,2.2 0 1 0 ${cx + 0.6},${cy + 2}`}></path>
        <path d=${`M${cx - 0.3},${cy - 1.2} v1.3 h1`}></path>
        <path d=${`M${cx + 1.9},${cy + 0.6} v1.8 M${cx + 1},${cy + 1.5} h1.8`}></path>
      </g>`;
    case "frozen":
      return svg`<g fill="none" stroke=${ink} stroke-width=${line["stroke-width"]} stroke-linecap="round">
        ${[0, 60, 120].map(
          (angle) => svg`<g transform=${`rotate(${angle} ${cx} ${cy})`}>
            <path d=${`M${cx},${cy - 2.4} v4.8 M${cx - 0.6},${cy - 2} l0.6,0.6 l0.6,-0.6 M${cx - 0.6},${cy + 2} l0.6,-0.6 l0.6,0.6`}></path>
          </g>`,
        )}
      </g>`;
    default:
      return svg`<path d=${`M${cx},${cy + 1.9} L${cx - 1.9},${cy} A1.1,1.1 0 0 1 ${cx},${cy - 1.5} A1.1,1.1 0 0 1 ${cx + 1.9},${cy} Z`}
        fill="none" stroke=${ink} stroke-width=${line["stroke-width"]} stroke-linejoin="round"></path>`;
  }
}

/** A small button: a raised ring, lit on its upper left, with its icon. */
function button(cy: number, kind: string, finish: Finish): SVGTemplateResult {
  const cx = PANEL.buttonX;
  const r = PANEL.buttonR;
  return svg`
    <circle cx=${cx + 0.15} cy=${cy + 0.35} r=${r + 0.2} fill="none" stroke="#000000" stroke-opacity="0.18" stroke-width="0.6"></circle>
    <circle cx=${cx} cy=${cy} r=${r} fill="none" stroke=${finish.button[1]} stroke-width="0.45"></circle>
    <path d=${`M${cx - r * 0.93},${cy + r * 0.35} A${r * 0.99},${r * 0.99} 0 0 1 ${cx + r * 0.35},${cy - r * 0.93}`} fill="none"
      stroke=${finish.button[0]} stroke-opacity="0.85" stroke-width="0.45"></path>
    ${icon(kind, cx, cy, finish.ink)}
  `;
}

function label(text: string, x: number, y: number, size: number, length: number, ink: string, weight = 700, anchor = "start"): SVGTemplateResult {
  return svg`<text x=${x} y=${y} font-size=${size} font-weight=${weight} font-family=${FONT} text-anchor=${anchor}
    textLength=${length} lengthAdjust="spacingAndGlyphs" fill=${ink}>${text}</text>`;
}

export function controlPanel(uid: string, state: OvenState, finish: Finish, black: boolean, motion: boolean): SVGTemplateResult {
  const ink = finish.ink;
  const awake = state.lcd !== null;
  const running = Boolean(state.lcd?.lit);
  const { confirm: c, temp, time } = PANEL;
  return svg`
    <g class="oven-panel">
      ${display(uid, black, state.lcd)}
      ${label("CONFIRM", c.cx, 112.6, 2.5, 10.4, ink, 700, "middle")}
      ${label("Rotate Remind", c.cx, 115.4, 1.45, 10.4, ink, 600, "middle")}
      ${label("START", 514.6, 114.4, 2.5, 7.6, ink, 700, "end")}
      <line x1="515.6" x2="515.6" y1="111.9" y2="114.6" stroke=${ink} stroke-width="0.3"></line>
      ${label("STOP", 516.6, 114.4, 2.5, 6.2, ink)}
      <g fill="none" stroke=${ink} stroke-width="0.55" stroke-linecap="round">
        <path d=${`M${c.cx + 12.6},${c.cy - 8.2} A15,15 0 0 1 ${c.cx + 12.6},${c.cy + 8.2}`}></path>
        <path d=${`M${c.cx + 10.6},${c.cy - 9.6} l2,1.4 l-0.5,-2.3`} fill=${ink}></path>
        <path d=${`M${c.cx + 10.6},${c.cy + 9.6} l2,-1.4 l-0.5,2.3`} fill=${ink}></path>
        <path d=${`M${c.cx + 16.2},${c.cy - 1.3} h3 M${c.cx + 16.2},${c.cy} h3 M${c.cx + 16.2},${c.cy + 1.3} h3`} stroke-width="0.45"></path>
      </g>
      ${label("TEMP", 457.6, 160.8, 2.5, 6.6, ink)}
      <line x1="457.6" x2="473.2" y1="161.9" y2="161.9" stroke=${ink} stroke-width="0.3"></line>
      ${label("Darkness", 457.6, 164.9, 1.6, 8.6, ink, 600)}
      ${label("TIME", 457.6, 229.6, 2.5, 6.4, ink)}
      <line x1="457.6" x2="473.2" y1="230.7" y2="230.7" stroke=${ink} stroke-width="0.3"></line>
      ${label("Slices", 457.6, 233.7, 1.6, 5.8, ink, 600)}
      ${label("°F", 516.4, 157.9, 1.6, 2.5, ink, 700)}
      <line x1="516.2" x2="519.4" y1="160.4" y2="158.4" stroke=${ink} stroke-width="0.25"></line>
      ${label("°C", 517.4, 161.6, 1.6, 2.5, ink, 700)}
      ${label("A Bit", 519.2, 218.3, 1.35, 3.8, ink, 700, "end")}
      ${label("More", 519.2, 220.2, 1.35, 3.8, ink, 700, "end")}
      ${label("Favorite", PANEL.buttonX, 284.4, 1.35, 6, ink, 700, "middle")}
      ${confirm(uid, finish, awake)}
      ${start(uid, finish, running || state.start_prompt, state.start_prompt && motion)}
      ${dial(uid, temp.cx, temp.cy, temp.r, finish)}
      ${dial(uid, time.cx, time.cy, time.r, finish)}
      ${PANEL.buttons.map(({ cy, icon: kind }) => button(cy, kind, finish))}
    </g>
  `;
}
