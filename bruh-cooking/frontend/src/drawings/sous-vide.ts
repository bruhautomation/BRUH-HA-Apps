/**
 * The Joule and the Joule Turbo, clipped to the back of a clear container of water, seen from a
 * little above. Drawn to scale in millimetres (the Joule 279 mm tall and 47 across, the Turbo
 * 312) and shaded as measured on Breville's photos: glossy white, lit from the left; a polished
 * cap with the light at its front; a chrome foot. The container is a clear 12-quart one with a
 * moulded rim and graduations; the water is nearly colourless, its surface catching the light.
 * While a cook runs, the water circulates (a stream of bubbles from the outlet, ripples round the
 * Joule); it steams as it warms; the bagged steak goes in with the food. No logos.
 */
import { html, nothing, svg, type SVGTemplateResult, type TemplateResult } from "lit";
import { unsafeSVG } from "lit/directives/unsafe-svg.js";
import { blur, floorShadow, labelSize, linear, mix, profile, radial, round, roundRect, type Profile } from "./materials";
import type { DrawingInput, SousVideState } from "./types";

const VIEW_W = 360;
const VIEW_H = 400;
// The container: its back rim and bottom edge are higher than the front ones, as seen from above.
const BOX = {
  backTop: 150,
  frontTop: 170,
  backBottom: 366,
  frontBottom: 382,
  topLeft: 20,
  topRight: 340,
  bottomLeft: 32,
  bottomRight: 328,
};
// The circulator's axis, and where its foot stands, just off the container's floor at the back.
const AXIS = 238;
const FOOT = 361;
const RADIUS = 23.5;

/** Glossy white across the body, left to right, as measured on each model's photo. */
const WHITE: Record<"CSJ100" | "BSV600", Profile> = {
  CSJ100: [
    [0, "#c9cacd"],
    [0.025, "#e9e9ec"],
    [0.08, "#f7f7f9"],
    [0.32, "#f6f6f8"],
    [0.5, "#dcdde1"],
    [0.7, "#c9cace"],
    [0.84, "#bebfc3"],
    [0.93, "#c6c6c8"],
    [0.975, "#d2d2d4"],
    [1, "#a7a8ac"],
  ],
  BSV600: [
    [0, "#c8c8cc"],
    [0.03, "#e3e3e7"],
    [0.21, "#fdfdff"],
    [0.45, "#f0f0f3"],
    [0.71, "#dcdbe0"],
    [0.88, "#e6e6e9"],
    [0.96, "#fcfcfc"],
    [1, "#b4b4b8"],
  ],
};

/** The polished cap across, its light at the front: brushed on the Joule, mirror chrome on the Turbo. */
const CAP: Profile = [
  [0, "#6f6f70"],
  [0.05, "#979797"],
  [0.15, "#a9a9a9"],
  [0.25, "#c4c4c4"],
  [0.33, "#e4e4e4"],
  [0.4, "#f3f3f3"],
  [0.46, "#e0e0e0"],
  [0.53, "#a8a8a8"],
  [0.62, "#b2b2b2"],
  [0.72, "#8a8a8a"],
  [0.8, "#5e5e5e"],
  [0.87, "#4f4f4f"],
  [0.94, "#7d7d7d"],
  [1, "#5a5a5a"],
];
const CHROME_CAP: Profile = [
  [0, "#3c3c3c"],
  [0.06, "#9a9a9a"],
  [0.15, "#eeeeee"],
  [0.35, "#fbfbfb"],
  [0.5, "#d6d6d6"],
  [0.62, "#8a8a8a"],
  [0.72, "#3a3a3a"],
  [0.82, "#6a6a6a"],
  [0.92, "#d8d8d8"],
  [1, "#5a5a5a"],
];

/** How full the container is: two-thirds, or under the minimum when the Joule reports low water. */
function level(state: SousVideState): number {
  return state.error === "low_water" ? 0.12 : 0.66;
}

/** Steam, 0 to 1: none in cool water, more as it nears boiling. */
function steam(state: SousVideState): number {
  if (!state.available || state.waterC === null) return 0;
  return Math.max(0, Math.min(1, (state.waterC - 42) / 45));
}

/** The container's left and right walls at a height, between its rim and its floor. */
function wallsAt(y: number, back: boolean): [number, number] {
  const top = back ? BOX.backTop : BOX.frontTop;
  const bottom = back ? BOX.backBottom : BOX.frontBottom;
  const share = (y - top) / (bottom - top);
  const inset = back ? 8 : 0;
  return [
    BOX.topLeft + inset + share * (BOX.bottomLeft - BOX.topLeft),
    BOX.topRight - inset - share * (BOX.topRight - BOX.bottomRight),
  ];
}

interface Surface {
  back: number;
  front: number;
}

function surface(state: SousVideState): Surface {
  const fill = level(state);
  return {
    back: BOX.backBottom - fill * (BOX.backBottom - BOX.backTop) * 0.96,
    front: BOX.frontBottom - fill * (BOX.frontBottom - BOX.frontTop) * 0.96,
  };
}

interface Tones {
  /** The container's edges: dark grey on a light page, light on a dark one. */
  edge: string;
  /** The water seen through the front wall, top to bottom. */
  water: readonly [string, string];
  waterAlpha: readonly [number, number];
  /** The surface: the light it mirrors. */
  sheen: string;
}

function tones(state: SousVideState, theme: "light" | "dark"): Tones {
  // Hot water takes the faintest warm tint.
  const warmth = state.waterC === null ? 0 : Math.max(0, Math.min(1, (state.waterC - 30) / 60)) * 0.35;
  return theme === "dark"
    ? {
        edge: "#d7e0e6",
        water: [mix("#6f8c99", "#8f8070", warmth), mix("#3f5a66", "#5a4d40", warmth)],
        waterAlpha: [0.3, 0.5],
        sheen: "#c9d6dc",
      }
    : {
        edge: "#7f8b93",
        water: [mix("#e6f1f5", "#f6eee4", warmth), mix("#b7d2dd", "#e2d3c2", warmth)],
        waterAlpha: [0.18, 0.42],
        sheen: "#ffffff",
      };
}

function defs(uid: string, state: SousVideState, theme: "light" | "dark", model: "CSJ100" | "BSV600"): SVGTemplateResult {
  const tone = tones(state, theme);
  const { back, front } = surface(state);
  return svg`
    ${profile(`${uid}-white`, WHITE[model])}
    ${profile(`${uid}-cap`, model === "BSV600" ? CHROME_CAP : CAP)}
    ${linear(`${uid}-cap-edge`, [
      [0, "#000000", 0.55],
      [0.12, "#000000", 0.08],
      [0.22, "#ffffff", 0.18],
      [0.4, "#ffffff", 0],
      [0.78, "#000000", 0],
      [0.92, "#000000", 0.18],
      [1, "#000000", 0.5],
    ], [0, 0], [0, 1])}
    ${linear(`${uid}-chrome`, [
      [0, "#5d6064"],
      [0.12, "#c9ced2"],
      [0.25, "#fbfcfc"],
      [0.42, "#dfe3e4"],
      [0.6, "#8f9497"],
      [0.75, "#e9ecec"],
      [0.9, "#9aa0a3"],
      [1, "#5a5e62"],
    ])}
    ${linear(`${uid}-neck`, [[0, "#151617"], [0.4, "#35383b"], [0.6, "#2a2c2f"], [1, "#0f1011"]])}
    ${linear(`${uid}-water`, [
      [0, tone.water[0], tone.waterAlpha[0]],
      [1, tone.water[1], tone.waterAlpha[1]],
    ], [0, front], [0, BOX.frontBottom], "userSpaceOnUse")}
    ${linear(`${uid}-sheet`, [
      [0, tone.sheen, theme === "dark" ? 0.32 : 0.85],
      [0.45, tone.sheen, theme === "dark" ? 0.12 : 0.45],
      [1, tone.water[1], theme === "dark" ? 0.3 : 0.35],
    ], [0, back], [0, front], "userSpaceOnUse")}
    ${linear(`${uid}-wall`, [
      [0, tone.edge, 0.4],
      [0.012, "#ffffff", 0.75],
      [0.03, tone.edge, 0.18],
      [0.06, "#ffffff", 0.22],
      [0.2, "#ffffff", 0.04],
      [0.5, "#ffffff", 0],
      [0.86, "#ffffff", 0.04],
      [0.95, "#ffffff", 0.2],
      [0.975, tone.edge, 0.2],
      [0.99, "#ffffff", 0.7],
      [1, tone.edge, 0.4],
    ])}
    ${linear(`${uid}-lip`, [
      [0, "#ffffff", 0.95],
      [0.25, "#f2f7f9", 0.55],
      [0.6, tone.edge, 0.12],
      [0.85, tone.edge, 0.35],
      [1, tone.edge, 0.6],
    ], [0, 0], [0, 1])}
    ${linear(`${uid}-bag`, [
      [0, "#ffffff", 0.5],
      [0.3, "#ffffff", 0.16],
      [0.7, "#ffffff", 0.1],
      [1, "#ffffff", 0.32],
    ], [0, 0], [0, 1])}
    ${radial(`${uid}-steak`, [
      [0, "#cc3f37"],
      [0.5, "#ad2b26"],
      [0.85, "#7c1a19"],
      [1, "#541010"],
    ], [0.45, 0.38], 0.72)}
    <pattern id=${`${uid}-seal`} width="1.6" height="1.6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <path d="M0,0 V1.6" stroke="#ffffff" stroke-opacity="0.7" stroke-width="0.35"></path>
    </pattern>
    ${radial(`${uid}-led`, [
      [0, "#e6ffd6"],
      [0.35, "#7ad83a"],
      [1, "#55c21f", 0],
    ])}
    ${linear(`${uid}-steam`, [
      [0, theme === "dark" ? "#ffffff" : "#cdd6db", 0],
      [0.25, theme === "dark" ? "#ffffff" : "#cdd6db", theme === "dark" ? 0.5 : 0.55],
      [1, theme === "dark" ? "#ffffff" : "#cdd6db", 0],
    ], [0, back], [0, back - 130], "userSpaceOnUse")}
    <filter id=${`${uid}-wisp`} x="-60%" y="-20%" width="220%" height="140%">
      <feTurbulence type="fractalNoise" baseFrequency="0.035 0.06" numOctaves="2" seed="5" result="noise"></feTurbulence>
      <feDisplacementMap in="SourceGraphic" in2="noise" scale="16" xChannelSelector="R" yChannelSelector="G" result="moved"></feDisplacementMap>
      <feGaussianBlur in="moved" stdDeviation="3.4"></feGaussianBlur>
    </filter>
    <filter id=${`${uid}-meat`} x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="13" result="noise"></feTurbulence>
      <feDiffuseLighting in="noise" surfaceScale="0.45" diffuseConstant="1" lighting-color="#ffffff" result="light">
        <feDistantLight azimuth="235" elevation="60"></feDistantLight>
      </feDiffuseLighting>
      <feComposite in="light" in2="SourceGraphic" operator="arithmetic" k1="1.12" k2="0" k3="0" k4="0" result="lit"></feComposite>
      <feComposite in="lit" in2="SourceAlpha" operator="in"></feComposite>
    </filter>
    ${blur(`${uid}-glow`, 1.2)}
    ${blur(`${uid}-soft`, 0.8)}
    <clipPath id=${`${uid}-above`}><rect x="0" y="0" width=${VIEW_W} height=${back}></rect></clipPath>
    <clipPath id=${`${uid}-below`}><rect x="0" y=${back} width=${VIEW_W} height=${VIEW_H}></rect></clipPath>
  `;
}

/** The circulator standing upright with its foot at y = FOOT. */
function circulator(uid: string, state: SousVideState, model: "CSJ100" | "BSV600"): SVGTemplateResult {
  const height = model === "BSV600" ? 312 : 279;
  const top = FOOT - height;
  const capH = 14.5;
  const left = AXIS - RADIUS;
  const width = RADIUS * 2;
  const bodyTop = top + capH;
  const bodyBottom = FOOT - 13;
  const slotY = FOOT - 62;
  const lit = state.available && state.running;
  const marks =
    model === "BSV600"
      ? svg`<g class="marks" fill="#a3a9ae" font-family="inherit" font-size="4.2" font-weight="600">
          ${[
            [FOOT - 210, "MAX"],
            [FOOT - 52, "MIN"],
          ].map(
            ([y, text]) => svg`<line x1=${left + 5} x2=${left + 12} y1=${y} y2=${y} stroke="#a3a9ae" stroke-width="0.8"></line>
              <text x=${left + 14} y=${Number(y) + 1.5}>${text}</text>`,
          )}
        </g>`
      : nothing;
  return svg`
    <!-- The clip on its back: a white moulding with a steel spring, hooked over the back rim. -->
    <g class="clip">
      <path d=${roundRect(AXIS + RADIUS - 6, BOX.backTop - 32, 12, 54, 4)} fill="#e9eaec"></path>
      <path d=${roundRect(AXIS + RADIUS - 6, BOX.backTop - 32, 12, 54, 4)} fill="none" stroke="#a7acb1" stroke-width="0.6"></path>
      <path d=${`M${AXIS + RADIUS + 4},${BOX.backTop - 22} q 10,-7 14,4 v 36`} fill="none" stroke="#9aa0a5" stroke-width="1.8" stroke-linecap="round"></path>
      <path d=${`M${AXIS + RADIUS + 4},${BOX.backTop - 22} q 10,-7 14,4 v 36`} fill="none" stroke="#f4f5f6" stroke-width="0.6" stroke-linecap="round"></path>
    </g>
    <!-- The body: glossy white, lit from the left, with a crisp highlight down it. -->
    <rect x=${left} y=${bodyTop} width=${width} height=${bodyBottom - bodyTop} fill=${`url(#${uid}-white)`}></rect>
    <rect x=${left + width * 0.13} y=${bodyTop + 1} width=${width * 0.05} height=${bodyBottom - bodyTop - 2} fill="#ffffff" opacity="0.7"></rect>
    <rect x=${left + width * 0.86} y=${bodyTop + 1} width=${width * 0.025} height=${bodyBottom - bodyTop - 2} fill="#ffffff" opacity="0.35"></rect>
    ${marks}
    <!-- The outlet: a black slot, its rim catching the light. -->
    <path d=${roundRect(AXIS - 4, slotY - 12, 8, 24, 3.6)} fill="#0c0d0e"></path>
    <path d=${roundRect(AXIS - 4, slotY - 12, 8, 24, 3.6)} fill="none" stroke="#ffffff" stroke-opacity="0.85" stroke-width="0.6"></path>
    <path d=${roundRect(AXIS - 2.6, slotY - 10, 2, 20, 1)} fill="#3b3f44"></path>
    <!-- The cap: polished, the light set in its front. -->
    <path d=${roundRect(left - 0.4, top, width + 0.8, capH, 2.2)} fill=${`url(#${uid}-cap)`}></path>
    <path d=${roundRect(left - 0.4, top, width + 0.8, capH, 2.2)} fill=${`url(#${uid}-cap-edge)`}></path>
    <line x1=${left + 1} x2=${left + width - 1} y1=${top + 0.6} y2=${top + 0.6} stroke="#ffffff" stroke-opacity="0.55" stroke-width="0.6"></line>
    <line x1=${left} x2=${left + width} y1=${bodyTop} y2=${bodyTop} stroke="#6f7478" stroke-width="0.6"></line>
    ${lit
      ? svg`<circle cx=${AXIS} cy=${top + capH * 0.42} r="4.2" fill=${`url(#${uid}-led)`} filter=${`url(#${uid}-glow)`}></circle>
          <circle cx=${AXIS} cy=${top + capH * 0.42} r="1.2" fill="#eaffdc"></circle>`
      : svg`<circle cx=${AXIS} cy=${top + capH * 0.42} r="1.2" fill="#55595e"></circle>`}
    <!-- The foot: a chrome band, a dark neck, and the magnetic disc with its rubber edge. -->
    <rect x=${left} y=${bodyBottom} width=${width} height="2.4" fill=${`url(#${uid}-chrome)`}></rect>
    <rect x=${AXIS - 15} y=${bodyBottom + 2.4} width="30" height="4.4" fill=${`url(#${uid}-neck)`}></rect>
    <path d=${roundRect(left + 1, bodyBottom + 6.8, width - 2, 4.6, 1.6)} fill=${`url(#${uid}-chrome)`}></path>
    <rect x=${left + 2} y=${FOOT - 1.6} width=${width - 4} height="1.6" rx="0.8" fill="#9a5f4b"></rect>
  `;
}

/** The container's back wall and floor, seen through the water and the front wall. */
function containerBack(tone: Tones): SVGTemplateResult {
  const [bl, br] = wallsAt(BOX.backBottom, true);
  return svg`
    <path d=${`M${BOX.topLeft + 8},${BOX.backTop} H${BOX.topRight - 8} L${br},${BOX.backBottom} H${bl} Z`}
      fill="#ffffff" fill-opacity="0.06" stroke=${tone.edge} stroke-opacity="0.3" stroke-width="0.7"></path>
    <path d=${`M${bl},${BOX.backBottom} L${BOX.bottomLeft + 2},${BOX.frontBottom - 4} M${br},${BOX.backBottom} L${BOX.bottomRight - 2},${BOX.frontBottom - 4}`}
      stroke=${tone.edge} stroke-opacity="0.3" stroke-width="0.7"></path>
    <path d=${`M${BOX.topLeft + 8},${BOX.backTop + 1.2} H${BOX.topRight - 8}`} stroke=${tone.edge} stroke-opacity="0.35" stroke-width="1.4"></path>
  `;
}

/** A deterministic scatter, 0 to 1, so the bubbles sit in the same places on every draw. */
const scatter = (index: number, salt: number) => {
  const value = Math.sin(index * 12.9898 + salt * 78.233) * 43758.5453;
  return value - Math.floor(value);
};

/** A cloud of fine bubbles jetting from the outlet while the water circulates, spreading as it goes. */
function bubbles(uid: string, motion: boolean): SVGTemplateResult {
  const slotY = FOOT - 62;
  const dots = Array.from({ length: 110 }, (_, index) => {
    const along = scatter(index, 1) ** 0.8;
    const spread = (scatter(index, 2) - 0.5) * (5 + along * 30);
    const x = AXIS - 5 - along * 96 + (scatter(index, 3) - 0.5) * 6;
    const y = slotY + spread - along * 5;
    const r = 0.25 + scatter(index, 4) ** 2 * 1.1;
    return svg`<circle cx=${round(x)} cy=${round(y)} r=${round(r)} opacity=${round(0.95 - along * 0.75)}></circle>`;
  });
  return svg`<g class=${motion ? `${uid}-stream` : ""} fill="#ffffff" stroke="#7f939c" stroke-width="0.22">${dots}</g>`;
}

/** The water: its body, seen through the front wall, and its surface, seen from above. */
function water(uid: string, state: SousVideState, tone: Tones, motion: boolean): SVGTemplateResult {
  const { back, front } = surface(state);
  const [bl, br] = wallsAt(back, true);
  const [fl, fr] = wallsAt(front, false);
  const body = `M${fl},${front} H${fr} L${BOX.bottomRight},${BOX.frontBottom - 8} Q${BOX.bottomRight},${BOX.frontBottom} ${BOX.bottomRight - 8},${BOX.frontBottom}
    H${BOX.bottomLeft + 8} Q${BOX.bottomLeft},${BOX.frontBottom} ${BOX.bottomLeft},${BOX.frontBottom - 8} Z`;
  const sheet = `M${bl},${back} H${br} L${fr},${front} H${fl} Z`;
  const circulating = state.running && state.available;
  const waves = [0.22, 0.42, 0.62, 0.8].map((share, index) => {
    const y = back + (front - back) * share;
    const [l, r] = [bl + (fl - bl) * share + 6, br + (fr - br) * share - 6];
    const amplitude = circulating ? 1.2 : 0.4;
    const step = (r - l) / 8;
    let d = `M${round(l)},${round(y)}`;
    for (let k = 0; k < 8; k++) d += ` q${round(step / 2)},${round((k + index) % 2 ? amplitude : -amplitude)} ${round(step)},0`;
    return svg`<path d=${d} fill="none" stroke=${tone.edge} stroke-opacity=${circulating ? 0.22 : 0.12} stroke-width="0.6"></path>`;
  });
  return svg`
    <path d=${body} fill=${`url(#${uid}-water)`}></path>
    ${circulating ? bubbles(uid, motion) : nothing}
    <path d=${sheet} fill=${`url(#${uid}-sheet)`}></path>
    ${waves}
    <path d=${`M${bl},${back} H${br}`} stroke="#ffffff" stroke-opacity="0.9" stroke-width="0.8"></path>
    <path d=${`M${bl},${back} L${fl},${front} M${br},${back} L${fr},${front}`} stroke=${tone.edge} stroke-opacity="0.35" stroke-width="0.7"></path>
    <path d=${`M${fl + 1},${front} H${fr - 1}`} stroke=${tone.edge} stroke-opacity="0.75" stroke-width="0.9"></path>
    <path d=${`M${fl + 2},${front + 1.4} H${fr - 2}`} stroke="#ffffff" stroke-opacity="0.85" stroke-width="1.1"></path>
    <path d=${`M${fl + 2},${front + 3.6} H${fr - 2}`} stroke=${tone.edge} stroke-opacity="0.12" stroke-width="3"></path>
    ${circulating
      ? svg`<g fill="none" stroke="#ffffff" stroke-width="0.8">
          ${[0, 1, 2].map(
            (index) => svg`<ellipse class=${motion ? `${uid}-ripple` : ""} style=${`animation-delay:${index * 1.1}s`}
              cx=${AXIS} cy=${back + 3} rx=${RADIUS + 10 + index * 18} ry=${3 + index * 2.2} stroke-opacity=${0.6 - index * 0.15}></ellipse>`,
          )}
        </g>`
      : nothing}
  `;
}

/**
 * A vacuum-sealed steak in the water: deep red, marbled, the clear bag hugging it with highlights
 * along its creases, a flat margin round it, and the sealer's ribbed strip along its top.
 */
function bag(uid: string, state: SousVideState, tone: Tones): SVGTemplateResult {
  const { front } = surface(state);
  const cx = 112;
  const cy = Math.max(front + 58, 300);
  const steak = `M${cx - 46},${cy - 10} C${cx - 40},${cy - 24} ${cx + 4},${cy - 27} ${cx + 38},${cy - 18}
    C${cx + 52},${cy - 12} ${cx + 52},${cy + 8} ${cx + 38},${cy + 16}
    C${cx + 12},${cy + 25} ${cx - 30},${cy + 23} ${cx - 44},${cy + 12}
    C${cx - 52},${cy + 4} ${cx - 52},${cy - 4} ${cx - 46},${cy - 10} Z`;
  return svg`<g transform=${`rotate(-6 ${cx} ${cy})`}>
    <path d=${roundRect(cx - 62, cy - 37, 124, 72, 8)} fill="#ffffff" fill-opacity="0.18"></path>
    <path d=${steak} fill=${`url(#${uid}-steak)`} filter=${`url(#${uid}-meat)`}></path>
    <path d=${`M${cx - 43},${cy - 11} C${cx - 31},${cy - 23} ${cx + 8},${cy - 25} ${cx + 37},${cy - 16}`}
      fill="none" stroke="#f3ddd2" stroke-width="3.4" stroke-linecap="round" opacity="0.9"></path>
    ${[[-32, -3, 24, 0.7], [-8, 6, 30, 0.6], [16, -7, 20, 0.55], [-38, 9, 14, 0.5], [10, 13, 18, 0.6], [-18, -13, 13, 0.45], [26, 4, 14, 0.5], [-2, -4, 10, 0.4]].map(
      ([dx, dy, length, width]) => svg`<path d=${`M${cx + dx},${cy + dy} q ${length / 4},-3 ${length / 2},-0.5 t ${length / 2},1.5`} fill="none"
        stroke="#f1d3c8" stroke-opacity="0.6" stroke-width=${width} stroke-linecap="round"></path>`,
    )}
    <path d=${roundRect(cx - 62, cy - 37, 124, 72, 8)} fill=${`url(#${uid}-bag)`}></path>
    <path d=${roundRect(cx - 62, cy - 37, 124, 72, 8)} fill="none" stroke=${tone.edge} stroke-opacity="0.55" stroke-width="1.2"></path>
    <path d=${roundRect(cx - 60.5, cy - 35.5, 121, 69, 7)} fill="none" stroke="#ffffff" stroke-opacity="0.85" stroke-width="0.7"></path>
    <path d=${roundRect(cx - 62, cy - 37, 124, 10, 4)} fill="#ffffff" fill-opacity="0.4"></path>
    <path d=${roundRect(cx - 60, cy - 35.5, 120, 7, 3)} fill=${`url(#${uid}-seal)`}></path>
    <line x1=${cx - 60} x2=${cx + 60} y1=${cy - 27.5} y2=${cy - 27.5} stroke=${tone.edge} stroke-opacity="0.35" stroke-width="0.5"></line>
    <g fill="none" stroke="#ffffff" stroke-linecap="round" filter=${`url(#${uid}-soft)`}>
      <path d=${`M${cx - 45},${cy - 15} C${cx - 30},${cy - 27} ${cx + 10},${cy - 29} ${cx + 40},${cy - 21}`} stroke-opacity="0.9" stroke-width="1.8"></path>
      <path d=${`M${cx + 47},${cy - 8} C${cx + 54},${cy - 2} ${cx + 52},${cy + 10} ${cx + 42},${cy + 17}`} stroke-opacity="0.6" stroke-width="1.2"></path>
      <path d=${`M${cx - 53},${cy - 2} q -3,9 2,16`} stroke-opacity="0.6" stroke-width="1"></path>
      <path d=${`M${cx - 24},${cy + 25} q 16,4 34,-1`} stroke-opacity="0.5" stroke-width="1"></path>
    </g>
  </g>`;
}

/** The front wall, its moulded graduations, and the thick rim round the top. */
function containerFront(uid: string, tone: Tones): SVGTemplateResult {
  const front = `M${BOX.topLeft},${BOX.frontTop} H${BOX.topRight} L${BOX.bottomRight},${BOX.frontBottom - 8}
    Q${BOX.bottomRight},${BOX.frontBottom} ${BOX.bottomRight - 8},${BOX.frontBottom} H${BOX.bottomLeft + 8}
    Q${BOX.bottomLeft},${BOX.frontBottom} ${BOX.bottomLeft},${BOX.frontBottom - 8} Z`;
  const marks = [2, 4, 6, 8, 10, 12].map((quarts) => {
    const y = BOX.frontBottom - 12 - (quarts / 12) * (BOX.frontBottom - BOX.frontTop - 34);
    const [left] = wallsAt(y, false);
    const x = left + 16;
    return svg`
      <line x1=${x} x2=${x + (quarts % 4 ? 6 : 10)} y1=${round(y + 0.5)} y2=${round(y + 0.5)} stroke=${tone.edge} stroke-opacity="0.35" stroke-width="0.6"></line>
      <line x1=${x} x2=${x + (quarts % 4 ? 6 : 10)} y1=${round(y)} y2=${round(y)} stroke="#ffffff" stroke-opacity="0.8" stroke-width="0.6"></line>
      ${quarts % 4 ? nothing : svg`<text x=${x + 12} y=${round(y + 1.6)} font-size="4.4" font-weight="600" fill=${tone.edge} fill-opacity="0.45">${quarts}</text>`}
    `;
  });
  return svg`
    <path d=${front} fill=${`url(#${uid}-wall)`}></path>
    <path d=${front} fill="none" stroke=${tone.edge} stroke-opacity="0.5" stroke-width="0.9"></path>
    <path d=${`M${BOX.bottomLeft + 10},${BOX.frontBottom - 2.2} H${BOX.bottomRight - 10}`} stroke=${tone.edge} stroke-opacity="0.35" stroke-width="2.2"></path>
    <path d=${`M${BOX.bottomLeft + 10},${BOX.frontBottom - 4} H${BOX.bottomRight - 10}`} stroke="#ffffff" stroke-opacity="0.55" stroke-width="0.8"></path>
    <g font-family="inherit">${marks}</g>
    <!-- The rim: the back edge, the sides of the opening, and the thick front lip. -->
    <path d=${`M${BOX.topLeft + 6},${BOX.backTop} H${BOX.topRight - 6} M${BOX.topLeft + 6},${BOX.backTop} L${BOX.topLeft - 3},${BOX.frontTop - 2} M${BOX.topRight - 6},${BOX.backTop} L${BOX.topRight + 3},${BOX.frontTop - 2}`}
      stroke=${tone.edge} stroke-opacity="0.55" stroke-width="2.4" stroke-linecap="round"></path>
    <path d=${`M${BOX.topLeft + 6},${BOX.backTop - 0.8} H${BOX.topRight - 6}`} stroke="#ffffff" stroke-opacity="0.8" stroke-width="0.7"></path>
    <path d=${roundRect(BOX.topLeft - 5, BOX.frontTop - 6, BOX.topRight - BOX.topLeft + 10, 11, 5)} fill=${`url(#${uid}-lip)`}></path>
    <path d=${roundRect(BOX.topLeft - 5, BOX.frontTop - 6, BOX.topRight - BOX.topLeft + 10, 11, 5)} fill="none" stroke=${tone.edge}
      stroke-opacity="0.55" stroke-width="0.7"></path>
    <path d=${`M${BOX.topLeft},${BOX.frontTop - 4.2} H${BOX.topRight}`} stroke="#ffffff" stroke-opacity="0.95" stroke-width="1.1" stroke-linecap="round"></path>
    <path d=${`M${BOX.topLeft + 10},${BOX.frontTop + 12} L${BOX.bottomLeft + 7},${BOX.frontBottom - 16}`}
      stroke="#ffffff" stroke-opacity="0.5" stroke-width="3" stroke-linecap="round" filter=${`url(#${uid}-soft)`}></path>
    <path d=${`M${BOX.topRight - 13},${BOX.frontTop + 16} L${BOX.bottomRight - 11},${BOX.frontBottom - 40}`}
      stroke="#ffffff" stroke-opacity="0.3" stroke-width="1.8" stroke-linecap="round" filter=${`url(#${uid}-soft)`}></path>
  `;
}

/** Steam rising off the water in soft, torn wisps, more of it and denser as it nears boiling. */
function steamWisps(uid: string, state: SousVideState, motion: boolean): SVGTemplateResult | typeof nothing {
  const strength = steam(state);
  if (strength <= 0) return nothing;
  const { back } = surface(state);
  const count = 3 + Math.round(strength * 5);
  const wisps = Array.from({ length: count }, (_, index) => {
    const x = 62 + ((index * 53) % 236);
    const height = 55 + strength * 55;
    const sway = index % 2 ? 10 : -10;
    return svg`<path class=${motion ? `${uid}-wisp` : ""} style=${`animation-delay:${(index * 0.9) % 4}s`}
      d=${`M${x},${back - 2} c ${sway},-${height * 0.3} ${-sway},-${height * 0.6} ${sway * 0.5},-${height}`}
      fill="none" stroke=${`url(#${uid}-steam)`} stroke-width=${10 + strength * 8} stroke-linecap="round"
      opacity=${round(0.25 + strength * 0.35)}></path>`;
  });
  return svg`<g filter=${`url(#${uid}-wisp)`}>${wisps}</g>`;
}

/** The water temperature on the container, with the target while it heats up. */
function readout(
  uid: string,
  state: SousVideState,
  viewHeight: number,
  pixelHeight: number | undefined,
): SVGTemplateResult | typeof nothing {
  if (!state.readout || !state.available) return nothing;
  const size = labelSize(viewHeight, pixelHeight, 12.5);
  const text = state.targetReadout ? `${state.readout} → ${state.targetReadout}` : state.readout;
  const width = size * (0.62 * [...text].length + 1.6);
  const height = size * 1.75;
  const x = 100 - width / 2;
  const y = BOX.frontTop + (surface(state).front - BOX.frontTop) / 2 - height / 2 + 4;
  return svg`<g class=${`${uid}-readout`}>
    <path d=${roundRect(x, y, width, height, height / 2)} fill="#101418" fill-opacity="0.62"></path>
    <text x=${x + width / 2} y=${y + height * 0.68} text-anchor="middle" fill="#ffffff" font-size=${size}
      font-weight="600" font-family="inherit" style="font-variant-numeric: tabular-nums">${text}</text>
  </g>`;
}

function badge(state: SousVideState): SVGTemplateResult | typeof nothing {
  if (!state.error) return nothing;
  const color = state.error === "low_water" ? "#e69500" : "#d93025";
  return svg`<g transform="translate(318 118)">
    <circle r="13" fill=${color}></circle>
    <rect x="-1.8" y="-7.5" width="3.6" height="9.5" rx="1.6" fill="#ffffff"></rect>
    <circle cy="6" r="2.1" fill="#ffffff"></circle>
  </g>`;
}

// Lit can't bind inside a <style> element, so the rules go in whole. The uid is the drawing's own.
function animations(uid: string) {
  return unsafeSVG(`<style>
    .${uid}-ripple { transform-box: fill-box; transform-origin: center; animation: ${uid}-ripple 3.3s ease-out infinite; }
    @keyframes ${uid}-ripple { from { transform: scale(0.6); opacity: 0.9; } to { transform: scale(1.25); opacity: 0; } }
    .${uid}-stream { animation: ${uid}-stream 1.4s linear infinite; }
    @keyframes ${uid}-stream { from { transform: translateX(6px); opacity: 0.6; } 50% { opacity: 1; } to { transform: translateX(-10px); opacity: 0.6; } }
    .${uid}-wisp { animation: ${uid}-wisp 4.5s ease-in-out infinite; }
    @keyframes ${uid}-wisp { 0% { transform: translateY(6px); opacity: 0; } 30% { opacity: 1; } 100% { transform: translateY(-18px); opacity: 0; } }
  </style>`);
}

export function renderSousVide(input: DrawingInput): TemplateResult {
  const state = input.state as SousVideState;
  const { uid, theme } = input;
  const model = input.model === "BSV600" ? "BSV600" : "CSJ100";
  const motion = !input.reducedMotion && state.available;
  const tone = tones(state, theme);
  const tipped = state.error === "tipped";
  const joule = circulator(uid, state, model);
  // Tipped over, it lies along the container's floor, its cap to the left.
  const placed = tipped ? svg`<g transform=${`translate(80 -12) rotate(-90 ${AXIS} ${FOOT})`}>${joule}</g>` : joule;
  const height = model === "BSV600" ? 312 : 279;
  const top = Math.min(FOOT - height - 6, 40);
  const viewHeight = VIEW_H - top;
  return html`<svg
    viewBox=${`0 ${top} ${VIEW_W} ${viewHeight}`}
    class=${state.available ? "" : "offline"}
    style=${state.available ? "" : "filter: grayscale(0.9) opacity(0.62)"}
    aria-hidden="true"
    focusable="false"
  >
    <defs>${defs(uid, state, theme, model)}</defs>
    ${motion ? animations(uid) : nothing}
    ${floorShadow(uid, 180, BOX.frontBottom + 3, 172, 7, theme)}
    ${containerBack(tone)}
    ${tipped
      ? placed
      : svg`<g clip-path=${`url(#${uid}-above)`}>${placed}</g>
          <g clip-path=${`url(#${uid}-below)`}><g transform=${`translate(${AXIS} 0) scale(1.07 1) translate(${-AXIS} 0)`}>${placed}</g></g>`}
    ${state.food ? bag(uid, state, tone) : nothing}
    ${water(uid, state, tone, motion)}
    ${containerFront(uid, tone)}
    ${steamWisps(uid, state, motion)}
    ${readout(uid, state, viewHeight, input.pixelHeight)}
    ${badge(state)}
  </svg>`;
}
