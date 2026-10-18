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
import { Component, computed, inject, OnDestroy, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Observable, forkJoin, map, of, Subscription, switchMap } from 'rxjs';

import { Api, type HistoryQuery, type HistorySeriesQuery } from '../core/api';
import type {
  ApiErrorDto,
  ConfigDto,
  ForecastHistoryDto,
  HistorySeriesCuesDto,
  HistorySeriesPageDto,
  HistorySeriesPointDto,
  PageDto,
  PlanHistoryDto,
  StatusDto,
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

type Tab = 'plans' | 'forecasts' | 'transitions' | 'planning' | 'measured';

interface MeasuredHistoryRow {
  at: string;
  scope: 'installation' | 'heater';
  heaterId: string | null;
  measured: Record<string, unknown>;
  projected: Record<string, unknown> | null;
  cues: HistorySeriesCuesDto;
}

const HISTORY_TABS: readonly { id: Tab; label: string; description: string }[] = [
  { id: 'plans', label: 'Planes', description: 'Planificaciones generadas' },
  { id: 'forecasts', label: 'Previsiones', description: 'Datos meteorológicos guardados' },
  { id: 'transitions', label: 'Transiciones', description: 'Cambios de las salidas' },
  { id: 'planning', label: 'Decisiones de planificación', description: 'Motivos del automático' },
  { id: 'measured', label: 'Medidas', description: 'Telemetría medida cada cinco minutos' },
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
export class History implements OnDestroy {
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
  readonly measured = signal<HistorySeriesPageDto | null>(null);
  readonly measuredHeaters = signal<Map<string, HistorySeriesPageDto>>(new Map());
  readonly measuredObservedAt = signal<string | null>(null);
  readonly historyWindowHours = signal<6 | 24 | 72>(24);
  private measuredRequest: Subscription | null = null;

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
      case 'measured':
        return this.measured();
    }
  });

  readonly empty = computed(() => {
    if (this.tab() === 'measured') {
      return this.measured() !== null && this.measuredRows().length === 0;
    }
    const current = this.page();
    return current !== null && current.items.length === 0;
  });

  readonly currentLoaded = computed(() =>
    this.tab() === 'planning' ? this.planningAudit() !== null : this.page() !== null,
  );

  readonly measuredRows = computed<MeasuredHistoryRow[]>(() => {
    const rows: MeasuredHistoryRow[] = [];
    const installation = this.measured();
    for (const point of installation?.items ?? []) {
      rows.push({
        at: point.at,
        scope: 'installation',
        heaterId: null,
        measured: point.measured,
        projected: point.projected,
        cues: point.cues,
      });
    }
    for (const [heaterId, page] of this.measuredHeaters()) {
      for (const point of page.items) {
        rows.push({
          at: point.at,
          scope: 'heater',
          heaterId,
          measured: point.measured,
          projected: point.projected,
          cues: point.cues,
        });
      }
    }
    return rows.sort((left, right) => {
      const leftAt = Date.parse(left.at);
      const rightAt = Date.parse(right.at);
      if (Number.isFinite(leftAt) && Number.isFinite(rightAt)) return leftAt - rightAt;
      return left.at.localeCompare(right.at);
    });
  });

  readonly measuredNowAt = computed(() => {
    const instants = this.measuredInstants();
    const position = this.historyNowPosition(this.measuredObservedAt(), instants);
    return position === null ? null : instants[Math.floor(position)] ?? null;
  });

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

  ngOnDestroy(): void {
    this.measuredRequest?.unsubscribe();
  }

  selectHistoryWindow(hours: 6 | 24 | 72): void {
    const changed = this.historyWindowHours() !== hours;
    this.historyWindowHours.set(hours);
    if (this.tab() === 'measured' && changed) this.loadMeasured();
  }

  historyNowPosition(
    observedAt: string | null | undefined,
    instants: readonly string[],
  ): number | null {
    if (!observedAt || instants.length === 0) return null;
    const target = Date.parse(observedAt);
    if (!Number.isFinite(target)) return null;
    const timestamps = instants.map((value) => Date.parse(value));
    if (timestamps.some((value) => !Number.isFinite(value))) return null;
    if (target <= timestamps[0]) return 0;
    const last = timestamps.length - 1;
    if (target >= timestamps[last]) return last;
    const right = timestamps.findIndex((value) => value >= target);
    if (right <= 0) return right === 0 ? 0 : null;
    const left = timestamps[right - 1];
    const span = timestamps[right] - left;
    return span > 0 ? right - 1 + (target - left) / span : right;
  }

  measuredInstants(): string[] {
    const values = new Map<string, string>();
    for (const row of this.measuredRows()) {
      const timestamp = Date.parse(row.at);
      const key = Number.isFinite(timestamp) ? String(timestamp) : row.at;
      if (!values.has(key)) values.set(key, row.at);
    }
    return [...values.values()].sort((left, right) => {
      const leftAt = Date.parse(left);
      const rightAt = Date.parse(right);
      if (Number.isFinite(leftAt) && Number.isFinite(rightAt)) return leftAt - rightAt;
      return left.localeCompare(right);
    });
  }

  historyValue(value: unknown): string {
    if (value === null || value === undefined) return 'sin dato';
    if (typeof value === 'number') return Number.isFinite(value) ? String(value) : 'sin dato';
    if (typeof value === 'boolean') return value ? 'sí' : 'no';
    return String(value);
  }

  historyTemperature(value: unknown): string {
    if (typeof value !== 'number' || !Number.isFinite(value)) return 'sin dato';
    return `${formatTemperature(value)} °C`;
  }

  historyCueText(cues: HistorySeriesCuesDto): string {
    const labels: string[] = [];
    if (cues.forecast_interpolated === true) labels.push('previsión interpolada');
    if (cues.forecast_stale === true) labels.push('previsión antigua');
    if (cues.guaranteed === true) labels.push('franja garantizada');
    if (cues.aggregate_limit_reached === true) labels.push('límite agregado alcanzado');
    if (cues.charge_reasons === null) labels.push('motivo de carga: no disponible');
    else if (cues.charge_reasons.length) labels.push(`motivos de carga: ${cues.charge_reasons.length}`);
    return labels.length ? labels.join(', ') : 'sin señal adicional';
  }

  measuredMetric(row: MeasuredHistoryRow, key: string, projected = false): string {
    const values = projected ? row.projected : row.measured;
    return this.historyValue(values?.[key]);
  }

  measuredScopeText(row: MeasuredHistoryRow): string {
    return row.scope === 'installation' ? 'Instalación' : this.heaterText(row.heaterId ?? '');
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
    if (this.tab() !== 'measured' && this.from() && this.to() && this.from() > this.to()) {
      this.rangeError.set(
        'El inicio del rango es posterior al fin. Corrígelo antes de consultar.',
      );
      return;
    }
    this.loading.set(true);
    if (this.tab() === 'measured') {
      this.loadMeasured();
      return;
    }
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

  private loadMeasured(): void {
    this.measuredRequest?.unsubscribe();
    this.loading.set(true);
    this.banner.set(null);
    this.measured.set(null);
    this.measuredHeaters.set(new Map());
    this.measuredObservedAt.set(null);
    this.measuredRequest = this.api.status().pipe(
      switchMap((status: StatusDto) => {
        const observedMs = Date.parse(status.observed_at);
        if (!Number.isFinite(observedMs)) return of(null);
        const to = new Date(observedMs).toISOString();
        const from = new Date(observedMs - this.historyWindowHours() * 60 * 60 * 1000).toISOString();
        const queries: HistorySeriesQuery[] = [
          { from, to, scope: 'installation', limit: 500 },
          ...status.heaters.map((heater) => ({
            from,
            to,
            scope: 'heater' as const,
            heaterId: heater.id,
            limit: 500,
          })),
        ];
        return forkJoin(queries.map((query) => this.fetchMeasuredHistoryPages(query, []))).pipe(
          map((pages) => ({ status, pages })),
        );
      }),
    ).subscribe({
      next: (result) => {
        if (!result || !result.pages[0]) {
          this.measured.set(null);
          this.measuredObservedAt.set(null);
          this.banner.set(UNREACHABLE);
          this.loading.set(false);
          return;
        }
        this.measuredObservedAt.set(result.status.observed_at);
        this.measured.set(result.pages[0]);
        const heaters = new Map<string, HistorySeriesPageDto>();
        result.status.heaters.forEach((heater, index) => {
          const page = result.pages[index + 1];
          if (page) heaters.set(heater.id, page);
        });
        this.measuredHeaters.set(heaters);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.measured.set(null);
        this.measuredHeaters.set(new Map());
        this.measuredObservedAt.set(null);
        this.banner.set(this.describe(error));
        this.loading.set(false);
      },
      complete: () => { this.measuredRequest = null; },
    });
  }

  private fetchMeasuredHistoryPages(
    query: HistorySeriesQuery,
    items: HistorySeriesPointDto[],
  ): Observable<HistorySeriesPageDto> {
    return this.api.historySeries(query).pipe(
      switchMap((page) => {
        const merged = [...items, ...page.items];
        if (page.has_more && page.next_cursor) {
          return this.fetchMeasuredHistoryPages({ ...query, cursor: page.next_cursor }, merged);
        }
        return of({ ...page, items: merged, has_more: false, next_cursor: null });
      }),
    );
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
