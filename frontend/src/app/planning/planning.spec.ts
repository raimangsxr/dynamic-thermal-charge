import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import type { PlanningDto } from '../core/api.types';
import { Planning } from './planning';

const PLANNING: PlanningDto = {
  observed_at: '2026-01-16T01:00:00Z',
  max_total_power_w: 5200,
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
      { start: '2026-01-16T00:00:00Z', end: '2026-01-16T00:30:00Z', heater_ids: ['salon'], total_power_w: 2800, temperature_c: 3, temperature_interpolated: false },
      { start: '2026-01-16T00:30:00Z', end: '2026-01-16T01:00:00Z', heater_ids: [], total_power_w: 0, temperature_c: null, temperature_interpolated: true },
    ],
  },
  horizon_start: '2026-01-16T00:00:00Z', horizon_end: '2026-01-18T00:00:00Z',
  timeline: [
    { start: '2026-01-16T00:00:00Z', end: '2026-01-16T00:30:00Z', heater_ids: ['salon'], total_power_w: 2800, temperature_c: 3, temperature_interpolated: false, charge_minutes_by_heater: { salon: 30 } },
    { start: '2026-01-16T00:30:00Z', end: '2026-01-16T01:00:00Z', heater_ids: [], total_power_w: 0, temperature_c: 3.5, temperature_interpolated: false, charge_minutes_by_heater: { salon: 20 } },
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
    await TestBed.configureTestingModule({
      imports: [Planning],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    fixture = TestBed.createComponent(Planning);
    backend = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  it('loads the protected planning projection and renders all visual levels', () => {
    backend.expectOne('/api/v1/planning').flush(PLANNING);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('[aria-labelledby="temperature-title"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="heater-title"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="aggregate-title"]')).not.toBeNull();
    expect(element.querySelector('[aria-labelledby="cumulative-title"]')).not.toBeNull();
    expect(element.querySelector('[data-testid="planning-table"] tbody tr')).not.toBeNull();
    expect(element.querySelector('[data-testid="planning-table"]')?.textContent).toContain('Carga acumulada');
    expect(element.querySelector('[data-testid="planning-deficit"]')?.textContent).toContain('Carga no atendida');
    expect(element.querySelector('[data-testid="forecast-table"] tbody tr')).not.toBeNull();
    expect(element.querySelector('[data-testid="forecast-next-run"]')?.textContent).toContain('Próxima consulta automática');
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
  });
});
