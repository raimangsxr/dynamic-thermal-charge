/** The interceptor: FR-003, FR-006. */

import {
  HttpClient,
  provideHttpClient,
  withInterceptors,
} from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { Auth } from './auth';
import { authInterceptor } from './auth.interceptor';

const TOKEN = 'test-token-' + 'q'.repeat(32);

describe('authInterceptor', () => {
  let http: HttpClient;
  let backend: HttpTestingController;
  let auth: Auth;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    backend = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(Auth);
  });

  it('adds the credential as a header', () => {
    auth.signIn(TOKEN);
    http.get('/api/v1/status').subscribe();
    const request = backend.expectOne('/api/v1/status');
    expect(request.request.headers.get('Authorization')).toBe(`Bearer ${TOKEN}`);
    request.flush({});
  });

  it('never puts the credential in the URL', () => {
    auth.signIn(TOKEN);
    http.get('/api/v1/status').subscribe();
    const request = backend.expectOne(
      (candidate) => !candidate.urlWithParams.includes(TOKEN),
    );
    expect(request.request.urlWithParams).not.toContain(TOKEN);
    expect(request.request.urlWithParams).not.toContain('token=');
    request.flush({});
  });

  it('sends no credential header when there is no session', () => {
    // The error handler is not decoration: without it the rejection is
    // unhandled, and Vitest warns that unhandled errors can turn other tests
    // into false positives.
    let rejected = false;
    http.get('/api/v1/status').subscribe({ error: () => (rejected = true) });
    const request = backend.expectOne('/api/v1/status');
    expect(request.request.headers.has('Authorization')).toBe(false);
    request.flush(
      { code: 'unauthorized', message: 'unauthorized' },
      { status: 401, statusText: 'Unauthorized' },
    );
    expect(rejected).toBe(true);
  });

  /**
   * FR-006: the credential was rotated on the server while the panel was in use.
   * The operator must land back on the sign-in screen, not stare at a technical
   * error in every panel.
   */
  it('signs out when the API rejects a rotated credential mid-use', () => {
    auth.signIn(TOKEN);
    expect(auth.authenticated()).toBe(true);

    let failed = false;
    http.get('/api/v1/config').subscribe({ error: () => (failed = true) });
    backend
      .expectOne('/api/v1/config')
      .flush(
        { code: 'unauthorized', message: 'unauthorized' },
        { status: 401, statusText: 'Unauthorized' },
      );

    expect(failed).toBe(true);
    expect(auth.authenticated()).toBe(false);
    expect(sessionStorage.getItem('dtc.api-token')).toBeNull();
  });

  it('keeps the session on errors that are not about the credential', () => {
    auth.signIn(TOKEN);
    http.get('/api/v1/status').subscribe({ error: () => undefined });
    backend
      .expectOne('/api/v1/status')
      .flush(
        { code: 'store_unavailable', message: 'gone' },
        { status: 503, statusText: 'Service Unavailable' },
      );
    expect(auth.authenticated()).toBe(true);
  });

  it('keeps the session on a validation error', () => {
    auth.signIn(TOKEN);
    http.patch('/api/v1/config', {}).subscribe({ error: () => undefined });
    backend
      .expectOne('/api/v1/config')
      .flush(
        { code: 'validation_failed', message: 'bad' },
        { status: 422, statusText: 'Unprocessable Content' },
      );
    expect(auth.authenticated()).toBe(true);
  });
});
