import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import type { SystemConfigurationDto, TopologyDto } from '../core/api.types';
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

describe('SystemConfig', () => {
  let backend: HttpTestingController;
  beforeEach(async () => {
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({ imports: [SystemConfig], providers: [provideHttpClient(), provideHttpClientTesting()] }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
  });

  it('sends the global revision and removes a new secret from the DOM after save', () => {
    const fixture = TestBed.createComponent(SystemConfig); fixture.detectChanges();
    backend.expectOne('/api/v1/system/configuration').flush(configuration);
    backend.expectOne('/api/v1/system/topology').flush(topology); fixture.detectChanges();
    fixture.componentInstance.choose('mqtt');
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

  it('disables mutations in fallback mode', () => {
    const fixture = TestBed.createComponent(SystemConfig); fixture.detectChanges();
    backend.expectOne('/api/v1/system/configuration').flush(configuration);
    backend.expectOne('/api/v1/system/topology').flush({ ...topology, mode: 'fallback', administrative_writes_allowed: false });
    fixture.detectChanges();
    expect(fixture.componentInstance.writable()).toBe(false);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('eventos pendientes');
  });

  it('renders the weather provider as a dropdown and sends every weather value plus the secret', () => {
    const fixture = TestBed.createComponent(SystemConfig); fixture.detectChanges();
    backend.expectOne('/api/v1/system/configuration').flush(configuration);
    backend.expectOne('/api/v1/system/topology').flush(topology); fixture.detectChanges();
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
});
