/**
 * The oven's display, laid out as on the BOV950 (measured on Breville's close-up of it): the list
 * of functions down the left with an arrow at the mode; the temperature and the time in
 * seven-segment digits with their units; convection; the rack position; and the prompts along
 * the bottom. Every word and digit is a fixed segment, lit or not, and the unlit ones show
 * faintly, as on the real glass. Pale blue-white while the oven waits, amber while it runs; the
 * black stainless model's is black, with white or orange segments. In millimetres from the
 * display's top-left corner.
 */
import { nothing, svg, type SVGTemplateResult } from "lit";
import { linear, roundRect } from "../materials";
import type { OvenLcd } from "../types";
import { PANEL } from "./measured";

const LCD = PANEL.lcd;

interface Look {
  bezel: string;
  /** The screen's light: top-left to bottom-right. */
  screen: readonly [string, string, string];
  /** The shadow the bezel casts on the screen's top and left edges. */
  shade: string;
  ink: string;
  ghost: number;
  glow: boolean;
}

/** Measured on the BOV950 photos: running (pdp2, pdp3) and waiting (the door-open view). */
const LOOKS: Record<"brushed" | "black", Record<"lit" | "pale" | "off", Look>> = {
  brushed: {
    lit: { bezel: "#6c6b68", screen: ["#e2b56a", "#d9a74f", "#cf942e"], shade: "#70422f", ink: "#4e402d", ghost: 0.06, glow: false },
    pale: { bezel: "#7d8b95", screen: ["#e2f0fb", "#d4e9f8", "#c3dcef"], shade: "#6f8ea6", ink: "#3f515d", ghost: 0.07, glow: false },
    off: { bezel: "#6c6b68", screen: ["#a9b3b8", "#9aa4a9", "#8b959a"], shade: "#4c5458", ink: "#4c5458", ghost: 0.08, glow: false },
  },
  black: {
    lit: { bezel: "#373435", screen: ["#2c2c2c", "#232323", "#1b1b1b"], shade: "#0c0c0c", ink: "#f2622f", ghost: 0.07, glow: true },
    pale: { bezel: "#373435", screen: ["#2c2c2c", "#232323", "#1b1b1b"], shade: "#0c0c0c", ink: "#eef1f3", ghost: 0.07, glow: true },
    off: { bezel: "#373435", screen: ["#262626", "#1e1e1e", "#171717"], shade: "#0a0a0a", ink: "#6a6a6a", ghost: 0.05, glow: false },
  },
};

// Seven segments: a top, b top right, c bottom right, d bottom, e bottom left, f top left, g middle.
const GLYPHS: Record<string, string> = {
  "0": "abcdef",
  "1": "bc",
  "2": "abdeg",
  "3": "abcdg",
  "4": "bcfg",
  "5": "acdfg",
  "6": "acdefg",
  "7": "abc",
  "8": "abcdefg",
  "9": "abcdfg",
  "-": "g",
  " ": "",
  A: "abcefg",
  C: "adef",
  E: "adefg",
  F: "aefg",
  H: "bcefg",
  I: "bc",
  L: "def",
  M: "abcef",
  P: "abefg",
  U: "bcdef",
  d: "bcdeg",
  n: "ceg",
  o: "cdeg",
  r: "eg",
};

/** The function list, top to bottom, and the modes each word stands for. */
const FUNCTIONS: ReadonlyArray<readonly [string, readonly string[]]> = [
  ["TOAST", ["toast"]],
  ["BAGEL", ["bagel"]],
  ["BAKE", ["bake", "bottom_bake"]],
  ["AIR FRY", ["air_fry", "gentle_broil"]],
  ["BROIL", ["broil", "bottom_broil", "outer_top_broil", "middle_top_broil", "windy_broil"]],
  ["ROAST", ["roast"]],
  ["PIZZA", ["pizza"]],
  ["COOKIES", ["cookies"]],
  ["PROOF", ["proof"]],
  ["REHEAT", ["reheat", "crispy_reheat"]],
  ["SLOW COOK", ["slow_cook"]],
  ["KEEP WARM", ["warm", "keep_warm"]],
  ["DEHYDRATE", ["dehydrate"]],
];

const FONT = "'Arial Narrow', 'Roboto Condensed', 'Helvetica Neue', Arial, sans-serif";
const DIGIT = { width: 5.9, height: 12.9, thickness: 1.45, pitch: 7.05 };
const SLANT = Math.tan((8 * Math.PI) / 180);

function segmentPaths(width: number, height: number, thickness: number): Record<string, string> {
  const half = thickness / 2;
  const gap = thickness * 0.14;
  const middle = height / 2;
  const across = (y: number) =>
    `M${half + gap},${y}l${half},${-half}H${width - thickness - gap}l${half},${half}l${-half},${half}H${thickness + gap}Z`;
  const down = (x: number, top: number, bottom: number) =>
    `M${x},${top + gap}l${half},${half}V${bottom - half - gap}l${-half},${half}l${-half},${-half}V${top + half + gap}Z`;
  return {
    a: across(half),
    g: across(middle),
    d: across(height - half),
    f: down(half, half, middle),
    b: down(width - half, half, middle),
    e: down(half, middle, height - half),
    c: down(width - half, middle, height - half),
  };
}

const BIG = segmentPaths(DIGIT.width, DIGIT.height, DIGIT.thickness);
const SMALL = segmentPaths(3.3, 6.6, 0.85);

/** One digit's segments at (x, y), its top left, slanted as the display's are. */
function digit(paths: Record<string, string>, height: number, x: number, y: number, glyph: string, look: Look): SVGTemplateResult {
  const lit = GLYPHS[glyph] ?? "";
  return svg`<g transform=${`translate(${x + height * SLANT * 0.5} ${y}) skewX(-8)`}>
    ${Object.entries(paths).map(
      ([segment, d]) => svg`<path d=${d} fill=${look.ink} fill-opacity=${lit.includes(segment) ? 1 : look.ghost}></path>`,
    )}
  </g>`;
}

/** A row of digits, right-aligned to `right`, with a colon after the second of four when asked. */
function digits(text: string | null, count: number, right: number, y: number, look: Look, colon: boolean): SVGTemplateResult {
  const glyphs = [...(text ?? "").replace(":", "")].slice(-count);
  const cells = [...Array(count - glyphs.length).fill(" "), ...glyphs];
  const colonWidth = colon ? 2.3 : 0;
  const left = right - (count * DIGIT.pitch - (DIGIT.pitch - DIGIT.width)) - colonWidth;
  const showColon = Boolean(text?.includes(":"));
  const dot = (cy: number) => {
    const cx = left + 2 * DIGIT.pitch + colonWidth / 2 - 0.55 + (DIGIT.height - cy + y) * SLANT;
    return svg`<path d=${`M${cx - 0.5},${cy - 0.55}h1.1l-0.15,1.1h-1.1Z`} fill=${look.ink} fill-opacity=${showColon ? 1 : look.ghost}></path>`;
  };
  return svg`
    ${cells.map((glyph, index) =>
      digit(BIG, DIGIT.height, left + index * DIGIT.pitch + (colon && index >= 2 ? colonWidth : 0), y, glyph, look),
    )}
    ${colon ? svg`${dot(y + DIGIT.height * 0.33)}${dot(y + DIGIT.height * 0.7)}` : nothing}
  `;
}

/** A printed word: lit in the ink, or faint. */
function word(text: string, x: number, y: number, size: number, length: number, lit: boolean, look: Look, anchor = "start"): SVGTemplateResult {
  return svg`<text x=${x} y=${y} font-size=${size} font-family=${FONT} font-weight="700" text-anchor=${anchor}
    textLength=${length} lengthAdjust="spacingAndGlyphs" fill=${look.ink} fill-opacity=${lit ? 1 : look.ghost}>${text}</text>`;
}

function fan(x: number, y: number, lit: boolean, look: Look): SVGTemplateResult {
  return svg`<g fill=${look.ink} fill-opacity=${lit ? 1 : look.ghost}>
    ${[0, 120, 240].map(
      (angle) => svg`<path d=${`M${x},${y} c0.2,-0.9 1.3,-1.5 1.6,-0.7 c0.2,0.6 -0.6,1 -1.6,0.7Z`} transform=${`rotate(${angle} ${x} ${y})`}></path>`,
    )}
    <circle cx=${x} cy=${y} r="0.35"></circle>
  </g>`;
}

function wifi(x: number, y: number, look: Look): SVGTemplateResult {
  return svg`<g fill="none" stroke=${look.ink} stroke-width="0.45" stroke-linecap="round">
    ${[0.9, 1.75, 2.6].map((r) => svg`<path d=${`M${x - r * 0.72},${y - r * 0.69} A${r},${r} 0 0 1 ${x + r * 0.72},${y - r * 0.69}`}></path>`)}
    <circle cx=${x} cy=${y} r="0.4" fill=${look.ink} stroke="none"></circle>
  </g>`;
}

export function lcdDefs(uid: string, black: boolean, lcd: OvenLcd | null): SVGTemplateResult {
  const look = LOOKS[black ? "black" : "brushed"][lcd === null ? "off" : lcd.lit ? "lit" : "pale"];
  return svg`
    ${linear(`${uid}-lcd`, [
      [0, look.screen[0]],
      [0.55, look.screen[1]],
      [1, look.screen[2]],
    ], [0.1, 0], [0.75, 1])}
    ${linear(`${uid}-lcd-shade`, [
      [0, look.shade, 0.75],
      [0.08, look.shade, 0.2],
      [0.2, look.shade, 0],
    ], [0, 0], [0, 1])}
    ${linear(`${uid}-lcd-shade-l`, [
      [0, look.shade, 0.55],
      [0.06, look.shade, 0.1],
      [0.15, look.shade, 0],
    ])}
    ${linear(`${uid}-lcd-glare`, [
      [0, "#ffffff", black ? 0.07 : 0.22],
      [0.45, "#ffffff", black ? 0.03 : 0.08],
      [0.46, "#ffffff", 0],
      [1, "#ffffff", 0],
    ], [0, 0], [0.6, 1])}
    ${look.glow
      ? svg`<filter id=${`${uid}-lcd-glow`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="0.6" result="blur"></feGaussianBlur>
          <feMerge><feMergeNode in="blur"></feMergeNode><feMergeNode in="SourceGraphic"></feMergeNode></feMerge>
        </filter>`
      : nothing}
  `;
}

/** The display in its window on the panel; `lcd` null shows it asleep, its segments faint. */
export function display(uid: string, black: boolean, lcd: OvenLcd | null): SVGTemplateResult {
  const look = LOOKS[black ? "black" : "brushed"][lcd === null ? "off" : lcd.lit ? "lit" : "pale"];
  const on = lcd !== null;
  const selected = on ? FUNCTIONS.findIndex(([, modes]) => modes.includes(lcd.mode)) : -1;
  const inset = 1.3;
  const screen = { x: inset, y: inset, width: LCD.width - inset * 2, height: LCD.height - inset * 2 };
  const row = (index: number) => 8.6 + index * 5.17;
  const fanOn = on && lcd.convection !== "off";
  const timeUnits = on ? lcd.timeUnits : null;
  const segments = svg`
    ${FUNCTIONS.map(([name], index) => word(name, 8, row(index), 4.1, [...name].length * 2.42, index === selected, look))}
    ${selected >= 0
      ? svg`<path d=${`M4.6,${row(selected) - 3.1}l2.4,1.5l-2.4,1.5Z`} fill=${look.ink}></path>`
      : nothing}
    ${word("PREHEATING", 61.5, 10.2, 2.5, 15.5, on && lcd.prompt === "preheating", look, "end")}
    ${digits(on ? lcd.temp : null, 3, 55.4, 12.9, look, false)}
    ${word(on && lcd.unit === "C" ? "°C" : "°F", 56.3, 16.6, 3.6, 4.4, on && lcd.unit !== null, look)}
    ${word("SUPER", 30.6, 31, 2.9, 9.2, on && lcd.convection === "super", look, "end")}
    ${fan(34.4, 29.8, fanOn, look)}
    ${word("CONVECTION", 37, 31, 2.9, 24.3, fanOn, look)}
    ${digits(on ? lcd.time : null, 4, 55.4, 32.6, look, true)}
    ${word(timeUnits === "hr_min" ? "HR" : "MIN", 56.3, 37.4, 2.5, 4.6, timeUnits !== null, look)}
    ${word(timeUnits === "hr_min" ? "MIN" : "SEC", 56.3, 40.6, 2.5, 4.6, timeUnits !== null, look)}
    ${word("FROZEN", 23.4, 49.4, 2.5, 10.8, on && lcd.frozen, look)}
    ${word("SLICES", 42, 49.4, 2.5, 9.6, false, look)}
    ${word("MY JOULE", 31.5, 53.2, 2.2, 10.4, false, look)}
    ${word("COOK", 34, 55.9, 2.2, 6.2, false, look)}
    ${on ? wifi(27.9, 56, look) : nothing}
    ${word("RACK POSITION", 33.4, 66.6, 2.85, 22.6, on && lcd.rack !== null, look)}
    <path d="M33.2,67.6v1.1h23.6v-1.1" fill="none" stroke=${look.ink} stroke-opacity=${on && lcd.rack !== null ? 1 : look.ghost}
      stroke-width="0.4"></path>
    ${digit(SMALL, 6.6, 57.3, 63.4, on && lcd.rack !== null ? String(lcd.rack) : " ", look)}
    ${word("PRESS CONFIRM", 5, 74.6, 2.9, 22.5, false, look)}
    ${word("PRESS", 36.4, 74.6, 2.9, 10.4, on && lcd.prompt === "press_start", look)}
    ${word("START", 61.5, 74.6, 2.9, 10.6, on && lcd.prompt === "press_start", look, "end")}
  `;
  return svg`<g class="oven-lcd" transform=${`translate(${LCD.x} ${LCD.y})`}>
    <path d=${roundRect(-0.5, -0.5, LCD.width + 1, LCD.height + 1, 5)} fill="#ffffff" opacity=${black ? 0.12 : 0.45}></path>
    <path d=${roundRect(0, 0, LCD.width, LCD.height, 4.6)} fill=${look.bezel}></path>
    <path d=${roundRect(screen.x, screen.y, screen.width, screen.height, 3.6)} fill=${`url(#${uid}-lcd)`}></path>
    <g filter=${look.glow && on ? `url(#${uid}-lcd-glow)` : nothing}>${segments}</g>
    <path d=${roundRect(screen.x, screen.y, screen.width, screen.height, 3.6)} fill=${`url(#${uid}-lcd-shade)`}></path>
    <path d=${roundRect(screen.x, screen.y, screen.width, screen.height, 3.6)} fill=${`url(#${uid}-lcd-shade-l)`}></path>
    <path d=${roundRect(screen.x, screen.y, screen.width, screen.height, 3.6)} fill=${`url(#${uid}-lcd-glare)`}></path>
  </g>`;
}
