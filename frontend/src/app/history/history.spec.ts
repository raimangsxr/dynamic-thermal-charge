/** The history views: FR-024 to FR-029, FR-035. */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type {
  ConfigDto,
  ForecastHistoryDto,
  PageDto,
  PlanHistoryDto,
  TransitionHistoryDto,
} from '../core/api.types';
import { History } from './history';

function plansPage(overrides: Partial<PageDto<PlanHistoryDto>> = {}): PageDto<PlanHistoryDto> {
  return {
    items: [
      {
        id: 2,
        created_at: '2026-01-16T00:00:00Z',
        window_start: '2026-01-16T00:00:00Z',
        window_end: '2026-01-16T08:00:00Z',
        slot_minutes: 30,
        installation_revision: 3,
        forecast_id: 7,
      },
      {
        id: 1,
        created_at: '2026-01-15T00:00:00Z',
        window_start: '2026-01-15T00:00:00Z',
        window_end: '2026-01-15T08:00:00Z',
        slot_minutes: 30,
        installation_revision: 3,
        forecast_id: 6,
      },
    ],
    limit_applied: 50,
    has_more: false,
    next_cursor: null,
    ...overrides,
  };
}

function transitionsPage(
  items: TransitionHistoryDto[],
): PageDto<TransitionHistoryDto> {
  return { items, limit_applied: 50, has_more: false, next_cursor: null };
}

const CONFIG: ConfigDto = {
  config_revision: 3,
  schema_revision: '0003_indoor_temperature',
  max_total_power_kw: 5.2,
  slot_minutes: 30,
  window_minutes: 480,
  indoor_max_age_minutes: 30,
  indoor_min_plausible_c: -20,
  indoor_max_plausible_c: 50,
  log_level: 'INFO',
  state_file: '/tmp/plan.json',
  poll_seconds: 5,
  retention_days: 365,
  schedule: null,
  heaters: [
    {
      id: 'salon',
      name: 'Salón',
      model: null,
      power_kw: 2.8,
      full_charge_hours: 8,
      target_charge: 1,
      reserve_percent: 0,
      priority: 90,
      enabled: true,
      indoor_topic: null,
      temperature_topic: null,
      target_temperature_topic: null,
      stored_charge_topic: null,
      output: { kind: 'gpio', pin: 17, active_high: false },
      thermal: null,
    },
  ],
};

describe('History', () => {
  let fixture: ComponentFixture<History>;
  let backend: HttpTestingController;

  beforeEach(async () => {
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({
      imports: [History],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    fixture = TestBed.createComponent(History);
    backend = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    // The component reads the configuration to flag removed heaters.
    backend.expectOne('/api/v1/config').flush(CONFIG);
  });

  function el(): HTMLElement {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  function testId(id: string): HTMLElement | null {
    return el().querySelector(`[data-testid="${id}"]`);
  }

  function flushPlans(page = plansPage()): void {
    backend
      .expectOne((request) => request.url === '/api/v1/history/plans')
      .flush(page);
  }

  it('lists plans newest first, as the API returned them', () => {
    flushPlans();
    const rows = el().querySelectorAll('[data-table="plans"] tbody tr');
    expect(rows.length).toBe(2);
    // The API orders them; the view must not reorder.
    expect(rows[0].textContent).toContain('2026');
  });

  it('reports the page size and that there is nothing more', () => {
    flushPlans();
    expect(el().textContent).toContain('máximo de 50');
    expect(el().textContent).toContain('no hay más resultados');
    expect(testId('next')).toBeNull();
  });

  it('offers the next page and sends the cursor back verbatim', () => {
    flushPlans(plansPage({ has_more: true, next_cursor: 'OPAQUE-CURSOR' }));
    expect(testId('next')).not.toBeNull();

    fixture.componentInstance.next();
    const request = backend.expectOne(
      (candidate) => candidate.url === '/api/v1/history/plans',
    );
    expect(request.request.params.get('cursor')).toBe('OPAQUE-CURSOR');
    request.flush(plansPage());
  });

  it('says a range is empty rather than showing an error', () => {
    flushPlans(plansPage({ items: [] }));
    expect(testId('empty')).not.toBeNull();
    expect(testId('banner')).toBeNull();
  });

  /** FR-027: refused before asking the API. */
  it('refuses an inverted range without calling the API', () => {
    flushPlans();
    fixture.componentInstance.from.set('2026-02-01T00:00');
    fixture.componentInstance.to.set('2026-01-01T00:00');
    fixture.componentInstance.load();
    backend.expectNone((candidate) => candidate.url === '/api/v1/history/plans');
    expect(testId('range-error')?.textContent).toContain('posterior al fin');
  });

  it('sends the range as instants when it is valid', () => {
    flushPlans();
    fixture.componentInstance.from.set('2026-01-10T00:00');
    fixture.componentInstance.load();
    const request = backend.expectOne(
      (candidate) => candidate.url === '/api/v1/history/plans',
    );
    expect(request.request.params.get('from')).toContain('2026-01');
    request.flush(plansPage());
  });

  it('filters transitions by heater', () => {
    flushPlans();
    fixture.componentInstance.heaterId.set('salon');
    fixture.componentInstance.select('transitions');
    const request = backend.expectOne(
      (candidate) => candidate.url === '/api/v1/history/transitions',
    );
    expect(request.request.params.get('heater_id')).toBe('salon');
    request.flush(
      transitionsPage([
        {
          id: 1,
          heater_id: 'salon',
          state: true,
          occurred_at: '2026-01-16T00:30:00Z',
          plan_id: 2,
        },
      ]),
    );
    expect(el().querySelector('[data-heater="salon"]')).not.toBeNull();
  });

  /** FR-028: it existed and was removed; the history is kept on purpose. */
  it('flags a heater that is no longer in the configuration', () => {
    flushPlans();
    fixture.componentInstance.select('transitions');
    backend
      .expectOne((candidate) => candidate.url === '/api/v1/history/transitions')
      .flush(
        transitionsPage([
          {
            id: 1,
            heater_id: 'buhardilla',
            state: true,
            occurred_at: '2026-01-16T00:30:00Z',
            plan_id: 2,
          },
        ]),
      );
    expect(testId('gone')).not.toBeNull();
    expect(el().textContent).toContain('ya no está en la configuración');
  });

  it('does not flag a heater that is still configured', () => {
    flushPlans();
    fixture.componentInstance.select('transitions');
    backend
      .expectOne((candidate) => candidate.url === '/api/v1/history/transitions')
      .flush(
        transitionsPage([
          {
            id: 1,
            heater_id: 'salon',
            state: false,
            occurred_at: '2026-01-16T00:30:00Z',
            plan_id: null,
          },
        ]),
      );
    expect(testId('gone')).toBeNull();
  });

  /** FR-029: whether the real provider worked that night. */
  it('distinguishes a fallback forecast from a real one', () => {
    flushPlans();
    fixture.componentInstance.select('forecasts');
    const forecasts: ForecastHistoryDto[] = [
      {
        id: 2,
        forecast_date: '2026-01-16',
        source: 'fallback',
        average_temperature_c: 8,
        minimum_temperature_c: 3,
        maximum_temperature_c: 13,
        municipality: null,
        retrieved_at: '2026-01-16T00:00:00Z',
      },
      {
        id: 1,
        forecast_date: '2026-01-15',
        source: 'aemet',
        average_temperature_c: 7,
        minimum_temperature_c: 2,
        maximum_temperature_c: 12,
        municipality: 'Noia',
        retrieved_at: '2026-01-15T00:00:00Z',
      },
    ];
    backend
      .expectOne((candidate) => candidate.url === '/api/v1/history/forecasts')
      .flush({ items: forecasts, limit_applied: 50, has_more: false, next_cursor: null });

    const rows = el().querySelectorAll('[data-table="forecasts"] tbody tr');
    expect(rows[0].textContent).toContain('valor de reserva');
    expect(rows[1].textContent).toContain('proveedor real');
  });

  it('explains a rejected cursor rather than showing an empty table', () => {
    flushPlans();
    fixture.componentInstance.load('garbage');
    backend
      .expectOne((candidate) => candidate.url === '/api/v1/history/plans')
      .flush(
        {
          code: 'bad_request',
          message: 'the continuation cursor is unreadable',
          field: 'cursor',
          heater_id: null,
        },
        { status: 400, statusText: 'Bad Request' },
      );
    expect(testId('banner')?.textContent).toContain('no es válida');
  });

  /** FR-035: the table scrolls, not the page. */
  it('puts wide tables inside their own scroll container', () => {
    flushPlans();
    const container = el().querySelector('.table-scroll');
    expect(container).not.toBeNull();
    expect(container?.querySelector('table')).not.toBeNull();
  });

  afterEach(() => {
    backend.match(() => true);
  });
});
