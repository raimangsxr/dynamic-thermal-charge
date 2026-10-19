import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ConfigDto, RoomDto } from '../core/api.types';
import { Calibration } from './calibration';

const VALID_VAPID_PUBLIC_KEY = 'BAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const COMPRESSED_VAPID_PUBLIC_KEY = 'AgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

function configDto(): ConfigDto {
  return {
    config_revision: 7,
    schema_revision: '0023_coherent_mqtt_topics',
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
    schedule: null,
    heaters: [{
      id: 'salon',
      name: 'Salón',
      model: null,
      power_kw: 2.8,
      full_charge_hours: 8,
      full_discharge_hours: 10,
      static_emission_percent: 20,
      room_thermal_capacity_kwh_per_c: 2.5,
      room_heat_loss_kw_per_c: 0.12,
      priority: 90,
      enabled: true,
      temperature_targets: [],
      output: { kind: 'simulated', pin: null, active_high: true },
    }],
  };
}

function roomDto(overrides: Partial<RoomDto> = {}): RoomDto {
  return {
    heater_id: 'salon',
    capacity_kwh_per_c: 1.234,
    loss_kw_per_c: 0.456,
    status: 'estimated',
    terminal_result: null,
    terminal_cause: null,
    terminal_at: null,
    applied_session_id: null,
    session: null,
    quality: null,
    input_ages_minutes: {
      indoor_temperature: 1,
      soc: 2,
      outdoor_temperature: 3,
    },
    ...overrides,
  };
}

describe('Calibration', () => {
  let fixture: ComponentFixture<Calibration>;
  let backend: HttpTestingController;

  beforeEach(async () => {
    TestBed.resetTestingModule();
    await TestBed.configureTestingModule({
      imports: [Calibration],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    fixture = TestBed.createComponent(Calibration);
    backend = TestBed.inject(HttpTestingController);
  });

  function load(room: RoomDto = roomDto()): HTMLElement {
    fixture.detectChanges();
    backend.expectOne('/api/v1/config').flush(configDto());
    backend.expectOne('/api/v1/rooms/salon').flush(room);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('rounds capacity and loss only in the visual summary', () => {
    const element = load();
    const summary = element.querySelector('dl');

    expect(summary?.textContent).toContain('1.23');
    expect(summary?.textContent).toContain('0.46');
    expect(summary?.textContent).not.toContain('1.234');
    expect(summary?.textContent).not.toContain('0.456');
    expect(fixture.componentInstance.cards()[0]?.room.capacity_kwh_per_c).toBe(1.234);
    expect(fixture.componentInstance.cards()[0]?.room.loss_kw_per_c).toBe(0.456);
  });

  it('keeps the unrounded numeric values when saving edited coefficients', () => {
    load();
    const card = fixture.componentInstance.cards()[0];
    if (!card) throw new Error('missing calibration card');
    card.room.capacity_kwh_per_c = 1.2349;
    card.room.loss_kw_per_c = 0.4567;

    fixture.componentInstance.saveAdvanced(card);
    const request = backend.expectOne('/api/v1/rooms/salon');
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toMatchObject({
      expected_revision: 7,
      capacity_kwh_per_c: 1.2349,
      loss_kw_per_c: 0.4567,
    });
    request.flush(roomDto({ capacity_kwh_per_c: 1.2349, loss_kw_per_c: 0.4567 }));
  });

  it('removes the local global-alert-tray link while keeping the global shell navigation', () => {
    const element = load();
    expect(element.querySelector('a[href="/avisos"]')).toBeNull();
  });

  it('reports a localized context failure without exposing technical status codes', async () => {
    load();
    vi.stubGlobal('isSecureContext', false);

    await fixture.componentInstance.registerPush();
    fixture.detectChanges();

    const status = elementText(fixture.nativeElement as HTMLElement, '[data-push-status]');
    expect(status).toContain('HTTPS');
    expect(status.toLowerCase()).not.toContain('unsupported');
  });

  it('reports a localized browser capability failure when standard APIs are absent', async () => {
    load();

    await fixture.componentInstance.registerPush();
    fixture.detectChanges();

    const status = elementText(fixture.nativeElement as HTMLElement, '[data-push-status]');
    expect(status).toContain('navegador');
    expect(status.toLowerCase()).not.toContain('unsupported');
  });

  it('distinguishes a denied notification permission and does not prompt again', async () => {
    load();
    const { requestPermission } = installPushApis('denied');

    await fixture.componentInstance.registerPush();
    fixture.detectChanges();

    expect(requestPermission).not.toHaveBeenCalled();
    const status = elementText(fixture.nativeElement as HTMLElement, '[data-push-status]');
    expect(status).toContain('bloqueados');
    expect(status.toLowerCase()).not.toContain('unsupported');
  });

  it('explains when the server has no VAPID public key', async () => {
    load();
    installPushApis('granted');

    const activation = fixture.componentInstance.registerPush();
    const keyRequest = backend.expectOne('/api/v1/push/public-key');
    keyRequest.flush({ public_key: null });
    await activation;
    fixture.detectChanges();

    const status = elementText(fixture.nativeElement as HTMLElement, '[data-push-status]');
    expect(status).toContain('clave pública');
    expect(status).toContain('Configúrala');
    expect(status.toLowerCase()).not.toContain('unsupported');
  });

  it('reports subscription errors separately from browser capability failures', async () => {
    load();
    const { register } = installPushApis('granted');
    register.mockRejectedValue(new Error('service worker failed'));

    const activation = fixture.componentInstance.registerPush();
    backend.expectOne('/api/v1/push/public-key').flush({ public_key: VALID_VAPID_PUBLIC_KEY });
    await activation;
    fixture.detectChanges();

    const status = elementText(fixture.nativeElement as HTMLElement, '[data-push-status]');
    expect(status).toContain('suscribir');
    expect(status.toLowerCase()).not.toContain('unsupported');
  });

  it('rejects short and compressed VAPID public keys before subscribing', async () => {
    load();
    const { register } = installPushApis('granted');

    for (const publicKey of ['AQID', COMPRESSED_VAPID_PUBLIC_KEY]) {
      const activation = fixture.componentInstance.registerPush();
      backend.expectOne('/api/v1/push/public-key').flush({ public_key: publicKey });
      await activation;
      fixture.detectChanges();

      expect(register).not.toHaveBeenCalled();
      expect(fixture.componentInstance.pushStatus()).toBe('server-invalid-key');
      expect(elementText(fixture.nativeElement as HTMLElement, '[data-push-status]').toLowerCase()).not.toContain('unsupported');
    }
  });

  it('maps the backend configuration status to the localized server state', async () => {
    load();
    installPushApis('granted');

    const activation = fixture.componentInstance.registerPush();
    backend.expectOne('/api/v1/push/public-key').flush({ public_key: VALID_VAPID_PUBLIC_KEY });
    for (let index = 0; index < 4; index += 1) await Promise.resolve();
    const registration = backend.expectOne('/api/v1/push/subscriptions');
    registration.flush({ browser_id: registration.request.body.browser_id, status: 'unsupported' });
    await activation;
    fixture.detectChanges();

    expect(fixture.componentInstance.pushStatus()).toBe('server-unconfigured');
    expect(elementText(fixture.nativeElement as HTMLElement, '[data-push-status]')).toContain('clave pública');
    expect(elementText(fixture.nativeElement as HTMLElement, '[data-push-status]').toLowerCase()).not.toContain('unsupported');
  });

  it('completes a compatible standard Web Push activation and registers its keys', async () => {
    load();
    installPushApis('granted');

    const activation = fixture.componentInstance.registerPush();
    backend.expectOne('/api/v1/push/public-key').flush({ public_key: VALID_VAPID_PUBLIC_KEY });
    for (let index = 0; index < 4; index += 1) await Promise.resolve();
    const registration = backend.expectOne('/api/v1/push/subscriptions');
    expect(registration.request.method).toBe('POST');
    expect(registration.request.body.endpoint).toBe('https://push.example/subscription');
    expect(registration.request.body.keys).toEqual({ p256dh: 'p256dh', auth: 'auth' });
    registration.flush({ browser_id: registration.request.body.browser_id, status: 'active' });
    await activation;
    fixture.detectChanges();

    expect(elementText(fixture.nativeElement as HTMLElement, '[data-push-status]')).toContain('activados');
  });

  afterEach(() => {
    backend.verify();
    vi.unstubAllGlobals();
    delete (navigator as { serviceWorker?: ServiceWorkerContainer }).serviceWorker;
  });
});

function installPushApis(permission: NotificationPermission): {
  requestPermission: ReturnType<typeof vi.fn>;
  register: ReturnType<typeof vi.fn>;
} {
  vi.stubGlobal('isSecureContext', true);
  const requestPermission = vi.fn().mockResolvedValue(permission);
  const notification = vi.fn() as unknown as { permission: NotificationPermission; requestPermission: () => Promise<NotificationPermission> };
  notification.permission = permission;
  notification.requestPermission = requestPermission;
  vi.stubGlobal('Notification', notification);
  vi.stubGlobal('PushManager', class PushManager {});

  const pushManager = {
    getSubscription: vi.fn().mockResolvedValue(null),
    subscribe: vi.fn().mockResolvedValue({
      toJSON: () => ({ endpoint: 'https://push.example/subscription', keys: { p256dh: 'p256dh', auth: 'auth' } }),
    }),
  };
  const register = vi.fn().mockResolvedValue({ pushManager });
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: { register },
  });
  return { requestPermission, register };
}

function elementText(root: HTMLElement, selector: string): string {
  return root.querySelector(selector)?.textContent?.trim() ?? '';
}
