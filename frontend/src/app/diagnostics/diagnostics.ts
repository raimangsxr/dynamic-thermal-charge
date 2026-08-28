import { DestroyRef, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import type { ControllerLogEventDto, ControllerLogLevel } from '../core/api.types';
import { formatInstant } from '../shared/age/age';

@Component({ selector: 'dtc-diagnostics', imports: [FormsModule], templateUrl: './diagnostics.html', styleUrl: './diagnostics.css' })
export class Diagnostics {
  private readonly api = inject(Api);
  readonly events = signal<ControllerLogEventDto[]>([]);
  readonly level = signal<ControllerLogLevel | ''>('');
  readonly query = signal(''); readonly loading = signal(true); readonly error = signal('');
  readonly more = signal<number | null>(null); private timer: number | null = null;
  constructor() { this.load(); this.timer = window.setInterval(() => this.refresh(), 5000); inject(DestroyRef).onDestroy(() => { if (this.timer) window.clearInterval(this.timer); }); }
  load(beforeId?: number): void { this.loading.set(!beforeId); this.api.controllerLog({ limit: 100, beforeId, level: this.level() || undefined, q: this.query() || undefined }).subscribe({ next: page => { this.events.set(beforeId ? [...this.events(), ...page.items] : page.items); this.more.set(page.next_before_id); this.error.set(''); this.loading.set(false); }, error: () => { this.error.set('No se pudieron cargar los eventos. Inténtalo de nuevo.'); this.loading.set(false); } }); }
  apply(): void { this.load(); }
  refresh(): void { if (document.visibilityState !== 'visible' || !this.events().length) return; const newest = this.events()[0].id; this.api.controllerLog({ afterId: newest, level: this.level() || undefined, q: this.query() || undefined }).subscribe({ next: page => { if (page.items.length) this.events.set([...page.items, ...this.events()].slice(0, 300)); }, error: () => undefined }); }
  instant(value: string): string { return formatInstant(value); }
}
