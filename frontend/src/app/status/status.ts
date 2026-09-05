/**
 * What is happening right now -- and what cannot be claimed.
 *
 * The rule that governs this component: when the API says the state is not
 * current, no heater is presented as charging and NO power figure is shown. Not a
 * zero either: a zero asserts that nothing is being drawn.
 *
 * When the API cannot be reached at all, the last snapshot stays on screen marked
 * as no longer current (FR-030). Emptying the screen destroys useful
 * information; leaving it looking live would be a lie.
 */

import { HttpErrorResponse } from '@angular/common/http';
import {
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';

import { Api } from '../core/api';
import type { ApiErrorDto, StatusDto } from '../core/api.types';
import { type Explained, UNREACHABLE, explain } from '../core/errors';
import { outputStateOf } from '../core/output-state';
import { Poller } from '../core/poll';
import { OutputIndicator } from '../shared/output-indicator/output-indicator';
import { formatAge, formatInstant } from '../shared/age/age';
import { ControllerHealth } from './controller-health/controller-health';
import { formatTemperature } from '../shared/temperature/temperature';

@Component({
  selector: 'dtc-status',
  imports: [ControllerHealth, OutputIndicator],
  templateUrl: './status.html',
  styleUrl: './status.css',
})
export class Status {
  private readonly api = inject(Api);

  /** The last snapshot we managed to read. Kept on purpose when the API falls. */
  readonly snapshot = signal<StatusDto | null>(null);
  /** Set when the last attempt failed. The snapshot above is then stale. */
  readonly failure = signal<Explained | null>(null);
  readonly loading = signal(true);

  readonly heaters = computed(() => {
    const current = this.snapshot();
    if (current === null) {
      return [];
    }
    return current.heaters.map((heater) => ({
      dto: heater,
      state: outputStateOf(heater),
    }));
  });

  /** True when we are showing data we know is no longer being refreshed. */
  readonly showingStaleSnapshot = computed(
    () => this.failure() !== null && this.snapshot() !== null,
  );

  readonly unmet = computed(() =>
    (this.snapshot()?.allocations ?? []).filter(
      (allocation) => allocation.unmet_minutes > 0,
    ),
  );

  readonly charging = computed(() => this.heaters().filter((item) => item.state.kind === 'on'));
  readonly resting = computed(() => this.heaters().filter((item) => item.state.kind === 'off'));
  readonly telemetryReady = computed(() => (this.snapshot()?.telemetry ?? []).filter((item) => item.state === 'ready').length);
  readonly telemetryTotal = computed(() => this.snapshot()?.telemetry?.length ?? 0);

  planStatus(status: string | null | undefined): string {
    switch (status) {
      case 'feasible': return 'Cumplido';
      case 'deficit': return 'Con déficit';
      case 'best_effort': return 'Mejor esfuerzo';
      default: return status ?? 'Sin evaluación';
    }
  }

  private readonly poller = new Poller(() => this.refresh());

  constructor() {
    this.refresh();
    this.poller.start();
    inject(DestroyRef).onDestroy(() => this.poller.stop());
  }

  refresh(): void {
    this.api.status().subscribe({
      next: (dto) => {
        this.snapshot.set(dto);
        this.failure.set(null);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.loading.set(false);
        this.failure.set(this.describe(error));
      },
    });
  }

  hours(minutes: number): string {
    return (minutes / 60).toFixed(1).replace('.0', '');
  }

  temperature(value: number | null | undefined): string {
    return value === null || value === undefined ? 'sin dato' : `${formatTemperature(value)} °C`;
  }

  age(seconds: number | null): string {
    return formatAge(seconds);
  }

  instant(iso: string | null): string {
    return formatInstant(iso);
  }

  private describe(error: unknown): Explained {
    if (error instanceof HttpErrorResponse) {
      const body = error.error as ApiErrorDto | null;
      if (body && typeof body === 'object' && 'code' in body) {
        return explain(body);
      }
      // No structured body: the API is not answering as itself.
      return UNREACHABLE;
    }
    return UNREACHABLE;
  }
}
