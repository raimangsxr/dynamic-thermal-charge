import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './app';
import { Auth } from './core/auth';

describe('App shell', () => {
  beforeEach(() => {
    sessionStorage.clear();
    TestBed.resetTestingModule();
  });

  it('clears the session and navigates to login from the accessible logout action', async () => {
    const auth = TestBed.inject(Auth);
    auth.signIn('test-token');
    const fixture = TestBed.createComponent(App);
    const backend = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    backend.expectOne('/api/v1/system/topology').flush({ mode: 'normal', canonical_driver: 'sqlite', connected: true, configuration_revision: 1, pending_events: 0, administrative_writes_allowed: true, fallback_captured_at: null, last_reconciled_at: null });
    backend.expectOne('/api/v1/relay-test').flush(null);
    fixture.detectChanges();
    const logout = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-testid="logout"]');
    expect(logout?.getAttribute('aria-label')).toBe('Cerrar sesión');
    logout?.click();
    await fixture.whenStable();
    expect(auth.authenticated()).toBe(false);
    expect(TestBed.inject(Router).url).toBe('/login');
  });

  it('renders a full-width toolbar and toggles the navigation on desktop', async () => {
    const auth = TestBed.inject(Auth);
    auth.signIn('test-token');
    const fixture = TestBed.createComponent(App);
    const backend = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    backend.expectOne('/api/v1/system/topology').flush({ mode: 'normal', canonical_driver: 'sqlite', connected: true, configuration_revision: 1, pending_events: 0, administrative_writes_allowed: true, fallback_captured_at: null, last_reconciled_at: null });
    backend.expectOne('/api/v1/relay-test').flush(null);
    fixture.detectChanges();
    await fixture.whenStable();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('mat-toolbar')?.classList.contains('app-toolbar')).toBe(true);
    expect(element.querySelectorAll('a[routerLink="/configuracion"]')).toHaveLength(1);
    expect(element.querySelector('a[routerLink="/configuracion-sistema"]')).toBeNull();
    expect(element.querySelector('[data-testid="navigation-toggle"]')).not.toBeNull();
    expect(fixture.componentInstance.navigationOpen()).toBe(true);

    (element.querySelector<HTMLButtonElement>('[data-testid="navigation-toggle"]'))?.click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.componentInstance.navigationOpen()).toBe(false);
    (element.querySelector<HTMLButtonElement>('[data-testid="navigation-toggle"]'))?.click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.componentInstance.navigationOpen()).toBe(true);
  });

  it('refreshes the global alert indicator while the app remains visible', () => {
    vi.useFakeTimers();
    const auth = TestBed.inject(Auth);
    auth.signIn('test-token');
    const fixture = TestBed.createComponent(App);
    const backend = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    backend.expectOne('/api/v1/system/topology').flush({ mode: 'normal', canonical_driver: 'sqlite', connected: true, configuration_revision: 1, pending_events: 0, administrative_writes_allowed: true, fallback_captured_at: null, last_reconciled_at: null });
    backend.expectOne('/api/v1/relay-test').flush(null);
    backend.expectOne((request) => request.url === '/api/v1/alerts').flush({ items: [], view: 'active', limit_applied: 1, has_more: false, next_cursor: null, active_count: 0, maximum_severity: null });

    vi.advanceTimersByTime(5000);
    const refresh = backend.expectOne((request) => request.url === '/api/v1/alerts');
    refresh.flush({ items: [], view: 'active', limit_applied: 1, has_more: false, next_cursor: null, active_count: 2, maximum_severity: 'warning' });
    fixture.detectChanges();

    expect(fixture.componentInstance.alertSummary()?.active_count).toBe(2);
    fixture.destroy();
    vi.useRealTimers();
  });

  it('starts the global alert indicator after login without recreating the shell', () => {
    const fixture = TestBed.createComponent(App);
    const auth = TestBed.inject(Auth);
    const backend = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    auth.signIn('test-token');
    fixture.detectChanges();
    backend.expectOne('/api/v1/system/topology').flush({ mode: 'normal', canonical_driver: 'sqlite', connected: true, configuration_revision: 1, pending_events: 0, administrative_writes_allowed: true, fallback_captured_at: null, last_reconciled_at: null });
    backend.expectOne('/api/v1/relay-test').flush(null);
    backend.expectOne((request) => request.url === '/api/v1/alerts').flush({ items: [], view: 'active', limit_applied: 1, has_more: false, next_cursor: null, active_count: 3, maximum_severity: 'critical' });
    fixture.detectChanges();

    expect(fixture.componentInstance.alertSummary()?.active_count).toBe(3);
    fixture.destroy();
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([{ path: 'login', loadComponent: () => import('./core/login/login').then((m) => m.Login) }])],
    });
  });
});
