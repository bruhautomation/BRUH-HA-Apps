import { svg, type SVGTemplateResult } from "lit";

/**
 * Materials shared by the drawings, measured on Breville's studio photos: brushed stainless lit
 * from the right with a soft falloff to the left, black stainless a graphite with the same grain,
 * spun and polished metal that mirrors the studio, glossy white polycarbonate, glass, water and
 * steam. The brushed grain is the Sub-Zero drawings' own.
 *
 * Every id is prefixed with the drawing's uid, since several drawings share one shadow root.
 */

/** A point in drawing units (mm). */
export type Pt = readonly [number, number];

export type Stops = ReadonlyArray<readonly [number, string, number?]>;

/** Measured colours along a part: [offset 0–1, colour]. */
export type Profile = ReadonlyArray<readonly [number, string]>;

/** Measured colours at even steps round a disc, from 0° (right) counter-clockwise. */
export type Ring = readonly string[];

/** One gradient stop list as SVG. */
function stops(list: Stops): SVGTemplateResult[] {
  return list.map(
    ([offset, color, opacity]) =>
      svg`<stop offset=${offset} stop-color=${color} stop-opacity=${opacity === undefined ? 1 : opacity}></stop>`,
  );
}

export function linear(id: string, list: Stops, from: Pt = [0, 0], to: Pt = [1, 0], units = "objectBoundingBox"): SVGTemplateResult {
  return svg`<linearGradient id=${id} x1=${from[0]} y1=${from[1]} x2=${to[0]} y2=${to[1]} gradientUnits=${units}>${stops(list)}</linearGradient>`;
}

export function radial(
  id: string,
  list: Stops,
  center: Pt = [0.5, 0.5],
  r = 0.5,
  focus: Pt | null = null,
  units = "objectBoundingBox",
): SVGTemplateResult {
  const [fx, fy] = focus ?? center;
  return svg`<radialGradient id=${id} cx=${center[0]} cy=${center[1]} r=${r} fx=${fx} fy=${fy} gradientUnits=${units}>${stops(list)}</radialGradient>`;
}

/** A gradient from a measured profile, its colours scaled by `factor` (1 as measured). */
export function profile(id: string, list: Profile, from: Pt = [0, 0], to: Pt = [1, 0], factor = 1, units = "objectBoundingBox"): SVGTemplateResult {
  return linear(
    id,
    list.map(([offset, color]) => [offset, factor === 1 ? color : shade(color, factor)] as const),
    from,
    to,
    units,
  );
}

/**
 * Brushed grain, as on the Sub-Zero drawings: noise stretched along the brushing, made grey and
 * laid over the metal with a gentle contrast. `strength` is 1 for brushed stainless and less for
 * darker finishes, whose grain shows less.
 */
export function grainFilter(id: string, strength: number, frequency = "0.0025 0.33"): SVGTemplateResult {
  const slope = (0.12 * strength).toFixed(3);
  const intercept = (0.5 - 0.06 * strength).toFixed(3);
  return svg`<filter id=${id} x="0" y="0" width="1" height="1" color-interpolation-filters="sRGB">
    <feTurbulence type="fractalNoise" baseFrequency=${frequency} numOctaves="2" seed="11" result="noise"></feTurbulence>
    <feColorMatrix in="noise" type="matrix" values="0.5 0.5 0 0 0  0.5 0.5 0 0 0  0.5 0.5 0 0 0  0 0 0 0 1" result="gray"></feColorMatrix>
    <feComponentTransfer in="gray" result="grain">
      <feFuncR type="linear" slope=${slope} intercept=${intercept}></feFuncR>
      <feFuncG type="linear" slope=${slope} intercept=${intercept}></feFuncG>
      <feFuncB type="linear" slope=${slope} intercept=${intercept}></feFuncB>
    </feComponentTransfer>
    <feBlend in="grain" in2="SourceGraphic" mode="overlay" result="brushed"></feBlend>
    <feComposite in="brushed" in2="SourceAlpha" operator="in"></feComposite>
  </filter>`;
}

/**
 * A blur sized to what it blurs (a share of its box), for smoothing the steps of a spun disc
 * whatever its size.
 */
export function softFilter(id: string, share: number): SVGTemplateResult {
  return svg`<filter id=${id} primitiveUnits="objectBoundingBox" x="-5%" y="-5%" width="110%" height="110%">
    <feGaussianBlur stdDeviation=${share}></feGaussianBlur>
  </filter>`;
}

/** A ring's colour at `angle` degrees, between its measured steps. */
function ringColor(ring: Ring, angle: number): string {
  const position = ((((angle % 360) + 360) % 360) / 360) * ring.length;
  const index = Math.floor(position);
  return mix(ring[index % ring.length], ring[(index + 1) % ring.length], position - index);
}

/** The point at `angle` degrees (counter-clockwise from the right, as measured) on a circle. */
function polar(cx: number, cy: number, r: number, angle: number): string {
  const radians = (angle * Math.PI) / 180;
  return `${round(cx + r * Math.cos(radians))},${round(cy - r * Math.sin(radians))}`;
}

/**
 * A disc of spun or polished metal: it mirrors the studio round its centre, so its colour turns
 * with the angle. Drawn as wedges, each a little wider than its share so no seam shows between
 * them; a soft blur over them (`softFilter`) smooths the steps.
 */
export function spunDisc(cx: number, cy: number, r: number, ring: Ring, steps = 72): SVGTemplateResult[] {
  const share = 360 / steps;
  return Array.from({ length: steps }, (_, index) => {
    const from = index * share - 0.8;
    const to = (index + 1) * share;
    return svg`<path d=${`M${round(cx)},${round(cy)}L${polar(cx, cy, r, from)}A${r},${r} 0 0 0 ${polar(cx, cy, r, to)}Z`}
      fill=${ringColor(ring, (index + 0.5) * share)}></path>`;
  });
}

/** A soft shadow under the appliance, darker on light pages. */
export function floorShadow(uid: string, cx: number, cy: number, rx: number, ry: number, theme: "light" | "dark"): SVGTemplateResult {
  const strength = theme === "dark" ? 0.55 : 0.28;
  return svg`
    ${radial(`${uid}-floor`, [
      [0, "#000000", strength],
      [0.6, "#000000", strength * 0.35],
      [1, "#000000", 0],
    ])}
    <ellipse cx=${cx} cy=${cy} rx=${rx} ry=${ry} fill=${`url(#${uid}-floor)`}></ellipse>
  `;
}

/** A blur for glows, sized in drawing units. */
export function blur(id: string, deviation: number): SVGTemplateResult {
  return svg`<filter id=${id} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation=${deviation}></feGaussianBlur></filter>`;
}

/** A colour scaled toward black (factor below 1) or white (above 1). */
export function shade(color: string, factor: number): string {
  return factor <= 1 ? mix("#000000", color, Math.max(0, factor)) : mix(color, "#ffffff", Math.min(1, factor - 1));
}

/** Rounded to hundredths, to keep paths short. */
export function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/** Two hex colors mixed, `amount` of the way from `a` to `b`. */
export function mix(a: string, b: string, amount: number): string {
  const parse = (hex: string) => [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16));
  const [ar, ag, ab] = parse(a);
  const [br, bg, bb] = parse(b);
  const channel = (x: number, y: number) =>
    Math.round(x + (y - x) * amount)
      .toString(16)
      .padStart(2, "0");
  return `#${channel(ar, br)}${channel(ag, bg)}${channel(ab, bb)}`;
}

/** A rounded rectangle's path, with its own corner radius. */
export function roundRect(x: number, y: number, width: number, height: number, r: number): string {
  const radius = Math.min(r, width / 2, height / 2);
  return (
    `M${x + radius},${y}H${x + width - radius}A${radius},${radius} 0 0 1 ${x + width},${y + radius}` +
    `V${y + height - radius}A${radius},${radius} 0 0 1 ${x + width - radius},${y + height}` +
    `H${x + radius}A${radius},${radius} 0 0 1 ${x},${y + height - radius}V${y + radius}A${radius},${radius} 0 0 1 ${x + radius},${y}Z`
  );
}

/**
 * Text that reads the same size on screen whatever size the drawing is shown at: `px` CSS pixels
 * tall when the caller knows the drawing's height, else `share` of the drawing's height.
 */
export function labelSize(viewHeight: number, pixelHeight: number | undefined, px = 12, share = 0.045): number {
  return pixelHeight ? (px * viewHeight) / pixelHeight : viewHeight * share;
}
