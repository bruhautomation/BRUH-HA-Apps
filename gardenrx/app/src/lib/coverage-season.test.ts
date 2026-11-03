import { describe, expect, it } from 'vitest';

import { needsCoverageNow } from '@/lib/coverage-season';

describe('needsCoverageNow', () => {
  it('is false when every variety is dormant', () => {
    expect(needsCoverageNow([{ stage: 'dormant' }, { stage: 'dormant' }])).toBe(false);
  });

  it('is false once every variety is past harvest', () => {
    expect(needsCoverageNow([{ stage: 'post_harvest' }, { stage: 'dormant' }])).toBe(false);
  });

  it('is true while any variety is in an active stage', () => {
    expect(needsCoverageNow([{ stage: 'dormant' }, { stage: 'fruit_set' }])).toBe(true);
    expect(needsCoverageNow([{ stage: 'harvest' }])).toBe(true);
  });

  it('is true for a crop with no varieties, since nothing says it is resting', () => {
    expect(needsCoverageNow([])).toBe(true);
  });
});
