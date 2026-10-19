/**
 * Shared crop color palette — the same botanical field-journal tones used on
 * the Garden Map. Importing from here keeps pills, badges, and map fills in
 * sync so a single Apple reads "sage green" everywhere in the app.
 */

export const COLOR_PRESETS = [
  '#a8c896',
  '#c4d8a3',
  '#e8d08a',
  '#dfa979',
  '#c68e8e',
  '#a897c6',
  '#90b3c8',
  '#b5a77c',
  '#8fb396',
  '#d7c4a8',
  '#b09080',
  '#a7ada0',
  '#cfd2d0',
  '#b0b3b0',
  '#8a8d8a',
];

export const BORDER_PRESETS = [
  '#5e8660',
  '#6e8f46',
  '#a68033',
  '#9c5a35',
  '#7a4040',
  '#5e4a7e',
  '#3e6180',
  '#75653a',
  '#3f6b48',
  '#7c6244',
  '#604a3c',
  '#4e5246',
  '#6b6e6b',
  '#4a4d4a',
  '#323432',
];

/** Stable per-crop fill + border color derived from the crop id. */
export function colorsForCrop(cropId: number): { fill: string; border: string } {
  const n = COLOR_PRESETS.length;
  const idx = (((cropId - 1) % n) + n) % n;
  return { fill: COLOR_PRESETS[idx], border: BORDER_PRESETS[idx] };
}

/** Convenience helper for pill-style badges — returns inline-style + class hints. */
export function cropPillStyle(cropId: number) {
  const { fill, border } = colorsForCrop(cropId);
  return {
    backgroundColor: `${fill}2e`, // ~18% alpha — subtle wash
    borderColor: border,
    color: border, // border tone reads well on the washed fill
  };
}
