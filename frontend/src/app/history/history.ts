/**
 * The audit trail, in paged tables.
 *
 * The cursor is OPAQUE: it is sent back exactly as the API gave it. Parsing or
 * building one would reimplement the API's pagination and break the first time a
 * record is inserted between two pages.
 */

import { HttpErrorResponse } from '@angular/common/http';
import { JsonPipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTabsModule } from '@angular/material/tabs';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api, type HistoryQuery } from '../core/api';
import type {
  ApiErrorDto,
  ConfigDto,
  ForecastHistoryDto,
  PageDto,
  PlanHistoryDto,
  TransitionHistoryDto,
  AutomaticPlanAuditPage,
} from '../core/api.types';
import { type Explained, UNREACHABLE, explain } from '../core/errors';
import { formatDateOnly, formatInstant } from '../shared/age/age';
import { formatTemperature } from '../shared/temperature/temperature';
import {
  forecastSourceLabel,
  planEventLabel,
  planReasonLabel,
  planStatusLabel,
} from '../shared/presentation/presentation';

type Tab = 'plans' | 'forecasts' | 'transitions' | 'planning';

const HISTORY_TABS: readonly { id: Tab; label: string; description: string }[] = [
  { id: 'plans', label: 'Planes', description: 'Planificaciones generadas' },
  { id: 'forecasts', label: 'Previsiones', description: 'Datos meteorológicos guardados' },
  { id: 'transitions', label: 'Transiciones', description: 'Cambios de las salidas' },
  { id: 'planning', label: 'Decisiones de planificación', description: 'Motivos del automático' },
];

@Component({
  selector: 'dtc-history',
  imports: [
    FormsModule, JsonPipe, MatButtonModule, MatFormFieldModule, MatIconModule,
    MatInputModule, MatSelectModule, MatTabsModule,
  ],
  templateUrl: './history.html',
  styleUrl: './history.css',
})
export class History {
  private readonly api = inject(Api);

  readonly tab = signal<Tab>('plans');
  readonly tabs = HISTORY_TABS;
  readonly selectedIndex = computed(() => this.tabs.findIndex((item) => item.id === this.tab()));
  readonly activeTab = computed(() => this.tabs.find((item) => item.id === this.tab()) ?? this.tabs[0]);
  readonly from = signal('');
  readonly to = signal('');
  readonly heaterId = signal('');
  readonly banner = signal<Explained | null>(null);
  readonly rangeError = signal('');
  readonly loading = signal(false);

  readonly plans = signal<PageDto<PlanHistoryDto> | null>(null);
  readonly forecasts = signal<PageDto<ForecastHistoryDto> | null>(null);
  readonly transitions = signal<PageDto<TransitionHistoryDto> | null>(null);
  readonly planningAudit = signal<AutomaticPlanAuditPage | null>(null);

  /** Heater ids present in the configuration, to flag the ones that are gone. */
  readonly configuredHeaters = signal<Set<string>>(new Set());
  readonly heaterNames = signal<Map<string, string>>(new Map());
  readonly installationTimezone = signal('Europe/Madrid');

  temperature(value: number | null | undefined): string {
    return value === null || value === undefined ? '—' : `${formatTemperature(value)} °C`;
  }

  readonly page = computed(() => {
    switch (this.tab()) {
      case 'plans':
        return this.plans();
      case 'forecasts':
        return this.forecasts();
      case 'transitions':
        return this.transitions();
      case 'planning':
        return null;
    }
  });

  readonly empty = computed(() => {
    const current = this.page();
    return current !== null && current.items.length === 0;
  });

  readonly currentLoaded = computed(() =>
    this.tab() === 'planning' ? this.planningAudit() !== null : this.page() !== null,
  );

  constructor() {
    this.api.config().subscribe({
      next: (config: ConfigDto) => {
        this.configuredHeaters.set(new Set(config.heaters.map((h) => h.id)));
        this.heaterNames.set(new Map(config.heaters.map((heater) => [heater.id, heater.name])));
        this.installationTimezone.set(config.schedule?.timezone ?? 'Europe/Madrid');
      },
      // The panel still works without it; heaters just are not flagged.
      error: () => undefined,
    });
    this.load();
  }

  select(tab: Tab): void {
    this.tab.set(tab);
    this.load();
  }

  onTabChange(index: number): void {
    const selected = this.tabs[index];
    if (selected && selected.id !== this.tab()) {
      this.select(selected.id);
    }
  }

  /** FR-027: an inverted range is refused before asking the API. */
  load(cursor?: string): void {
    this.rangeError.set('');
    this.banner.set(null);
    if (this.from() && this.to() && this.from() > this.to()) {
      this.rangeError.set(
        'El inicio del rango es posterior al fin. Corrígelo antes de consultar.',
      );
      return;
    }
    this.loading.set(true);
    const query: HistoryQuery = {
      from: this.from() ? new Date(this.from()).toISOString() : undefined,
      to: this.to() ? new Date(this.to()).toISOString() : undefined,
      cursor,
    };
    const onError = (error: unknown) => {
      this.banner.set(this.describe(error));
      this.loading.set(false);
    };
    const clear = () => this.banner.set(null);
    const finish = () => this.loading.set(false);

    switch (this.tab()) {
      case 'plans':
        this.api.plans(query).subscribe({
          next: (page) => {
            this.plans.set(page);
            clear();
            finish();
          },
          error: onError,
        });
        return;
      case 'forecasts':
        this.api.forecasts(query).subscribe({
          next: (page) => {
            this.forecasts.set(page);
            clear();
            finish();
          },
          error: onError,
        });
        return;
      case 'transitions':
        this.api
          .transitions({
            ...query,
            heaterId: this.heaterId() || undefined,
          })
          .subscribe({
            next: (page) => {
              this.transitions.set(page);
              clear();
              finish();
            },
            error: onError,
          });
        return;
      case 'planning':
        this.api.planningAudit({ from: query.from, to: query.to, limit: query.limit }).subscribe({ next: (page) => { this.planningAudit.set(page); clear(); finish(); }, error: onError });
        return;
    }
  }

  planningEmpty(): boolean { const page = this.planningAudit(); return page !== null && page.items.length === 0; }

  next(): void {
    const cursor = this.page()?.next_cursor;
    if (cursor) {
      this.load(cursor);
    }
  }

  instant(iso: string): string {
    return formatInstant(iso, this.installationTimezone());
  }

  dateOnly(value: string): string {
    return formatDateOnly(value);
  }

  heaterText(heaterId: string): string {
    return this.heaterNames().get(heaterId) ?? heaterId;
  }

  planSourceText(source: string | undefined): string {
    return source === 'automatic' ? 'plan automático' : 'histórico compatible';
  }

  planStatusText(status: string | null | undefined): string {
    return planStatusLabel(status);
  }

  planReasonText(reason: string | null | undefined): string {
    return planReasonLabel(reason);
  }

  auditEventText(event: string): string {
    return planEventLabel(event);
  }

  auditReasonText(reason: string): string {
    return planReasonLabel(reason);
  }

  auditDetailsText(details: Record<string, unknown>): string {
    return JSON.stringify(details);
  }

  /** FR-028: a heater in the history that is no longer configured. */
  isGone(heaterId: string): boolean {
    const configured = this.configuredHeaters();
    return configured.size > 0 && !configured.has(heaterId);
  }

  sourceText(source: string): string {
    return forecastSourceLabel(source);
  }

  private describe(error: unknown): Explained {
    if (error instanceof HttpErrorResponse) {
      const body = error.error as ApiErrorDto | null;
      if (body && typeof body === 'object' && 'code' in body) {
        return explain(body);
      }
    }
    return UNREACHABLE;
  }
}
