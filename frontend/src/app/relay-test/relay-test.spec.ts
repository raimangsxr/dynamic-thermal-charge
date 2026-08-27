import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RelayTestViewDto } from '../core/api.types';
import { RelayTest } from './relay-test';

const VIEW: RelayTestViewDto = {
  session: null,
  controller: { state_is_current: true, last_seen_at: '2026-01-01T00:00:00Z' },
  safety: { automatic_control_blocked: false, fault_latched: false, fault_session_id: null, fault_reason: null, fault_latched_at: null, fault_recovery_attempted_at: null, fault_recovered_at: null },
  audit: { degraded: false, degraded_since: null }, heaters: [],
};

describe('RelayTest', () => {
  let backend: HttpTestingController;
  beforeEach(async () => {
    sessionStorage.clear();
    vi.useFakeTimers();
    await TestBed.configureTestingModule({ imports: [RelayTest], providers: [provideHttpClient(), provideHttpClientTesting()] }).compileComponents();
    backend = TestBed.inject(HttpTestingController);
  });

  it('does not poll after a stable terminal-free view, and explains an empty installation', () => {
    const fixture = TestBed.createComponent(RelayTest);
    fixture.detectChanges();
    backend.expectOne('/api/v1/relay-test').flush(VIEW);
    fixture.detectChanges();
    vi.advanceTimersByTime(2000);
    backend.expectNone('/api/v1/relay-test');
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Entrar en modo test');
  });

  it('recovers the terminal result using the stored session id', () => {
    sessionStorage.setItem('dtc.relay-test.id', 'terminal-id');
    const fixture = TestBed.createComponent(RelayTest);
    fixture.detectChanges();
    backend.expectOne('/api/v1/relay-test/terminal-id').flush({ ...VIEW, session: { id: 'terminal-id', status: 'ended', owner: false, requested_at: '2026-01-01T00:00:00Z', activated_at: null, ended_at: '2026-01-01T00:01:00Z', lease_expires_at: null, end_reason: 'owner_finished' } });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('ended');
  });

  afterEach(() => { backend.verify(); vi.useRealTimers(); });
});
