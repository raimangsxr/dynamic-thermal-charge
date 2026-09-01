/** Editing over HTTP: FR-017 to FR-023, FR-033, SC-005, SC-006. */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { ApiErrorCode, ChangeDto, ConfigDto } from '../core/api.types';
import { Config } from './config';
import { ELECTRICAL_FIELDS, needsConfirmation } from './electrical-fields';

function configDto(overrides: Partial<ConfigDto> = {}): ConfigDto {
  return {
    config_revision: 3,
    schema_revision: '0003_indoor_temperature',
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
        target_charge: 1,
        reserve_percent: 0,
        demand_factor: 1,
        priority: 90,
        enabled: true,
        indoor_topic: null,
        temperature_topic: null,
        target_temperature_topic: null,
        stored_charge_topic: null,
        output: { kind: 'gpio', pin: 17, active_high: false },
      },
    ],
    ...overrides,
  };
}

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

  it('shows the configuration with its revisions', () => {
    const element = load();
    expect(element.textContent).toContain('rev. 3');
    expect(element.textContent).toContain('0003_indoor_temperature');
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
    fixture.componentInstance.updateHeaterForm('target_charge', '0.8');
    fixture.componentInstance.saveHeater();
    const request = backend.expectOne('/api/v1/config/heaters/salon');
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toMatchObject({ revision: 3, target_charge: 0.8 });
    request.flush(change({ entity: 'heater', entity_key: 'salon' }));
    backend.expectOne('/api/v1/config').flush(configDto());
  });

  it('renders all indoor policy fields and the per-heater topic', () => {
    const element = load(
      configDto({
        heaters: [
          { ...configDto().heaters[0], indoor_topic: 'ha/salon/temp' },
        ],
      }),
    );
    for (const field of [
      'indoor_max_age_minutes',
      'indoor_min_plausible_c',
      'indoor_max_plausible_c',
    ]) {
      expect(element.querySelector(`[data-field="${field}"]`)).not.toBeNull();
    }
    fixture.componentInstance.openEditHeater(fixture.componentInstance.config()!.heaters[0]);
    fixture.detectChanges();
    const topic = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>('[name="indoor_topic"]');
    expect(topic).not.toBeNull();
    expect(
      fixture.componentInstance.heaterText(
        fixture.componentInstance.config()!.heaters[0],
        'indoor_topic',
      ),
    ).toBe('ha/salon/temp');
  });

  it('sends an empty indoor topic and keeps it on rejection', () => {
    load(configDto({ heaters: [{ ...configDto().heaters[0], indoor_topic: 'ha/old' }] }));
    fixture.componentInstance.openEditHeater(fixture.componentInstance.config()!.heaters[0]);
    fixture.componentInstance.updateHeaterForm('indoor_topic', '');
    fixture.componentInstance.saveHeater();
    const request = backend.expectOne('/api/v1/config/heaters/salon');
    expect(request.request.body).toMatchObject({
      revision: 3,
      indoor_topic: null,
    });
    const { body, options } = apiError('validation_failed', 'invalid topic', 422);
    request.flush(body, options);
    expect(fixture.componentInstance.heaterForm()).not.toBeNull();
    expect(el().querySelector('[data-testid="heater-form-error"]')).not.toBeNull();
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

    it.each(['poll_seconds', 'slot_minutes', 'priority', 'target_charge', 'log_level'])(
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
    expect(el().querySelector('[data-error="log_level"]')?.textContent).toContain(
      'environment variable',
    );
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

  it('edits an accumulator and advances the revision returned by each field write', () => {
    load();
    fixture.componentInstance.openEditHeater(fixture.componentInstance.config()!.heaters[0]);
    fixture.componentInstance.updateHeaterForm('target_charge', '0.8');
    fixture.componentInstance.saveHeater();
    const request = backend.expectOne('/api/v1/config/heaters/salon');
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toMatchObject({ revision: 3, target_charge: 0.8, reserve_percent: 0, power_kw: 2.8, full_charge_hours: 8 });
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
