/**
 * The output of one heater, as THREE appearances and not two.
 *
 * On, off and unconfirmed must be distinguishable, and distinguishable WITHOUT
 * relying on colour (FR-036): a panel that reports on an electrical installation
 * cannot exclude someone who does not tell green from grey. So each state gets a
 * glyph and a word, not just a hue.
 *
 * The unconfirmed appearance carries the last known value labelled as PAST, with
 * the instant it changed. Never with the appearance of a confirmed state.
 */

import { Component, computed, input } from '@angular/core';

import { formatAge, formatInstant } from '../age/age';
import {
  type OutputState,
  outputGlyph,
  outputLabel,
} from '../../core/output-state';

@Component({
  selector: 'dtc-output-indicator',
  template: `
    <span class="indicator" [class]="cssClass()" [attr.data-state]="state().kind">
      <span class="glyph" aria-hidden="true">{{ glyph() }}</span>
      <span class="label">{{ label() }}</span>
      @if (state().kind === 'unknown' && changedAt()) {
        <span class="since">último cambio: {{ changedAt() }}</span>
      }
    </span>
  `,
  styles: `
    .indicator {
      display: inline-flex; align-items: baseline; gap: 0.4rem;
      font-variant-numeric: tabular-nums;
    }
    .glyph { font-size: 1.1em; }
    .label { font-weight: 600; }
    .since { font-size: 0.8em; color: #555; }
    /* Colour is an addition, never the only difference. */
    .on { color: #0a6b2d; }
    .off { color: #444; }
    .unknown { color: #7a4a00; font-style: italic; }
    .unknown .label::after { content: ' (sin confirmar)'; font-weight: 400; }
  `,
})
export class OutputIndicator {
  readonly state = input.required<OutputState>();

  readonly glyph = computed(() => outputGlyph(this.state()));
  readonly label = computed(() => outputLabel(this.state()));
  readonly cssClass = computed(() => this.state().kind);

  readonly changedAt = computed(() => {
    const current = this.state();
    if (current.kind !== 'unknown' || current.changedAt === null) {
      return '';
    }
    return formatInstant(current.changedAt.toISOString());
  });
}
