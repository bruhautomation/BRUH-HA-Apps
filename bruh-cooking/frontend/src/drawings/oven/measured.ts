/**
 * The Joule Oven Air Fryer Pro as measured on Breville's product photos (the front views of
 * BOV950BSS1BUS1 and BOV950BST1BUS1, the door-open view and the display close-up): its geometry
 * in millimetres from the photo's left edge and the top of the handle, and the colours and light
 * across each part. The photos are only measured, never traced or embedded.
 */
import type { Profile, Ring } from "../materials";

export const OVEN = {
  width: 544,
  /** The body's top edge; the handle stands proud of it. */
  top: 8.3,
  /** The radius of the body's top corners, and of its bottom ones. */
  topCorner: 20,
  bottomCorner: 10,
  /** The door's bottom edge, the gap under it, and the base below that. */
  doorBottom: 270,
  baseTop: 272,
  bottom: 297.5,
  floor: 317,
  /** The gap between the door and the control panel. */
  gap: { left: 450.5, right: 453.5 },
} as const;

/**
 * The window: the glass, and the frame round it, whose four bevels slope in to the glass and
 * catch the light differently (the bottom one, facing up, brightest).
 */
export const WINDOW_GLASS = { x: 53, y: 57.5, width: 354.8, height: 174.6 } as const;
export const WINDOW_FRAME = { x: 40.8, y: 49, width: 377.2, height: 193.5 } as const;

/** The handle: a polished bar on two brackets, casting a soft shadow down the door under it. */
export const HANDLE = {
  bar: { x: 24.5, y: 2, width: 408.5, height: 18 },
  brackets: [
    { x: 26.6, width: 22.7 },
    { x: 408.6, width: 22.7 },
  ],
  bracketTop: 0,
  bracketBottom: 50,
} as const;

export const TRAY = { x: 147, width: 162, top: 285.5, bottom: 298.5 } as const;
/** The feet, a little narrower at the floor than at the body. */
export const FEET = [
  { x: 9, width: 92 },
  { x: 443, width: 95 },
] as const;

export const PANEL = {
  x: 453.5,
  lcd: { x: 463, y: 25, width: 65, height: 78 },
  confirm: { cx: 477.3, cy: 133, r: 11.5 },
  start: { cx: 516, cy: 133, r: 14 },
  temp: { cx: 496.1, cy: 184.7, r: 25 },
  time: { cx: 496.1, cy: 254, r: 25 },
  buttons: [
    { cy: 159.6, icon: "light" },
    { cy: 203.4, icon: "fan" },
    { cy: 219, icon: "more" },
    { cy: 233, icon: "frozen" },
    { cy: 276.5, icon: "favorite" },
  ],
  buttonX: 525.3,
  buttonR: 4.7,
} as const;

/**
 * Rack positions 1 to 8 as shares of the window's height, where the glass prints each number:
 * four slots, each holding the reversible rack high or low.
 */
export const RACK_SHARES = [0.221, 0.29, 0.454, 0.519, 0.687, 0.746, 0.901, 0.966] as const;

/** Light across the whole front, by share of its width, as factors of the finish's brightest. */
export const FALLOFF: ReadonlyArray<readonly [number, number]> = [
  [0, 0.58],
  [0.003, 0.74],
  [0.009, 0.86],
  [0.013, 0.84],
  [0.03, 0.815],
  [0.18, 0.81],
  [0.37, 0.83],
  [0.55, 0.875],
  [0.64, 0.895],
  [0.735, 0.955],
  [0.77, 0.98],
  [0.81, 1],
  [0.828, 1],
  // The control panel: brighter, nearly even, its right edge rounding away.
  [0.834, 1.04],
  [0.837, 0.95],
  [0.9, 0.98],
  [0.96, 1.02],
  [0.988, 1],
  [0.995, 0.86],
  [1, 0.6],
];

export interface Finish {
  /** The front at its brightest, at the bottom of the door next to the panel. */
  bright: string;
  /** The door and panel brighten toward the bottom: factors from the top (8.3) to 270. */
  rise: ReadonlyArray<readonly [number, number]>;
  /** Down the handle bar, top to bottom: a polished tube mirroring the studio. */
  handle: Profile;
  /** Across a bracket, left to right: dark, as it faces down, with lit edges. */
  bracket: Profile;
  /** The window frame's bevels, each from the door face in to the glass. */
  bevelTop: Profile;
  bevelLeft: Profile;
  bevelRight: Profile;
  bevelBottom: Profile;
  /** The crumb tray: its top lip, then its face from top to bottom. */
  trayLip: string;
  tray: readonly [string, string];
  feet: Profile;
  dialCap: Ring;
  dialRim: Ring;
  dialGroove: Ring;
  /** The panel's printing. */
  ink: string;
  /** A small button's raised ring: its lit and its shaded side. */
  button: readonly [string, string];
  grain: number;
}

export const FINISHES: Record<"brushed_stainless" | "black_stainless", Finish> = {
  brushed_stainless: {
    bright: "#e9ebeb",
    rise: [
      [0, 0.8],
      [0.2, 0.8],
      [0.35, 0.835],
      [0.54, 0.89],
      [0.73, 0.935],
      [0.885, 0.975],
      [0.94, 0.995],
      [1, 1],
    ],
    handle: [
      [0, "#4d4d4d"],
      [0.08, "#656565"],
      [0.14, "#3b3b3b"],
      [0.2, "#646464"],
      [0.27, "#d8d8d8"],
      [0.36, "#f8f8f8"],
      [0.45, "#fcfcfc"],
      [0.55, "#e2e2e2"],
      [0.63, "#a9a9a9"],
      [0.7, "#727272"],
      [0.76, "#505050"],
      [0.82, "#777777"],
      [0.88, "#bfbfbf"],
      [0.94, "#e6e6e6"],
      [1, "#8a8a8a"],
    ],
    bracket: [
      [0, "#8d8d8d"],
      [0.03, "#545454"],
      [0.1, "#4f4f4f"],
      [0.6, "#4c4c4c"],
      [0.88, "#464646"],
      [0.93, "#757575"],
      [0.96, "#898989"],
      [1, "#747474"],
    ],
    bevelTop: [
      [0, "#c7c7c7"],
      [0.14, "#747474"],
      [0.24, "#4f4f4f"],
      [0.86, "#535353"],
      [0.93, "#2a2a2a"],
      [1, "#161616"],
    ],
    bevelLeft: [
      [0, "#a7a7a7"],
      [0.1, "#a7a7a7"],
      [0.14, "#595959"],
      [0.22, "#434343"],
      [0.35, "#373737"],
      [0.76, "#383838"],
      [0.84, "#2f2f2f"],
      [0.88, "#151315"],
      [1, "#151315"],
    ],
    bevelRight: [
      [0, "#c8c8c8"],
      [0.14, "#c9c9c9"],
      [0.26, "#979797"],
      [0.33, "#8d8d8d"],
      [0.9, "#8d8d8d"],
      [1, "#3a3a3a"],
    ],
    bevelBottom: [
      [0, "#dcdcdb"],
      [0.08, "#f3f3f3"],
      [0.2, "#eaeaea"],
      [0.8, "#e7e7e7"],
      [0.88, "#797979"],
      [0.93, "#060607"],
      [1, "#060607"],
    ],
    trayLip: "#585d61",
    tray: ["#3b3e41", "#484c50"],
    feet: [
      [0, "#292929"],
      [0.15, "#242628"],
      [0.35, "#3a3c3e"],
      [0.8, "#3e4145"],
      [0.92, "#2a2c2e"],
      [1, "#1e1e1e"],
    ],
    dialCap: [
      "#abaaad", "#9c9c9c", "#999898", "#5f5f61", "#6f7075", "#b3b3ba", "#e1e0e3", "#f5f5f5",
      "#f9f9f9", "#faf9f9", "#efeff0", "#c2c1c5", "#a1a0a3", "#767779", "#8e8e8c", "#81817f",
      "#939394", "#bebdc1", "#e1e0e3", "#ececec", "#f5f4f4", "#f2f2f2", "#dddbdd", "#bab9bd",
    ],
    dialRim: [
      "#d8d6d7", "#e4e3e3", "#f4f4f4", "#ffffff", "#f6f6f6", "#a2a2a5", "#b6b4b9", "#d1d0d4",
      "#dcdade", "#d0cdd2", "#9e9ca0", "#76777c", "#727376", "#9c9c9a", "#d8d9d8", "#fafafa",
      "#f0f0f0", "#cac9ca", "#9e9c9a", "#6b6b6a", "#474747", "#b6b5b4", "#c6c4c4", "#d0cece",
    ],
    dialGroove: [
      "#979797", "#bdbdbd", "#c2c2c2", "#c2c2c2", "#c3c3c3", "#868686", "#383838", "#606060",
      "#828282", "#7b7a7a", "#393939", "#0c0d0d", "#222121", "#363636", "#5d5d5d", "#858686",
      "#737373", "#636363", "#464646", "#444444", "#494949", "#5f5f5f", "#5f5f5f", "#6c6c6c",
    ],
    ink: "#38393a",
    button: ["#f6f6f6", "#9a9a9a"],
    grain: 1,
  },
  black_stainless: {
    bright: "#7d7d78",
    rise: [
      [0, 0.75],
      [0.2, 0.73],
      [0.35, 0.76],
      [0.54, 0.83],
      [0.73, 0.89],
      [0.885, 0.95],
      [0.94, 0.98],
      [1, 1],
    ],
    handle: [
      [0, "#3e3e3d"],
      [0.08, "#363635"],
      [0.14, "#131411"],
      [0.2, "#4d4c4c"],
      [0.27, "#adabac"],
      [0.36, "#e0dfe1"],
      [0.45, "#fdfdfd"],
      [0.55, "#f0f0f0"],
      [0.63, "#ababad"],
      [0.7, "#7d7c7d"],
      [0.76, "#4f4d4c"],
      [0.82, "#252422"],
      [0.88, "#13130a"],
      [0.94, "#373836"],
      [1, "#525050"],
    ],
    bracket: [
      [0, "#474445"],
      [0.03, "#2a2829"],
      [0.1, "#242223"],
      [0.6, "#242222"],
      [0.88, "#211f20"],
      [0.93, "#353434"],
      [0.96, "#444142"],
      [1, "#3a3839"],
    ],
    bevelTop: [
      [0, "#787675"],
      [0.14, "#373536"],
      [0.24, "#2c2a2b"],
      [0.86, "#2d2b2c"],
      [0.93, "#1c1b1b"],
      [1, "#121212"],
    ],
    bevelLeft: [
      [0, "#4f4d4e"],
      [0.1, "#4f4d4e"],
      [0.14, "#2f2d2e"],
      [0.22, "#292728"],
      [0.35, "#252324"],
      [0.76, "#262324"],
      [0.84, "#242122"],
      [0.88, "#141214"],
      [1, "#141214"],
    ],
    bevelRight: [
      [0, "#666462"],
      [0.14, "#7c7a78"],
      [0.26, "#585655"],
      [0.33, "#3f3d3e"],
      [0.9, "#3f3d3e"],
      [1, "#1f1e1e"],
    ],
    bevelBottom: [
      [0, "#848480"],
      [0.08, "#aaa7a5"],
      [0.2, "#8f8d89"],
      [0.8, "#8e8d88"],
      [0.88, "#413f3f"],
      [0.93, "#070707"],
      [1, "#070707"],
    ],
    trayLip: "#c84a27",
    tray: ["#892613", "#963a1c"],
    feet: [
      [0, "#201f1f"],
      [0.15, "#242628"],
      [0.35, "#3a3c3e"],
      [0.8, "#3e4145"],
      [0.92, "#2a2c2e"],
      [1, "#1e1e1e"],
    ],
    dialCap: [
      "#555253", "#484647", "#454443", "#21211c", "#2d2c2b", "#5f5d5e", "#918e8f", "#a9a7a9",
      "#acacae", "#aeacae", "#a2a0a2", "#6d6a6b", "#4c4a4b", "#2f2f2d", "#3f3d3b", "#353532",
      "#40403f", "#686566", "#908d8f", "#9f9d9e", "#a7a6a8", "#a4a2a3", "#8b8788", "#646161",
    ],
    dialRim: [
      "#848080", "#989596", "#c4c4c8", "#f8f8fa", "#e2e1e5", "#545454", "#605d5e", "#7e7a7b",
      "#8b8688", "#7d787a", "#484848", "#303030", "#2e2d2c", "#474645", "#848080", "#adacae",
      "#a09e9f", "#726e6e", "#484646", "#272724", "#111006", "#5d5a59", "#6e6a69", "#7a7575",
    ],
    dialGroove: [
      "#413e3f", "#565553", "#5a5857", "#5a5957", "#5c5a59", "#413f40", "#272526", "#383536",
      "#3b3939", "#393637", "#272526", "#191718", "#1d1b1b", "#232021", "#302e2d", "#3a3738",
      "#353334", "#2f2c2d", "#262425", "#262324", "#282525", "#312f30", "#2d2b2c", "#312f30",
    ],
    ink: "#d9d9d6",
    button: ["#9a9995", "#3a3938"],
    grain: 0.7,
  },
};

/** The handle's shadow down the door, as black's opacity from the bar's bottom (20) to 44. */
export const HANDLE_SHADOW: ReadonlyArray<readonly [number, number]> = [
  [0, 0.42],
  [0.15, 0.5],
  [0.35, 0.47],
  [0.42, 0.3],
  [0.55, 0.36],
  [0.72, 0.28],
  [0.84, 0.08],
  [1, 0],
];

export const RACK_INK = "#d24929";
