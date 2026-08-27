/**
 * Reading and editing the configuration.
 *
 * Every write sends the revision that was read. A conflict is not an error to
 * avoid: it is the protection working, and it is presented as "the configuration
 * changed, re-read it" with the action to hand -- never retried on its own and
 * never overwritten.
 *
 * Rejections land next to the field the API named. A generic banner would throw
 * away information the API went to the trouble of providing.
 */

import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';

import { Api } from '../core/api';
import type { ApiErrorDto, ConfigDto } from '../core/api.types';
import { type Explained, UNREACHABLE, explain, messageFor } from '../core/errors';
import { confirmationText, needsConfirmation } from './electrical-fields';

interface PendingEdit {
  readonly field: string;
  readonly value: string;
  readonly heaterId: string | null;
}

@Component({
  selector: 'dtc-config',
  imports: [FormsModule, RouterLink],
  templateUrl: './config.html',
  styleUrl: './config.css',
})
export class Config {
  private readonly api = inject(Api);

  readonly config = signal<ConfigDto | null>(null);
  readonly banner = signal<Explained | null>(null);
  /** Rejections indexed by field, so each lands next to its input (FR-018). */
  readonly fieldErrors = signal<Record<string, string>>({});
  /** Fields the view actually renders, registered as it renders them.
   *
   *  A field-scoped rejection for a field with no input on screen would be
   *  invisible: the operator would see nothing at all, which is worse than a
   *  generic banner. Those fall back to the banner instead. */
  private readonly rendered = new Set<string>();
  /** What the operator typed but has not saved. Survives a failed write. */
  readonly pending = signal<Record<string, string>>({});
  readonly confirming = signal<PendingEdit | null>(null);
  readonly saved = signal<string>('');
  readonly relayConflict = signal(false);

  readonly dirty = computed(() => Object.keys(this.pending()).length > 0);

  constructor() {
    this.load();
  }

  load(): void {
    this.api.config().subscribe({
      next: (dto) => {
        this.config.set(dto);
        this.banner.set(null);
        // A successful re-read clears stale rejections but keeps nothing typed:
        // the operator asked for the current truth.
        this.fieldErrors.set({});
        this.pending.set({});
        this.relayConflict.set(false);
      },
      error: (error: unknown) => this.banner.set(this.describe(error)),
    });
  }

  key(field: string, heaterId: string | null): string {
    return heaterId === null ? field : `${heaterId}.${field}`;
  }

  /** Called from the template so the component knows what is on screen. */
  register(field: string, heaterId: string | null): string {
    this.rendered.add(this.key(field, heaterId));
    return '';
  }

  edit(field: string, heaterId: string | null, value: string): void {
    this.pending.update((current) => ({
      ...current,
      [this.key(field, heaterId)]: value,
    }));
  }

  /** Ask before touching the three fields with electrical consequences. */
  submit(field: string, heaterId: string | null): void {
    const value = this.pending()[this.key(field, heaterId)];
    if (value === undefined) {
      return;
    }
    if (needsConfirmation(field)) {
      this.confirming.set({ field, value, heaterId });
      return;
    }
    this.apply({ field, value, heaterId });
  }

  confirmationMessage(): string {
    const edit = this.confirming();
    return edit === null ? '' : confirmationText(edit.field, edit.value);
  }

  confirm(): void {
    const edit = this.confirming();
    this.confirming.set(null);
    if (edit !== null) {
      this.apply(edit);
    }
  }

  cancelConfirmation(): void {
    this.confirming.set(null);
  }

  discard(field: string, heaterId: string | null): void {
    const target = this.key(field, heaterId);
    this.pending.update((current) => {
      const next = { ...current };
      delete next[target];
      return next;
    });
  }

  /** The stored value of an installation field, as text for an input. */
  asText(config: ConfigDto, field: string): string {
    const value = (config as unknown as Record<string, unknown>)[field];
    if (value === null || value === undefined) {
      // retention_days null means unlimited; the API accepts the word back.
      return field === 'retention_days' ? 'none' : '';
    }
    return String(value);
  }

  /** The stored value of a heater field, as text for an input. */
  heaterText(heater: ConfigDto['heaters'][number], field: string): string {
    switch (field) {
      case 'pin':
        return heater.output.pin === null ? '' : String(heater.output.pin);
      case 'active_high':
        return String(heater.output.active_high);
      default: {
        const value = (heater as unknown as Record<string, unknown>)[field];
        return value === null || value === undefined ? '' : String(value);
      }
    }
  }

  private apply(edit: PendingEdit): void {
    const current = this.config();
    if (current === null) {
      return;
    }
    const body = {
      revision: current.config_revision,
      field: edit.field,
      value: edit.value,
    };
    const call =
      edit.heaterId === null
        ? this.api.setField(body)
        : this.api.setHeaterField(edit.heaterId, body);

    const target = this.key(edit.field, edit.heaterId);
    call.subscribe({
      next: (change) => {
        this.saved.set(
          `${edit.field}: ${change.old_value ?? '—'} → ${change.new_value ?? '—'}`,
        );
        this.fieldErrors.update((errors) => {
          const next = { ...errors };
          delete next[target];
          return next;
        });
        this.discard(edit.field, edit.heaterId);
        // Re-read so the revision advances and the view shows the stored truth.
        this.load();
      },
      error: (error: unknown) => this.reject(target, error),
    });
  }

  private reject(target: string, error: unknown): void {
    // Whatever happens, what the operator typed stays in the form (FR-033).
    if (!(error instanceof HttpErrorResponse)) {
      this.banner.set(UNREACHABLE);
      return;
    }
    const body = error.error as ApiErrorDto | null;
    if (body === null || typeof body !== 'object' || !('code' in body)) {
      this.banner.set(UNREACHABLE);
      return;
    }
    const explained = explain(body);
    this.relayConflict.set(
      body.code === 'relay_test_active' ||
      body.code === 'relay_test_fault_latched' ||
      (body.code === 'config_conflict' && body.message.includes('relay test')),
    );
    if (explained.fieldScoped && this.rendered.has(target)) {
      this.fieldErrors.update((errors) => ({
        ...errors,
        [target]: messageFor(body),
      }));
      this.banner.set(null);
      return;
    }
    if (explained.fieldScoped) {
      // No input on screen for this field. Showing it in the banner keeps the
      // message visible rather than dropping it silently.
      this.banner.set({
        ...explained,
        title: messageFor(body),
        action: explained.action,
      });
      return;
    }
    this.banner.set(explained);
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
