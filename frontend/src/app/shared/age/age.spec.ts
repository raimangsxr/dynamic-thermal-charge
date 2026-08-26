/** Ages come from the API, never from the local clock: FR-016. */

import { describe, expect, it, vi } from 'vitest';

import { formatAge, formatInstant } from './age';

describe('formatAge', () => {
  it('reports nothing to age as a dash', () => {
    expect(formatAge(null)).toBe('—');
  });

  it.each([
    [0, 'hace 0 s'],
    [2, 'hace 2 s'],
    [59, 'hace 59 s'],
    [60, 'hace 1 min'],
    [3599, 'hace 59 min'],
    [3600, 'hace 1 h'],
    [86_399, 'hace 23 h'],
    [86_400, 'hace 1 d'],
  ])('formats %i seconds as %s', (seconds, expected) => {
    expect(formatAge(seconds)).toBe(expected);
  });

  it('never prints a negative age', () => {
    expect(formatAge(-30)).toBe('instante futuro');
    expect(formatAge(-3600)).not.toContain('-');
  });

  /**
   * The reason this function takes a number instead of computing one.
   *
   * The browser clock is moved hours in both directions and the reported age
   * must not move at all: it comes from the API.
   */
  it('is unaffected by a browser clock that disagrees with the device', () => {
    const fromApi = 12;
    const expected = formatAge(fromApi);

    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date('2030-01-01T00:00:00Z')); // years ahead
      expect(formatAge(fromApi)).toBe(expected);
      vi.setSystemTime(new Date('2000-01-01T00:00:00Z')); // years behind
      expect(formatAge(fromApi)).toBe(expected);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('formatInstant', () => {
  it('reports a missing instant as a dash', () => {
    expect(formatInstant(null)).toBe('—');
  });

  it('reports an unparseable instant as a dash rather than "Invalid Date"', () => {
    expect(formatInstant('not-a-date')).toBe('—');
  });

  it('formats a real instant', () => {
    expect(formatInstant('2026-01-16T01:00:00Z')).not.toBe('—');
  });
});
