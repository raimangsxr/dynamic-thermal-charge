/** The session: FR-002, FR-003, FR-004, FR-005, SC-007. */

import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { Auth } from './auth';

const TOKEN = 'test-token-' + 'z'.repeat(32);

describe('Auth', () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    TestBed.resetTestingModule();
  });

  function auth(): Auth {
    return TestBed.inject(Auth);
  }

  it('starts unauthenticated', () => {
    expect(auth().authenticated()).toBe(false);
    expect(auth().token()).toBeNull();
  });

  it('remembers the credential after signing in', () => {
    const service = auth();
    service.signIn(TOKEN);
    expect(service.authenticated()).toBe(true);
    expect(service.token()).toBe(TOKEN);
  });

  it('survives a reload', () => {
    auth().signIn(TOKEN);
    // A fresh service, as after reloading the page.
    TestBed.resetTestingModule();
    expect(auth().token()).toBe(TOKEN);
  });

  it('does NOT persist beyond the tab', () => {
    auth().signIn(TOKEN);
    expect(sessionStorage.getItem('dtc.api-token')).toBe(TOKEN);
    // sessionStorage is cleared by the browser when the tab closes; the point
    // here is that nothing was written anywhere that outlives it.
    expect(localStorage.length).toBe(0);
  });

  it('never writes the credential to localStorage', () => {
    auth().signIn(TOKEN);
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      expect(localStorage.getItem(key ?? '')).not.toContain(TOKEN);
    }
    expect(localStorage.length).toBe(0);
  });

  it('forgets it on sign-out', () => {
    const service = auth();
    service.signIn(TOKEN);
    service.signOut();
    expect(service.authenticated()).toBe(false);
    expect(service.token()).toBeNull();
    expect(sessionStorage.getItem('dtc.api-token')).toBeNull();
  });

  it('ignores an empty credential', () => {
    const service = auth();
    service.signIn('   ');
    expect(service.authenticated()).toBe(false);
  });

  it('trims surrounding whitespace, which is easy to paste by accident', () => {
    const service = auth();
    service.signIn(`  ${TOKEN}\n`);
    expect(service.token()).toBe(TOKEN);
  });

  it('does not appear anywhere in the page address', () => {
    auth().signIn(TOKEN);
    expect(globalThis.location.href).not.toContain(TOKEN);
    expect(globalThis.location.search).not.toContain(TOKEN);
  });
});
