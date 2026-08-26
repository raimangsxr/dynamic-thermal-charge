/**
 * The session: the API credential, and nothing else.
 *
 * Stored in `sessionStorage` on purpose. It survives reloading the page and dies
 * when the tab closes, which is exactly what FR-002 asks for. `localStorage`
 * would leave the credential on the machine indefinitely, and it is functionally
 * the password to the electrical panel: whoever holds it can change the maximum
 * power and the pin assignments.
 *
 * A guard test in the Python suite fails if any module reaches for
 * `localStorage`, `indexedDB` or cookies.
 */

import { Injectable, computed, signal } from '@angular/core';

const STORAGE_KEY = 'dtc.api-token';

@Injectable({ providedIn: 'root' })
export class Auth {
  private readonly stored = signal<string | null>(this.read());

  readonly token = this.stored.asReadonly();
  readonly authenticated = computed(() => this.stored() !== null);

  /** Remember the credential for this tab. */
  signIn(token: string): void {
    const trimmed = token.trim();
    if (trimmed.length === 0) {
      return;
    }
    try {
      globalThis.sessionStorage?.setItem(STORAGE_KEY, trimmed);
    } catch {
      // Storage can be unavailable in a private window. The session still works
      // for as long as the page lives; it just will not survive a reload.
    }
    this.stored.set(trimmed);
  }

  /** Forget it. Called on explicit sign-out and when the API rejects it. */
  signOut(): void {
    try {
      globalThis.sessionStorage?.removeItem(STORAGE_KEY);
    } catch {
      // Nothing to do: the in-memory copy is cleared below either way.
    }
    this.stored.set(null);
  }

  private read(): string | null {
    try {
      return globalThis.sessionStorage?.getItem(STORAGE_KEY) ?? null;
    } catch {
      return null;
    }
  }
}
