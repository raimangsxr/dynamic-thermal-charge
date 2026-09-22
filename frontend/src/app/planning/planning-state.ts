import { computed, Injectable, signal } from '@angular/core';

import type { PlanningDto, PlanningPreviewDto, PlanningPreviewJobDto, PlanHistoryDto, TemperatureTargetRequest } from '../core/api.types';
import type { Explained } from '../core/errors';

export type TemperatureTargetDraft = TemperatureTargetRequest;

/** The single mutable state owner for the planning editor and preview flow. */
@Injectable()
export class PlanningState {
  readonly snapshot = signal<PlanningDto | null>(null);
  readonly failure = signal<Explained | null>(null);
  readonly loading = signal(true);
  readonly draftTargets = signal<TemperatureTargetDraft[]>([]);
  readonly preview = signal<PlanningPreviewDto | null>(null);
  readonly actionMessage = signal('');
  readonly actionError = signal('');
  readonly activationInFlight = signal(false);
  readonly previewJob = signal<PlanningPreviewJobDto | null>(null);
  readonly selectedTab = signal(0);
  readonly selectedTargetIndex = signal<number | null>(null);
  readonly planHistory = signal<PlanHistoryDto[]>([]);
  readonly explanationError = signal('');
  readonly selectedTarget = computed<TemperatureTargetDraft | null>(() => {
    const targets = this.draftTargets();
    if (!targets.length) return null;
    const requestedIndex = this.selectedTargetIndex();
    const index = requestedIndex === null ? 0 : Math.min(Math.max(requestedIndex, 0), targets.length - 1);
    return targets[index] ?? null;
  });
}
