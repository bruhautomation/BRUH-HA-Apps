/**
 * The oven's body, front on, as measured on Breville's photos: the brushed shell lit brightest at
 * the bottom of the door by the panel, falling off to the left and up; the door with its polished
 * handle on two brackets, the handle's shadow down the door, and the window's frame of four
 * bevels; the base under the door with the crumb tray; the feet. With the door open, the door
 * lies forward under the opening, nearer the camera and so a little wider, its handle hanging
 * below it.
 */
import { svg, type SVGTemplateResult } from "lit";
import { grainFilter, linear, profile, round, roundRect, shade } from "../materials";
import { FALLOFF, FEET, HANDLE, HANDLE_SHADOW, OVEN, TRAY, WINDOW_FRAME, WINDOW_GLASS, type Finish } from "./measured";

/** The opening behind the door, and where the open door lies. */
export const OPENING = { x: 9, y: 13, width: 440, height: 234 } as const;
const OPEN = {
  /** The door's inner face, from the hinge to its near edge, and that edge's band. */
  face: { top: 247, bottom: 270 },
  edge: { top: 270, bottom: 291 },
  /** The open door is nearer the camera: wider, about the middle of the opening. */
  scale: 1.075,
  center: OPENING.x + OPENING.width / 2,
  bracketBottom: 341,
  bar: { top: 324, bottom: 341 },
} as const;

const near = (x: number) => round(OPEN.center + (x - OPEN.center) * OPEN.scale);

function shellPath(): string {
  const { width: w, top: t, bottom: b, topCorner: r, bottomCorner: q } = OVEN;
  return `M0,${t + r}A${r},${r} 0 0 1 ${r},${t}H${w - r}A${r},${r} 0 0 1 ${w},${t + r}V${b - q}A${q},${q} 0 0 1 ${w - q},${b}H${q}A${q},${q} 0 0 1 0,${b - q}Z`;
}

export function bodyDefs(uid: string, finish: Finish): SVGTemplateResult {
  const { width, top, doorBottom } = OVEN;
  const frame = WINDOW_FRAME;
  return svg`
    <linearGradient id=${`${uid}-metal`} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2=${width} y2="0">
      ${FALLOFF.map(([offset, factor]) => svg`<stop offset=${offset} stop-color=${shade(finish.bright, factor)}></stop>`)}
    </linearGradient>
    <linearGradient id=${`${uid}-rise`} gradientUnits="userSpaceOnUse" x1="0" y1=${top} x2="0" y2=${doorBottom}>
      ${finish.rise.map(
        ([offset, factor]) => svg`<stop offset=${offset} stop-color="#000000" stop-opacity=${round(1 - factor)}></stop>`,
      )}
    </linearGradient>
    <linearGradient id=${`${uid}-handle-shadow`} gradientUnits="userSpaceOnUse" x1="0" y1="20" x2="0" y2="44">
      ${HANDLE_SHADOW.map(([offset, alpha]) => svg`<stop offset=${offset} stop-color="#000000" stop-opacity=${alpha}></stop>`)}
    </linearGradient>
    ${grainFilter(`${uid}-grain`, finish.grain)}
    ${profile(`${uid}-bar`, finish.handle, [0, 0], [0, 1])}
    ${profile(`${uid}-bracket`, finish.bracket)}
    ${linear(`${uid}-bracket-v`, [
      [0, "#ffffff", 0.18],
      [0.4, "#ffffff", 0],
      [0.85, "#000000", 0],
      [1, "#000000", 0.25],
    ], [0, 0], [0, 1])}
    ${linear(`${uid}-bar-end`, [
      [0, "#000000", 0.35],
      [0.35, "#000000", 0],
      [0.65, "#000000", 0],
      [1, "#000000", 0.35],
    ])}
    ${profile(`${uid}-bevel-t`, finish.bevelTop, [0, frame.y], [0, WINDOW_GLASS.y], 1, "userSpaceOnUse")}
    ${profile(`${uid}-bevel-b`, finish.bevelBottom, [0, frame.y + frame.height], [0, WINDOW_GLASS.y + WINDOW_GLASS.height], 1, "userSpaceOnUse")}
    ${profile(`${uid}-bevel-l`, finish.bevelLeft, [frame.x, 0], [WINDOW_GLASS.x, 0], 1, "userSpaceOnUse")}
    ${profile(`${uid}-bevel-r`, finish.bevelRight, [frame.x + frame.width, 0], [WINDOW_GLASS.x + WINDOW_GLASS.width, 0], 1, "userSpaceOnUse")}
    ${linear(`${uid}-base-edge`, [
      [0, "#000000", 0],
      [0.25, "#000000", 0.05],
      [0.55, "#000000", 0.32],
      [1, "#000000", 0.62],
    ], [0, 0], [0, 1])}
    ${linear(`${uid}-tray`, [
      [0, finish.trayLip],
      [0.22, finish.trayLip],
      [0.27, shade(finish.tray[0], 0.85)],
      [0.4, finish.tray[0]],
      [1, finish.tray[1]],
    ], [0, 0], [0, 1])}
    ${linear(`${uid}-tray-ends`, [
      [0, "#000000", 0.45],
      [0.04, "#000000", 0.1],
      [0.1, "#000000", 0],
      [0.9, "#000000", 0],
      [0.96, "#000000", 0.1],
      [1, "#000000", 0.4],
    ])}
    ${profile(`${uid}-foot`, finish.feet, [0, 0], [0, 1])}
    ${linear(`${uid}-foot-x`, [
      [0, "#000000", 0.3],
      [0.08, "#000000", 0.05],
      [0.7, "#ffffff", 0.03],
      [0.86, "#000000", 0.1],
      [1, "#000000", 0.45],
    ])}
    ${linear(`${uid}-door-face`, [
      [0, "#000000", 0.55],
      [0.5, "#000000", 0.2],
      [1, "#000000", 0],
    ], [0, 0], [0, 1])}
    <clipPath id=${`${uid}-shell`}><path d=${shellPath()}></path></clipPath>
    <filter id=${`${uid}-shadow-soft`} x="-5%" y="-40%" width="110%" height="180%">
      <feGaussianBlur stdDeviation="1.4"></feGaussianBlur>
    </filter>
  `;
}

/** The shell: one brushed front for door, base and panel, lit as in the photos. */
export function shell(uid: string): SVGTemplateResult {
  const { width, top, doorBottom, bottom } = OVEN;
  return svg`
    <path d=${shellPath()} fill=${`url(#${uid}-metal)`} filter=${`url(#${uid}-grain)`}></path>
    <g clip-path=${`url(#${uid}-shell)`}>
      <rect x="0" y=${top} width=${width} height=${doorBottom - top} fill=${`url(#${uid}-rise)`}></rect>
      <rect x="0" y=${bottom - 3.5} width=${width} height="3.5" fill=${`url(#${uid}-base-edge)`}></rect>
      <path d=${`M2,${top + OVEN.topCorner} A${OVEN.topCorner - 2},${OVEN.topCorner - 2} 0 0 1 ${OVEN.topCorner},${top + 2}H${width - OVEN.topCorner}`}
        fill="none" stroke="#ffffff" stroke-opacity="0.45" stroke-width="1.6"></path>
    </g>
  `;
}

/** The seams: round the door, under it, and down the panel's left edge. */
export function seams(): SVGTemplateResult {
  const { top, doorBottom, baseTop, bottom, gap } = OVEN;
  return svg`
    <rect x=${gap.left} y=${top + 0.6} width=${gap.right - gap.left} height=${bottom - top - 1.2} fill="#070707"></rect>
    <line x1=${gap.left - 0.3} x2=${gap.left - 0.3} y1=${top + 2} y2=${doorBottom} stroke="#ffffff" stroke-opacity="0.35" stroke-width="0.5"></line>
    <line x1=${gap.right + 0.3} x2=${gap.right + 0.3} y1=${top + 2} y2=${bottom - 1} stroke="#ffffff" stroke-opacity="0.45" stroke-width="0.5"></line>
    <line x1=${gap.right + 1.1} x2=${gap.right + 1.1} y1=${top + 2} y2=${bottom - 1} stroke="#000000" stroke-opacity="0.1" stroke-width="0.9"></line>
    <rect x="0.4" y=${doorBottom} width=${gap.left - 0.4} height=${baseTop - doorBottom} fill="#0b0b0b"></rect>
    <line x1="1" x2=${gap.left} y1=${doorBottom - 0.3} y2=${doorBottom - 0.3} stroke="#ffffff" stroke-opacity="0.25" stroke-width="0.5"></line>
    <line x1="1" x2=${gap.left} y1=${baseTop + 0.7} y2=${baseTop + 0.7} stroke="#ffffff" stroke-opacity="0.5" stroke-width="0.8"></line>
  `;
}

/** The window's frame: four bevels sloping in to the glass, mitred at the corners. */
export function windowFrame(uid: string): SVGTemplateResult {
  const o = { x1: WINDOW_FRAME.x, y1: WINDOW_FRAME.y, x2: WINDOW_FRAME.x + WINDOW_FRAME.width, y2: WINDOW_FRAME.y + WINDOW_FRAME.height };
  const i = { x1: WINDOW_GLASS.x, y1: WINDOW_GLASS.y, x2: WINDOW_GLASS.x + WINDOW_GLASS.width, y2: WINDOW_GLASS.y + WINDOW_GLASS.height };
  return svg`
    <clipPath id=${`${uid}-frame`}><path d=${roundRect(o.x1, o.y1, o.x2 - o.x1, o.y2 - o.y1, 9)}></path></clipPath>
    <g clip-path=${`url(#${uid}-frame)`}>
      <path d=${`M${o.x1},${o.y1}H${o.x2}L${i.x2},${i.y1}H${i.x1}Z`} fill=${`url(#${uid}-bevel-t)`}></path>
      <path d=${`M${o.x1},${o.y2}H${o.x2}L${i.x2},${i.y2}H${i.x1}Z`} fill=${`url(#${uid}-bevel-b)`}></path>
      <path d=${`M${o.x1},${o.y1}L${i.x1},${i.y1}V${i.y2}L${o.x1},${o.y2}Z`} fill=${`url(#${uid}-bevel-l)`}></path>
      <path d=${`M${o.x2},${o.y1}L${i.x2},${i.y1}V${i.y2}L${o.x2},${o.y2}Z`} fill=${`url(#${uid}-bevel-r)`}></path>
    </g>
  `;
}

/** The handle's shadow down the door, the brackets, and the polished bar across them. */
export function handle(uid: string): SVGTemplateResult {
  const bar = HANDLE.bar;
  const r = bar.height / 2;
  return svg`
    <path d=${roundRect(bar.x + 3, 20, bar.width - 6, 24, 6)} fill=${`url(#${uid}-handle-shadow)`} filter=${`url(#${uid}-shadow-soft)`}></path>
    ${HANDLE.brackets.map(
      ({ x, width }) => svg`
        <path d=${`M${x},${HANDLE.bracketTop + 3} Q${x},${HANDLE.bracketTop} ${x + 3},${HANDLE.bracketTop} H${x + width - 3} Q${x + width},${HANDLE.bracketTop} ${x + width},${HANDLE.bracketTop + 3}
            V${HANDLE.bracketBottom - 5} Q${x + width},${HANDLE.bracketBottom} ${x + width - 5},${HANDLE.bracketBottom} H${x + 5} Q${x},${HANDLE.bracketBottom} ${x},${HANDLE.bracketBottom - 5} Z`}
          fill=${`url(#${uid}-bracket)`}></path>
        <path d=${roundRect(x, HANDLE.bracketTop, width, HANDLE.bracketBottom - HANDLE.bracketTop, 4)} fill=${`url(#${uid}-bracket-v)`}></path>
        <path d=${`M${x + 3},${HANDLE.bracketBottom - 0.4} H${x + width - 3}`} stroke="#000000" stroke-opacity="0.3" stroke-width="0.8"></path>
      `,
    )}
    <path d=${roundRect(bar.x, bar.y, bar.width, bar.height, r)} fill=${`url(#${uid}-bar)`}></path>
    <path d=${roundRect(bar.x, bar.y, bar.width, bar.height, r)} fill=${`url(#${uid}-bar-end)`} opacity="0.6"></path>
    <path d=${roundRect(bar.x, bar.y, bar.width, bar.height, r)} fill="none" stroke="#000000" stroke-opacity="0.22" stroke-width="0.5"></path>
  `;
}

/** The crumb tray under the door: dark grey, or orange on black stainless. */
export function crumbTray(uid: string): SVGTemplateResult {
  const { x, width, top, bottom } = TRAY;
  return svg`
    <path d=${`M${x},${top + 1.5} Q${x},${top} ${x + 1.5},${top} H${x + width - 1.5} Q${x + width},${top} ${x + width},${top + 1.5}
        V${bottom - 2} Q${x + width},${bottom} ${x + width - 2},${bottom} H${x + 2} Q${x},${bottom} ${x},${bottom - 2} Z`}
      fill=${`url(#${uid}-tray)`}></path>
    <rect x=${x} y=${top} width=${width} height=${bottom - top} rx="2" fill=${`url(#${uid}-tray-ends)`}></rect>
    <line x1=${x + 2} x2=${x + width - 2} y1=${top + 0.4} y2=${top + 0.4} stroke="#ffffff" stroke-opacity="0.22" stroke-width="0.5"></line>
  `;
}

export function feet(uid: string): SVGTemplateResult {
  const top = OVEN.bottom - 3;
  const floor = OVEN.floor;
  return svg`${FEET.map(({ x, width }) => {
    const path = `M${x},${top} H${x + width} L${x + width - 3},${floor - 3} Q${x + width - 3.4},${floor} ${x + width - 6.5},${floor}
      H${x + 6.5} Q${x + 3.4},${floor} ${x + 3},${floor - 3} Z`;
    return svg`<path d=${path} fill=${`url(#${uid}-foot)`}></path><path d=${path} fill=${`url(#${uid}-foot-x)`}></path>`;
  })}`;
}

/**
 * The open door: its inner face (dark glass in a steel rim, the rack numbers printed on it) from
 * the hinge to its near edge, that edge's brushed band, and the handle hanging under it.
 */
export function openDoor(uid: string): SVGTemplateResult {
  const left = OPENING.x;
  const right = OPENING.x + OPENING.width;
  const { face, edge, bar } = OPEN;
  const rim = 9;
  const brackets = HANDLE.brackets.map(({ x, width }) => ({ x: near(x), width: width * OPEN.scale }));
  return svg`
    <g class="open-door">
      <path d=${`M${left - 3},${face.top} H${right + 3} L${near(OVEN.gap.left) + 2},${face.bottom} H${near(0) - 2} Z`} fill=${`url(#${uid}-metal)`}></path>
      <path d=${`M${left - 3},${face.top} H${right + 3} L${near(OVEN.gap.left) + 2},${face.bottom} H${near(0) - 2} Z`} fill="#000000" opacity="0.18"></path>
      <path d=${`M${left + rim},${face.top + 2.2} H${right - rim} L${near(OVEN.gap.left) - rim * 1.5},${face.bottom - 3.4} H${near(0) + rim * 1.5} Z`}
        fill="#17191b"></path>
      <path d=${`M${left + rim},${face.top + 2.2} H${right - rim} L${near(OVEN.gap.left) - rim * 1.5},${face.bottom - 3.4} H${near(0) + rim * 1.5} Z`}
        fill=${`url(#${uid}-door-face)`}></path>
      <path d=${`M${left + 70},${face.top + 4} H${left + 190} L${left + 170},${face.bottom - 5} H${left + 40} Z`} fill="#ffffff" opacity="0.05"></path>
      <g fill="#d24929" opacity="0.8">
        ${[0, 1, 2, 3].map(
          (index) => svg`<rect x=${right - 46 + index * 6.5} y=${face.top + 9 + (index % 2) * 0.6} width="2.2" height="1.2" rx="0.4"></rect>`,
        )}
      </g>
      <path d=${`M${near(0) - 2},${edge.top} H${near(OVEN.gap.left) + 2} V${edge.bottom - 3} Q${near(OVEN.gap.left) + 2},${edge.bottom} ${near(OVEN.gap.left) - 1},${edge.bottom}
          H${near(0) + 1} Q${near(0) - 2},${edge.bottom} ${near(0) - 2},${edge.bottom - 3} Z`}
        fill=${`url(#${uid}-metal)`} filter=${`url(#${uid}-grain)`}></path>
      <line x1=${near(0)} x2=${near(OVEN.gap.left)} y1=${edge.top + 0.6} y2=${edge.top + 0.6} stroke="#ffffff" stroke-opacity="0.7" stroke-width="1.1"></line>
      <rect x=${near(0) - 2} y=${edge.bottom - 4} width=${near(OVEN.gap.left) - near(0) + 4} height="4" fill="#000000" opacity="0.18"></rect>
      ${brackets.map(
        ({ x, width }) => svg`
          <path d=${`M${x},${edge.bottom} H${x + width} V${OPEN.bracketBottom - 5} Q${x + width},${OPEN.bracketBottom} ${x + width - 5},${OPEN.bracketBottom}
              H${x + 5} Q${x},${OPEN.bracketBottom} ${x},${OPEN.bracketBottom - 5} Z`} fill=${`url(#${uid}-metal)`}></path>
          <path d=${roundRect(x, edge.bottom, width, OPEN.bracketBottom - edge.bottom, 5)} fill=${`url(#${uid}-bracket)`} opacity="0.35"></path>
          <rect x=${x} y=${edge.bottom} width=${width} height="5" fill="#000000" opacity="0.3"></rect>
        `,
      )}
      <path d=${roundRect(brackets[0].x - 2, bar.top, brackets[1].x + brackets[1].width - brackets[0].x + 4, bar.bottom - bar.top, (bar.bottom - bar.top) / 2)}
        fill=${`url(#${uid}-bar)`}></path>
      <path d=${roundRect(brackets[0].x - 2, bar.top, brackets[1].x + brackets[1].width - brackets[0].x + 4, bar.bottom - bar.top, (bar.bottom - bar.top) / 2)}
        fill="none" stroke="#000000" stroke-opacity="0.22" stroke-width="0.5"></path>
    </g>
  `;
}

/** The thin steel frame round the opening, seen with the door open. */
export function openingFrame(): SVGTemplateResult {
  return svg`
    <path d=${roundRect(OPENING.x, OPENING.y, OPENING.width, OPENING.height, 6)} fill="none" stroke="#000000" stroke-opacity="0.55" stroke-width="1.2"></path>
    <path d=${roundRect(OPENING.x - 1.2, OPENING.y - 1.2, OPENING.width + 2.4, OPENING.height + 2.4, 7)} fill="none" stroke="#ffffff" stroke-opacity="0.4" stroke-width="0.6"></path>
  `;
}
