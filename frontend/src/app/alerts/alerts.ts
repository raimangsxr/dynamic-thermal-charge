import { CommonModule } from '@angular/common';
import { Component, inject, signal } from '@angular/core';

import { Api } from '../core/api';
import type { AlertPageDto } from '../core/api.types';

type AlertView = 'active' | 'history';

@Component({
  selector: 'dtc-alerts',
  imports: [CommonModule],
  templateUrl: './alerts.html',
  styleUrl: './alerts.css',
})
export class Alerts {
  private readonly api = inject(Api);
  readonly view = signal<AlertView>('active');
  readonly page = signal<AlertPageDto | null>(null);
  readonly loading = signal(true);
  readonly message = signal<string | null>(null);

  constructor() {
    this.refresh();
  }

  selectView(view: AlertView): void {
    this.view.set(view);
    this.refresh();
  }

  acknowledge(id: number): void {
    this.api.acknowledgeAlert(id, this.view()).subscribe({
      next: (page) => this.page.set(page),
      error: () => this.message.set('No se pudo acusar el aviso.'),
    });
  }

  nextPage(): void {
    const current = this.page();
    if (!current?.has_more || !current.next_cursor) return;
    this.api.alerts(this.view(), 50, current.next_cursor).subscribe({
      next: (page) => this.page.set({ ...page, items: [...(current.items ?? []), ...page.items] }),
      error: () => this.message.set('No se pudo cargar el histórico.'),
    });
  }

  refresh(): void {
    this.loading.set(true);
    this.message.set(null);
    this.api.alerts(this.view()).subscribe({
      next: (page) => { this.page.set(page); this.loading.set(false); },
      error: () => { this.message.set('No se pudieron cargar los avisos.'); this.loading.set(false); },
    });
  }
}
