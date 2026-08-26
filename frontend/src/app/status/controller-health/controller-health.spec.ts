/** The four situations, and the two-controller warning: FR-009, FR-012, FR-013. */

import { Component, signal } from '@angular/core';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import type { ControllerHealthDto, Liveness } from '../../core/api.types';
import { ControllerHealth } from './controller-health';

function health(overrides: Partial<ControllerHealthDto> = {}): ControllerHealthDto {
  return {
    liveness: 'live',
    state_is_current: true,
    last_seen_at: '2026-01-16T01:00:00Z',
    age_seconds: 2,
    started_at: '2026-01-15T22:00:00Z',
    degraded: false,
    driver_kind: 'gpio',
    tolerance_seconds: 30,
    multiple_controllers_suspected: false,
    ...overrides,
  };
}

/** Signal-held, because the app is zoneless: a plain property would never
 *  re-render and every assertion after the first would be stale. */
@Component({
  imports: [ControllerHealth],
  template: `<dtc-controller-health [health]="health()" />`,
})
class Host {
  readonly health = signal<ControllerHealthDto>(health());
}

describe('ControllerHealth', () => {
  let fixture: ComponentFixture<Host>;

  beforeEach(async () => {
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({ imports: [Host] }).compileComponents();
    fixture = TestBed.createComponent(Host);
  });

  function render(dto: ControllerHealthDto): HTMLElement {
    fixture.componentInstance.health.set(dto);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  const SITUATIONS: Array<[Liveness, Partial<ControllerHealthDto>]> = [
    ['live', { state_is_current: true }],
    ['live_degraded', { state_is_current: true, degraded: true }],
    ['stale', { state_is_current: false, age_seconds: 3600 }],
    ['never_seen', { state_is_current: false, age_seconds: null, last_seen_at: null }],
  ];

  it('distinguishes the four situations with distinct text', () => {
    const texts = SITUATIONS.map(([liveness, extra]) =>
      (render(health({ liveness, ...extra })).textContent ?? '').replace(/\s+/g, ' '),
    );
    expect(new Set(texts).size).toBe(4);
  });

  it('marks the situation in the markup', () => {
    for (const [liveness, extra] of SITUATIONS) {
      const element = render(health({ liveness, ...extra }));
      expect(
        element.querySelector('[data-liveness]')?.getAttribute('data-liveness'),
      ).toBe(liveness);
    }
  });

  it('separates "never started" from "stopped answering"', () => {
    const never = render(
      health({ liveness: 'never_seen', state_is_current: false, last_seen_at: null }),
    ).textContent ?? '';
    const stale = render(
      health({ liveness: 'stale', state_is_current: false, age_seconds: 3600 }),
    ).textContent ?? '';
    expect(never).toContain('nunca');
    expect(stale).not.toContain('nunca');
    expect(never).not.toBe(stale);
  });

  it('orients on what to check in every anomalous situation', () => {
    for (const liveness of ['live_degraded', 'stale', 'never_seen'] as Liveness[]) {
      const element = render(
        health({ liveness, state_is_current: liveness === 'live_degraded' }),
      );
      expect(element.querySelector('.check')).not.toBeNull();
      expect((element.querySelector('.check')?.textContent ?? '').length).toBeGreaterThan(10);
    }
  });

  it('offers nothing to check when everything is normal', () => {
    expect(render(health({ liveness: 'live' })).querySelector('.check')).toBeNull();
  });

  /** FR-009: the warning appears whenever the state is not current, and says
   *  what that implies for the numbers on screen. */
  it('warns visibly that the state is not current, and says what that means', () => {
    for (const liveness of ['stale', 'never_seen'] as Liveness[]) {
      const element = render(health({ liveness, state_is_current: false }));
      const warning = element.querySelector('.warning');
      expect(warning).not.toBeNull();
      const text = warning?.textContent ?? '';
      expect(text).toContain('no es actual');
      expect(text).toContain('último dato conocido');
      expect(text).toContain('potencia');
    }
  });

  it('does not warn when the state is current, degraded included', () => {
    expect(render(health({ liveness: 'live' })).querySelector('.warning')).toBeNull();
    expect(
      render(health({ liveness: 'live_degraded', degraded: true, state_is_current: true }))
        .querySelector('.warning'),
    ).toBeNull();
  });

  it('says a degraded controller is still running its plan', () => {
    const text =
      render(health({ liveness: 'live_degraded', degraded: true })).textContent ?? '';
    expect(text).toContain('Sigue ejecutando su plan');
  });

  it('shows the age from the API', () => {
    expect(render(health({ age_seconds: 120 })).textContent).toContain('hace 2 min');
  });

  it('says whether the controller started with real or simulated outputs', () => {
    expect(render(health({ driver_kind: 'gpio' })).textContent).toContain('reales');
    expect(render(health({ driver_kind: 'simulated' })).textContent).toContain('simuladas');
  });

  /** FR-013: prominent, with the reason, not a discreet note. */
  describe('the two-controller warning', () => {
    it('appears only when the API suspects it', () => {
      expect(
        render(health({ multiple_controllers_suspected: false })).querySelector(
          '[role="alert"]',
        ),
      ).toBeNull();
      expect(
        render(health({ multiple_controllers_suspected: true })).querySelector(
          '[role="alert"]',
        ),
      ).not.toBeNull();
    });

    it('explains the electrical risk rather than just flagging it', () => {
      const text =
        render(health({ multiple_controllers_suspected: true })).textContent ?? '';
      expect(text).toContain('riesgo eléctrico');
      expect(text).toContain('mismos relés');
    });

    it('tells the operator what to check', () => {
      const text =
        render(health({ multiple_controllers_suspected: true })).textContent ?? '';
      expect(text).toContain('despliegue');
    });

    it('is announced to assistive technology', () => {
      const banner = render(
        health({ multiple_controllers_suspected: true }),
      ).querySelector('[role="alert"]');
      expect(banner).not.toBeNull();
    });

    it('shows up even when the controller looks healthy', () => {
      const element = render(
        health({ liveness: 'live', state_is_current: true, multiple_controllers_suspected: true }),
      );
      expect(element.querySelector('[role="alert"]')).not.toBeNull();
    });
  });
});
