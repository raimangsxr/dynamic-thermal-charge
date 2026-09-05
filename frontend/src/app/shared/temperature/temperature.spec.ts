import { describe, expect, it } from 'vitest';

import { formatTemperature, truncateTemperature } from './temperature';

describe('temperature formatting', () => {
  it('truncates positive and negative values to one decimal', () => {
    expect(truncateTemperature(12.39)).toBe(12.3);
    expect(truncateTemperature(-2.39)).toBe(-2.3);
  });

  it('keeps one decimal in the displayed value', () => {
    expect(formatTemperature(12)).toBe('12.0');
    expect(formatTemperature(12.39)).toBe('12.3');
    expect(formatTemperature(null)).toBe('sin dato');
  });
});
