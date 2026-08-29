/**
 * The status view: FR-007 to FR-015, FR-030, SC-002.
 *
 * The assertions that matter are the negative ones: with no proof, no heater is
 * shown as charging and no power figure appears.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Liveness, StatusDto } from '../core/api.types';
import { Status } from './status';

function statusDto(overrides: Partial<StatusDto> = {}): StatusDto {
  return {
    observed_at: '2026-01-16T01:00:00Z',
    controller: {
      liveness: 'live',
      state_is_current: true,
      last_seen_at: '2026-01-16T01:00:00Z',
      age_seconds: 1,
      started_at: '2026-01-15T22:00:00Z',
      degraded: false,
      driver_kind: 'gpio',
      tolerance_seconds: 30,
      multiple_controllers_suspected: false,
    },
    power: { instant_w: 2800, limit_w: 5200, percent_of_limit: 53.8 },
    heaters: [
      {
        id: 'salon',
        name: 'Salón',
        enabled: true,
        power_w: 2800,
        output_on: true,
        last_known_output_on: true,
        changed_at: '2026-01-16T00:30:00Z',
      },
      {
        id: 'entrada',
        name: 'Entrada',
        enabled: true,
        power_w: 2400,
        output_on: false,
        last_known_output_on: false,
        changed_at: null,
      },
    ],
    plan: {
      window_start: '2026-01-16T00:00:00Z',
      window_end: '2026-01-16T08:00:00Z',
      slot_minutes: 30,
      installation_revision: 3,
      created_at: '2026-01-16T00:00:00Z',
      slots: [],
    },
    forecast: {
      date: '2026-01-16',
      source: 'aemet',
      average_temperature_c: 8,
      minimum_temperature_c: 3,
      maximum_temperature_c: 13,
      municipality: 'Noia, A Coruña',
    },
    allocations: [
      {
        heater_id: 'salon',
        requested_minutes: 480,
        allocated_minutes: 480,
        unmet_minutes: 0,
      },
    ],
    ...overrides,
  };
}

/** The state as the API reports it when the controller is not visible. */
function notCurrent(liveness: Liveness = 'stale'): StatusDto {
  const dto = statusDto();
  return {
    ...dto,
    controller: {
      ...dto.controller,
      liveness,
      state_is_current: false,
      age_seconds: liveness === 'never_seen' ? null : 3600,
      last_seen_at: liveness === 'never_seen' ? null : dto.controller.last_seen_at,
    },
    // This is exactly what the API does: no power, and every output_on null.
    power: null,
    heaters: dto.heaters.map((heater) => ({
      ...heater,
      output_on: null,
    })),
  };
}

describe('Status', () => {
  let fixture: ComponentFixture<Status>;
  let backend: HttpTestingController;

  beforeEach(async () => {
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({
      imports: [Status],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    fixture = TestBed.createComponent(Status);
    backend = TestBed.inject(HttpTestingController);
  });

  function load(dto: StatusDto): HTMLElement {
    fixture.detectChanges();
    backend.expectOne('/api/v1/status').flush(dto);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  function fail(status: number, body: Record<string, unknown> | null): HTMLElement {
    fixture.detectChanges();
    backend
      .expectOne('/api/v1/status')
      .flush(body, { status, statusText: 'error' });
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  function testId(root: HTMLElement, id: string): HTMLElement | null {
    return root.querySelector(`[data-testid="${id}"]`);
  }

  /* ---------------------------------------------------------------- current */

  it('shows the power, the plan and the forecast when the state is current', () => {
    const element = load(statusDto());
    expect(testId(element, 'power')?.textContent).toContain('2.8 kW');
    expect(testId(element, 'power')?.textContent).toContain('5.2 kW');
    expect(testId(element, 'plan')).not.toBeNull();
    expect(testId(element, 'forecast')?.textContent).toContain('8');
  });

  it('shows each heater with its confirmed state', () => {
    const element = load(statusDto());
    const salon = element.querySelector('[data-heater="salon"]');
    expect(salon?.textContent).toContain('Cargando');
    const entrada = element.querySelector('[data-heater="entrada"]');
    expect(entrada?.textContent).toContain('En reposo');
  });

  it('reports a fallback forecast as coming from the reserve values', () => {
    const dto = statusDto();
    const element = load({
      ...dto,
      forecast: { ...dto.forecast!, source: 'fallback' },
    });
    expect(testId(element, 'forecast')?.textContent).toContain('valor de reserva');
  });

  /* ------------------------------------------------------------ not current */

  it.each(['stale', 'never_seen'] as Liveness[])(
    'shows NO power figure when the controller is %s',
    (liveness) => {
      const element = load(notCurrent(liveness));
      expect(testId(element, 'power-unavailable')).not.toBeNull();
      const text = testId(element, 'power')?.textContent ?? '';
      expect(text).not.toMatch(/\d+(\.\d+)?\s*kW/);
      expect(text).not.toContain('0 kW');
    },
  );

  it.each(['stale', 'never_seen'] as Liveness[])(
    'presents NO heater as charging when the controller is %s',
    (liveness) => {
      const element = load(notCurrent(liveness));
      for (const item of element.querySelectorAll('[data-heater]')) {
        expect(item.textContent).toContain('Sin confirmar');
        expect(item.textContent).not.toContain('En reposo');
      }
      expect(element.querySelectorAll('[data-state="on"]').length).toBe(0);
      expect(element.querySelectorAll('[data-state="off"]').length).toBe(0);
    },
  );

  it('keeps the last known value visible, labelled as past', () => {
    const element = load(notCurrent('stale'));
    const salon = element.querySelector('[data-heater="salon"]');
    expect(salon?.textContent).toContain('estaba cargando');
    expect(salon?.querySelector('.since')).not.toBeNull();
  });

  it('shows the power when the controller is degraded, because it is still current', () => {
    const dto = statusDto();
    const element = load({
      ...dto,
      controller: {
        ...dto.controller,
        liveness: 'live_degraded',
        degraded: true,
        state_is_current: true,
      },
    });
    expect(testId(element, 'power-unavailable')).toBeNull();
    expect(testId(element, 'power')?.textContent).toContain('kW');
  });

  /* --------------------------------------------------------------- absences */

  it('says explicitly that there is no plan in progress', () => {
    const element = load({ ...statusDto(), plan: null });
    expect(testId(element, 'no-plan')).not.toBeNull();
    expect(testId(element, 'plan')).toBeNull();
  });

  it('says the installation has no heaters instead of showing an empty list', () => {
    const element = load({ ...statusDto(), heaters: [], allocations: [] });
    expect(element.textContent).toContain('ningún acumulador');
  });

  /* ------------------------------------------------------------------ unmet */

  it('shows unmet minutes prominently when there are any', () => {
    const element = load({
      ...statusDto(),
      allocations: [
        {
          heater_id: 'buhardilla',
          requested_minutes: 480,
          allocated_minutes: 120,
          unmet_minutes: 360,
        },
      ],
    });
    const unmet = testId(element, 'unmet');
    expect(unmet).not.toBeNull();
    expect(unmet?.textContent).toContain('buhardilla');
    expect(unmet?.textContent).toContain('6 h');
  });

  it('does not show the deficit banner when everything was served', () => {
    expect(testId(load(statusDto()), 'unmet')).toBeNull();
  });

  /* ------------------------------------------------------- unreachable API  */

  it('explains a database failure without a stack trace', () => {
    const element = fail(503, {
      code: 'store_unavailable',
      message: 'the configuration database is unavailable',
      field: null,
      heater_id: null,
    });
    const failure = testId(element, 'failure');
    expect(failure?.textContent).toContain('no responde');
    expect(element.textContent).not.toContain('Traceback');
  });

  it('says what to do on the device when the schema needs attention', () => {
    const element = fail(503, {
      code: 'schema_unusable',
      message: 'needs migrating',
      field: null,
      heater_id: null,
    });
    const text = testId(element, 'failure')?.textContent ?? '';
    expect(text).toContain('migre la base de datos');
    expect(text).toContain('dispositivo');
    expect(text.toLowerCase()).toContain('no puede');
  });

  /**
   * FR-030: the API stops answering after we already had data. The screen must
   * not empty, and must not keep looking live either.
   */
  it('keeps the last snapshot marked as no longer current when the API falls', () => {
    // First a good read.
    fixture.detectChanges();
    backend.expectOne('/api/v1/status').flush(statusDto());
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Salón');

    // Then the API stops answering.
    fixture.componentInstance.refresh();
    backend
      .expectOne('/api/v1/status')
      .error(new ProgressEvent('error'), { status: 0, statusText: 'unknown' });
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    // The data is still there...
    expect(element.textContent).toContain('Salón');
    // ...and it is explicitly marked as no longer current.
    const failure = testId(element, 'failure');
    expect(failure).not.toBeNull();
    expect(failure?.textContent).toContain('ya no es actual');
    expect(failure?.textContent).toContain('No se puede contactar');
  });

  it('does not claim staleness before it has ever loaded anything', () => {
    const element = fail(0, null);
    expect(testId(element, 'failure')?.textContent).not.toContain('debajo');
  });

  afterEach(() => {
    // Any extra polling request is fine; we only assert on the ones we drove.
    backend.match(() => true);
  });
});
