import { describe, expect, it } from 'vitest';

import { calculateDose } from '@/lib/dose';

describe('calculateDose', () => {
  it('multiplies a per-gallon rate across the mix volume', () => {
    // 2 fl oz/gal over 4 gallons = 8 fl oz of product.
    const result = calculateDose(2, 'fl oz/gal', 4);
    expect(result.flOz).toBe(8);
    expect(result.ratePerGallon).toBe(2);
    expect(result.notFoliar).toBeUndefined();
    // 8 fl oz should display in fl oz, not a smaller unit.
    expect(result.bestUnit).toBe('fl oz');
  });

  it('converts a per-acre rate through the 100 gal/acre dilute assumption', () => {
    // 100 fl oz/acre / 100 gal per acre = 1 fl oz/gal; over 4 gal = 4 fl oz.
    const result = calculateDose(100, 'fl oz/acre', 4);
    expect(result.ratePerGallon).toBe(1);
    expect(result.flOz).toBe(4);
    expect(result.warning).toMatch(/gal\/acre dilute spray/);
  });

  it('flags non-foliar rate units as not tank-mixable', () => {
    const result = calculateDose(5, 'granular', 4);
    expect(result.notFoliar).toBe(true);
    expect(result.flOz).toBe(0);
    expect(result.bestDisplay).toBe('N/A');
  });
});
