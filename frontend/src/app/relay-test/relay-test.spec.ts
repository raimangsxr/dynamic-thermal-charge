import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import type { ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RelayTestHeaterDto, RelayTestViewDto } from '../core/api.types';
import { RelayTest } from './relay-test';

type Session = NonNullable<RelayTestViewDto['session']>;

const HEATER: RelayTestHeaterDto = {
  id: 'salon', name: 'Salón', position: 0, power_w: 2800,
  desired_state: false, confirmed_state: false, result: 'confirmed', result_code: null, confirmed_at: '2026-01-01T00:00:02Z',
};

const ACTIVE_SESSION: Session = {
  id: 'session-1', status: 'active', owner: true,
  requested_at: '2026-01-01T00:00:00Z', activated_at: '2026-01-01T00:00:02Z', ended_at: null,
  lease_expires_at: '2026-01-01T00:00:30Z', end_reason: null,
};

function view(overrides: Partial<RelayTestViewDto> = {}): RelayTestViewDto {
  return {
    session: null,
    controller: { state_is_current: true, last_seen_at: '2026-01-01T00:00:02Z' },
    safety: { automatic_control_blocked: false, fault_latched: false, fault_session_id: null, fault_reason: null, fault_latched_at: null, fault_recovery_attempted_at: null, fault_recovered_at: null },
    audit: { degraded: false, degraded_since: null },
    state_poll_seconds: 1,
    lease_renew_seconds: 5,
    heaters: [],
    ...overrides,
  };
}

describe('RelayTest', () => {
  let backend: HttpTestingController;
  let fixture: ComponentFixture<RelayTest>;

  beforeEach(async () => {
    TestBed.resetTestingModule();
    sessionStorage.clear();
    vi.useFakeTimers();
    await TestBed.configureTestingModule({
      imports: [RelayTest],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    backend.verify();
    vi.useRealTimers();
  });

  function create(initial: RelayTestViewDto | null = view()): HTMLElement {
    fixture = TestBed.createComponent(RelayTest);
    fixture.detectChanges();
    const storedId = sessionStorage.getItem('dtc.relay-test.id');
    backend.expectOne(storedId ? `/api/v1/relay-test/${storedId}` : '/api/v1/relay-test').flush(initial);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('shows a guided empty state and does not poll a stable installation', () => {
    const element = create();

    vi.advanceTimersByTime(2000);

    backend.expectNone('/api/v1/relay-test');
    expect(element.textContent).toContain('Entrar en modo test');
    expect(element.textContent).toContain('Antes de empezar');
  });

  it('keeps terminal results readable and offers a new test', () => {
    sessionStorage.setItem('dtc.relay-test.id', 'terminal-id');
    const element = create(view({
      session: { ...ACTIVE_SESSION, id: 'terminal-id', status: 'ended', owner: false, ended_at: '2026-01-01T00:01:00Z', end_reason: 'owner_finished' },
    }));

    expect(element.textContent).toContain('Prueba finalizada');
    expect(element.querySelector('[data-testid="start-another-relay-test"]')).not.toBeNull();
    expect(element.textContent).not.toContain('· ended');
  });

  it('requires confirmation before starting and prevents duplicate start requests', async () => {
    const element = create();
    const start = element.querySelector<HTMLButtonElement>('[data-testid="start-relay-test"]');

    start?.click();
    start?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    expect(document.querySelector('mat-dialog-container')?.textContent).toContain('Iniciar prueba de relés');
    document.querySelector<HTMLButtonElement>('[data-testid="confirm-cancel"]')?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    backend.expectNone((candidate) => candidate.method === 'POST' && candidate.url === '/api/v1/relay-test');

    start?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    document.querySelector<HTMLButtonElement>('[data-testid="confirm-delete"]')?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    const request = backend.expectOne((candidate) => candidate.method === 'POST' && candidate.url === '/api/v1/relay-test');
    request.flush({ session_id: 'session-1', client_credential: 'credential', status: 'starting', lease_expires_at: '2026-01-01T00:00:30Z', state_poll_seconds: 2, lease_renew_seconds: 7 });
    backend.expectOne('/api/v1/relay-test/session-1').flush(view({ session: ACTIVE_SESSION, state_poll_seconds: 2, lease_renew_seconds: 7, heaters: [HEATER] }));
    fixture.detectChanges();

    vi.advanceTimersByTime(1999);
    backend.expectNone('/api/v1/relay-test/session-1');
    vi.advanceTimersByTime(1);
    backend.expectOne('/api/v1/relay-test/session-1').flush(view({ session: ACTIVE_SESSION, state_poll_seconds: 2, lease_renew_seconds: 7, heaters: [HEATER] }));
  });

  it('keeps relay controls stable while the active test is polled in the background', () => {
    sessionStorage.setItem('dtc.relay-test.id', ACTIVE_SESSION.id);
    sessionStorage.setItem('dtc.relay-test.credential', 'credential');
    const element = create(view({ session: ACTIVE_SESSION, heaters: [HEATER] }));
    const button = element.querySelector<HTMLButtonElement>('[data-command="salon"]');

    expect(button?.disabled).toBe(false);
    vi.advanceTimersByTime(1000);
    fixture.detectChanges();

    const poll = backend.expectOne('/api/v1/relay-test/session-1');
    expect(fixture.componentInstance.refreshing()).toBe(false);
    expect(button?.disabled).toBe(false);
    poll.flush(view({ session: ACTIVE_SESSION, heaters: [HEATER] }));
  });

  it('keeps lease renewal independent and uses its configured interval', () => {
    sessionStorage.setItem('dtc.relay-test.id', ACTIVE_SESSION.id);
    sessionStorage.setItem('dtc.relay-test.credential', 'credential');
    create(view({ session: ACTIVE_SESSION, state_poll_seconds: 20, lease_renew_seconds: 7, heaters: [HEATER] }));

    vi.advanceTimersByTime(6999);
    backend.expectNone((candidate) => candidate.method === 'POST' && candidate.url.endsWith('/lease'));
    vi.advanceTimersByTime(1);

    const lease = backend.expectOne((candidate) => candidate.method === 'POST' && candidate.url === '/api/v1/relay-test/session-1/lease');
    expect(lease.request.headers.get('X-Relay-Test-Credential')).toBe('credential');
    lease.flush(view({ session: ACTIVE_SESSION, state_poll_seconds: 20, lease_renew_seconds: 7, heaters: [HEATER] }));
  });

  it('requires confirmation and disables a relay while its command is waiting for confirmation', async () => {
    sessionStorage.setItem('dtc.relay-test.id', ACTIVE_SESSION.id);
    sessionStorage.setItem('dtc.relay-test.credential', 'credential');
    const element = create(view({ session: ACTIVE_SESSION, heaters: [HEATER] }));
    const button = element.querySelector<HTMLButtonElement>('[data-command="salon"]');
    button?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    expect(document.querySelector('mat-dialog-container')?.textContent).toContain('Encender Salón');
    document.querySelector<HTMLButtonElement>('[data-testid="confirm-cancel"]')?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    backend.expectNone((candidate) => candidate.method === 'PUT');

    button?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    document.querySelector<HTMLButtonElement>('[data-testid="confirm-delete"]')?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();

    const request = backend.expectOne((candidate) => candidate.method === 'PUT' && candidate.url === '/api/v1/relay-test/session-1/heaters/salon');
    expect(request.request.headers.get('X-Relay-Test-Credential')).toBe('credential');
    request.flush({ heater_id: 'salon', desired_state: true, result: 'pending', command_seq: 1 });
    backend.expectOne('/api/v1/relay-test/session-1').flush(view({
      session: ACTIVE_SESSION,
      heaters: [{ ...HEATER, desired_state: true, confirmed_state: false, result: 'pending', confirmed_at: HEATER.confirmed_at }],
    }));
    fixture.detectChanges();

    expect((element.querySelector('[data-command="salon"]') as HTMLButtonElement).disabled).toBe(true);
    expect(element.textContent).toContain('Esperando confirmación');
    expect(element.textContent).toContain('Se ha solicitado encender esta salida.');
  });

  it('requires confirmation before ending a relay test and preserves it when cancelled', async () => {
    sessionStorage.setItem('dtc.relay-test.id', ACTIVE_SESSION.id);
    sessionStorage.setItem('dtc.relay-test.credential', 'credential');
    const element = create(view({ session: ACTIVE_SESSION, heaters: [HEATER] }));
    element.querySelector<HTMLButtonElement>('[data-testid="end-relay-test"]')?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    expect(document.querySelector('mat-dialog-container')?.textContent).toContain('Finalizar prueba de relés');
    document.querySelector<HTMLButtonElement>('[data-testid="confirm-cancel"]')?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    backend.expectNone((candidate) => candidate.method === 'DELETE' && candidate.url === '/api/v1/relay-test/session-1');
    expect(fixture.componentInstance.view()?.session?.status).toBe('active');

    element.querySelector<HTMLButtonElement>('[data-testid="end-relay-test"]')?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    document.querySelector<HTMLButtonElement>('[data-testid="confirm-delete"]')?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    const request = backend.expectOne((candidate) => candidate.method === 'DELETE' && candidate.url === '/api/v1/relay-test/session-1');
    expect(request.request.headers.get('X-Relay-Test-Credential')).toBe('credential');
    request.flush({});
    backend.expectOne('/api/v1/relay-test/session-1').flush(view({ session: { ...ACTIVE_SESSION, status: 'ending' }, heaters: [HEATER] }));
    expect(document.querySelector('.dtc-snackbar-container')?.textContent).toContain('Solicitud de finalización');
  });

  it('explains a power-limit rejection next to the relay action and in a snackbar', async () => {
    sessionStorage.setItem('dtc.relay-test.id', ACTIVE_SESSION.id);
    sessionStorage.setItem('dtc.relay-test.credential', 'credential');
    const element = create(view({ session: ACTIVE_SESSION, heaters: [HEATER] }));
    element.querySelector<HTMLButtonElement>('[data-command="salon"]')?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();
    document.querySelector<HTMLButtonElement>('[data-testid="confirm-delete"]')?.click();
    vi.advanceTimersByTime(100);
    await fixture.whenStable();

    const command = backend.expectOne((candidate) => candidate.method === 'PUT');
    command.flush(
      { code: 'relay_test_power_limit', message: 'límite', field: null, heater_id: 'salon' },
      { status: 409, statusText: 'Conflict' },
    );
    backend.expectOne('/api/v1/relay-test/session-1').flush(view({ session: ACTIVE_SESSION, heaters: [{ ...HEATER, desired_state: true, result: 'rejected', result_code: 'power_limit' }] }));
    fixture.detectChanges();

    expect(document.querySelector('.dtc-snackbar-container')?.textContent).toContain('Se supera el límite de potencia');
    expect(document.querySelector('.dtc-snackbar-container')?.textContent).toContain('Apaga otra salida confirmada');
    expect(element.textContent).toContain('Orden rechazada');
  });

  it('keeps an external session in read-only mode', () => {
    const element = create(view({ session: { ...ACTIVE_SESSION, owner: false }, heaters: [HEATER] }));

    const button = element.querySelector<HTMLButtonElement>('[data-command="salon"]');
    expect(button?.disabled).toBe(true);
    expect(button?.textContent).toContain('Solo consulta');
    expect(element.textContent).toContain('Otra pestaña controla la prueba');
  });

  it('blocks commands when the controller state is not current', () => {
    const element = create(view({ session: ACTIVE_SESSION, controller: { state_is_current: false, last_seen_at: '2026-01-01T00:00:02Z' }, heaters: [HEATER] }));

    expect(element.querySelector('[data-testid="controller-warning"]')).not.toBeNull();
    expect((element.querySelector('[data-command="salon"]') as HTMLButtonElement).disabled).toBe(true);
    expect(element.textContent).toContain('Bloqueado: el controlador no tiene un estado reciente.');
  });

  it('does not offer to start while safety recovery is latched', () => {
    const element = create(view({ safety: { automatic_control_blocked: true, fault_latched: true, fault_session_id: 'failed', fault_reason: 'off_sweep_failed', fault_latched_at: '2026-01-01T00:00:00Z', fault_recovery_attempted_at: null, fault_recovered_at: null } }));

    expect(element.querySelector('[data-testid="safety-latch"]')).not.toBeNull();
    expect(element.textContent).toContain('No limpies este bloqueo desde el panel');
    expect(element.querySelector('[data-testid="start-relay-test"]')).toBeNull();
  });
});
