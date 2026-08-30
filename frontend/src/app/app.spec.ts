import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';

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

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([{ path: 'login', loadComponent: () => import('./core/login/login').then((m) => m.Login) }])],
    });
  });
});
