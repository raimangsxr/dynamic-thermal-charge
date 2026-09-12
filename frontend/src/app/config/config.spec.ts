/** Editing over HTTP: FR-017 to FR-023, FR-033, SC-005, SC-006. */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { ApiErrorCode, ChangeDto, ConfigDto, PlanningSiteConfigDto, SystemConfigurationDto, TopologyDto } from '../core/api.types';
import { Config } from './config';
import { ELECTRICAL_FIELDS, needsConfirmation } from './electrical-fields';

function configDto(overrides: Partial<ConfigDto> = {}): ConfigDto {
  return {
    config_revision: 3,
    schema_revision: '0015_temperature_target_intervals',
    max_total_power_kw: 5.2,
    slot_minutes: 30,
    window_minutes: 480,
    indoor_max_age_minutes: 30,
    indoor_min_plausible_c: -20,
    indoor_max_plausible_c: 50,
    log_level: 'INFO',
    state_file: '/var/lib/dtc/active-plan.json',
    poll_seconds: 5,
    retention_days: 365,
    schedule: {
      timezone: 'Europe/Madrid',
      start_time: '00:00',
      end_time: '08:00',
      weekdays: [0, 1, 2, 3, 4, 5, 6],
    },
    heaters: [
      {
        id: 'salon',
        name: 'Salón',
        model: 'ADS-2812',
        power_kw: 2.8,
        full_charge_hours: 8,
        full_discharge_hours: 10,
        static_emission_percent: 20,
        room_thermal_capacity_kwh_per_c: 2.5,
        room_heat_loss_kw_per_c: 0.12,
        priority: 90,
        enabled: true,
        telemetry_topic: null,
        temperature_targets: [{ id: 1, heater_id: 'salon', target_temperature_c: 21, start_time: '00:00', end_time: '24:00', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true }],
        output: { kind: 'gpio', pin: 17, active_high: false },
      },
    ],
    ...overrides,
  };
}

function systemConfigurationDto(overrides: Partial<SystemConfigurationDto> = {}): SystemConfigurationDto {
  return {
    revision: 3,
    format_version: 1,
    sections: {
      database: { driver: 'sqlite', host: null, port: null, database: null, tls: true, trusted_no_tls: false },
      api: { host: '127.0.0.1', port: 8080, cors_origins: [], stale_seconds: null },
      mqtt: { enabled: false, host: null, port: 1883, tls: false, prefix: 'dtc', discovery_prefix: 'homeassistant', publish_seconds: 15, fixed_stored_soc_percent: 50, fixed_indoor_temperature_c: 20 },
      weather: { provider: 'simulated', municipality_code: null, timeout_seconds: 10, simulated_average_temperature_c: 8, simulated_minimum_temperature_c: 3, fallback_average_temperature_c: 8, fallback_minimum_temperature_c: 3, retry_minutes: 15, refresh_minutes: 180 },
      output: { driver: 'simulated' },
      logging: { level: 'INFO', max_events: 1000 },
      operations: { controller_poll_seconds: 5, heartbeat_stale_multiplier: 3, relay_test_lease_seconds: 30, relay_test_state_poll_seconds: 1, relay_test_lease_renew_seconds: 10, retention_days: 365, fallback_max_age_minutes: 1440 },
      email: { enabled: false, host: null, port: 587, security: 'starttls', sender: null, recipients: [], timeout_seconds: 10 },
    },
    secrets: { mqtt_password: { configured: false, rotated_at: null }, aemet_api_key: { configured: false, rotated_at: null } },
    activation: { 'mqtt.enabled': 'hot', 'database.driver': 'restart' },
    ...overrides,
  };
}

function planningConfigDto(overrides: Partial<PlanningSiteConfigDto> = {}): PlanningSiteConfigDto {
  return {
    revision: 2, replan_minutes: 30, planning_window_hours: 12, forecast_horizon_hours: 48, solver_time_limit_seconds: 120, aemet_query_hour: 12,
    contracted_power_w: 5200, max_heating_power_w: 5200, base_load_w: 0, deviation_shortfall_tolerance_c: 0.1, deviation_surplus_soc_percent: 5,
    mqtt_simulation_enabled: false, mqtt_simulation_initial_temperature_c: 45, mqtt_simulation_publish_seconds: 30, mqtt_simulation_topic_prefix: 'dtc/sim', mqtt_simulation_thermal_loss_c_per_hour: 2,
    ...overrides,
  };
}

const topologyDto: TopologyDto = { mode: 'normal', canonical_driver: 'sqlite', connected: true, configuration_revision: 3, fallback_captured_at: null, last_reconciled_at: null, pending_events: 0, administrative_writes_allowed: true };

function change(overrides: Partial<ChangeDto> = {}): ChangeDto {
  return {
    entity: 'installation',
    entity_key: null,
    field: 'poll_seconds',
    old_value: '5',
    new_value: '7',
    action: 'set',
    revision_before: 3,
    revision_after: 4,
    ...overrides,
  };
}

describe('Config', () => {
  let fixture: ComponentFixture<Config>;
  let backend: HttpTestingController;

  beforeEach(async () => {
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({
      imports: [Config],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    fixture = TestBed.createComponent(Config);
    backend = TestBed.inject(HttpTestingController);
  });

  function load(dto: ConfigDto = configDto()): HTMLElement {
    fixture.detectChanges();
    backend.expectOne('/api/v1/config').flush(dto);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  function loadUnified(
    dto: ConfigDto = configDto(),
    system: SystemConfigurationDto = systemConfigurationDto(),
  ): HTMLElement {
    const element = load(dto);
    backend.expectOne('/api/v1/system/configuration').flush(system);
    backend.expectOne('/api/v1/system/topology').flush(topologyDto);
    backend.expectOne('/api/v1/planning/config').flush(planningConfigDto());
    fixture.detectChanges();
    return element;
  }

  function el(): HTMLElement {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  function testId(id: string): HTMLElement | null {
    return el().querySelector(`[data-testid="${id}"]`);
  }

  function apiError(code: ApiErrorCode, message: string, status: number, field: string | null = null) {
    return {
      body: { code, message, field, heater_id: null },
      options: { status, statusText: 'error' },
    };
  }

  /* ------------------------------------------------------------------ read */

  it('organizes the merged workspace by tasks and hides legacy duplicate controls', () => {
    const element = loadUnified();
    expect(element.querySelectorAll('.area-tab')).toHaveLength(6);
    expect([...element.querySelectorAll('.area-tab')].map((item) => item.textContent)).not.toContain('Sistema');

    fixture.componentInstance.chooseArea('installation');
    fixture.detectChanges();
    expect(element.querySelector('#installation-max_total_power_kw')).toBeNull();
    expect(element.querySelector('#installation-poll_seconds')).toBeNull();
    expect(element.querySelector('#installation-log_level')).toBeNull();
    expect(element.querySelector('#installation-retention_days')).toBeNull();

    fixture.componentInstance.chooseArea('planning');
    fixture.detectChanges();
    expect(element.querySelector('#planning-contracted_power_w')).not.toBeNull();

    fixture.componentInstance.chooseArea('service');
    fixture.componentInstance.chooseService('operations');
    fixture.detectChanges();
    expect(element.querySelector('#operations-controller_poll_seconds')).not.toBeNull();
    expect(element.querySelectorAll('#operations-retention_days')).toHaveLength(1);
  });

  it('shows the installation timezone and the effective global output driver', () => {
    const system = systemConfigurationDto({
      sections: {
        ...systemConfigurationDto().sections,
        output: {
          driver: 'simulated',
          configured_driver: 'simulated',
          effective_driver: 'simulated',
          effective_driver_reason: 'El driver global simulado prevalece sobre las salidas GPIO configuradas por acumulador.',
          overridden_gpio_heaters: ['Salón'],
        },
      },
    });
    const element = loadUnified(configDto(), system);
    expect(element.textContent).toContain('horas de instalación: Europe/Madrid');
    fixture.componentInstance.chooseArea('service');
    fixture.componentInstance.chooseService('output');
    fixture.detectChanges();
    expect(element.querySelector('.output-note')?.textContent).toContain('Driver configurado: Simulado');
    expect(element.querySelector('.output-note')?.textContent).toContain('driver efectivo: Simulado');
    expect(element.querySelector('.output-note')?.textContent).toContain('prevalece la simulación global');
    expect(element.querySelector('.output-note')?.textContent).toContain('Salón');
  });

  it('keeps a replaced secret out of the DOM after saving from the merged page', () => {
    loadUnified();
    fixture.componentInstance.chooseArea('integrations');
    fixture.componentInstance.chooseIntegration('mqtt');
    fixture.componentInstance.systemEdit('mqtt', 'enabled', true);
    fixture.componentInstance.setSecretAction('mqtt_password', 'replace');
    fixture.componentInstance.setSecretValue('mqtt_password', 'sentinel-secret');
    fixture.componentInstance.requestSystemSave('mqtt');
    expect(testId('confirm-system')).not.toBeNull();
    fixture.componentInstance.confirmSystemSave();
    const request = backend.expectOne('/api/v1/system/configuration/mqtt');
    expect(request.request.body.expected_revision).toBe(3);
    expect(request.request.body.secrets.mqtt_password).toEqual({ action: 'replace', value: 'sentinel-secret' });
    request.flush(systemConfigurationDto({ revision: 4, secrets: { mqtt_password: { configured: true, rotated_at: '2026-09-06T00:00:00Z' } } }));
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('sentinel-secret');
    expect(fixture.componentInstance.secretValues()).toEqual({});
  });

  it('shows the configuration with its revisions', () => {
    const element = load();
    fixture.componentInstance.chooseArea('heaters');
    fixture.detectChanges();
    expect(element.textContent).toContain('rev. 3');
    expect(element.textContent).toContain('0015_temperature_target_intervals');
    expect(element.querySelector('[data-heater="salon"]')).not.toBeNull();
  });

  /* --------------------------------------------------------------- editing */

  it('sends the revision it read with every write', () => {
    load();
    fixture.componentInstance.edit('poll_seconds', null, '7');
    fixture.componentInstance.saveInstallation();
    const request = backend.expectOne(
      (candidate) => candidate.method === 'PATCH' && candidate.url === '/api/v1/config/batch',
    );
    expect(request.request.body).toEqual({
      revision: 3,
      values: { poll_seconds: '7' },
    });
    request.flush({ changes: [change()] });
    backend.expectOne('/api/v1/config').flush(configDto({ config_revision: 4 }));
  });

  it('confirms the change with both values', () => {
    load();
    fixture.componentInstance.edit('poll_seconds', null, '7');
    fixture.componentInstance.saveInstallation();
    backend.expectOne('/api/v1/config/batch').flush({ changes: [change()] });
    backend.expectOne('/api/v1/config').flush(configDto({ config_revision: 4 }));
    expect(testId('saved')?.textContent).toContain('5');
    expect(testId('saved')?.textContent).toContain('7');
  });

  it('saves several installation fields in one request', () => {
    load();
    fixture.componentInstance.edit('poll_seconds', null, '7');
    fixture.componentInstance.edit('slot_minutes', null, '15');
    fixture.componentInstance.saveInstallation();
    const request = backend.expectOne('/api/v1/config/batch');
    expect(request.request.body).toEqual({
      revision: 3,
      values: { poll_seconds: '7', slot_minutes: '15' },
    });
    request.flush({
      changes: [
        change({ field: 'poll_seconds' }),
        change({ field: 'slot_minutes', old_value: '30', new_value: '15' }),
      ],
    });
    backend.expectOne('/api/v1/config').flush(configDto({ config_revision: 4 }));
    expect(testId('saved')?.textContent).toContain('2 cambios');
  });

  it('edits an accumulator through one complete update endpoint', () => {
    load();
    expect(el().querySelector('[data-save="salon.target_charge"]')).toBeNull();
    fixture.componentInstance.openEditHeater(fixture.componentInstance.config()!.heaters[0]);
    fixture.componentInstance.updateHeaterForm('room_thermal_capacity_kwh_per_c', '3.1');
    fixture.componentInstance.saveHeater();
    const request = backend.expectOne('/api/v1/config/heaters/salon');
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toMatchObject({ revision: 3, room_thermal_capacity_kwh_per_c: 3.1 });
    request.flush(change({ entity: 'heater', entity_key: 'salon' }));
    backend.expectOne('/api/v1/config').flush(configDto());
  });

  it('opens electrical accumulator changes in a popup dialog', async () => {
    load();
    fixture.componentInstance.openEditHeater(fixture.componentInstance.config()!.heaters[0]);
    expect(el().querySelector('label[for="heater-pin"]')?.textContent).toContain('Pin GPIO');
    expect(el().querySelector('label[for="heater-pin"]')?.textContent).not.toContain('BCM');
    fixture.componentInstance.updateHeaterForm('pin', '24');
    fixture.componentInstance.saveHeater();
    await fixture.whenStable();

    const dialog = document.querySelector('mat-dialog-container');
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain('Confirmar cambios en Salón');
    expect(dialog?.textContent).toContain('valores eléctricos');
    expect(dialog?.querySelector('[data-testid="confirm-delete"]')).not.toBeNull();
    expect(testId('confirm')).toBeNull();

    dialog?.querySelector<HTMLButtonElement>('[data-testid="confirm-delete"]')?.click();
    await new Promise((resolve) => setTimeout(resolve, 100));
    const request = backend.expectOne('/api/v1/config/heaters/salon');
    expect(request.request.body).toMatchObject({ revision: 3, pin: 24 });
    request.flush(change({ entity: 'heater', entity_key: 'salon' }));
    backend.expectOne('/api/v1/config').flush(configDto());
  });

  it('renders the effective grouped telemetry topic without an editor', () => {
    const element = load(
      configDto({
        heaters: [
          { ...configDto().heaters[0], telemetry_topic: 'telemetria/acumuladores/salon/telemetry' },
        ],
      }),
    );
    fixture.componentInstance.chooseArea('installation');
    fixture.detectChanges();
    for (const field of [
      'indoor_max_age_minutes',
      'indoor_min_plausible_c',
      'indoor_max_plausible_c',
    ]) {
      expect(element.querySelector(`[data-field="${field}"]`)).not.toBeNull();
    }
    fixture.componentInstance.chooseArea('heaters');
    fixture.detectChanges();
    expect(element.querySelector('[data-heater="salon"] code')?.textContent).toContain(
      'telemetria/acumuladores/salon/telemetry',
    );
    fixture.componentInstance.openEditHeater(fixture.componentInstance.config()!.heaters[0]);
    fixture.detectChanges();
    expect(element.querySelector('[name="telemetry_topic"]')).toBeNull();
  });

  it('does not send a telemetry topic when saving the accumulator form', () => {
    load(configDto({ heaters: [{ ...configDto().heaters[0], telemetry_topic: 'ha/old' }] }));
    fixture.componentInstance.openEditHeater(fixture.componentInstance.config()!.heaters[0]);
    fixture.componentInstance.updateHeaterForm('name', 'Salón actualizado');
    fixture.componentInstance.saveHeater();
    const request = backend.expectOne('/api/v1/config/heaters/salon');
    expect(request.request.body).toMatchObject({
      revision: 3,
    });
    expect(request.request.body).not.toHaveProperty('telemetry_topic');
  });

  /* ------------------------------------------------- electrical confirmation */

  describe('the three electrical fields (FR-020)', () => {
    it('is exactly those three', () => {
      expect(ELECTRICAL_FIELDS).toEqual(
        new Set(['max_total_power_kw', 'pin', 'active_high']),
      );
    });

    it.each([...ELECTRICAL_FIELDS])('asks before changing %s', (field) => {
      expect(needsConfirmation(field)).toBe(true);
    });

    it.each(['poll_seconds', 'slot_minutes', 'priority', 'room_thermal_capacity_kwh_per_c', 'log_level'])(
      'does NOT ask before changing %s',
      (field) => {
        expect(needsConfirmation(field)).toBe(false);
      },
    );

    it('does not touch the API until the operator confirms', () => {
      load();
      fixture.componentInstance.edit('max_total_power_kw', null, '9.9');
      fixture.componentInstance.saveInstallation();
      backend.expectNone(
        (candidate) => candidate.method === 'PATCH',
      );
      expect(testId('confirm')).not.toBeNull();
    });

    it('says what is being changed, and why it matters', () => {
      load();
      fixture.componentInstance.edit('max_total_power_kw', null, '9.9');
      fixture.componentInstance.saveInstallation();
      const text = testId('confirm')?.textContent ?? '';
      expect(text).toContain('9.9');
      expect(text).toContain('sobrecarga');
    });

    it('applies the change once confirmed', () => {
      load();
      fixture.componentInstance.edit('max_total_power_kw', null, '6.0');
      fixture.componentInstance.saveInstallation();
      fixture.componentInstance.confirm();
      const request = backend.expectOne(
        (candidate) => candidate.method === 'PATCH' && candidate.url === '/api/v1/config/batch',
      );
      expect(request.request.body).toMatchObject({ values: { max_total_power_kw: '6.0' } });
      request.flush({ changes: [change({ field: 'max_total_power_kw' })] });
      backend.expectOne('/api/v1/config').flush(configDto());
    });

    it('changes nothing when cancelled, and keeps what was typed', () => {
      load();
      fixture.componentInstance.edit('pin', 'salon', '24');
      fixture.componentInstance.submit('pin', 'salon');
      fixture.componentInstance.cancelConfirmation();
      backend.expectNone((candidate) => candidate.method === 'PATCH');
      expect(fixture.componentInstance.pending()['salon.pin']).toBe('24');
    });
  });

  /* ------------------------------------------------------------ rejections */

  it('puts a validation rejection next to its field, not in a banner', () => {
    load();
    fixture.componentInstance.chooseArea('installation');
    fixture.detectChanges();
    fixture.componentInstance.edit('slot_minutes', null, '45');
    fixture.componentInstance.saveInstallation();
    const { body, options } = apiError(
      'validation_failed',
      'slot_minutes must be a divisor of 60',
      422,
      'slot_minutes',
    );
    backend.expectOne('/api/v1/config/batch').flush(body, options);

    const fieldError = el().querySelector('[data-error="slot_minutes"]');
    expect(fieldError?.textContent).toContain('divisor of 60');
    expect(testId('banner')).toBeNull();
  });

  it('keeps what was typed when a write is rejected (FR-033)', () => {
    load();
    fixture.componentInstance.edit('slot_minutes', null, '45');
    fixture.componentInstance.saveInstallation();
    const { body, options } = apiError('validation_failed', 'nope', 422);
    backend.expectOne('/api/v1/config/batch').flush(body, options);
    expect(fixture.componentInstance.pending()['slot_minutes']).toBe('45');
  });

  it('keeps what was typed when the network fails mid-write', () => {
    load();
    fixture.componentInstance.edit('poll_seconds', null, '9');
    fixture.componentInstance.saveInstallation();
    backend
      .expectOne('/api/v1/config/batch')
      .error(new ProgressEvent('error'), { status: 0, statusText: 'unknown' });
    expect(fixture.componentInstance.pending()['poll_seconds']).toBe('9');
    expect(testId('banner')?.textContent).toContain('No se puede contactar');
  });

  it('explains a rejected secret and where secrets belong', () => {
    load();
    fixture.componentInstance.edit('log_level', null, 'postgresql://u:p@h/d');
    fixture.componentInstance.saveInstallation();
    const { body, options } = apiError(
      'secret_rejected',
      'that looks like a credential; serve it through an environment variable',
      422,
      'log_level',
    );
    backend.expectOne('/api/v1/config/batch').flush(body, options);
    expect(testId('banner')?.textContent).toContain('environment variable');
  });

  /**
   * A field-scoped rejection for a field with no input on screen must not vanish.
   * The operator seeing nothing at all is worse than a generic banner.
   */
  it('falls back to the banner when the field is not on screen', () => {
    load();
    fixture.componentInstance.edit('state_file', null, 'postgresql://u:p@h/d');
    fixture.componentInstance.submit('state_file', null);
    const { body, options } = apiError(
      'secret_rejected',
      'that looks like a credential; serve it through an environment variable',
      422,
    );
    backend.expectOne('/api/v1/config').flush(body, options);
    expect(testId('banner')?.textContent).toContain('environment variable');
  });

  /* -------------------------------------------------------------- conflict */

  it('reports a conflict and offers to re-read, without retrying', () => {
    load();
    fixture.componentInstance.edit('poll_seconds', null, '7');
    fixture.componentInstance.saveInstallation();
    const { body, options } = apiError(
      'config_conflict',
      'the configuration changed while the edit was being prepared',
      409,
    );
    backend.expectOne('/api/v1/config/batch').flush(body, options);

    // No automatic retry: nothing else was sent.
    backend.expectNone((candidate) => candidate.method === 'PATCH');
    const banner = testId('banner');
    expect(banner?.textContent).toContain('cambió');
    expect(banner?.textContent).toContain('No se ha sobrescrito');
    expect(testId('reread')).not.toBeNull();
  });

  it('re-reads on request after a conflict', () => {
    load();
    fixture.componentInstance.edit('poll_seconds', null, '7');
    fixture.componentInstance.saveInstallation();
    const { body, options } = apiError('config_conflict', 'changed', 409);
    backend.expectOne('/api/v1/config/batch').flush(body, options);

    fixture.componentInstance.load();
    backend.expectOne('/api/v1/config').flush(configDto({ config_revision: 9 }));
    expect(el().textContent).toContain('rev. 9');
  });

  /* --------------------------------------------------------------- CRUD */

  it('reads the alert catalogue when the email section is selected and silences one alert', () => {
    loadUnified();
    fixture.componentInstance.chooseArea('integrations');
    fixture.componentInstance.chooseIntegration('email');
    backend.expectOne('/api/v1/system/alerts').flush({
      alerts: [{ name: 'plan_recalculation_invalid', title: 'Replanificación imposible', description: 'x', enabled: true }],
    });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="alert-catalogue"]')).not.toBeNull();

    fixture.componentInstance.toggleAlert('plan_recalculation_invalid', false);
    const request = backend.expectOne('/api/v1/system/alerts/plan_recalculation_invalid');
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({ enabled: false });
    request.flush({
      alerts: [{ name: 'plan_recalculation_invalid', title: 'Replanificación imposible', description: 'x', enabled: false }],
    });

    expect(fixture.componentInstance.alertCatalogue()[0].enabled).toBe(false);
    // Selecting the section again does not re-read a catalogue it already has.
    fixture.componentInstance.chooseIntegration('email');
    backend.expectNone('/api/v1/system/alerts');
  });

  it('reports the outcome of the email test send', () => {
    loadUnified();
    fixture.componentInstance.testEmail();
    backend.expectOne('/api/v1/system/tests/email').flush({ ok: true, host: 'smtp.example.org', port: 587 });
    expect(fixture.componentInstance.emailTestMessage()).toContain('prueba');

    fixture.componentInstance.testEmail();
    backend.expectOne('/api/v1/system/tests/email').flush(
      { code: 'connection_test_failed', message: 'email test failed (connection refused)' },
      { status: 503, statusText: 'Service Unavailable' },
    );
    expect(fixture.componentInstance.emailTestError()).toContain('connection refused');
  });

  it('sends the email recipients as a list and a blank sender as absent', () => {
    loadUnified();
    fixture.componentInstance.chooseArea('integrations');
    fixture.componentInstance.chooseIntegration('email');
    backend.expectOne('/api/v1/system/alerts').flush({ alerts: [] });
    fixture.componentInstance.systemEdit('email', 'recipients', 'uno@example.org, dos@example.org');
    fixture.componentInstance.systemEdit('email', 'sender', '');
    fixture.componentInstance.requestSystemSave('email');
    fixture.componentInstance.confirmSystemSave();

    const request = backend.expectOne('/api/v1/system/configuration/email');
    expect(request.request.body.values).toMatchObject({
      recipients: ['uno@example.org', 'dos@example.org'],
      sender: null,
    });
  });

  it('creates an accumulator with the configuration revision', () => {
    load();
    fixture.componentInstance.openAddHeater();
    fixture.componentInstance.updateHeaterForm('id', 'cocina');
    fixture.componentInstance.updateHeaterForm('power_kw', '1.2');
    fixture.componentInstance.updateHeaterForm('full_charge_hours', '7');
    fixture.componentInstance.saveHeater();
    const request = backend.expectOne('/api/v1/config/heaters');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toMatchObject({ revision: 3, id: 'cocina', power_kw: 1.2, full_charge_hours: 7 });
    request.flush(change({ action: 'add', entity: 'heater', entity_key: 'cocina' }));
    backend.expectOne('/api/v1/config').flush(configDto({ config_revision: 4 }));
    expect(fixture.componentInstance.heaterForm()).toBeNull();
  });

  it('rejects discharge figures outside their physical range', () => {
    load();
    fixture.componentInstance.openEditHeater(fixture.componentInstance.config()!.heaters[0]);
    fixture.componentInstance.updateHeaterForm('full_discharge_hours', '0');
    fixture.componentInstance.saveHeater();
    expect(fixture.componentInstance.heaterFormError()).toContain('descarga nominal');

    fixture.componentInstance.updateHeaterForm('full_discharge_hours', '10');
    fixture.componentInstance.updateHeaterForm('static_emission_percent', '120');
    fixture.componentInstance.saveHeater();
    expect(fixture.componentInstance.heaterFormError()).toContain('emisión residual');
  });

  it('edits an accumulator and advances the revision returned by each field write', () => {
    load();
    fixture.componentInstance.openEditHeater(fixture.componentInstance.config()!.heaters[0]);
    fixture.componentInstance.updateHeaterForm('room_heat_loss_kw_per_c', '0.2');
    fixture.componentInstance.saveHeater();
    const request = backend.expectOne('/api/v1/config/heaters/salon');
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toMatchObject({ revision: 3, room_heat_loss_kw_per_c: 0.2, power_kw: 2.8, full_charge_hours: 8, full_discharge_hours: 10, static_emission_percent: 20 });
    request.flush(change({ entity: 'heater', entity_key: 'salon', field: null, revision_after: 4 }));
    backend.expectOne('/api/v1/config').flush(configDto({ config_revision: 4 }));
    expect(fixture.componentInstance.heaterForm()).toBeNull();
  });

  it('cancels the accumulator form without writing', () => {
    load();
    fixture.componentInstance.openAddHeater();
    fixture.componentInstance.updateHeaterForm('id', 'cocina');
    fixture.componentInstance.cancelHeaterForm();
    backend.expectNone((candidate) => candidate.method === 'POST' || candidate.method === 'PATCH');
    expect(fixture.componentInstance.heaterForm()).toBeNull();
  });

  it('removes an accumulator with the current revision', () => {
    load();
    fixture.componentInstance.removeHeater('salon');
    const request = backend.expectOne((candidate) => candidate.method === 'DELETE' && candidate.url === '/api/v1/config/heaters/salon');
    expect(request.request.method).toBe('DELETE');
    expect(request.request.params.get('revision')).toBe('3');
    request.flush(change({ action: 'remove', entity: 'heater', entity_key: 'salon' }));
    backend.expectOne('/api/v1/config').flush(configDto({ config_revision: 4, heaters: [] }));
  });

  afterEach(() => {
    backend.match(() => true);
  });
});
