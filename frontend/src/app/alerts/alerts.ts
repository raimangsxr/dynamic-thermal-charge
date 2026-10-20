import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { Component, inject, signal } from '@angular/core';

import { Api } from '../core/api';
import type { AlertPageDto } from '../core/api.types';

type AlertView = 'active' | 'history';
type AlertPageSize = 5 | 10 | 20 | 50;

@Component({
  selector: 'dtc-alerts',
  imports: [CommonModule, MatButtonModule, MatCardModule, MatIconModule, MatTabsModule],
  templateUrl: './alerts.html',
  styleUrl: './alerts.css',
})
export class Alerts {
  private readonly api = inject(Api);
  readonly view = signal<AlertView>('active');
  readonly page = signal<AlertPageDto | null>(null);
  readonly loading = signal(true);
  readonly message = signal<string | null>(null);
  readonly pageSizeOptions: readonly AlertPageSize[] = [5, 10, 20, 50];
  readonly pageSize = signal<AlertPageSize>(10);

  constructor() {
    this.refresh();
  }

  selectView(view: AlertView): void {
    this.view.set(view);
    this.refresh();
  }

  selectPageSize(value: number | string): void {
    const parsed = Number(value);
    if (!this.pageSizeOptions.some((option) => option === parsed)) return;
    const size = parsed as AlertPageSize;
    if (size === this.pageSize()) return;
    this.pageSize.set(size);
    this.page.set(null);
    this.refresh();
  }

  selectTab(index: number): void {
    this.selectView(index === 1 ? 'history' : 'active');
  }

  acknowledge(id: number): void {
    this.api.acknowledgeAlert(id, this.view(), this.pageSize()).subscribe({
      next: (page) => this.page.set(page),
      error: () => this.message.set('No se pudo acusar el aviso.'),
    });
  }

  nextPage(): void {
    const current = this.page();
    if (!current?.has_more || !current.next_cursor) return;
    this.api.alerts(this.view(), this.pageSize(), current.next_cursor).subscribe({
      next: (page) => this.page.set(page),
      error: () => this.message.set('No se pudo cargar la página siguiente.'),
    });
  }

  refresh(): void {
    this.loading.set(true);
    this.message.set(null);
    this.api.alerts(this.view(), this.pageSize()).subscribe({
      next: (page) => { this.page.set(page); this.loading.set(false); },
      error: () => { this.message.set('No se pudieron cargar los avisos.'); this.loading.set(false); },
    });
  }
}
