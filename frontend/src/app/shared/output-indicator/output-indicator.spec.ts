/** Three appearances, distinguishable without colour: FR-011, FR-036. */

import { Component, signal } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import type { OutputState } from '../../core/output-state';
import { OutputIndicator } from './output-indicator';

/**
 * The host holds the state in a SIGNAL, not a plain property.
 *
 * This app is zoneless: changing a plain property does not mark the component
 * dirty, so `detectChanges()` would render the first value for ever and every
 * assertion after the first would silently compare against stale markup.
 */
@Component({
  imports: [OutputIndicator],
  template: `<dtc-output-indicator [state]="state()" />`,
})
class Host {
  readonly state = signal<OutputState>({ kind: 'off' });
}

describe('OutputIndicator', () => {
  let fixture: ComponentFixture<Host>;

  beforeEach(async () => {
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({ imports: [Host] }).compileComponents();
    fixture = TestBed.createComponent(Host);
  });

  function render(state: OutputState): HTMLElement {
    fixture.componentInstance.state.set(state);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  const on: OutputState = { kind: 'on' };
  const off: OutputState = { kind: 'off' };
  const unknownWasOn: OutputState = {
    kind: 'unknown',
    lastKnown: true,
    changedAt: new Date('2026-01-16T01:00:00Z'),
  };
  const unknownWasOff: OutputState = {
    kind: 'unknown',
    lastKnown: false,
    changedAt: null,
  };

  it('marks the state in the markup so it can be styled and asserted', () => {
    expect(render(on).querySelector('[data-state]')?.getAttribute('data-state')).toBe('on');
    expect(render(off).querySelector('[data-state]')?.getAttribute('data-state')).toBe('off');
    expect(
      render(unknownWasOn).querySelector('[data-state]')?.getAttribute('data-state'),
    ).toBe('unknown');
  });

  /**
   * FR-036. Colour is stripped from the comparison on purpose: what remains --
   * the text and the glyph -- must already be enough to tell the three apart.
   */
  it('distinguishes the three states without relying on colour', () => {
    const texts = [on, off, unknownWasOn].map(
      (state) => render(state).textContent?.replace(/\s+/g, ' ').trim() ?? '',
    );
    expect(new Set(texts).size).toBe(3);
    for (const text of texts) {
      expect(text.length).toBeGreaterThan(0);
    }
  });

  it('gives each state a distinct glyph', () => {
    const glyphs = [on, off, unknownWasOn].map(
      (state) => render(state).querySelector('.glyph')?.textContent?.trim() ?? '',
    );
    expect(new Set(glyphs).size).toBe(3);
  });

  it('says explicitly that an unconfirmed state is unconfirmed', () => {
    expect(render(unknownWasOn).textContent).toContain('Sin confirmar');
  });

  it('shows the last known value as past when it was on', () => {
    const text = render(unknownWasOn).textContent ?? '';
    expect(text).toContain('estaba cargando');
  });

  it('shows the instant of the last change when it knows it', () => {
    expect(render(unknownWasOn).querySelector('.since')).not.toBeNull();
  });

  it('omits the instant when there is none, instead of inventing one', () => {
    expect(render(unknownWasOff).querySelector('.since')).toBeNull();
  });

  it('never renders an unconfirmed state with the confirmed appearance', () => {
    const confirmed = [render(on), render(off)].map(
      (element) => element.querySelector('[data-state]')?.className ?? '',
    );
    const unconfirmed =
      render(unknownWasOn).querySelector('[data-state]')?.className ?? '';
    for (const className of confirmed) {
      expect(className).not.toBe(unconfirmed);
    }
  });

  it('hides the glyph from assistive technology, which reads the label instead', () => {
    const glyph = render(on).querySelector('.glyph');
    expect(glyph?.getAttribute('aria-hidden')).toBe('true');
  });
});
