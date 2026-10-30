/**
 * The Joule Oven Air Fryer Pro, front on, to scale in millimetres (544 wide, 317 tall to the
 * floor), measured on Breville's photos and lit as they are: brushed or black stainless, the door
 * with its polished handle and bevelled window onto the cavity, the control panel down the right
 * with its display and spun-metal dials. No logos. Inside, the rack sits at the mode's position
 * with that mode's accessory, food while it cooks, and the cavity lit by the lamp and glowing from
 * the elements the mode uses. The door lies open when it's open.
 */
import { html, nothing, svg, type SVGTemplateResult, type TemplateResult } from "lit";
import { unsafeSVG } from "lit/directives/unsafe-svg.js";
import { floorShadow } from "./materials";
import { bodyDefs, crumbTray, feet, handle, openDoor, openingFrame, seams, shell, windowFrame } from "./oven/body";
import { cavity, cavityDefs, cavityLight, glass, rackY } from "./oven/cavity";
import { accessory, contentsDefs, food } from "./oven/contents";
import { FINISHES, OVEN } from "./oven/measured";
import { controlPanel, panelDefs } from "./oven/panel";
import type { DrawingInput, OvenState } from "./types";

const WIDTH = OVEN.width;
const HEIGHT = 345;

/** How what stands in the cavity is lit: dim when the oven is dark, warm under the lamp or the elements. */
function lightFilters(uid: string): SVGTemplateResult {
  return svg`
    <filter id=${`${uid}-in-off`} color-interpolation-filters="sRGB">
      <feColorMatrix type="matrix" values="0.24 0 0 0 0.01  0 0.24 0 0 0.01  0 0 0.25 0 0.012  0 0 0 1 0"></feColorMatrix>
    </filter>
    <filter id=${`${uid}-in-lamp`} color-interpolation-filters="sRGB">
      <feColorMatrix type="matrix" values="0.86 0.04 0 0 0  0.02 0.76 0 0 0  0 0 0.6 0 0  0 0 0 1 0"></feColorMatrix>
    </filter>
    <filter id=${`${uid}-in-heat`} color-interpolation-filters="sRGB">
      <feColorMatrix type="matrix" values="1.02 0.06 0 0 0.01  0.02 0.8 0 0 0  0 0 0.62 0 0  0 0 0 1 0"></feColorMatrix>
    </filter>
  `;
}

/** The cavity seen through the window or the opening, with the rack and what's on it. */
function inside(uid: string, state: OvenState, clip: string, motion: boolean): SVGTemplateResult {
  const held = accessory(uid, state.accessory, rackY(state.rack));
  const light = cavityLight(state);
  return svg`<g clip-path=${`url(#${uid}-${clip})`}>
    ${cavity(uid, state, motion)}
    <g filter=${`url(#${uid}-in-${light})`}>
      ${held.back}
      ${state.food ? food(uid, state.food, held.place, state.frozen) : nothing}
      ${held.front}
    </g>
  </g>`;
}

function badge(state: OvenState): SVGTemplateResult | typeof nothing {
  if (!state.error) return nothing;
  return svg`<g transform="translate(392 72)">
    <circle r="13" fill="#d93025"></circle>
    <rect x="-1.8" y="-7.5" width="3.6" height="9.5" rx="1.6" fill="#ffffff"></rect>
    <circle cy="6" r="2.1" fill="#ffffff"></circle>
  </g>`;
}

// Lit can't bind inside a <style> element, so the rules go in whole. The uid is the drawing's own.
function animations(uid: string) {
  return unsafeSVG(`<style>
    .${uid}-spin { animation: ${uid}-spin var(--${uid}-spin, 2s) linear infinite; }
    @keyframes ${uid}-spin { to { transform: rotate(360deg); } }
    .${uid}-pulse { animation: ${uid}-pulse 1.4s ease-in-out infinite; }
    @keyframes ${uid}-pulse { 50% { opacity: 0.3; } }
  </style>`);
}

export function renderOven(input: DrawingInput): TemplateResult {
  const state = input.state as OvenState;
  const { uid, theme } = input;
  const black = input.finish === "black_stainless";
  const finish = FINISHES[black ? "black_stainless" : "brushed_stainless"];
  const motion = !input.reducedMotion && state.available;
  const light = cavityLight(state);
  return html`<svg
    viewBox=${`-14 -4 ${WIDTH + 28} ${HEIGHT + 4}`}
    style=${state.available ? "" : "filter: grayscale(0.9) opacity(0.62)"}
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      ${bodyDefs(uid, finish)}
      ${cavityDefs(uid, state)}
      ${contentsDefs(uid)}
      ${panelDefs(uid, black, state)}
      ${lightFilters(uid)}
    </defs>
    ${motion ? animations(uid) : nothing}
    ${floorShadow(uid, WIDTH / 2, OVEN.floor + 1, WIDTH / 2 + 20, 7, theme)}
    ${feet(uid)}
    ${shell(uid)}
    ${seams()}
    ${crumbTray(uid)}
    ${state.door_open
      ? svg`${inside(uid, state, "opening", motion)}${openingFrame()}${openDoor(uid)}`
      : svg`${windowFrame(uid)}${inside(uid, state, "window", motion)}${glass(uid, light)}${handle(uid)}`}
    ${controlPanel(uid, state, finish, black, motion)}
    ${badge(state)}
  </svg>`;
}
