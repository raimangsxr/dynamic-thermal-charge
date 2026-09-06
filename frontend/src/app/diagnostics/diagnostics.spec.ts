import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import type { ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ControllerLogEventDto, ControllerLogPageDto } from '../core/api.types';
import { Diagnostics } from './diagnostics';

function event(overrides: Partial<ControllerLogEventDto> = {}): ControllerLogEventDto {
  return {
    id: 10,
    occurred_at: '2026-01-16T01:00:00Z',
    level: 'INFO',
    logger: 'controller',
    message: 'Plan actualizado',
    ...overrides,
  };
}

function page(items: ControllerLogEventDto[], nextBeforeId: number | null = null): ControllerLogPageDto {
  return {
    items,
    limit_applied: 100,
    has_more: nextBeforeId !== null,
    next_before_id: nextBeforeId,
  };
}

describe('Diagnostics', () => {
  let fixture: ComponentFixture<Diagnostics>;
  let backend: HttpTestingController;

  beforeEach(async () => {
    TestBed.resetTestingModule();
    vi.useFakeTimers();
    await TestBed.configureTestingModule({
      imports: [Diagnostics],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    fixture = TestBed.createComponent(Diagnostics);
    backend = TestBed.inject(HttpTestingController);
  });

  function element(): HTMLElement {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  function initial(events: ControllerLogEventDto[], nextBeforeId: number | null = null): HTMLElement {
    const root = element();
    const request = backend.expectOne((candidate) => candidate.url === '/api/v1/controller-log');
    expect(request.request.params.get('limit')).toBe('100');
    request.flush(page(events, nextBeforeId));
    fixture.detectChanges();
    return root;
  }

  it('shows an explicit loading state before the first event page', () => {
    expect(element().querySelector('[data-testid="diagnostics-loading"]')).not.toBeNull();
  });

  it('shows a readable event panel with level and source', () => {
    const root = initial([event({ level: 'WARNING', logger: 'mqtt', message: 'Heartbeat retrasado' })]);

    expect(root.querySelector('[data-testid="events-table"]')).not.toBeNull();
    expect(root.querySelector('[data-level="WARNING"]')?.textContent).toContain('Heartbeat retrasado');
    expect(root.textContent).toContain('WARNING');
    expect(root.textContent).toContain('mqtt');
    expect(root.querySelector('[data-testid="diagnostics-empty"]')).toBeNull();
  });

  it('sends the selected level and text query when filters are applied', () => {
    initial([event()]);
    fixture.componentInstance.level.set('ERROR');
    fixture.componentInstance.query.set('base de datos');
    fixture.componentInstance.apply();

    const request = backend.expectOne((candidate) => candidate.url === '/api/v1/controller-log');
    expect(request.request.params.get('level')).toBe('ERROR');
    expect(request.request.params.get('q')).toBe('base de datos');
    request.flush(page([event({ id: 9, level: 'ERROR', message: 'Error de base de datos' })]));
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Error de base de datos');
  });

  it('refreshes visible events after the newest id', () => {
    initial([event({ id: 10 })]);

    vi.advanceTimersByTime(5000);
    const request = backend.expectOne((candidate) => candidate.url === '/api/v1/controller-log');
    expect(request.request.params.get('after_id')).toBe('10');
    request.flush(page([event({ id: 11, message: 'Nuevo evento' })]));
    fixture.detectChanges();

    const rows = (fixture.nativeElement as HTMLElement).querySelectorAll('[data-testid="events-table"] tbody tr');
    expect(rows[0].textContent).toContain('Nuevo evento');
    expect(rows.length).toBe(2);
  });

  it('appends older events using the server cursor', () => {
    initial([event({ id: 10 })], 7);
    fixture.componentInstance.load(7);

    const request = backend.expectOne((candidate) => candidate.url === '/api/v1/controller-log');
    expect(request.request.params.get('before_id')).toBe('7');
    request.flush(page([event({ id: 6, message: 'Evento anterior' })]));
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Evento anterior');
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-testid="load-older"]')).toBeNull();
  });

  it('shows an intentional empty state', () => {
    const root = initial([]);
    expect(root.querySelector('[data-testid="diagnostics-empty"]')).not.toBeNull();
    expect(root.textContent).toContain('No hay eventos');
  });

  it('shows a recoverable error without presenting an empty result as success', () => {
    const root = element();
    backend.expectOne((candidate) => candidate.url === '/api/v1/controller-log').flush(
      { code: 'store_unavailable', message: 'unavailable', field: null, heater_id: null },
      { status: 503, statusText: 'Service Unavailable' },
    );
    fixture.detectChanges();

    expect(root.querySelector('[data-testid="diagnostics-error"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="diagnostics-empty"]')).toBeNull();
    expect(root.querySelector('[data-testid="retry-diagnostics"]')).not.toBeNull();
  });

  afterEach(() => {
    backend.match(() => true);
    fixture.destroy();
    vi.useRealTimers();
  });
});
