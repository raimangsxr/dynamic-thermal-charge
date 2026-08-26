/**
 * The three-state output: FR-011, FR-016, SC-002.
 *
 * The assertion that matters most is the last one: no input may ever produce a
 * confirmed state when the controller is not visible.
 */

import { describe, expect, it } from 'vitest';

import type { HeaterStateDto } from './api.types';
import {
  isConfirmed,
  outputGlyph,
  outputLabel,
  outputStateOf,
} from './output-state';

function heater(
  overrides: Partial<HeaterStateDto> = {},
): HeaterStateDto {
  return {
    id: 'salon',
    name: 'Salón',
    enabled: true,
    power_w: 2800,
    output_on: false,
    last_known_output_on: false,
    changed_at: null,
    ...overrides,
  };
}

describe('outputStateOf', () => {
  it('reports a confirmed on state', () => {
    const state = outputStateOf(heater({ output_on: true, last_known_output_on: true }));
    expect(state.kind).toBe('on');
    expect(isConfirmed(state)).toBe(true);
  });

  it('reports a confirmed off state', () => {
    const state = outputStateOf(heater({ output_on: false }));
    expect(state.kind).toBe('off');
    expect(isConfirmed(state)).toBe(true);
  });

  it('treats a null output as unknown, not as off', () => {
    const state = outputStateOf(heater({ output_on: null }));
    expect(state.kind).toBe('unknown');
    expect(isConfirmed(state)).toBe(false);
  });

  it('keeps the last known value when unknown, so it can be shown as past', () => {
    const state = outputStateOf(
      heater({
        output_on: null,
        last_known_output_on: true,
        changed_at: '2026-01-16T01:00:00Z',
      }),
    );
    expect(state).toEqual({
      kind: 'unknown',
      lastKnown: true,
      changedAt: new Date('2026-01-16T01:00:00Z'),
    });
  });

  it('keeps a last known off value too', () => {
    const state = outputStateOf(
      heater({ output_on: null, last_known_output_on: false }),
    );
    expect(state).toMatchObject({ kind: 'unknown', lastKnown: false });
  });

  it('tolerates a missing change instant when unknown', () => {
    const state = outputStateOf(heater({ output_on: null, changed_at: null }));
    expect(state).toMatchObject({ kind: 'unknown', changedAt: null });
  });

  /**
   * The assertion this whole file exists for.
   *
   * If it ever fails, the panel is claiming a state it cannot know, and every
   * downstream view inherits the lie.
   */
  it('NEVER produces a confirmed state from a null output', () => {
    const inputs: HeaterStateDto[] = [
      heater({ output_on: null, last_known_output_on: true }),
      heater({ output_on: null, last_known_output_on: false }),
      heater({ output_on: null, changed_at: '2026-01-16T01:00:00Z' }),
      heater({ output_on: null, enabled: false }),
      heater({ output_on: null, power_w: 0 }),
    ];
    for (const input of inputs) {
      const state = outputStateOf(input);
      expect(state.kind).toBe('unknown');
      expect(isConfirmed(state)).toBe(false);
    }
  });
});

describe('presentation without relying on colour (FR-036)', () => {
  const states = [
    outputStateOf(heater({ output_on: true })),
    outputStateOf(heater({ output_on: false })),
    outputStateOf(heater({ output_on: null })),
  ];

  it('gives every state a distinct label', () => {
    const labels = states.map(outputLabel);
    expect(new Set(labels).size).toBe(3);
  });

  it('gives every state a distinct glyph', () => {
    const glyphs = states.map(outputGlyph);
    expect(new Set(glyphs).size).toBe(3);
  });

  it('says explicitly that an unknown state is unconfirmed', () => {
    expect(outputLabel(outputStateOf(heater({ output_on: null })))).toContain(
      'Sin confirmar',
    );
  });

  it('mentions the last known value when it was on, so it reads as past', () => {
    const label = outputLabel(
      outputStateOf(heater({ output_on: null, last_known_output_on: true })),
    );
    expect(label).toContain('estaba');
  });
});
