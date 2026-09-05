import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatDialog } from '@angular/material/dialog';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PlanningDto, PlanningPreviewDto } from '../core/api.types';
import { Planning } from './planning';

const chartState = vi.hoisted(() => ({ configs: [] as Array<{ type: string; data: { labels: unknown[]; datasets: Array<{ label?: string; data?: unknown[] }> } }> }));

vi.mock('chart.js/auto', () => ({
  Chart: class {
    constructor(_target: unknown, config: { type: string; data: { labels: unknown[]; datasets: Array<{ label?: string }> } }) {
      chartState.configs.push(config);
    }

    destroy(): void {}
  },
}));

const PLANNING: PlanningDto = {
  observed_at: '2026-01-16T01:00:00Z',
  max_total_power_w: 5200,
  max_heating_power_w: 4200,
  base_load_w: 600,
  forecast: {
    date: '2026-01-16', source: 'aemet', average_temperature_c: 6,
    minimum_temperature_c: 3, maximum_temperature_c: 10, municipality: 'Madrid',
    hourly_points: [
      { timestamp: '2026-01-16T00:00:00Z', temperature_c: 3, interpolated: false },
      { timestamp: '2026-01-16T01:00:00Z', temperature_c: 4, interpolated: false },
    ],
  },
  plan: {
    window_start: '2026-01-16T00:00:00Z', window_end: '2026-01-16T01:00:00Z',
    slot_minutes: 30, installation_revision: 4, created_at: '2026-01-15T20:00:00Z',
    slots: [
      { start: '2026-01-16T00:00:00Z', end: '2026-01-16T00:30:00Z', heater_ids: ['salon'], total_power_w: 2800, temperature_c: 3, temperature_interpolated: false, stored_charge_percent_by_heater: { salon: 6.25 } },
      { start: '2026-01-16T00:30:00Z', end: '2026-01-16T01:00:00Z', heater_ids: [], total_power_w: 0, temperature_c: null, temperature_interpolated: true, stored_charge_percent_by_heater: { salon: 4.17 } },
    ],
  },
  horizon_start: '2026-01-16T00:00:00Z', horizon_end: '2026-01-18T00:00:00Z',
  timeline: [
    { start: '2026-01-16T00:00:00Z', end: '2026-01-16T00:30:00Z', heater_ids: ['salon'], total_power_w: 2800, temperature_c: 3, temperature_interpolated: false, charge_minutes_by_heater: { salon: 30 }, stored_charge_percent_by_heater: { salon: 6.25 }, estimated_temperature_c_by_heater: { salon: 18.5 } },
    { start: '2026-01-16T00:30:00Z', end: '2026-01-16T01:00:00Z', heater_ids: [], total_power_w: 0, temperature_c: 3.5, temperature_interpolated: false, charge_minutes_by_heater: { salon: 20 }, stored_charge_percent_by_heater: { salon: 4.17 }, estimated_temperature_c_by_heater: { salon: 18.2 } },
  ],
  allocations: [{ heater_id: 'salon', requested_minutes: 60, allocated_minutes: 30, unmet_minutes: 30 }],
  heaters: [{ id: 'salon', name: 'Salón', power_w: 2800, priority: 90, enabled: true }],
  absence_reason: null,
  forecast_status: 'success',
  forecast_last_attempt_at: '2026-01-16T01:00:00Z',
  forecast_last_error: null,
  forecast_next_run_at: '2026-01-16T04:00:00Z',
};

describe('Planning', () => {
  let fixture: ComponentFixture<Planning>;
  let backend: HttpTestingController;

  beforeEach(async () => {
    TestBed.resetTestingModule();
    sessionStorage.removeItem('dtc.planning.preview-job');
    await TestBed.configureTestingModule({
      imports: [Planning],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    chartState.configs.length = 0;
    fixture = TestBed.createComponent(Planning);
    backend = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  it('loads the protected planning projection and renders summaries and all visual levels', () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('[data-testid="forecast-summary"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="planning-summary"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="forecast-summary"]')?.textContent).toContain('Registros horarios');
    expect(element.querySelector('[data-testid="forecast-summary"]')?.textContent).toContain('Última consulta');
    expect(element.querySelector('[data-testid="forecast-summary"]')?.textContent).toContain('16 ene 2026');
    expect(element.querySelector('[data-testid="forecast-detail-button"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="planning-detail-button"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="temperature-card"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="heater-card"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="aggregate-card"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="cumulative-card"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="temperature-title"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="heater-title"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="aggregate-title"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="cumulative-title"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="planning-table"]')).toBeNull();
    expect(element.querySelector('[data-testid="planning-deficit"]')?.textContent).toContain('Carga no atendida');
    expect(element.querySelector('[data-testid="forecast-table"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="forecast-chart-card"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="forecast-next-run"]')?.textContent).toContain('Próxima consulta automática');
    expect(element.querySelector('section.planning')).toBeNull();
    expect(element.querySelectorAll('[data-testid$="-card"]')).toHaveLength(5);
  });

  it('creates all data-backed charts when the initial response arrives after AfterViewInit', async () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    await fixture.whenStable();

    expect(chartState.configs).toHaveLength(5);
    expect(fixture.componentInstance.slotLabel(PLANNING.plan!.slots[0])).toBe(
      fixture.componentInstance.dateTime(PLANNING.plan!.slots[0].start),
    );
    expect(fixture.componentInstance.slotLabel(PLANNING.plan!.slots[0])).not.toContain('–');
    expect(chartState.configs[1].data.labels).toEqual([
      fixture.componentInstance.dateTime(PLANNING.timeline[0].start),
      '',
    ]);
    expect(chartState.configs[2].type).toBe('line');
    expect(chartState.configs[2].data.datasets[0].data?.[0]).toBe(2.8);
    expect(chartState.configs[4].data.datasets[0].data).toEqual([6.25, 4.17]);
  });

  it('opens forecast and planning details in accessible dialogs with explicit close actions', async () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    element.querySelector<HTMLButtonElement>('[data-testid="forecast-detail-button"]')?.click();
    await fixture.whenStable();
    expect(document.querySelector('mat-dialog-container')).not.toBeNull();
    expect(document.querySelector('mat-dialog-container')?.textContent).toContain('3.0 °C');
    expect(document.querySelector('.cdk-overlay-backdrop')).not.toBeNull();
    expect(document.querySelector('[data-testid="detail-dialog-close"]')).not.toBeNull();
    (document.querySelector<HTMLButtonElement>('[data-testid="detail-dialog-close"]'))?.click();
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(document.querySelector('mat-dialog-container')).toBeNull();

    element.querySelector<HTMLButtonElement>('[data-testid="planning-detail-button"]')?.click();
    await fixture.whenStable();
    expect(document.querySelector('mat-dialog-container')?.textContent).toContain('Detalle de la planificación');
    (document.querySelector<HTMLButtonElement>('[data-testid="detail-dialog-close"]'))?.click();
    await new Promise((resolve) => setTimeout(resolve, 100));
  });

  it('opens both detail dialogs with a wide responsive viewport-bound width', () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    fixture.detectChanges();
    const dialog = TestBed.inject(MatDialog);
    const open = vi.spyOn(dialog, 'open').mockReturnValue({} as never);

    fixture.componentInstance.openForecastDetails();
    fixture.componentInstance.openPlanningDetails();

    expect(open.mock.calls[0][1]).toMatchObject({ width: 'min(92vw, 72rem)' });
    expect(open.mock.calls[1][1]).toMatchObject({ width: 'min(92vw, 72rem)' });
    open.mockRestore();
  });

  it('states explicitly when there is no plan instead of fabricating rows', () => {
    backend.expectOne('/api/v1/planning').flush({
      observed_at: PLANNING.observed_at, max_total_power_w: 5200,
      plan: null, forecast: null, allocations: [], heaters: [],
      absence_reason: 'no_current_or_next_plan',
    });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="planning-empty"]')?.textContent).toContain('No hay un plan');
    expect((fixture.nativeElement as HTMLElement).querySelector('table')).toBeNull();
  });

  it('shows the reserve dropping when the next interval has no charge', () => {
    expect(fixture.componentInstance.cumulativeMinutes(PLANNING, 'salon', 0)).toBe(30);
    expect(fixture.componentInstance.cumulativeMinutes(PLANNING, 'salon', 1)).toBe(20);
    expect(fixture.componentInstance.storedChargePercent(PLANNING, 'salon', 0)).toBe(6.25);
    expect(fixture.componentInstance.storedChargePercent(PLANNING, 'salon', 1)).toBe(4.17);
  });

  it('shows only charging intervals in the preview slots table', () => {
    const slots = fixture.componentInstance.previewChargingSlots({
      ...({} as PlanningPreviewDto),
      slots: [
        { start: '2026-01-16T00:00:00Z', power_w: 0 },
        { start: '2026-01-16T00:30:00Z', power_w: 2400 },
        { start: '2026-01-16T01:00:00Z', power_w: -1 },
      ],
    });
    expect(slots.map((slot) => slot['power_w'])).toEqual([2400]);
  });

  it('renders constraint percentages and converts them back to the API fraction', () => {
    fixture.componentInstance.draftConstraints.set([
      { heater_id: 'salon', target_charge: 25, at_time: '07:00', weekdays: [0, 1, 2, 3, 4, 5, 6] },
    ]);
    fixture.componentInstance.snapshot.set({ ...PLANNING, constraints_revision: 4 });
    fixture.componentInstance.recalculate();
    const request = backend.expectOne('/api/v1/planning/preview/jobs');
    expect(request.request.body.constraints).toEqual([
      { heater_id: 'salon', target_charge: 0.25, at_time: '07:00', weekdays: [0, 1, 2, 3, 4, 5, 6] },
    ]);
    request.flush({ job_id: 'preview-job', status: 'completed', cancellation_requested: false, requested_at: PLANNING.observed_at, started_at: PLANNING.observed_at, finished_at: PLANNING.observed_at, checks: [], result: { token: 'preview', status: 'FEASIBLE', score: [], horizon_start: PLANNING.horizon_start!, horizon_end: PLANNING.horizon_end!, slot_minutes: 30, slots: [], deficits: [], violations: [], explanations: [], demand: [], constraints: [], operator_summary: {} }, operator_summary: {}, error_code: null, error_detail: null });
  });

  it('uses the received hourly temperatures and exposes sparse labels with complete tooltips', () => {
    expect(fixture.componentInstance.forecastTemperatures(PLANNING.forecast!.hourly_points)).toEqual([3, 4]);
    const labels = Array.from({ length: 11 }, (_item, index) => `intervalo-${index}`);
    expect(fixture.componentInstance.intervalLabels(labels)).toEqual([
      'intervalo-0', '', '', '', '', 'intervalo-5', '', '', '', '', 'intervalo-10',
    ]);
    expect(fixture.componentInstance.intervalTooltipLabel(labels, 7)).toBe('intervalo-7');
  });

  it('offers failure details for a failed preview step and includes the general error', async () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    fixture.detectChanges();
    fixture.componentInstance.previewJob.set({
      job_id: 'failed-job', status: 'error', cancellation_requested: false,
      requested_at: PLANNING.observed_at, started_at: PLANNING.observed_at,
      finished_at: PLANNING.observed_at, checks: [{
        name: 'resolution', status: 'error', detail: 'CBC no devolvió una solución válida.',
        started_at: PLANNING.observed_at, finished_at: PLANNING.observed_at,
      }], result: null, operator_summary: {}, error_code: 'preview_failed',
      error_detail: 'El trabajo de vista previa terminó con error.',
    });
    fixture.detectChanges();
    const button = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-testid="preview-check-failure-button"]');
    expect(button).not.toBeNull();
    button?.click();
    await fixture.whenStable();
    const dialog = document.querySelector('mat-dialog-container');
    expect(dialog?.textContent).toContain('Resolución');
    expect(dialog?.textContent).toContain('CBC no devolvió una solución válida.');
    expect(dialog?.textContent).toContain('El trabajo de vista previa terminó con error.');
    document.querySelector<HTMLButtonElement>('[data-testid="detail-dialog-close"]')?.click();
    await new Promise((resolve) => setTimeout(resolve, 100));
  });
});
