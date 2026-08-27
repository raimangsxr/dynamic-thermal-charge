import { Injectable, signal } from '@angular/core';
import type { RelayTestViewDto } from './api.types';
const ID = 'dtc.relay-test.id'; const CREDENTIAL = 'dtc.relay-test.credential';
@Injectable({ providedIn: 'root' })
export class RelayTestSession {
  readonly id = signal<string | null>(sessionStorage.getItem(ID));
  readonly credential = signal<string | null>(sessionStorage.getItem(CREDENTIAL));
  /** Last safely-read coordination state, for the authenticated global nav. */
  readonly view = signal<RelayTestViewDto | null>(null);
  save(id: string, credential: string): void { sessionStorage.setItem(ID, id); sessionStorage.setItem(CREDENTIAL, credential); this.id.set(id); this.credential.set(credential); }
  clear(): void { sessionStorage.removeItem(ID); sessionStorage.removeItem(CREDENTIAL); this.id.set(null); this.credential.set(null); this.view.set(null); }
  clearCredential(): void { sessionStorage.removeItem(CREDENTIAL); this.credential.set(null); }
  observe(view: RelayTestViewDto | null): void { this.view.set(view); }
}
