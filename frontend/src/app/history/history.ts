/**
 * The audit trail, in paged tables.
 *
 * The cursor is OPAQUE: it is sent back exactly as the API gave it. Parsing or
 * building one would reimplement the API's pagination and break the first time a
 * record is inserted between two pages.
 */

import { HttpErrorResponse } from '@angular/common/http';
import { JsonPipe } from '@angular/common';
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
import { formatInstant } from '../shared/age/age';

type Tab = 'plans' | 'forecasts' | 'transitions' | 'planning';

@Component({
  selector: 'dtc-history',
  imports: [FormsModule, JsonPipe],
  templateUrl: './history.html',
  styleUrl: './history.css',
})
export class History {
  private readonly api = inject(Api);

  readonly tab = signal<Tab>('plans');
  readonly from = signal('');
  readonly to = signal('');
  readonly heaterId = signal('');
  readonly banner = signal<Explained | null>(null);
  readonly rangeError = signal('');

  readonly plans = signal<PageDto<PlanHistoryDto> | null>(null);
  readonly forecasts = signal<PageDto<ForecastHistoryDto> | null>(null);
  readonly transitions = signal<PageDto<TransitionHistoryDto> | null>(null);
  readonly planningAudit = signal<AutomaticPlanAuditPage | null>(null);

  /** Heater ids present in the configuration, to flag the ones that are gone. */
  readonly configuredHeaters = signal<Set<string>>(new Set());

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

  constructor() {
    this.api.config().subscribe({
      next: (config: ConfigDto) =>
        this.configuredHeaters.set(new Set(config.heaters.map((h) => h.id))),
      // The panel still works without it; heaters just are not flagged.
      error: () => undefined,
    });
    this.load();
  }

  select(tab: Tab): void {
    this.tab.set(tab);
    this.load();
  }

  /** FR-027: an inverted range is refused before asking the API. */
  load(cursor?: string): void {
    this.rangeError.set('');
    if (this.from() && this.to() && this.from() > this.to()) {
      this.rangeError.set(
        'El inicio del rango es posterior al fin. Corrígelo antes de consultar.',
      );
      return;
    }
    const query: HistoryQuery = {
      from: this.from() ? new Date(this.from()).toISOString() : undefined,
      to: this.to() ? new Date(this.to()).toISOString() : undefined,
      cursor,
    };
    const onError = (error: unknown) => this.banner.set(this.describe(error));
    const clear = () => this.banner.set(null);

    switch (this.tab()) {
      case 'plans':
        this.api.plans(query).subscribe({
          next: (page) => {
            this.plans.set(page);
            clear();
          },
          error: onError,
        });
        return;
      case 'forecasts':
        this.api.forecasts(query).subscribe({
          next: (page) => {
            this.forecasts.set(page);
            clear();
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
            },
            error: onError,
          });
        return;
      case 'planning':
        this.api.planningAudit({ from: query.from, to: query.to, limit: query.limit }).subscribe({ next: (page) => { this.planningAudit.set(page); clear(); }, error: onError });
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
    return formatInstant(iso);
  }

  /** FR-028: a heater in the history that is no longer configured. */
  isGone(heaterId: string): boolean {
    const configured = this.configuredHeaters();
    return configured.size > 0 && !configured.has(heaterId);
  }

  sourceText(source: string): string {
    switch (source) {
      case 'aemet':
        return 'proveedor real';
      case 'fallback':
        return 'valor de reserva';
      default:
        return 'simulado';
    }
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
