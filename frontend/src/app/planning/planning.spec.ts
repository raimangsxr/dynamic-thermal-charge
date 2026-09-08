import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MatDialog } from '@angular/material/dialog';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PlanningDto, PlanningPreviewDto, PlanningPreviewJobDto } from '../core/api.types';
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
      { start: '2026-01-16T00:00:00Z', end: '2026-01-16T00:30:00Z', heater_ids: ['salon'], total_power_w: 2800, temperature_c: 3, temperature_interpolated: false, stored_energy_kwh_by_heater: { salon: 10.9 }, indoor_temperature_c_by_heater: { salon: 18.5 }, target_temperature_c_by_heater: { salon: 21 }, heat_delivered_kwh_by_heater: { salon: 1.2 }, thermal_loss_kwh_by_heater: { salon: 0.4 }, temperature_shortfall_c_by_heater: { salon: 2.5 }, charge_energy_kwh_by_heater: { salon: 1.4 } },
      { start: '2026-01-16T00:30:00Z', end: '2026-01-16T01:00:00Z', heater_ids: [], total_power_w: 0, temperature_c: null, temperature_interpolated: true, stored_energy_kwh_by_heater: { salon: 9.8 }, indoor_temperature_c_by_heater: { salon: 18.2 }, target_temperature_c_by_heater: { salon: 21 }, heat_delivered_kwh_by_heater: { salon: 0.3 }, thermal_loss_kwh_by_heater: { salon: 0.4 }, temperature_shortfall_c_by_heater: { salon: 2.8 }, charge_energy_kwh_by_heater: { salon: 0 } },
    ],
  },
  horizon_start: '2026-01-16T00:00:00Z', horizon_end: '2026-01-18T00:00:00Z',
  timeline: [
    { start: '2026-01-16T00:00:00Z', end: '2026-01-16T00:30:00Z', heater_ids: ['salon'], total_power_w: 2800, temperature_c: 3, temperature_interpolated: false, stored_energy_kwh_by_heater: { salon: 10.9 }, indoor_temperature_c_by_heater: { salon: 18.5 }, target_temperature_c_by_heater: { salon: 21 }, heat_delivered_kwh_by_heater: { salon: 1.2 }, thermal_loss_kwh_by_heater: { salon: 0.4 }, temperature_shortfall_c_by_heater: { salon: 2.5 }, charge_energy_kwh_by_heater: { salon: 1.4 } },
    { start: '2026-01-16T00:30:00Z', end: '2026-01-16T01:00:00Z', heater_ids: [], total_power_w: 0, temperature_c: 3.5, temperature_interpolated: false, stored_energy_kwh_by_heater: { salon: 9.8 }, indoor_temperature_c_by_heater: { salon: 18.2 }, target_temperature_c_by_heater: { salon: 21 }, heat_delivered_kwh_by_heater: { salon: 0.3 }, thermal_loss_kwh_by_heater: { salon: 0.4 }, temperature_shortfall_c_by_heater: { salon: 2.8 }, charge_energy_kwh_by_heater: { salon: 0 } },
  ],
  allocations: [{ heater_id: 'salon', requested_minutes: 60, allocated_minutes: 30, unmet_minutes: 30 }],
  heaters: [{ id: 'salon', name: 'Salón', power_w: 2800, priority: 90, enabled: true }],
  absence_reason: null,
  forecast_status: 'success',
  forecast_last_attempt_at: '2026-01-16T01:00:00Z',
  forecast_last_error: null,
  forecast_next_run_at: '2026-01-16T04:00:00Z',
  temperature_targets_revision: 4,
  temperature_targets: [{ id: 1, heater_id: 'salon', target_temperature_c: 21, start_time: '00:00', end_time: '24:00', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true }],
};

const TWO_HEATER_PLANNING: PlanningDto = {
  ...PLANNING,
  heaters: [
    ...PLANNING.heaters,
    { id: 'cocina', name: 'Cocina', power_w: 1800, priority: 80, enabled: true },
  ],
};

const SAVED_PLANNING: PlanningDto = {
  ...PLANNING,
  temperature_targets: [{ id: 1, heater_id: 'salon', target_temperature_c: 20, start_time: '08:30', end_time: '10:00', weekdays: [1, 3], enabled: true }],
};

const PREVIEW: PlanningPreviewDto = {
  token: 'preview-token', status: 'DEGRADED', score: [],
  window_start: '2026-01-16T00:00:00Z', window_end: '2026-01-16T01:00:00Z',
  horizon_start: '2026-01-16T00:00:00Z', horizon_end: '2026-01-16T02:00:00Z', slot_minutes: 30,
  slots: [
    { start: '2026-01-16T00:00:00Z', end: '2026-01-16T00:30:00Z', heater_ids: ['salon'], power_w: 2800, heater_power_w: { salon: 2800, cocina: 0 }, stored_energy_kwh: { salon: 10.9, cocina: 8.1 }, indoor_temperature_c: { salon: 18.5, cocina: 19 }, target_temperature_c: { salon: 21, cocina: 21 }, heat_delivered_kwh: { salon: 1.4, cocina: 0 }, thermal_loss_kwh: { salon: 0.4, cocina: 0.3 }, temperature_shortfall_c: { salon: 2.5, cocina: 2 }, charge_energy_kwh: { salon: 1.4, cocina: 0 } },
    { start: '2026-01-16T00:30:00Z', end: '2026-01-16T01:00:00Z', heater_ids: ['cocina'], power_w: 1800, heater_power_w: { salon: 0, cocina: 1800 }, stored_energy_kwh: { salon: 10.5, cocina: 7.8 }, indoor_temperature_c: { salon: 18.3, cocina: 19.2 }, target_temperature_c: { salon: 21, cocina: 21 }, heat_delivered_kwh: { salon: 0, cocina: 0.9 }, thermal_loss_kwh: { salon: 0.4, cocina: 0.3 }, temperature_shortfall_c: { salon: 2.7, cocina: 1.8 }, charge_energy_kwh: { salon: 0, cocina: 0.9 } },
    { start: '2026-01-16T01:00:00Z', end: '2026-01-16T01:30:00Z', heater_ids: [], power_w: 0, heater_power_w: { salon: 0, cocina: 0 }, stored_energy_kwh: { salon: 10.1, cocina: 7.5 }, indoor_temperature_c: { salon: 18.1, cocina: 19 }, target_temperature_c: { salon: 21, cocina: 21 }, heat_delivered_kwh: { salon: 0, cocina: 0 }, thermal_loss_kwh: { salon: 0.4, cocina: 0.3 }, temperature_shortfall_c: { salon: 2.9, cocina: 2 }, charge_energy_kwh: { salon: 0, cocina: 0 } },
  ],
  deficits: [{ heater_id: 'salon', requirement: 'temperature_comfort', achievable_value: 18.5, shortfall: 2.5, at: '2026-01-16T01:00:00Z', reason: 'insufficient_stored_energy_or_power', target_temperature_c: 21, projected_temperature_c: 18.5, shortfall_c: 2.5, stored_energy_kwh: 10.9, stored_soc_percent: 48.7 }],
  violations: [], explanations: [], demand: [],
  temperature_targets: [{ id: 1, heater_id: 'salon', target_temperature_c: 21, start_time: '00:00', end_time: '24:00', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true }],
  operator_summary: { warnings: [{ cause: 'insufficient_stored_energy_or_power', count: 1, recommended_action: 'Revisa potencia disponible, capacidad térmica y la consigna programada.' }] },
};

const PREVIEW_JOB = (result: PlanningPreviewDto): PlanningPreviewJobDto => ({
  job_id: 'preview-job', status: 'completed', cancellation_requested: false,
  requested_at: PLANNING.observed_at, started_at: PLANNING.observed_at, finished_at: PLANNING.observed_at,
  checks: [], result, operator_summary: result.operator_summary, error_code: null, error_detail: null,
});

async function selectPlanningTab(fixture: ComponentFixture<Planning>, index: number): Promise<void> {
  const tabs = (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="tab"]');
  tabs[index]?.click();
  await fixture.whenStable();
  fixture.detectChanges();
  await fixture.whenStable();
}

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

  it('loads the protected planning projection with the active tab selected by default', () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('[data-testid="planning-tabs"]')).not.toBeNull();
    expect(Array.from(element.querySelectorAll('[role="tab"]')).map((tab) => tab.textContent?.trim())).toEqual([
      'Planificación activa', 'Nueva planificación', 'Previsión meteorológica',
    ]);
    expect(fixture.componentInstance.selectedTab()).toBe(0);
    expect(element.querySelector('[data-testid="active-planning-tab"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="planning-summary"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="planning-detail-button"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="temperature-card"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="heater-card"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="aggregate-card"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="cumulative-card"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="temperature-title"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="heater-title"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="aggregate-title"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="cumulative-title"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="planning-deficit"]')?.textContent).toContain('Carga no atendida');
    expect(element.querySelector('[data-testid="temperature-table"]')).toBeNull();
    expect(element.querySelector('[data-testid="heater-table"]')).toBeNull();
    expect(element.querySelector('[data-testid="aggregate-table"]')).toBeNull();
    expect(element.querySelector('[data-testid="cumulative-table"]')).toBeNull();
    expect(element.querySelector('[data-testid="forecast-summary"]')).toBeNull();
    expect(element.querySelector('[data-testid="forecast-chart-card"]')).toBeNull();
    expect(element.querySelector('[data-testid="new-planning-tab"]')).toBeNull();
    expect(element.querySelectorAll('[data-testid$="-card"]')).toHaveLength(4);
  });

  it('creates active charts initially and renders forecast charts when its tab is selected', async () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    await fixture.whenStable();

    expect(chartState.configs).toHaveLength(4);
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
    expect(chartState.configs[3].data.datasets[0].data).toEqual([10.9, 9.8]);

    chartState.configs.length = 0;
    await selectPlanningTab(fixture, 2);
    expect(fixture.componentInstance.selectedTab()).toBe(2);
    expect(fixture.nativeElement.querySelector('[data-testid="forecast-summary"]')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('[data-testid="forecast-summary"]')?.textContent).toContain('Registros horarios');
    expect(fixture.nativeElement.querySelector('[data-testid="forecast-detail-button"]')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('[data-testid="forecast-chart-card"]')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('[data-testid="active-planning-tab"]')).toBeNull();
    expect(chartState.configs).toHaveLength(1);
    expect(chartState.configs[0].data.datasets[0].data).toEqual([3, 4]);
  });

  it('renders one compact preview chart and keeps preview tables in the detail dialog', async () => {
    backend.expectOne('/api/v1/planning').flush({ ...TWO_HEATER_PLANNING, preview_job: PREVIEW_JOB(PREVIEW) });
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('[data-testid="active-planning-tab"]')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('[data-testid="temperature-card"]')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('[data-testid="preview-visualization"]')).toBeNull();

    chartState.configs.length = 0;
    await selectPlanningTab(fixture, 1);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(fixture.componentInstance.previewWindowSlots(PREVIEW)).toHaveLength(2);
    expect(fixture.componentInstance.previewChartPoint(PREVIEW.slots[0], 'salon')).toMatchObject({
      y: 2.8, power_w: 2800, stored_energy_kwh: 10.9, indoor_temperature_c: 18.5, target_temperature_c: 21, heat_delivered_kwh: 1.4,
    });
    expect(element.querySelector('[data-testid="preview-visualization"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="new-planning-tab"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="temperature-card"]')).toBeNull();
    expect(element.querySelector('[data-testid="forecast-chart-card"]')).toBeNull();
    expect(element.querySelector('section[data-testid="preview-visualization"]')).toBeNull();
    expect(element.querySelector('[data-testid="charge-matrix"]')).toBeNull();
    expect(element.querySelector('[data-testid="preview-slots-table"]')).toBeNull();
    expect(element.querySelectorAll('[data-testid="forecast-table"]')).toHaveLength(0);
    expect(element.querySelector('.preview[role="status"]')?.textContent).toContain('2 intervalos de 30 minutos');

    const previewChart = chartState.configs.find((config) => config.data.datasets.length === 2);
    expect(previewChart).toBeDefined();
    expect(previewChart?.data.labels).toHaveLength(2);
    expect(previewChart?.data.datasets[0].data?.[0]).toMatchObject({
      x: 0, power_w: 2800, stored_energy_kwh: 10.9, indoor_temperature_c: 18.5, target_temperature_c: 21,
    });
  });

  it('keeps the editor and preview state while returning to the active planning tab', async () => {
    backend.expectOne('/api/v1/planning').flush({ ...TWO_HEATER_PLANNING, preview_job: PREVIEW_JOB(PREVIEW) });
    await fixture.whenStable();
    fixture.detectChanges();

    await selectPlanningTab(fixture, 1);
    fixture.componentInstance.addTarget('salon');
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="new-planning-tab"]')).not.toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelectorAll('.constraint-row')).toHaveLength(2);
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="preview-visualization"]')).not.toBeNull();

    await selectPlanningTab(fixture, 0);
    expect(fixture.componentInstance.selectedTab()).toBe(0);
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="temperature-card"]')).not.toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="preview-visualization"]')).toBeNull();

    await selectPlanningTab(fixture, 1);
    expect((fixture.nativeElement as HTMLElement).querySelectorAll('.constraint-row')).toHaveLength(2);
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="preview-visualization"]')).not.toBeNull();
  });

  it('duplicates an interval as an independent exact draft copy', () => {
    const target = { heater_id: 'salon', target_temperature_c: 20, start_time: '22:00', end_time: '02:00', weekdays: [4, 5], enabled: true };
    fixture.componentInstance.draftTargets.set([target]);

    fixture.componentInstance.duplicateTarget(0);
    expect(fixture.componentInstance.draftTargets()).toEqual([target, target]);

    fixture.componentInstance.editTarget(1, 'start_time', '23:00');
    fixture.componentInstance.toggleDay(1, 0);
    expect(fixture.componentInstance.draftTargets()[0]).toEqual(target);
    expect(fixture.componentInstance.draftTargets()[1]).toEqual({ ...target, start_time: '23:00', weekdays: [0, 4, 5] });
  });

  it('does not overlap preview job polls when duplicate ticks arrive', () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    fixture.componentInstance.previewJob.set({ ...PREVIEW_JOB(PREVIEW), status: 'running', result: null });

    const poll = (fixture.componentInstance as unknown as { pollPreviewJob: () => void }).pollPreviewJob;
    poll.call(fixture.componentInstance);
    poll.call(fixture.componentInstance);

    const request = backend.expectOne('/api/v1/planning/preview/jobs/preview-job');
    expect(() => backend.expectOne('/api/v1/planning/preview/jobs/preview-job')).toThrow();
    request.flush({ ...PREVIEW_JOB(PREVIEW), status: 'running', result: null });
  });

  it('shows problem details for degraded previews and falls back to violations for invalid previews', async () => {
    backend.expectOne('/api/v1/planning').flush(TWO_HEATER_PLANNING);
    await fixture.whenStable();
    fixture.detectChanges();
    await selectPlanningTab(fixture, 1);
    fixture.componentInstance.previewJob.set(PREVIEW_JOB(PREVIEW));
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    const button = element.querySelector<HTMLButtonElement>('[data-testid="preview-problems-button"]');
    expect(button).not.toBeNull();
    button?.click();
    await fixture.whenStable();
    let dialog = document.querySelector('mat-dialog-container');
    expect(dialog?.textContent).toContain('Salón');
    expect(dialog?.textContent).toContain('temperature_comfort');
    expect(dialog?.textContent).toContain('21.0 °C');
    expect(dialog?.textContent).toContain('Revisa potencia disponible');
    expect(dialog?.querySelectorAll('[data-testid="preview-problem"]')).toHaveLength(1);
    document.querySelector<HTMLButtonElement>('[data-testid="detail-dialog-close"]')?.click();
    await new Promise((resolve) => setTimeout(resolve, 100));

    const invalid = { ...PREVIEW, status: 'INVALID' as const, deficits: [], violations: PREVIEW.deficits };
    fixture.componentInstance.previewJob.set(PREVIEW_JOB(invalid));
    fixture.componentInstance.preview.set(invalid);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="preview-problems-button"]')).not.toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelector('.preview-reasons')?.textContent).toContain('La energía almacenada o la potencia disponible');
  });

  it('does not show the problem button for a feasible preview', async () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    await selectPlanningTab(fixture, 1);
    fixture.componentInstance.previewJob.set(PREVIEW_JOB({ ...PREVIEW, status: 'FEASIBLE', deficits: [], violations: [] }));
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="preview-problems-button"]')).toBeNull();
  });

  it('opens forecast and planning details in accessible dialogs with explicit close actions', async () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    await fixture.whenStable();
    fixture.detectChanges();
    await selectPlanningTab(fixture, 2);

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

    await selectPlanningTab(fixture, 0);
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

  it('opens the interval summary and one detail table per heater without a chart', async () => {
    backend.expectOne('/api/v1/planning').flush({ ...TWO_HEATER_PLANNING, preview_job: PREVIEW_JOB(PREVIEW) });
    await fixture.whenStable();
    fixture.detectChanges();
    await selectPlanningTab(fixture, 1);
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-testid="preview-chart-detail-button"]')?.click();
    await fixture.whenStable();

    const dialog = document.querySelector('mat-dialog-container');
    expect(dialog?.querySelector('[data-testid="preview-slots-detail-table"]')).not.toBeNull();
    expect(dialog?.querySelectorAll('[data-testid="preview-slots-detail-table"] tbody tr')).toHaveLength(2);
    expect(dialog?.querySelector('[data-testid="preview-detail-tabs"]')).not.toBeNull();
    expect(dialog?.querySelectorAll('[role="tab"]')).toHaveLength(2);
    expect(dialog?.querySelectorAll('[data-testid="preview-detail-heater-table"]')).toHaveLength(1);
    expect(dialog?.querySelectorAll('canvas')).toHaveLength(0);
    expect(dialog?.textContent).toContain('Salón');
    expect(dialog?.textContent).toContain('Cocina');
    expect(dialog?.textContent).toContain('2800');
    dialog?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[1]?.click();
    await fixture.whenStable();
    const secondTabDialog = document.querySelector('mat-dialog-container');
    expect(secondTabDialog?.querySelectorAll('[data-testid="preview-detail-heater-table"]')).toHaveLength(1);
    expect(secondTabDialog?.textContent).toContain('0.90');
    expect(secondTabDialog?.querySelectorAll('canvas')).toHaveLength(0);
    document.querySelector<HTMLButtonElement>('[data-testid="detail-dialog-close"]')?.click();
    await new Promise((resolve) => setTimeout(resolve, 100));
  });

  it('opens an enlarged dialog from each graph section', async () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    fixture.detectChanges();
    const dialog = TestBed.inject(MatDialog);
    const open = vi.spyOn(dialog, 'open').mockReturnValue({} as never);
    const element = fixture.nativeElement as HTMLElement;
    for (const testId of [
      'temperature-chart-detail-button', 'heater-chart-detail-button',
      'aggregate-chart-detail-button', 'cumulative-chart-detail-button',
    ]) {
      element.querySelector<HTMLButtonElement>(`[data-testid="${testId}"]`)?.click();
    }
    await selectPlanningTab(fixture, 2);
    element.querySelector<HTMLButtonElement>('[data-testid="forecast-chart-detail-button"]')?.click();
    await selectPlanningTab(fixture, 1);
    fixture.componentInstance.previewJob.set(PREVIEW_JOB(PREVIEW));
    fixture.componentInstance.preview.set(PREVIEW);
    fixture.detectChanges();
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-testid="preview-chart-detail-button"]')?.click();

    expect(open).toHaveBeenCalledTimes(6);
    expect(open.mock.calls.slice(0, 4).every(([, config]) => (config as { data?: { kind?: string } }).data?.kind === 'planning-table')).toBe(true);
    expect(open.mock.calls.slice(0, 4).every(([, config]) => (config as { width?: string; maxWidth?: string }).width === 'min(98vw, 192rem)' && (config as { maxWidth?: string }).maxWidth === '98vw')).toBe(true);
    expect((open.mock.calls[0][1] as { data?: { table?: { headers: string[]; rows: string[][] } } }).data?.table).toMatchObject({
      headers: ['Intervalo', 'Salón interior (°C)', 'Salón objetivo (°C)', 'Exterior (°C)'],
      rows: [[fixture.componentInstance.slotLabel(PLANNING.timeline[0]), '18.5', '21.0', '3.0'], [fixture.componentInstance.slotLabel(PLANNING.timeline[1]), '18.2', '21.0', '3.5']],
    });
    expect((open.mock.calls[1][1] as { data?: { table?: { headers: string[]; rows: string[][] } } }).data?.table?.headers).toEqual(['Intervalo', 'Salón (W)', 'Total (W)']);
    expect((open.mock.calls[2][1] as { data?: { table?: { headers: string[] } } }).data?.table?.headers).toEqual(['Intervalo', 'Total (W)', 'Carga base (W)', 'Límite contratado (W)', 'Límite calefacción (W)']);
    expect((open.mock.calls[3][1] as { data?: { table?: { headers: string[] } } }).data?.table?.headers).toEqual(['Intervalo', 'Salón (kWh)']);
    expect((open.mock.calls[4][1] as { data?: { kind?: string } }).data?.kind).toBe('chart');
    expect((open.mock.calls[5][1] as { data?: { kind?: string } }).data?.kind).toBe('preview');
    expect((open.mock.calls[4][1] as { data?: { chart?: { labels: string[] } } }).data?.chart?.labels.length).toBe(2);
    open.mockRestore();
  });

  it('renders each active graph detail as a compact table-only dialog', async () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    await fixture.whenStable();
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    const details = [
      { testId: 'temperature-chart-detail-button', headers: ['Intervalo', 'Salón interior (°C)', 'Salón objetivo (°C)', 'Exterior (°C)'], values: ['18.5', '21.0', '3.0'] },
      { testId: 'heater-chart-detail-button', headers: ['Intervalo', 'Salón (W)', 'Total (W)'], values: ['2800', '2800'] },
      { testId: 'aggregate-chart-detail-button', headers: ['Intervalo', 'Total (W)', 'Carga base (W)', 'Límite contratado (W)', 'Límite calefacción (W)'], values: ['2800', '600', '5200', '4200'] },
      { testId: 'cumulative-chart-detail-button', headers: ['Intervalo', 'Salón (kWh)'], values: ['10.90 kWh'] },
    ];

    for (const detail of details) {
      element.querySelector<HTMLButtonElement>(`[data-testid="${detail.testId}"]`)?.click();
      await fixture.whenStable();
      const dialog = document.querySelector('mat-dialog-container');
      const table = dialog?.querySelector<HTMLTableElement>('[data-testid="planning-detail-table"]');
      expect(table).not.toBeNull();
      expect(Array.from(table?.querySelectorAll('thead th') ?? []).map((header) => header.textContent?.trim())).toEqual(detail.headers);
      expect(table?.querySelectorAll('tbody tr')).toHaveLength(2);
      expect(Array.from(table?.querySelectorAll('tbody tr:first-child td') ?? []).map((cell) => cell.textContent?.trim())).toEqual(detail.values);
      expect(table?.querySelector('tbody th[scope="row"]')).not.toBeNull();
      expect(dialog?.querySelectorAll('canvas')).toHaveLength(0);
      document.querySelector<HTMLButtonElement>('[data-testid="detail-dialog-close"]')?.click();
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  });

  it('marks missing active temperature values as sin dato in the detail table', async () => {
    const planningWithoutTemperature: PlanningDto = {
      ...PLANNING,
      timeline: PLANNING.timeline.map((slot, index) => index === 0 ? {
        ...slot,
        temperature_c: null,
        indoor_temperature_c_by_heater: {},
      } : slot),
    };
    backend.expectOne('/api/v1/planning').flush(planningWithoutTemperature);
    await fixture.whenStable();
    fixture.detectChanges();
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-testid="temperature-chart-detail-button"]')?.click();
    await fixture.whenStable();

    const table = document.querySelector<HTMLTableElement>('[data-testid="planning-detail-table"]');
    expect(Array.from(table?.querySelectorAll('tbody tr:first-child td') ?? []).map((cell) => cell.textContent?.trim())).toEqual(['sin dato', '21.0', 'sin dato']);
    document.querySelector<HTMLButtonElement>('[data-testid="detail-dialog-close"]')?.click();
    await new Promise((resolve) => setTimeout(resolve, 100));
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

  it('shows stored room energy in kWh for every interval', () => {
    expect(fixture.componentInstance.storedEnergyKwh(PLANNING, 'salon', 0)).toBe(10.9);
    expect(fixture.componentInstance.storedEnergyKwh(PLANNING, 'salon', 1)).toBe(9.8);
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

  it('renders temperature targets and sends them to the API unchanged', () => {
    fixture.componentInstance.draftTargets.set([
      { heater_id: 'salon', target_temperature_c: 19.5, start_time: '07:00', end_time: '09:00', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true },
    ]);
    fixture.componentInstance.snapshot.set({ ...PLANNING, temperature_targets_revision: 4 });
    fixture.componentInstance.recalculate();
    const request = backend.expectOne('/api/v1/planning/preview/jobs');
    expect(request.request.body).toEqual({
      temperature_targets: [{ heater_id: 'salon', target_temperature_c: 19.5, start_time: '07:00', end_time: '09:00', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true }],
      expected_revision: 4,
    });
    request.flush({ job_id: 'preview-job', status: 'completed', cancellation_requested: false, requested_at: PLANNING.observed_at, started_at: PLANNING.observed_at, finished_at: PLANNING.observed_at, checks: [], result: { token: 'preview', status: 'FEASIBLE', score: [], window_start: PLANNING.plan!.window_start, window_end: PLANNING.plan!.window_end, horizon_start: PLANNING.horizon_start!, horizon_end: PLANNING.horizon_end!, slot_minutes: 30, slots: [], deficits: [], violations: [], explanations: [], demand: [], temperature_targets: [], operator_summary: {} }, operator_summary: {}, error_code: null, error_detail: null });
  });

  it('activates a valid preview from the new planning tab', async () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    await fixture.whenStable();
    fixture.detectChanges();
    await selectPlanningTab(fixture, 1);

    fixture.componentInstance.draftTargets.set([
      { heater_id: 'salon', target_temperature_c: 19.5, start_time: '07:00', end_time: '09:00', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true },
    ]);
    fixture.componentInstance.snapshot.set({ ...PLANNING, temperature_targets_revision: 4 });
    fixture.componentInstance.preview.set({ ...PREVIEW, status: 'FEASIBLE', deficits: [], violations: [] });
    fixture.detectChanges();

    const activateButton = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-testid="activate-button"]');
    expect(activateButton?.disabled).toBe(false);
    activateButton?.click();
    fixture.detectChanges();
    expect(activateButton?.disabled).toBe(true);
    expect(fixture.componentInstance.actionMessage()).toBe('Guardando y activando…');
    const request = backend.expectOne('/api/v1/planning/activate');
    expect(request.request.body).toEqual({
      token: 'preview-token',
      temperature_targets: [{ heater_id: 'salon', target_temperature_c: 19.5, start_time: '07:00', end_time: '09:00', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true }],
      expected_revision: 4,
    });
    request.flush({ ...PREVIEW, status: 'FEASIBLE', deficits: [], violations: [] });
    const refresh = backend.expectOne('/api/v1/planning');
    refresh.flush({ ...PLANNING, preview_job: PREVIEW_JOB(PREVIEW) });
    fixture.detectChanges();
    expect(fixture.componentInstance.actionMessage()).toBe('Planificación guardada y activada correctamente.');
    expect(fixture.componentInstance.activationInFlight()).toBe(false);
    expect(fixture.componentInstance.preview()).toBeNull();
    expect(fixture.componentInstance.previewJob()).toBeNull();
    expect(sessionStorage.getItem('dtc.planning.preview-job')).toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="planning-action-status"]')?.textContent).toContain('Planificación guardada y activada correctamente.');
  });

  it('shows an actionable error and allows retry when activation fails', async () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    await fixture.whenStable();
    fixture.detectChanges();
    await selectPlanningTab(fixture, 1);

    fixture.componentInstance.snapshot.set({ ...PLANNING, temperature_targets_revision: 4 });
    fixture.componentInstance.preview.set({ ...PREVIEW, status: 'FEASIBLE', deficits: [], violations: [] });
    fixture.detectChanges();
    const activateButton = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-testid="activate-button"]');
    activateButton?.click();
    fixture.detectChanges();
    expect(activateButton?.disabled).toBe(true);

    const request = backend.expectOne('/api/v1/planning/activate');
    request.flush({ code: 'config_conflict', message: 'temperature targets changed' }, { status: 409, statusText: 'Conflict' });
    fixture.detectChanges();

    expect(fixture.componentInstance.activationInFlight()).toBe(false);
    expect(fixture.componentInstance.actionMessage()).toBe('');
    expect(fixture.componentInstance.actionError()).toContain('No se pudo guardar y activar');
    expect(fixture.componentInstance.actionError()).toContain('La configuración cambió mientras editabas');
    expect(fixture.componentInstance.preview()).not.toBeNull();
    expect(activateButton?.disabled).toBe(false);
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="planning-action-error"]')?.getAttribute('role')).toBe('alert');
  });

  it('discards local edits and preview state without reloading the planning projection', async () => {
    backend.expectOne('/api/v1/planning').flush(SAVED_PLANNING);
    await fixture.whenStable();
    fixture.detectChanges();
    await selectPlanningTab(fixture, 1);

    fixture.componentInstance.draftTargets.set([
      { heater_id: 'salon', target_temperature_c: 19.5, start_time: '07:00', end_time: '09:00', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true },
    ]);
    fixture.componentInstance.preview.set({ ...PREVIEW, status: 'FEASIBLE', deficits: [], violations: [] });
    fixture.componentInstance.previewJob.set(PREVIEW_JOB(PREVIEW));
    fixture.componentInstance.actionError.set('Mensaje anterior');
    sessionStorage.setItem('dtc.planning.preview-job', 'preview-job');
    fixture.detectChanges();

    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-testid="discard-button"]')?.click();
    fixture.detectChanges();

    expect(fixture.componentInstance.draftTargets()).toEqual([
      { heater_id: 'salon', target_temperature_c: 20, start_time: '08:30', end_time: '10:00', weekdays: [1, 3], enabled: true },
    ]);
    expect((fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>('[data-testid="target-temperature-input"]')?.value).toBe('20');
    expect(fixture.componentInstance.preview()).toBeNull();
    expect(fixture.componentInstance.previewJob()).toBeNull();
    expect(sessionStorage.getItem('dtc.planning.preview-job')).toBeNull();
    expect(fixture.componentInstance.actionError()).toBe('');
    expect(fixture.componentInstance.actionMessage()).toBe('Cambios descartados. Se han restaurado las consignas guardadas.');
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="preview-job"]')).toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="planning-action-status"]')?.textContent).toContain('Cambios descartados');
    backend.expectNone('/api/v1/planning');
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
    await fixture.whenStable();
    fixture.detectChanges();
    await selectPlanningTab(fixture, 1);
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
