import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Login } from './login';
import { Auth } from '../auth';
import { authInterceptor } from '../auth.interceptor';

const TOKEN = 'test-token-' + 'l'.repeat(32);

describe('Login', () => {
  beforeEach(() => {
    sessionStorage.clear();
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [Login],
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        { provide: Router, useValue: { navigateByUrl: vi.fn() } },
      ],
    });
  });

  it('waits for API acceptance before storing the credential or navigating', () => {
    const fixture = TestBed.createComponent(Login);
    const component = fixture.componentInstance;
    const backend = TestBed.inject(HttpTestingController);
    const router = TestBed.inject(Router);
    const auth = TestBed.inject(Auth);

    component.value = TOKEN;
    component.submit(new Event('submit'));
    const request = backend.expectOne('/api/v1/status');

    expect(request.request.headers.get('Authorization')).toBe(`Bearer ${TOKEN}`);
    expect(auth.authenticated()).toBe(false);
    expect(router.navigateByUrl).not.toHaveBeenCalled();

    request.flush({});
    expect(auth.token()).toBe(TOKEN);
    expect(sessionStorage.getItem('dtc.api-token')).toBe(TOKEN);
    expect(router.navigateByUrl).toHaveBeenCalledWith('/estado');
  });

  it('keeps a rejected credential out of the session and shows one generic message', () => {
    const fixture = TestBed.createComponent(Login);
    const component = fixture.componentInstance;
    const backend = TestBed.inject(HttpTestingController);
    const auth = TestBed.inject(Auth);

    component.value = TOKEN;
    component.submit(new Event('submit'));
    backend.expectOne('/api/v1/status').flush(
      { code: 'unauthorized', message: 'unauthorized' },
      { status: 401, statusText: 'Unauthorized' },
    );

    expect(auth.authenticated()).toBe(false);
    expect(sessionStorage.getItem('dtc.api-token')).toBeNull();
    expect(component.value).toBe('');
    expect(component.message()).toBe('La credencial no es válida.');
    expect(component.message()).not.toContain(TOKEN);
  });
});
