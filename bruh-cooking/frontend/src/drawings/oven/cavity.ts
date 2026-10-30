/**
 * Inside the oven, seen through the door's window or, with the door open, through the opening:
 * the black enamel cavity in perspective (the camera level with the middle of the oven), the light
 * on its left wall, the six quartz elements (three across the top, three across the bottom), the
 * convection fan behind its cover, and the rack at its position (1 at the top, 8 at the bottom).
 * Lit as Breville's photos show it: smoky black when off, warm from the lamp's side when it's on,
 * and glowing from the elements as they heat, brightest by the lamp and at the floor. The glass is
 * smoked, with the rack positions printed down its right edge.
 */
import { nothing, svg, type SVGTemplateResult } from "lit";
import type { Elements } from "../../types";
import { blur, linear, mix, round } from "../materials";
import type { OvenState } from "../types";
import { OPENING } from "./body";
import { RACK_INK, RACK_SHARES, WINDOW_GLASS } from "./measured";

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const WINDOW: Box = WINDOW_GLASS;

/** Where the camera looks from, in the front plane, and how far the cavity recedes. */
export const EYE = { x: 272, y: 150 } as const;
// The back wall looks 78% the size of the opening.
const RECEDE = 0.282;

export function scaleAt(depth: number): number {
  return 1 / (1 + RECEDE * depth);
}

/** A point inside the cavity (front-plane x and y, depth 0 at the opening to 1 at the back) on the drawing. */
export function project(x: number, y: number, depth: number): [number, number] {
  const s = scaleAt(depth);
  return [round(EYE.x + (x - EYE.x) * s), round(EYE.y + (y - EYE.y) * s)];
}

const pts = (list: ReadonlyArray<readonly [number, number]>) => list.map(([x, y]) => `${x},${y}`).join(" ");

/** The cavity's walls: the opening at the front, the back wall behind. */
const FRONT = { x1: OPENING.x, y1: OPENING.y, x2: OPENING.x + OPENING.width, y2: OPENING.y + OPENING.height };
const BACK = (() => {
  const [x1, y1] = project(FRONT.x1, FRONT.y1, 1);
  const [x2, y2] = project(FRONT.x2, FRONT.y2, 1);
  return { x1, y1, x2, y2 };
})();
/** The middle of the cavity, across. */
export const CENTER_X = (FRONT.x1 + FRONT.x2) / 2;

export function rackY(position: number): number {
  const index = Math.max(1, Math.min(8, Math.round(position))) - 1;
  return WINDOW.y + RACK_SHARES[index] * WINDOW.height;
}

/** Which of the six tubes glow, and how hot, for the elements a mode uses. */
export function glowing(elements: Elements | null): { top: number[]; bottom: number[]; heat: number } {
  switch (elements) {
    case "top":
      return { top: [0, 1, 2], bottom: [], heat: 1 };
    case "bottom":
      return { top: [], bottom: [0, 1, 2], heat: 1 };
    case "outer_top":
      return { top: [0, 2], bottom: [], heat: 1 };
    case "middle_top":
      return { top: [1], bottom: [], heat: 1 };
    case "top_bottom":
      return { top: [0, 1, 2], bottom: [0, 1, 2], heat: 1 };
    case "bottom_low":
      return { top: [], bottom: [0, 1, 2], heat: 0.45 };
    case "low":
      return { top: [0, 1, 2], bottom: [0, 1, 2], heat: 0.4 };
    default:
      return { top: [], bottom: [], heat: 0 };
  }
}

type Light = "off" | "lamp" | "heat";

function lightOf(state: OvenState): Light {
  const glow = glowing(state.elements);
  if (glow.top.length || glow.bottom.length) return "heat";
  return state.light ? "lamp" : "off";
}

interface Walls {
  back: ReadonlyArray<readonly [number, string]>;
  left: readonly [string, string];
  right: readonly [string, string];
  ceiling: readonly [string, string];
  floor: readonly [string, string];
}

/**
 * The walls' light, front to back. Heat is measured through the glass of Breville's photo of the
 * oven baking; the lamp alone is the same light, dimmer and without the elements' red.
 */
const WALLS: Record<Light, Walls> = {
  off: {
    back: [
      [0, "#1b1c1e"],
      [0.5, "#151617"],
      [1, "#131415"],
    ],
    left: ["#232527", "#17181a"],
    right: ["#111213", "#18191b"],
    ceiling: ["#1c1d1f", "#161718"],
    floor: ["#26282a", "#1a1b1d"],
  },
  lamp: {
    back: [
      [0, "#4a3f39"],
      [0.12, "#3a302a"],
      [0.3, "#2a221e"],
      [0.55, "#1d1815"],
      [1, "#141110"],
    ],
    left: ["#6a5a50", "#2e2620"],
    right: ["#141110", "#1e1915"],
    ceiling: ["#332a24", "#211b17"],
    floor: ["#3e322a", "#211b16"],
  },
  heat: {
    back: [
      [0, "#998c8a"],
      [0.08, "#928380"],
      [0.17, "#79625b"],
      [0.25, "#604640"],
      [0.33, "#4d332d"],
      [0.42, "#412721"],
      [0.5, "#442821"],
      [0.58, "#3a2119"],
      [0.67, "#2e1a15"],
      [0.75, "#291611"],
      [1, "#271308"],
    ],
    left: ["#b4a6a2", "#8a7670"],
    right: ["#2a150c", "#3b1d12"],
    ceiling: ["#6a3e2c", "#43231a"],
    floor: ["#9a4f32", "#5e3022"],
  },
};

export function cavityDefs(uid: string, state: OvenState): SVGTemplateResult {
  const walls = WALLS[lightOf(state)];
  const glow = glowing(state.elements);
  return svg`
    <linearGradient id=${`${uid}-cav-back`} gradientUnits="userSpaceOnUse" x1=${BACK.x1} y1="0" x2=${BACK.x2} y2="0">
      ${walls.back.map(([offset, color]) => svg`<stop offset=${offset} stop-color=${color}></stop>`)}
    </linearGradient>
    ${linear(`${uid}-cav-left`, [[0, walls.left[0]], [1, walls.left[1]]])}
    ${linear(`${uid}-cav-right`, [[0, walls.right[1]], [1, walls.right[0]]])}
    ${linear(`${uid}-cav-ceiling`, [[0, walls.ceiling[0]], [1, walls.ceiling[1]]], [0, 0], [0, 1])}
    ${linear(`${uid}-cav-floor`, [[0, walls.floor[1]], [1, walls.floor[0]]], [0, 0], [0, 1])}
    <linearGradient id=${`${uid}-cav-low`} gradientUnits="userSpaceOnUse" x1="0" y1="100" x2="0" y2=${BACK.y2}>
      <stop offset="0" stop-color="#4a2219" stop-opacity="0"></stop>
      <stop offset="0.55" stop-color="#4f281f" stop-opacity="0.55"></stop>
      <stop offset="1" stop-color="#5a2c22" stop-opacity="0.75"></stop>
    </linearGradient>
    <linearGradient id=${`${uid}-heat-top`} gradientUnits="userSpaceOnUse" x1="0" y1=${FRONT.y1} x2="0" y2=${FRONT.y1 + 95}>
      <stop offset="0" stop-color="#ff8a3d" stop-opacity=${round(0.7 * glow.heat)}></stop>
      <stop offset="0.35" stop-color="#ff6a2a" stop-opacity=${round(0.2 * glow.heat)}></stop>
      <stop offset="0.5" stop-color="#e2541f" stop-opacity=${round(0.08 * glow.heat)}></stop>
      <stop offset="0.65" stop-color="#e2541f" stop-opacity="0"></stop>
    </linearGradient>
    <linearGradient id=${`${uid}-heat-bottom`} gradientUnits="userSpaceOnUse" x1="0" y1=${FRONT.y2} x2="0" y2=${FRONT.y2 - 70}>
      <stop offset="0" stop-color="#ff9a5a" stop-opacity=${round(0.95 * glow.heat)}></stop>
      <stop offset="0.12" stop-color="#e5763f" stop-opacity=${round(0.8 * glow.heat)}></stop>
      <stop offset="0.35" stop-color="#b8502c" stop-opacity=${round(0.42 * glow.heat)}></stop>
      <stop offset="1" stop-color="#8a3a22" stop-opacity="0"></stop>
    </linearGradient>
    <radialGradient id=${`${uid}-lamp-light`} gradientUnits="userSpaceOnUse" cx=${FRONT.x1 + 10} cy=${FRONT.y1 + 40} r="240">
      <stop offset="0" stop-color="#fff1dc" stop-opacity="0.5"></stop>
      <stop offset="0.35" stop-color="#ffd9a8" stop-opacity="0.16"></stop>
      <stop offset="1" stop-color="#ffd9a8" stop-opacity="0"></stop>
    </radialGradient>
    ${linear(`${uid}-tube`, [
      [0, "#5d6266"],
      [0.3, "#c9cdd0"],
      [0.45, "#f1f2f3"],
      [0.65, "#9ca1a5"],
      [1, "#43474b"],
    ], [0, 0], [0, 1])}
    ${linear(`${uid}-tube-hot`, [
      [0, "#ff5a14"],
      [0.35, "#ffc27a"],
      [0.5, "#fff1d6"],
      [0.65, "#ffb35a"],
      [1, "#ff4a10"],
    ], [0, 0], [0, 1])}
    ${linear(`${uid}-wire`, [
      [0, "#9da1a4"],
      [0.35, "#f4f1ea"],
      [0.6, "#c8c3ba"],
      [1, "#55585b"],
    ], [0, 0], [0, 1])}
    ${blur(`${uid}-halo`, 2.4)}
    ${blur(`${uid}-haze`, 6)}
    <clipPath id=${`${uid}-window`}><rect x=${WINDOW.x} y=${WINDOW.y} width=${WINDOW.width} height=${WINDOW.height} rx="4"></rect></clipPath>
    <clipPath id=${`${uid}-opening`}><rect x=${OPENING.x} y=${OPENING.y} width=${OPENING.width} height=${OPENING.height} rx="6"></rect></clipPath>
  `;
}

/** The fan cover on the back wall, the fan behind it turning with convection. */
function fan(uid: string, state: OvenState, light: Light, motion: boolean): SVGTemplateResult {
  const [cx, cy] = project(330, 128, 1);
  const r = 34;
  const tone = light === "off" ? "#0f1011" : light === "lamp" ? "#1a1411" : "#2a1610";
  const spin = state.fan === "super" ? 0.5 : 1.8;
  const blades = [0, 60, 120, 180, 240, 300].map(
    (angle) => svg`<path d=${`M${cx},${cy} q 5,-12 2,-${r - 6} q -9,5 -8,${r - 7} z`} fill=${mix(tone, "#000000", 0.25)}
      opacity="0.45" transform=${`rotate(${angle} ${cx} ${cy})`}></path>`,
  );
  return svg`
    <g opacity=${light === "off" ? 0.5 : 0.3}>
      <circle cx=${cx} cy=${cy} r=${r} fill=${tone}></circle>
      ${state.fan !== "off" && motion
        ? svg`<g class=${`${uid}-spin`} style=${`--${uid}-spin:${spin}s; transform-origin:${cx}px ${cy}px`}>${blades}</g>`
        : svg`<g>${blades}</g>`}
      <g fill="none" stroke="#ffffff" stroke-opacity="0.08" stroke-width="0.8">
        ${[r - 3, r - 10, r - 17, r - 24].map((radius) => svg`<circle cx=${cx} cy=${cy} r=${radius}></circle>`)}
      </g>
    </g>
  `;
}

/** The cavity's walls in perspective, lit for the state. */
function walls(uid: string, state: OvenState, light: Light, motion: boolean): SVGTemplateResult {
  return svg`
    <rect x=${BACK.x1} y=${BACK.y1} width=${round(BACK.x2 - BACK.x1)} height=${round(BACK.y2 - BACK.y1)} fill=${`url(#${uid}-cav-back)`}></rect>
    ${light === "heat"
      ? svg`<rect x=${BACK.x1} y=${BACK.y1} width=${round(BACK.x2 - BACK.x1)} height=${round(BACK.y2 - BACK.y1)} fill=${`url(#${uid}-cav-low)`}></rect>`
      : nothing}
    ${fan(uid, state, light, motion)}
    <polygon points=${pts([[FRONT.x1, FRONT.y1], [BACK.x1, BACK.y1], [BACK.x1, BACK.y2], [FRONT.x1, FRONT.y2]])} fill=${`url(#${uid}-cav-left)`}></polygon>
    <polygon points=${pts([[FRONT.x2, FRONT.y1], [BACK.x2, BACK.y1], [BACK.x2, BACK.y2], [FRONT.x2, FRONT.y2]])} fill=${`url(#${uid}-cav-right)`}></polygon>
    <polygon points=${pts([[FRONT.x1, FRONT.y1], [FRONT.x2, FRONT.y1], [BACK.x2, BACK.y1], [BACK.x1, BACK.y1]])} fill=${`url(#${uid}-cav-ceiling)`}></polygon>
    <polygon points=${pts([[FRONT.x1, FRONT.y2], [FRONT.x2, FRONT.y2], [BACK.x2, BACK.y2], [BACK.x1, BACK.y2]])} fill=${`url(#${uid}-cav-floor)`}></polygon>
    ${slots(light)}
  `;
}

/** The rack slots pressed into the side walls: four, each holding the rack high or low. */
function slots(light: Light): SVGTemplateResult {
  const ink = light === "off" ? "#2c2e30" : light === "lamp" ? "#5a4c43" : "#9a847c";
  const shadow = light === "off" ? "#0b0c0d" : "#140a06";
  return svg`<g stroke-linecap="round">
    ${[0, 2, 4, 6].map((index) => {
      const y = WINDOW.y + ((RACK_SHARES[index] + RACK_SHARES[index + 1]) / 2) * WINDOW.height;
      const [lx1, ly1] = project(FRONT.x1, y, 0.06);
      const [lx2, ly2] = project(FRONT.x1, y, 0.92);
      const [rx1, ry1] = project(FRONT.x2, y, 0.06);
      const [rx2, ry2] = project(FRONT.x2, y, 0.92);
      return svg`
        <line x1=${lx1} y1=${ly1 + 1.2} x2=${lx2} y2=${ly2 + 1} stroke=${shadow} stroke-opacity="0.45" stroke-width="2.2"></line>
        <line x1=${lx1} y1=${ly1} x2=${lx2} y2=${ly2} stroke=${ink} stroke-opacity="0.3" stroke-width="1"></line>
        <line x1=${rx1} y1=${ry1 + 1.2} x2=${rx2} y2=${ry2 + 1} stroke=${shadow} stroke-opacity="0.45" stroke-width="2.2"></line>
        <line x1=${rx1} y1=${ry1} x2=${rx2} y2=${ry2} stroke=${ink} stroke-opacity="0.2" stroke-width="1"></line>
      `;
    })}
  </g>`;
}

/** The light on the left wall, lit or not, and the warm light it throws. */
function lamp(uid: string, light: Light): SVGTemplateResult {
  const [x1, y1] = project(FRONT.x1, FRONT.y1 + 24, 0.14);
  const [x2, y2] = project(FRONT.x1, FRONT.y1 + 40, 0.24);
  const on = light !== "off";
  return svg`
    ${on ? svg`<rect x=${FRONT.x1} y=${FRONT.y1} width=${OPENING.width} height=${OPENING.height} fill=${`url(#${uid}-lamp-light)`}></rect>` : nothing}
    <polygon points=${pts([[x1 + 2, y1], [x2 + 1, y2 - 2], [x2 + 1, y2 + 9], [x1 + 2, y1 + 18]])}
      fill=${on ? "#ffeccc" : "#2b2c2e"} stroke=${on ? "#c9a77a" : "#3a3b3d"} stroke-width="0.6"></polygon>
    ${on
      ? svg`<polygon points=${pts([[x1 + 2, y1], [x2 + 1, y2 - 2], [x2 + 1, y2 + 9], [x1 + 2, y1 + 18]])} fill="#ffd9a0"
          filter=${`url(#${uid}-halo)`} opacity="0.7"></polygon>`
      : nothing}
  `;
}

/** The six quartz tubes, three by the ceiling and three by the floor, glowing as the mode uses them. */
function elements(uid: string, state: OvenState): SVGTemplateResult {
  const glow = glowing(state.elements);
  const tube = (y: number, depth: number, hot: boolean) => {
    const [x1, ty] = project(FRONT.x1 + 14, y, depth);
    const [x2] = project(FRONT.x2 - 14, y, depth);
    const thickness = round(5 * scaleAt(depth));
    return svg`
      ${hot
        ? svg`<rect x=${x1} y=${round(ty - thickness * 1.8)} width=${round(x2 - x1)} height=${round(thickness * 3.6)} rx=${thickness}
            fill="#ff7a24" opacity=${round(0.75 * glow.heat)} filter=${`url(#${uid}-halo)`}></rect>`
        : nothing}
      <rect x=${x1} y=${round(ty - thickness / 2)} width=${round(x2 - x1)} height=${thickness} rx=${round(thickness / 2)}
        fill=${`url(#${uid}-tube${hot ? "-hot" : ""})`} opacity=${hot ? round(0.6 + glow.heat * 0.4) : 0.8}></rect>
    `;
  };
  const depths = [0.18, 0.5, 0.82];
  return svg`
    ${depths.map((depth, index) => tube(FRONT.y1 + 9, depth, glow.top.includes(index)))}
    ${depths.map((depth, index) => tube(FRONT.y2 - 7, depth, glow.bottom.includes(index)))}
  `;
}

/** The elements' light filling the cavity: from the ceiling, and stronger from the floor. */
function heatLight(uid: string, state: OvenState): SVGTemplateResult | typeof nothing {
  const glow = glowing(state.elements);
  if (!glow.top.length && !glow.bottom.length) return nothing;
  return svg`
    ${glow.top.length
      ? svg`<rect x=${FRONT.x1} y=${FRONT.y1} width=${OPENING.width} height="95" fill=${`url(#${uid}-heat-top)`}
          opacity=${glow.top.length === 3 ? 1 : 0.7}></rect>`
      : nothing}
    ${glow.bottom.length
      ? svg`<rect x=${FRONT.x1} y=${FRONT.y2 - 70} width=${OPENING.width} height="70" fill=${`url(#${uid}-heat-bottom)`}></rect>`
      : nothing}
  `;
}

/**
 * The wire rack at its position: the frame's front and back wires, the wires front to back
 * between them (catching the light where they meet the front wire), and the side wires.
 */
export function rack(uid: string, position: number, light: Light): SVGTemplateResult {
  const y = rackY(position);
  const left = FRONT.x1 + 14;
  const right = FRONT.x2 - 14;
  const [fx1, fy] = project(left, y, 0.04);
  const [fx2] = project(right, y, 0.04);
  const [bx1, by] = project(left, y, 0.94);
  const [bx2] = project(right, y, 0.94);
  const wires = 21;
  const dim = light === "off" ? 0.32 : light === "lamp" ? 0.75 : 0.9;
  return svg`<g class="rack" stroke-linecap="round" opacity=${dim}>
    ${Array.from({ length: wires }, (_, index) => {
      const share = (index + 0.5) / wires;
      const x1 = round(fx1 + share * (fx2 - fx1));
      const x2 = round(bx1 + share * (bx2 - bx1));
      return svg`<line x1=${x1} y1=${fy} x2=${x2} y2=${by} stroke="#8d8f91" stroke-width="0.8"></line>`;
    })}
    <line x1=${bx1} y1=${by} x2=${bx2} y2=${by} stroke="#a7a9ab" stroke-width="1.1"></line>
    <line x1=${fx1} y1=${fy} x2=${bx1} y2=${by} stroke="#c9c6c0" stroke-width="1.4"></line>
    <line x1=${fx2} y1=${fy} x2=${bx2} y2=${by} stroke="#c9c6c0" stroke-width="1.4"></line>
    <line x1=${fx1 - 4} y1=${fy} x2=${fx2 + 4} y2=${fy} stroke=${`url(#${uid}-wire)`} stroke-width="2.4"></line>
    <line x1=${fx1} y1=${fy + 1.5} x2=${fx2} y2=${fy + 1.5} stroke="#000000" stroke-opacity="0.3" stroke-width="0.8"></line>
    ${Array.from({ length: wires }, (_, index) => {
      const share = (index + 0.5) / wires;
      return svg`<circle cx=${round(fx1 + share * (fx2 - fx1))} cy=${fy - 0.2} r="0.75" fill="#fffaf0" opacity="0.85"></circle>`;
    })}
  </g>`;
}

/**
 * Everything inside, for a view through `box` (the window or the opening): walls, lamp, fan,
 * elements and their light, then the rack. The caller draws what stands on the rack last.
 */
export function cavity(uid: string, state: OvenState, motion: boolean): SVGTemplateResult {
  const light = lightOf(state);
  return svg`
    ${walls(uid, state, light, motion)}
    ${lamp(uid, light)}
    ${elements(uid, state)}
    ${heatLight(uid, state)}
    ${rack(uid, state.rack, light)}
  `;
}

export function cavityLight(state: OvenState): Light {
  return lightOf(state);
}

/**
 * The door glass over the window: smoked, with a soft reflection of the studio, and the rack
 * positions printed down its right edge (a bracket joining each slot's two).
 */
export function glass(uid: string, light: Light): SVGTemplateResult {
  const x = WINDOW.x + WINDOW.width - 10;
  const numbers = RACK_SHARES.map((share, index) => {
    const y = WINDOW.y + share * WINDOW.height;
    const high = index % 2 === 0;
    return svg`<text x=${x} y=${round(y + 2.2)} font-size="6.2" font-weight="600" text-anchor="end">${index + 1}</text>
      ${high
        ? svg`<path d=${`M${x + 1.6},${round(y - 0.4)} h2 v${round((RACK_SHARES[index + 1] - share) * WINDOW.height * 0.5)} h1.4 M${x + 3.6},${round(y - 0.4 + (RACK_SHARES[index + 1] - share) * WINDOW.height * 0.5)} v${round((RACK_SHARES[index + 1] - share) * WINDOW.height * 0.5)} h-2`}
            fill="none" stroke=${RACK_INK} stroke-width="0.6"></path>`
        : nothing}`;
  });
  return svg`
    <rect x=${WINDOW.x} y=${WINDOW.y} width=${WINDOW.width} height=${WINDOW.height} fill="#140d09" opacity=${light === "off" ? 0.3 : 0.18}></rect>
    <g clip-path=${`url(#${uid}-window)`}>
      <path d=${`M${WINDOW.x + 30},${WINDOW.y} H${WINDOW.x + 120} L${WINDOW.x + 50},${WINDOW.y + WINDOW.height} H${WINDOW.x - 40} Z`}
        fill="#ffffff" opacity=${light === "off" ? 0.045 : 0.03}></path>
      <path d=${`M${WINDOW.x + 150},${WINDOW.y} H${WINDOW.x + 168} L${WINDOW.x + 98},${WINDOW.y + WINDOW.height} H${WINDOW.x + 80} Z`}
        fill="#ffffff" opacity=${light === "off" ? 0.03 : 0.02}></path>
      <rect x=${WINDOW.x} y=${WINDOW.y} width=${WINDOW.width} height="5" fill="#000000" opacity="0.35" filter=${`url(#${uid}-halo)`}></rect>
    </g>
    <g fill=${RACK_INK} font-family="'Arial Narrow', 'Roboto Condensed', Arial, sans-serif" opacity="0.92">${numbers}</g>
  `;
}
