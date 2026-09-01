import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import type { PlanningSiteConfigDto, SystemConfigurationDto, TopologyDto } from '../core/api.types';
import { SystemConfig } from './system-config';

const configuration: SystemConfigurationDto = {
  revision: 3, format_version: 1,
  sections: {
    database: { driver: 'sqlite', host: null, port: null, database: null, tls: true, trusted_no_tls: false },
    api: { host: '127.0.0.1', port: 8080, cors_origins: [], stale_seconds: null },
    mqtt: { enabled: false, host: null, port: 1883, tls: false, prefix: 'dtc', discovery_prefix: 'homeassistant', publish_seconds: 15 },
    weather: {
      provider: 'simulated', municipality_code: null, timeout_seconds: 10,
      simulated_average_temperature_c: 8, simulated_minimum_temperature_c: 3,
      fallback_average_temperature_c: 8, fallback_minimum_temperature_c: 3,
      retry_minutes: 15, refresh_minutes: 180,
    },
    output: { driver: 'simulated' }, logging: { level: 'INFO', max_events: 1000 },
    operations: { controller_poll_seconds: 5, heartbeat_stale_multiplier: 3, relay_test_lease_seconds: 30, relay_test_state_poll_seconds: 1, relay_test_lease_renew_seconds: 10, retention_days: 365, fallback_max_age_minutes: 1440 },
  },
  secrets: { mqtt_password: { configured: false, rotated_at: null }, aemet_api_key: { configured: false, rotated_at: null } },
  activation: { 'mqtt.enabled': 'hot', 'database.driver': 'restart' },
};
const topology: TopologyDto = { mode: 'normal', canonical_driver: 'sqlite', connected: true, configuration_revision: 3, fallback_captured_at: null, last_reconciled_at: null, pending_events: 0, administrative_writes_allowed: true };
const planningConfig: PlanningSiteConfigDto = {
  revision: 2,
  replan_minutes: 30,
  forecast_horizon_hours: 48,
  aemet_query_hour: 12,
  contracted_power_w: 5200,
  max_heating_power_w: 5200,
  design_indoor_temperature_c: 21,
  design_outdoor_temperature_c: 0,
  feedback_horizon_hours: 6,
};

function flushInitialLoads(backend: HttpTestingController): void {
  backend.expectOne('/api/v1/system/configuration').flush(configuration);
  backend.expectOne('/api/v1/system/topology').flush(topology);
  backend.expectOne('/api/v1/planning/config').flush(planningConfig);
}

describe('SystemConfig', () => {
  let backend: HttpTestingController;
  beforeEach(async () => {
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({ imports: [SystemConfig], providers: [provideHttpClient(), provideHttpClientTesting()] }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
  });

  it('sends the global revision and removes a new secret from the DOM after save', () => {
    const fixture = TestBed.createComponent(SystemConfig); fixture.detectChanges();
    flushInitialLoads(backend); fixture.detectChanges();
    fixture.componentInstance.choose('mqtt');
    fixture.componentInstance.edit('enabled', true);
    fixture.componentInstance.setSecretAction('mqtt_password', 'replace');
    fixture.componentInstance.setSecretValue('mqtt_password', 'sentinel-secret');
    fixture.componentInstance.save();
    const request = backend.expectOne('/api/v1/system/configuration/mqtt');
    expect(request.request.body.expected_revision).toBe(3);
    expect(request.request.body.secrets.mqtt_password).toEqual({ action: 'replace', value: 'sentinel-secret' });
    request.flush({ ...configuration, revision: 4, secrets: { mqtt_password: { configured: true, rotated_at: '2026-08-28T00:00:00Z' } } });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('sentinel-secret');
    expect(fixture.componentInstance.secretValues()).toEqual({});
  });

  it('renders and saves the four global MQTT fixed values as active when disabled', () => {
    const fixture = TestBed.createComponent(SystemConfig); fixture.detectChanges();
    flushInitialLoads(backend); fixture.detectChanges();
    fixture.componentInstance.choose('mqtt');
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).querySelector('#host')).toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelector('#mqtt_password-action')).toBeNull();

    for (const field of [
      'fixed_temperature_c',
      'fixed_target_temperature_c',
      'fixed_stored_charge_percent',
      'fixed_indoor_temperature_c',
    ]) {
      expect((fixture.nativeElement as HTMLElement).querySelector(`#${field}`)).not.toBeNull();
    }
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="mqtt-fixed-active"]')).not.toBeNull();

    fixture.componentInstance.edit('fixed_temperature_c', '19.5');
    fixture.componentInstance.edit('fixed_target_temperature_c', '22');
    fixture.componentInstance.edit('fixed_stored_charge_percent', '65');
    fixture.componentInstance.edit('fixed_indoor_temperature_c', '18');
    fixture.componentInstance.save();
    const request = backend.expectOne('/api/v1/system/configuration/mqtt');
    expect(request.request.body.values).toEqual({
      fixed_temperature_c: 19.5,
      fixed_target_temperature_c: 22,
      fixed_stored_charge_percent: 65,
      fixed_indoor_temperature_c: 18,
    });
  });

  it('shows only broker fields and credentials when MQTT is enabled', () => {
    const fixture = TestBed.createComponent(SystemConfig); fixture.detectChanges();
    backend.expectOne('/api/v1/system/configuration').flush({
      ...configuration,
      sections: { ...configuration.sections, mqtt: { ...configuration.sections.mqtt, enabled: true, host: 'broker.local' } },
    });
    backend.expectOne('/api/v1/system/topology').flush(topology);
    backend.expectOne('/api/v1/planning/config').flush(planningConfig);
    fixture.detectChanges();
    fixture.componentInstance.choose('mqtt'); fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).querySelector('#host')).not.toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelector('#fixed_temperature_c')).toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelector('#mqtt_password-action')).not.toBeNull();
  });

  it('disables mutations in fallback mode', () => {
    const fixture = TestBed.createComponent(SystemConfig); fixture.detectChanges();
    backend.expectOne('/api/v1/system/configuration').flush(configuration);
    backend.expectOne('/api/v1/system/topology').flush({ ...topology, mode: 'fallback', administrative_writes_allowed: false });
    backend.expectOne('/api/v1/planning/config').flush(planningConfig);
    fixture.detectChanges();
    expect(fixture.componentInstance.writable()).toBe(false);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('eventos pendientes');
  });

  it('renders the weather provider as a dropdown and sends every weather value plus the secret', () => {
    const fixture = TestBed.createComponent(SystemConfig); fixture.detectChanges();
    flushInitialLoads(backend); fixture.detectChanges();
    fixture.componentInstance.choose('weather');
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('#provider')?.tagName).toBe('SELECT');
    fixture.componentInstance.edit('provider', 'aemet');
    fixture.componentInstance.edit('municipality_code', '28079');
    fixture.componentInstance.edit('timeout_seconds', '12.5');
    fixture.componentInstance.edit('simulated_average_temperature_c', '9');
    fixture.componentInstance.edit('simulated_minimum_temperature_c', '4');
    fixture.componentInstance.edit('fallback_average_temperature_c', '7');
    fixture.componentInstance.edit('fallback_minimum_temperature_c', '1');
    fixture.componentInstance.edit('retry_minutes', '20');
    fixture.componentInstance.edit('refresh_minutes', '240');
    fixture.componentInstance.setSecretAction('aemet_api_key', 'replace');
    fixture.componentInstance.setSecretValue('aemet_api_key', 'secret-key');
    fixture.componentInstance.save();
    const request = backend.expectOne('/api/v1/system/configuration/weather');
    expect(request.request.body.values).toEqual({
      provider: 'aemet', municipality_code: '28079', timeout_seconds: 12.5,
      simulated_average_temperature_c: 9, simulated_minimum_temperature_c: 4,
      fallback_average_temperature_c: 7, fallback_minimum_temperature_c: 1,
      retry_minutes: 20, refresh_minutes: 240,
    });
    expect(request.request.body.secrets.aemet_api_key).toEqual({ action: 'replace', value: 'secret-key' });
  });

  it('runs a manual AEMET refresh and prevents duplicate clicks while pending', () => {
    const fixture = TestBed.createComponent(SystemConfig); fixture.detectChanges();
    flushInitialLoads(backend); fixture.detectChanges();
    fixture.componentInstance.choose('weather');
    fixture.componentInstance.edit('provider', 'aemet');
    fixture.detectChanges();
    fixture.componentInstance.refreshWeather();
    expect(fixture.componentInstance.weatherRefreshLoading()).toBe(true);
    const request = backend.expectOne('/api/v1/system/weather/refresh');
    fixture.componentInstance.refreshWeather();
    expect(backend.match('/api/v1/system/weather/refresh')).toHaveLength(0);
    request.flush({
      status: 'success', forecast_status: 'success',
      forecast_last_attempt_at: '2026-01-16T01:00:00Z',
      forecast_last_error: null, forecast_next_run_at: '2026-01-16T04:00:00Z', forecast: null,
    });
    fixture.detectChanges();
    expect(fixture.componentInstance.weatherRefreshLoading()).toBe(false);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('completada correctamente');
  });

  it('loads and saves planning parameters through the planning config API', () => {
    const fixture = TestBed.createComponent(SystemConfig); fixture.detectChanges();
    flushInitialLoads(backend); fixture.detectChanges();
    fixture.componentInstance.choose('planning');
    fixture.detectChanges();
    fixture.componentInstance.edit('forecast_horizon_hours', '36');
    fixture.componentInstance.edit('design_indoor_temperature_c', '22');
    fixture.componentInstance.save();
    const request = backend.expectOne('/api/v1/planning/config');
    expect(request.request.body).toEqual({
      expected_revision: 2,
      replan_minutes: 30,
      forecast_horizon_hours: 36,
      aemet_query_hour: 12,
      contracted_power_w: 5200,
      max_heating_power_w: 5200,
      design_indoor_temperature_c: 22,
      design_outdoor_temperature_c: 0,
      feedback_horizon_hours: 6,
    });
    request.flush({ ...planningConfig, revision: 3, forecast_horizon_hours: 36, design_indoor_temperature_c: 22 });
    fixture.detectChanges();
    expect(fixture.componentInstance.planningConfig()?.revision).toBe(3);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Parámetros de planificación guardados.');
  });
});
