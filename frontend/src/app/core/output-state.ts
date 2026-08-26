/**
 * The state of a heater output, as THREE values and not a boolean.
 *
 * This is the smallest file in the project and the one the honesty of the whole
 * panel rests on.
 *
 * The API returns `output_on` as `true`, `false` or `null`, and `null` means "I
 * have no proof either way" -- not "it is off". A boolean here would collapse
 * `null` into `false` on the very first conversion, and from that point the
 * information would be gone with nothing to warn anybody: the screen would show
 * a heater as confidently off when it might be drawing 2.8 kW.
 *
 * With three variants the type checker FORCES a decision about the third case,
 * everywhere it is rendered. That obligation is the mechanism. A comment saying
 * "remember to check state_is_current" is not.
 */

import type { HeaterStateDto } from './api.types';

export type OutputState =
  /** On, and confirmed by a live controller. */
  | { readonly kind: 'on' }
  /** Off, and confirmed by a live controller. */
  | { readonly kind: 'off' }
  /**
   * Nobody can confirm the current state. Carries the last recorded value, which
   * must be presented as PAST -- never with the appearance of a confirmed state.
   */
  | {
      readonly kind: 'unknown';
      readonly lastKnown: boolean;
      readonly changedAt: Date | null;
    };

/** Derive the state from what the API returned for one heater. */
export function outputStateOf(heater: HeaterStateDto): OutputState {
  if (heater.output_on === null) {
    return {
      kind: 'unknown',
      lastKnown: heater.last_known_output_on,
      changedAt: heater.changed_at === null ? null : new Date(heater.changed_at),
    };
  }
  return heater.output_on ? { kind: 'on' } : { kind: 'off' };
}

/**
 * Whether this state may be presented as what is happening right now.
 *
 * Deliberately NOT a `isOn()` helper returning a boolean: that would be the same
 * collapse this type exists to prevent, one function call further down.
 */
export function isConfirmed(state: OutputState): boolean {
  return state.kind !== 'unknown';
}

/** Text for the state, distinguishable without relying on colour (FR-036). */
export function outputLabel(state: OutputState): string {
  switch (state.kind) {
    case 'on':
      return 'Cargando';
    case 'off':
      return 'En reposo';
    case 'unknown':
      return state.lastKnown ? 'Sin confirmar (estaba cargando)' : 'Sin confirmar';
  }
}

/** A shape, so the three states differ without relying on colour (FR-036). */
export function outputGlyph(state: OutputState): string {
  switch (state.kind) {
    case 'on':
      return '▲'; // filled triangle: energy flowing
    case 'off':
      return '●'; // filled circle: at rest
    case 'unknown':
      return '?'; // no proof either way
  }
}
