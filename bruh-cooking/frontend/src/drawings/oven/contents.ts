/**
 * What stands on the rack: the oven's own accessories (the enamel roasting pan, the broil rack
 * that sits in it, the stainless air fry and dehydrate basket, the 13-inch pizza pan), a cast-iron
 * pot for a slow cook, and the food each mode cooks, shaded and textured like food in Breville's
 * photos (the croissants are theirs). Each piece is placed in the cavity's perspective: it stands
 * on the rack at its depth, and food is drawn front on, from a little above, at its own scale.
 */
import { nothing, svg, type SVGTemplateResult } from "lit";
import type { Accessory, Food } from "../../types";
import { linear, radial, round } from "../materials";
import { CENTER_X, EYE, project, scaleAt } from "./cavity";

export function contentsDefs(uid: string): SVGTemplateResult {
  return svg`
    ${linear(`${uid}-enamel`, [[0, "#4c4744"], [0.15, "#2f2c2a"], [0.6, "#1f1d1c"], [1, "#151413"]], [0, 0], [0, 1])}
    ${linear(`${uid}-enamel-in`, [[0, "#121111"], [1, "#2a2726"]], [0, 0], [0, 1])}
    ${linear(`${uid}-chrome-bar`, [[0, "#f6f4f0"], [0.35, "#c9c6c0"], [0.7, "#7c7a77"], [1, "#4c4b49"]], [0, 0], [0, 1])}
    ${linear(`${uid}-mesh-rim`, [[0, "#e9eaeb"], [0.4, "#a9acaf"], [1, "#5b5e61"]], [0, 0], [0, 1])}
    ${linear(`${uid}-pizza-pan`, [[0, "#3a3b3d"], [0.5, "#232426"], [1, "#151617"]], [0, 0], [0, 1])}
    ${radial(`${uid}-roll`, [[0, "#f9cb84"], [0.28, "#e49b48"], [0.58, "#c26b2a"], [0.84, "#8f4416"], [1, "#5c240a"]], [0.42, 0.36], 0.7, [0.3, 0.22])}
    ${linear(`${uid}-roll-base`, [[0, "#2a0e03", 0], [1, "#2a0e03", 0.45]], [0, 0], [0, 1])}
    <clipPath id=${`${uid}-on-tray`}><rect x="-90" y="-70" width="180" height="71"></rect></clipPath>
    ${radial(`${uid}-skin`, [[0, "#f3c27c"], [0.4, "#d38b44"], [0.75, "#a35a24"], [1, "#5d2e10"]], [0.42, 0.3], 0.72)}
    ${radial(`${uid}-seared`, [[0, "#6b3420"], [0.6, "#4a2112"], [1, "#2a120a"]], [0.45, 0.4], 0.7)}
    ${linear(`${uid}-meat-side`, [[0, "#7a3424"], [0.45, "#b0544a"], [1, "#6a2a1c"]], [0, 0], [0, 1])}
    ${linear(`${uid}-fry`, [[0, "#f6d58a"], [0.35, "#ecbd62"], [0.7, "#d99a3f"], [1, "#a8691f"]], [0, 0], [0, 1])}
    ${radial(`${uid}-cheese`, [[0, "#f7d77a"], [0.6, "#eab650"], [1, "#c98a2e"]], [0.45, 0.4], 0.7)}
    ${linear(`${uid}-pizza-crust`, [[0, "#e7b36a"], [0.5, "#c47f37"], [1, "#8a4c1c"]], [0, 0], [0, 1])}
    ${radial(`${uid}-cookie`, [[0, "#e8b56b"], [0.55, "#c98a42"], [0.85, "#a66325"], [1, "#7a4316"]], [0.45, 0.35], 0.7)}
    ${linear(`${uid}-ceramic`, [[0, "#ffffff"], [0.55, "#ecebe7"], [1, "#bcb9b2"]], [0, 0], [0, 1])}
    ${linear(`${uid}-dome`, [[0, "#6d7175"], [0.18, "#d9dcde"], [0.3, "#ffffff"], [0.45, "#b9bdc0"], [0.7, "#7b8085"], [0.85, "#c2c6c9"], [1, "#5d6165"]])}
    ${linear(`${uid}-castiron`, [[0, "#6a1612"], [0.2, "#c23a2e"], [0.32, "#e86a55"], [0.45, "#b8322a"], [0.8, "#7c1a15"], [1, "#4a0d0a"]])}
    ${radial(`${uid}-dough`, [[0, "#fff4de"], [0.6, "#f1dcb4"], [1, "#d9bd8e"]], [0.45, 0.3], 0.7)}
    ${radial(`${uid}-toast`, [[0, "#e9b264"], [0.6, "#c98a3e"], [1, "#9a5a22"]], [0.5, 0.4], 0.7)}
    <pattern id=${`${uid}-mesh`} width="3.4" height="3.4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <path d="M0,0 H3.4 M0,0 V3.4" stroke="#b8bbbe" stroke-width="0.6"></path>
    </pattern>
    <filter id=${`${uid}-crust`} x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.22" numOctaves="3" seed="4" result="noise"></feTurbulence>
      <feDiffuseLighting in="noise" surfaceScale="1.1" diffuseConstant="1" lighting-color="#ffffff" result="light">
        <feDistantLight azimuth="235" elevation="58"></feDistantLight>
      </feDiffuseLighting>
      <feComposite in="light" in2="SourceGraphic" operator="arithmetic" k1="1.18" k2="0" k3="0" k4="0" result="lit"></feComposite>
      <feComposite in="lit" in2="SourceAlpha" operator="in"></feComposite>
    </filter>
    <filter id=${`${uid}-fine`} x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="2" seed="9" result="noise"></feTurbulence>
      <feDiffuseLighting in="noise" surfaceScale="1.2" diffuseConstant="1" lighting-color="#ffffff" result="light">
        <feDistantLight azimuth="235" elevation="58"></feDistantLight>
      </feDiffuseLighting>
      <feComposite in="light" in2="SourceGraphic" operator="arithmetic" k1="1.2" k2="0" k3="0" k4="0" result="lit"></feComposite>
      <feComposite in="lit" in2="SourceAlpha" operator="in"></feComposite>
    </filter>
    <filter id=${`${uid}-glaze`} x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.35 0.6" numOctaves="2" seed="21" result="noise"></feTurbulence>
      <feDiffuseLighting in="noise" surfaceScale="0.5" diffuseConstant="1" lighting-color="#ffffff" result="light">
        <feDistantLight azimuth="235" elevation="62"></feDistantLight>
      </feDiffuseLighting>
      <feComposite in="light" in2="SourceGraphic" operator="arithmetic" k1="1.1" k2="0" k3="0" k4="0" result="lit"></feComposite>
      <feComposite in="lit" in2="SourceAlpha" operator="in"></feComposite>
    </filter>
    <filter id=${`${uid}-crease`} x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="0.7"></feGaussianBlur></filter>
    <filter id=${`${uid}-gloss`} x="-30%" y="-60%" width="160%" height="220%"><feGaussianBlur stdDeviation="0.9"></feGaussianBlur></filter>
    <filter id=${`${uid}-soft-shadow`} x="-20%" y="-100%" width="140%" height="300%"><feGaussianBlur stdDeviation="2"></feGaussianBlur></filter>
  `;
}

/** Where food stands: a point on the accessory's floor, at a depth, and how wide it may spread. */
export interface Place {
  x: number;
  y: number;
  depth: number;
  /** Half the width the food may spread over, in front-plane millimetres. */
  half: number;
}

const poly = (list: ReadonlyArray<readonly [number, number]>) => list.map(([x, y]) => `${x},${y}`).join(" ");

/** A box's outline in the cavity's perspective: the corners at the front and back of its top. */
function quad(x1: number, x2: number, y: number, d1: number, d2: number): string {
  return poly([project(x1, y, d1), project(x2, y, d1), project(x2, y, d2), project(x1, y, d2)]);
}

/** What an accessory draws behind the food, what in front of it, and where the food stands. */
export interface Held {
  back: SVGTemplateResult | typeof nothing;
  front: SVGTemplateResult | typeof nothing;
  place: Place;
}

const PAN_DEPTH = 11;

/** The enamel roasting pan: dark and glossy, its rim catching the light. */
function roastingPan(uid: string, y: number): Held {
  const x1 = CENTER_X - 150;
  const x2 = CENTER_X + 150;
  const rim = y - PAN_DEPTH;
  const d1 = 0.12;
  const d2 = 0.78;
  const [fl, fb] = project(x1 + 5, y, d1);
  const [fr] = project(x2 - 5, y, d1);
  const [rl, rt] = project(x1, rim, d1);
  const [rr] = project(x2, rim, d1);
  const into = rim > EYE.y;
  return {
    place: { x: CENTER_X, y: y - 3, depth: 0.45, half: 140 },
    back: svg`
      <ellipse cx=${CENTER_X} cy=${round(fb + 1)} rx="160" ry="4" fill="#000000" opacity="0.35" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
      ${into
        ? svg`<polygon points=${quad(x1, x2, rim, d1, d2)} fill=${`url(#${uid}-enamel-in)`}></polygon>
            <polygon points=${quad(x1 + 7, x2 - 7, rim + 1, d1 + 0.04, d2 - 0.04)} fill="#0e0d0d" opacity="0.6"></polygon>`
        : nothing}
      <polyline points=${poly([project(x1, rim, d2), project(x2, rim, d2)])} stroke="#6a625d" stroke-width="1.1" fill="none"></polyline>
    `,
    front: svg`
      <polygon points=${poly([[rl, rt], [rr, rt], [fr, fb], [fl, fb]])} fill=${`url(#${uid}-enamel)`}></polygon>
      <line x1=${rl - 1} y1=${rt} x2=${rr + 1} y2=${rt} stroke="#9a928c" stroke-width="1.6" stroke-linecap="round"></line>
      <line x1=${rl + 4} y1=${round(rt + 2.2)} x2=${rr - 4} y2=${round(rt + 2.2)} stroke="#ffffff" stroke-opacity="0.12" stroke-width="1.4"></line>
      <path d=${`M${rl + 30},${round(rt + 4)} L${rl + 120},${round(rt + 4)} L${rl + 112},${round(fb - 2)} L${rl + 26},${round(fb - 2)} Z`}
        fill="#ffffff" opacity="0.05"></path>
    `,
  };
}

/** The chrome broil rack in the pan, its slots dark. */
function broilRack(uid: string, y: number): SVGTemplateResult {
  const rim = y - PAN_DEPTH;
  const x1 = CENTER_X - 146;
  const x2 = CENTER_X + 146;
  const d1 = 0.14;
  const d2 = 0.76;
  const slots = 16;
  const top = quad(x1, x2, rim, d1, d2);
  return svg`
    <polygon points=${top} fill=${`url(#${uid}-chrome-bar)`}></polygon>
    ${Array.from({ length: slots }, (_, index) => {
      const share = (index + 0.5) / slots;
      const x = x1 + 10 + share * (x2 - x1 - 20);
      const [ax, ay] = project(x - 3, rim, d1 + 0.05);
      const [bx, by] = project(x + 3, rim, d1 + 0.05);
      const [cx, cy] = project(x + 3, rim, d2 - 0.05);
      const [dx, dy] = project(x - 3, rim, d2 - 0.05);
      return svg`<polygon points=${poly([[ax, ay], [bx, by], [cx, cy], [dx, dy]])} fill="#1b1a19"></polygon>`;
    })}
    <polyline points=${poly([project(x1, rim, d1), project(x2, rim, d1)])} stroke="#ffffff" stroke-opacity="0.6" stroke-width="1"></polyline>
  `;
}

/** The stainless mesh basket for air frying and dehydrating. */
function basket(uid: string, y: number): Held {
  const x1 = CENTER_X - 142;
  const x2 = CENTER_X + 142;
  const rim = y - 26;
  const d1 = 0.1;
  const d2 = 0.8;
  const [fl, fb] = project(x1 + 6, y, d1);
  const [fr] = project(x2 - 6, y, d1);
  const [rl, rt] = project(x1, rim, d1);
  const [rr] = project(x2, rim, d1);
  return {
    place: { x: CENTER_X, y: y - 3, depth: 0.45, half: 130 },
    back: svg`
      <ellipse cx=${CENTER_X} cy=${round(fb + 1)} rx="150" ry="4" fill="#000000" opacity="0.3" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
      ${rim > EYE.y ? svg`<polygon points=${quad(x1, x2, rim, d1, d2)} fill=${`url(#${uid}-mesh)`}></polygon>` : nothing}
      <polyline points=${poly([project(x1, rim, d2), project(x2, rim, d2)])} stroke="#9fa2a5" stroke-width="1.4" fill="none"></polyline>
    `,
    front: svg`
      <polygon points=${poly([[rl, rt], [rr, rt], [fr, fb], [fl, fb]])} fill="#000000" opacity="0.28"></polygon>
      <polygon points=${poly([[rl, rt], [rr, rt], [fr, fb], [fl, fb]])} fill=${`url(#${uid}-mesh)`}></polygon>
      <line x1=${rl - 1} y1=${rt} x2=${rr + 1} y2=${rt} stroke=${`url(#${uid}-mesh-rim)`} stroke-width="2.6" stroke-linecap="round"></line>
      <line x1=${fl} y1=${fb} x2=${fr} y2=${fb} stroke="#9fa2a5" stroke-width="1.2"></line>
    `,
  };
}

/** The round non-stick pizza pan. */
function pizzaPan(uid: string, y: number): Held {
  const radius = 165;
  const [cx, cy] = project(CENTER_X, y - 3, 0.45);
  const s = scaleAt(0.45);
  const tilt = Math.max(0.035, Math.min(0.2, (y - EYE.y) / 300));
  const rx = round(radius * s);
  const ry = round(radius * s * tilt);
  return {
    place: { x: CENTER_X, y: y - 4, depth: 0.45, half: 150 },
    front: nothing,
    back: svg`
      <ellipse cx=${cx} cy=${round(cy + 4)} rx=${rx + 6} ry=${ry + 3} fill="#000000" opacity="0.3" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
      <path d=${`M${cx - rx},${cy} A${rx},${ry} 0 0 0 ${cx + rx},${cy} V${round(cy + 3)} A${rx},${ry} 0 0 1 ${cx - rx},${round(cy + 3)} Z`} fill="#1a1b1c"></path>
      <ellipse cx=${cx} cy=${cy} rx=${rx} ry=${ry} fill=${`url(#${uid}-pizza-pan)`} stroke="#6a6c6e" stroke-width="1"></ellipse>
    `,
  };
}

/** A cast-iron pot, red enamel, lid on. */
function pot(uid: string, y: number): Held {
  const [cx, base] = project(CENTER_X, y, 0.45);
  const s = scaleAt(0.45);
  const w = 98 * s;
  const h = 72 * s;
  return {
    place: { x: CENTER_X, y: y - 70, depth: 0.45, half: 90 },
    front: nothing,
    back: svg`
      <ellipse cx=${cx} cy=${round(base + 1)} rx=${round(w + 10)} ry="4" fill="#000000" opacity="0.4" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
      <path d=${`M${round(cx - w)},${round(base - h)} H${round(cx + w)} V${round(base - 10 * s)} Q${round(cx + w)},${base} ${round(cx + w - 12 * s)},${base}
          H${round(cx - w + 12 * s)} Q${round(cx - w)},${base} ${round(cx - w)},${round(base - 10 * s)} Z`} fill=${`url(#${uid}-castiron)`}></path>
      <path d=${`M${round(cx - w - 12 * s)},${round(base - h + 10 * s)} h${round(12 * s)} v${round(14 * s)} h${round(-12 * s)} a${round(4 * s)},${round(4 * s)} 0 0 1 0,${round(-14 * s)} z
          M${round(cx + w + 12 * s)},${round(base - h + 10 * s)} h${round(-12 * s)} v${round(14 * s)} h${round(12 * s)} a${round(4 * s)},${round(4 * s)} 0 0 0 0,${round(-14 * s)} z`}
        fill="#8a1d16"></path>
      <path d=${`M${round(cx - w - 3 * s)},${round(base - h)} Q${cx},${round(base - h - 34 * s)} ${round(cx + w + 3 * s)},${round(base - h)} Z`} fill=${`url(#${uid}-castiron)`}></path>
      <line x1=${round(cx - w - 3 * s)} y1=${round(base - h)} x2=${round(cx + w + 3 * s)} y2=${round(base - h)} stroke="#3a0907" stroke-width="1.4"></line>
      <path d=${`M${round(cx - 13 * s)},${round(base - h - 24 * s)} h${round(26 * s)} v${round(-6 * s)} a3,3 0 0 0 -3,-3 h${round(-20 * s)} a3,3 0 0 0 -3,3 z`} fill="#2b2c2e"></path>
      <path d=${`M${round(cx - w * 0.72)},${round(base - h - 10 * s)} Q${round(cx - w * 0.2)},${round(base - h - 27 * s)} ${round(cx + w * 0.35)},${round(base - h - 22 * s)}`}
        fill="none" stroke="#ffffff" stroke-opacity="0.4" stroke-width=${round(3 * s)} stroke-linecap="round" filter=${`url(#${uid}-gloss)`}></path>
      <rect x=${round(cx - w * 0.55)} y=${round(base - h + 8 * s)} width=${round(w * 0.16)} height=${round(h * 0.75)} rx="3" fill="#ffffff" opacity="0.2" filter=${`url(#${uid}-gloss)`}></rect>
    `,
  };
}

/** The accessory on the rack at `y`, and where food stands on it. */
export function accessory(uid: string, kind: Accessory, y: number): Held {
  switch (kind) {
    case "roasting_pan":
      return roastingPan(uid, y);
    case "broil_rack": {
      const pan = roastingPan(uid, y);
      return { place: { ...pan.place, y: y - PAN_DEPTH - 1 }, back: svg`${pan.back}${broilRack(uid, y)}`, front: pan.front };
    }
    case "air_fry_basket":
      return basket(uid, y);
    case "pizza_pan":
      return pizzaPan(uid, y);
    case "pot":
      return pot(uid, y);
    default:
      // The food stands on the wire rack itself.
      return { place: { x: CENTER_X, y: y - 1, depth: 0.45, half: 170 }, back: nothing, front: nothing };
  }
}

/** Food drawn front on in its own millimetres, placed and scaled for its depth. */
function placed(place: Place, dx: number, content: SVGTemplateResult, depth = place.depth): SVGTemplateResult {
  const [x, y] = project(place.x + dx, place.y, depth);
  return svg`<g transform=${`translate(${x} ${y}) scale(${round(scaleAt(depth))})`}>${content}</g>`;
}

/**
 * A croissant's rolls, tips first and the fattest, middle one last: each a band slanting in
 * toward the crown, as centre x and y, length, thickness, and the slant of its length.
 */
const ROLLS: ReadonlyArray<readonly [number, number, number, number, number]> = [
  [-58, 1, 30, 16, -30],
  [59, 1, 29, 16, 28],
  [-41, -2, 38, 22, -46],
  [42, -2, 37, 22, 44],
  [-21, -7, 46, 26, -60],
  [22, -7, 45, 26, 58],
  [0, -13, 52, 30, -80],
];

/** An ellipse at any slant as a path, so its gradient keeps the studio's light fixed. */
function slanted(cx: number, cy: number, rx: number, ry: number, degrees: number): string {
  const angle = (degrees * Math.PI) / 180;
  const dx = rx * Math.cos(angle);
  const dy = rx * Math.sin(angle);
  const a = `${round(cx - dx)},${round(cy - dy)}`;
  const b = `${round(cx + dx)},${round(cy + dy)}`;
  return `M${a}A${rx},${ry} ${degrees} 1 0 ${b}A${rx},${ry} ${degrees} 1 0 ${a}Z`;
}

/**
 * A croissant as in Breville's photos: glazed rolls slanting in toward the fattest one in the
 * middle, each lit on its upper left and shadowed where the next folds over it. `shift` varies
 * the rolls a little from one croissant to the next.
 */
function croissant(uid: string, shift: number): SVGTemplateResult {
  const rolls = ROLLS.map(([x, y, length, thickness, slant], index) => {
    const cx = x + shift * (index % 2 ? -1 : 1);
    const along = (share: number) => [cx + Math.cos((slant * Math.PI) / 180) * length * share, y + Math.sin((slant * Math.PI) / 180) * length * share];
    const [hx, hy] = along(-0.08);
    return svg`
      ${index > 1
        ? svg`<path d=${slanted(cx, y, length / 2 + 1.5, thickness / 2 + 1.4, slant)} fill="#2e0f03" opacity="0.5" filter=${`url(#${uid}-crease)`}></path>`
        : nothing}
      <path d=${slanted(cx, y, length / 2, thickness / 2, slant)} fill=${`url(#${uid}-roll)`}></path>
      <path d=${slanted(round(hx - thickness * 0.14), round(hy - thickness * 0.12), round(length * 0.3), round(thickness * 0.16), slant)}
        fill="#fff0c8" opacity="0.62" filter=${`url(#${uid}-gloss)`}></path>
    `;
  });
  return svg`
    <ellipse cx="0" cy="2.5" rx="72" ry="4.5" fill="#000000" opacity="0.5" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
    <g clip-path=${`url(#${uid}-on-tray)`}>
      <g filter=${`url(#${uid}-glaze)`}>${rolls}</g>
      <rect x="-80" y="-14" width="160" height="15" fill=${`url(#${uid}-roll-base)`}></rect>
    </g>
  `;
}

function croissants(uid: string, place: Place): SVGTemplateResult {
  return svg`${placed(place, -74, croissant(uid, 0))}${placed(place, 74, croissant(uid, 2))}`;
}

/** A baked casserole filling the pan, browned on top with bubbling edges. */
function casserole(uid: string, place: Place): SVGTemplateResult {
  const half = place.half - 4;
  return placed(
    place,
    0,
    svg`<g filter=${`url(#${uid}-crust)`}>
      <path d=${`M${-half},2 C${-half + 4},-22 ${-half * 0.4},-27 0,-27 C${half * 0.4},-27 ${half - 4},-22 ${half},2 Z`} fill=${`url(#${uid}-cheese)`}></path>
      ${[[-100, -12, 16], [-55, -20, 12], [-12, -23, 18], [36, -21, 13], [82, -15, 15], [118, -6, 9], [-128, -4, 9]].map(
        ([x, y, r]) => svg`<ellipse cx=${x} cy=${y} rx=${r} ry=${r * 0.32} fill="#8a4316" opacity="0.6"></ellipse>`,
      )}
    </g>`,
  );
}

/** A whole roast chicken, breast up, legs toward us, the skin crisp and glistening. */
function chicken(uid: string, place: Place): SVGTemplateResult {
  return placed(
    place,
    0,
    svg`
      <ellipse cx="0" cy="2" rx="78" ry="5" fill="#000000" opacity="0.45" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
      <g filter=${`url(#${uid}-crust)`}>
        <path d="M-74,-4 C-80,-30 -54,-58 -4,-60 C46,-60 78,-34 72,-6 C40,4 -40,4 -74,-4 Z" fill=${`url(#${uid}-skin)`}></path>
        <path d="M-62,-6 C-94,-6 -100,-30 -78,-38 C-62,-36 -54,-22 -48,-10 Z" fill=${`url(#${uid}-skin)`}></path>
        <path d="M60,-6 C92,-6 98,-30 76,-38 C60,-36 52,-22 46,-10 Z" fill=${`url(#${uid}-skin)`}></path>
        <path d="M-86,-30 c-6,-4 -10,-2 -10,3 c2,4 6,4 10,1 z M84,-30 c6,-4 10,-2 10,3 c-2,4 -6,4 -10,1 z" fill="#efe2c8"></path>
      </g>
      <path d="M-2,-58 C-6,-40 -4,-20 2,-4" fill="none" stroke="#6e3412" stroke-opacity="0.35" stroke-width="2"></path>
      <path d="M-40,-46 C-20,-56 18,-56 36,-46" fill="none" stroke="#fff1d0" stroke-opacity="0.45" stroke-width="5" stroke-linecap="round" filter=${`url(#${uid}-gloss)`}></path>
      <ellipse cx="-30" cy="-30" rx="10" ry="4" fill="#fff1d0" opacity="0.35" filter=${`url(#${uid}-gloss)`}></ellipse>
    `,
  );
}

/** Two steaks, seared on top with the grill's marks, pink at the edges. */
function steaks(uid: string, place: Place): SVGTemplateResult {
  const steak = svg`
    <ellipse cx="0" cy="3" rx="56" ry="5" fill="#000000" opacity="0.45" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
    <path d="M-54,-2 C-56,-10 -40,-15 -6,-15 C34,-15 56,-11 54,-3 C52,4 -50,5 -54,-2 Z" fill=${`url(#${uid}-meat-side)`}></path>
    <path d="M-54,-8 C-56,-17 -40,-24 -6,-24 C34,-24 56,-19 54,-10 C50,-3 -48,-1 -54,-8 Z" fill=${`url(#${uid}-seared)`} filter=${`url(#${uid}-fine)`}></path>
    ${[-30, -12, 6, 24].map(
      (x) => svg`<path d=${`M${x - 7},-6 L${x + 9},-21`} stroke="#160a05" stroke-width="3" stroke-linecap="round" opacity="0.8"></path>`,
    )}
    <ellipse cx="-14" cy="-19" rx="18" ry="2.2" fill="#ffffff" opacity="0.18" filter=${`url(#${uid}-gloss)`}></ellipse>
  `;
  return svg`${placed(place, -64, steak)}${placed(place, 64, steak)}`;
}

/** A heap of golden fries, lying every way, crisp at their ends; the heap highest in the middle. */
function fries(uid: string, place: Place): SVGTemplateResult {
  const sticks: SVGTemplateResult[] = [];
  for (let index = 0; index < 70; index++) {
    const x = -118 + ((index * 53) % 236);
    const crown = 22 * Math.sqrt(Math.max(0, 1 - (x / 125) ** 2));
    const height = ((index * 29) % 100) / 100;
    const y = -2 - height * crown;
    const angle = ((index * 47) % 70) - 35;
    const length = 34 + ((index * 17) % 20);
    const shade = 0.85 + ((index * 13) % 30) / 100;
    sticks.push(svg`<g transform=${`translate(${x} ${round(y)}) rotate(${angle})`} opacity=${round(Math.min(1, shade))}>
      <rect x=${-length / 2} y="-2.6" width=${length} height="5.2" rx="1.6" fill=${`url(#${uid}-fry)`}></rect>
      <rect x=${-length / 2} y="-2.6" width="4" height="5.2" rx="1.6" fill="#8a4a14" opacity="0.55"></rect>
      <rect x=${length / 2 - 4} y="-2.6" width="4" height="5.2" rx="1.6" fill="#8a4a14" opacity="0.45"></rect>
    </g>`);
  }
  return placed(
    place,
    0,
    svg`
      <ellipse cx="0" cy="2" rx="128" ry="6" fill="#000000" opacity="0.35" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
      <g filter=${`url(#${uid}-fine)`}>${sticks}</g>
    `,
  );
}

/** A pizza on the pan: browned crust, melted cheese, pepperoni; frosted when it's frozen. */
function pizza(uid: string, place: Place, frozen: boolean): SVGTemplateResult {
  const tilt = Math.max(0.035, Math.min(0.2, (place.y - EYE.y) / 300));
  const r = 150;
  const ry = r * tilt;
  return placed(
    place,
    0,
    svg`
      <path d=${`M${-r},0 A${r},${ry} 0 0 0 ${r},0 V-5 A${r},${ry} 0 0 1 ${-r},-5 Z`} fill="#b06a2c"></path>
      <ellipse cx="0" cy="-5" rx=${r} ry=${ry} fill=${`url(#${uid}-pizza-crust)`} filter=${`url(#${uid}-crust)`}></ellipse>
      <ellipse cx="0" cy="-5.5" rx=${r - 12} ry=${ry * 0.86} fill=${`url(#${uid}-cheese)`} filter=${`url(#${uid}-fine)`}></ellipse>
      ${[[-100, 0], [-58, -0.4], [-18, 0.3], [24, -0.3], [64, 0.2], [104, -0.1], [-80, 0.55], [40, 0.55], [-40, -0.6], [80, -0.55]].map(
        ([x, share]) => svg`<ellipse cx=${x} cy=${round(-5.5 + share * ry * 0.7)} rx="10" ry=${round(Math.max(1.6, ry * 0.2))} fill="#9e2a1c"></ellipse>
          <ellipse cx=${x - 2} cy=${round(-6 + share * ry * 0.7)} rx="4" ry=${round(Math.max(0.6, ry * 0.07))} fill="#ffffff" opacity="0.25"></ellipse>`,
      )}
      ${frozen
        ? svg`<ellipse cx="0" cy="-5.5" rx=${r} ry=${ry} fill="#eef6fb" opacity="0.55" filter=${`url(#${uid}-fine)`}></ellipse>`
        : nothing}
    `,
  );
}

/** Cookies in two rows, golden at the edges, with chocolate chips. */
function cookies(uid: string, place: Place): SVGTemplateResult {
  const cookie = (r: number) => svg`
    <ellipse cx="0" cy="1" rx=${r} ry=${r * 0.22} fill="#000000" opacity="0.4" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
    <path d=${`M${-r},0 C${-r},${-r * 0.62} ${r},${-r * 0.62} ${r},0 C${r * 0.6},${r * 0.14} ${-r * 0.6},${r * 0.14} ${-r},0 Z`} fill=${`url(#${uid}-cookie)`}
      filter=${`url(#${uid}-crust)`}></path>
    ${[[-0.4, -0.12], [0.1, -0.22], [0.45, -0.08], [-0.1, -0.04]].map(
      ([x, y]) => svg`<ellipse cx=${x * r} cy=${y * r} rx=${r * 0.11} ry=${r * 0.06} fill="#3a1d0e"></ellipse>`,
    )}
  `;
  return svg`
    ${[-96, -32, 32, 96].map((dx) => placed(place, dx, cookie(23), 0.66))}
    ${[-128, -64, 0, 64, 128].map((dx) => placed(place, dx, cookie(25), 0.4))}
  `;
}

/** A plate of leftovers. */
function plate(uid: string, place: Place): SVGTemplateResult {
  return placed(
    place,
    0,
    svg`
      <ellipse cx="0" cy="1" rx="80" ry="7" fill="#000000" opacity="0.35" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
      <ellipse cx="0" cy="-1" rx="76" ry="9" fill="#a9a59e"></ellipse>
      <ellipse cx="0" cy="-3" rx="76" ry="8.5" fill=${`url(#${uid}-ceramic)`}></ellipse>
      <g filter=${`url(#${uid}-crust)`}>
        <path d="M-50,-4 C-46,-26 -6,-30 14,-22 C24,-30 46,-26 50,-6 Z" fill=${`url(#${uid}-skin)`}></path>
      </g>
      <ellipse cx="34" cy="-8" rx="13" ry="5" fill="#4f7a2e" filter=${`url(#${uid}-fine)`}></ellipse>
    `,
  );
}

/** Dough rising in a bowl. */
function dough(uid: string, place: Place): SVGTemplateResult {
  return placed(
    place,
    0,
    svg`
      <ellipse cx="0" cy="1" rx="76" ry="6" fill="#000000" opacity="0.35" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
      <ellipse cx="0" cy="-58" rx="62" ry="24" fill=${`url(#${uid}-dough)`} filter=${`url(#${uid}-fine)`}></ellipse>
      <path d="M-74,-56 Q-68,0 -34,0 H34 Q68,0 74,-56 Z" fill=${`url(#${uid}-ceramic)`}></path>
      <ellipse cx="0" cy="-56" rx="74" ry="7" fill="none" stroke="#d6d2ca" stroke-width="2.4"></ellipse>
      <rect x="-56" y="-46" width="10" height="38" rx="5" fill="#ffffff" opacity="0.5" filter=${`url(#${uid}-gloss)`}></rect>
    `,
  );
}

/** A covered serving dish keeping warm: a stainless dome. */
function coveredDish(uid: string, place: Place): SVGTemplateResult {
  return placed(
    place,
    0,
    svg`
      <ellipse cx="0" cy="1" rx="92" ry="6" fill="#000000" opacity="0.35" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
      <ellipse cx="0" cy="-2" rx="88" ry="8" fill="#cfccc6"></ellipse>
      <path d="M-80,-4 Q-78,-50 0,-52 Q78,-50 80,-4 Z" fill=${`url(#${uid}-dome)`}></path>
      <rect x="-10" y="-60" width="20" height="8" rx="3.5" fill="#8c9195"></rect>
    `,
  );
}

/** Orange and apple slices drying in the basket. */
function fruit(uid: string, place: Place): SVGTemplateResult {
  const slice = (orange: boolean) => svg`
    <ellipse cx="0" cy="0" rx="17" ry="5" fill=${orange ? "#e98a22" : "#f1e2b4"} filter=${`url(#${uid}-fine)`}></ellipse>
    <ellipse cx="0" cy="0" rx="12.5" ry="3.4" fill="none" stroke=${orange ? "#ffc874" : "#b84a36"} stroke-width="1"></ellipse>
    ${orange
      ? svg`${[0, 60, 120].map((angle) => svg`<line x1="0" y1="0" x2=${round(12 * Math.cos((angle * Math.PI) / 180))} y2=${round(3.3 * Math.sin((angle * Math.PI) / 180))} stroke="#ffd79a" stroke-width="0.6"></line>`)}`
      : nothing}
  `;
  return svg`${[-105, -70, -35, 0, 35, 70, 105].map((dx, index) =>
    placed(place, dx, svg`<g transform=${`translate(0 ${-6 - (index % 2) * 3})`}>${slice(index % 3 !== 1)}</g>`, index % 2 ? 0.55 : 0.35),
  )}`;
}

/** Two slices of toast on the rack. */
function bread(uid: string, place: Place): SVGTemplateResult {
  const slice = svg`
    <ellipse cx="0" cy="1" rx="56" ry="4" fill="#000000" opacity="0.4" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
    <path d="M-54,0 q2,-12 16,-13 h76 q14,1 16,13 z" fill="#9a5a22"></path>
    <path d="M-49,-2 q2,-9 13,-10 h72 q11,1 13,10 z" fill=${`url(#${uid}-toast)`} filter=${`url(#${uid}-fine)`}></path>
  `;
  return svg`${placed(place, -64, slice)}${placed(place, 64, slice)}`;
}

/** Two bagel halves, cut side up. */
function bagel(uid: string, place: Place): SVGTemplateResult {
  const half = svg`
    <ellipse cx="0" cy="1" rx="46" ry="5" fill="#000000" opacity="0.4" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
    <ellipse cx="0" cy="-4" rx="44" ry="10" fill="#a8652a" filter=${`url(#${uid}-crust)`}></ellipse>
    <ellipse cx="0" cy="-6" rx="36" ry="7" fill=${`url(#${uid}-toast)`} filter=${`url(#${uid}-fine)`}></ellipse>
    <ellipse cx="0" cy="-6" rx="10" ry="2.6" fill="#2b1a10"></ellipse>
  `;
  return svg`${placed(place, -60, half)}${placed(place, 60, half)}`;
}

/** A slice of pizza. */
function pizzaSlice(uid: string, place: Place): SVGTemplateResult {
  return placed(
    place,
    0,
    svg`
      <ellipse cx="0" cy="1" rx="70" ry="4" fill="#000000" opacity="0.35" filter=${`url(#${uid}-soft-shadow)`}></ellipse>
      <path d="M-70,0 L60,-4 L66,-13 L-64,-9 Z" fill=${`url(#${uid}-pizza-crust)`} filter=${`url(#${uid}-crust)`}></path>
      <path d="M-56,-2 L52,-5 L56,-11 L-52,-8 Z" fill=${`url(#${uid}-cheese)`} filter=${`url(#${uid}-fine)`}></path>
      ${[-30, 0, 30].map((dx) => svg`<ellipse cx=${dx} cy="-6.5" rx="8" ry="1.6" fill="#9e2a1c"></ellipse>`)}
    `,
  );
}

/** The food on the accessory. */
export function food(uid: string, kind: Food, place: Place, frozen: boolean): SVGTemplateResult | typeof nothing {
  switch (kind) {
    case "croissants":
      return croissants(uid, place);
    case "casserole":
      return casserole(uid, place);
    case "chicken":
      return chicken(uid, place);
    case "steak":
      return steaks(uid, place);
    case "fries":
      return fries(uid, place);
    case "pizza":
      return pizza(uid, place, frozen);
    case "cookies":
      return cookies(uid, place);
    case "plate":
      return plate(uid, place);
    case "dough":
      return dough(uid, place);
    case "covered_dish":
      return coveredDish(uid, place);
    case "fruit":
      return fruit(uid, place);
    case "bread":
      return bread(uid, place);
    case "bagel":
      return bagel(uid, place);
    case "pizza_slice":
      return pizzaSlice(uid, place);
    default:
      return nothing;
  }
}
