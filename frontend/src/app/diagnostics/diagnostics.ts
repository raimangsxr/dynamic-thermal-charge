import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { DestroyRef, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import type { ControllerLogEventDto, ControllerLogLevel } from '../core/api.types';
import { formatInstant } from '../shared/age/age';

@Component({
  selector: 'dtc-diagnostics',
  imports: [
    FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule,
    MatInputModule, MatSelectModule,
  ],
  templateUrl: './diagnostics.html',
  styleUrl: './diagnostics.css',
})
export class Diagnostics {
  private readonly api = inject(Api);
  readonly events = signal<ControllerLogEventDto[]>([]);
  readonly level = signal<ControllerLogLevel | ''>('');
  readonly query = signal('');
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly error = signal('');
  readonly more = signal<number | null>(null);
  private timer: number | null = null;

  constructor() {
    this.load();
    this.timer = window.setInterval(() => this.refresh(), 5000);
    inject(DestroyRef).onDestroy(() => {
      if (this.timer) window.clearInterval(this.timer);
    });
  }

  load(beforeId?: number): void {
    const loadingOlder = beforeId !== undefined;
    if (loadingOlder) {
      this.loadingMore.set(true);
    } else {
      this.loading.set(true);
    }
    this.api.controllerLog({
      limit: 100,
      beforeId,
      level: this.level() || undefined,
      q: this.query() || undefined,
    }).subscribe({
      next: (page) => {
        this.events.set(loadingOlder ? [...this.events(), ...page.items] : page.items);
        this.more.set(page.next_before_id);
        this.error.set('');
        this.loading.set(false);
        this.loadingMore.set(false);
      },
      error: () => {
        this.error.set('No se pudieron cargar los eventos. Inténtalo de nuevo.');
        this.loading.set(false);
        this.loadingMore.set(false);
      },
    });
  }

  apply(): void { this.load(); }

  refresh(): void {
    if (document.visibilityState !== 'visible' || !this.events().length || this.loading() || this.loadingMore()) {
      return;
    }
    const newest = this.events()[0].id;
    this.api.controllerLog({
      afterId: newest,
      level: this.level() || undefined,
      q: this.query() || undefined,
    }).subscribe({
      next: (page) => {
        if (page.items.length) this.events.set([...page.items, ...this.events()].slice(0, 300));
      },
      error: () => undefined,
    });
  }

  levelIcon(level: ControllerLogLevel): string {
    switch (level) {
      case 'DEBUG': return 'bug_report';
      case 'INFO': return 'info';
      case 'WARNING': return 'warning';
      case 'ERROR': return 'error_outline';
      case 'CRITICAL': return 'report';
    }
  }

  instant(value: string): string { return formatInstant(value); }
}
