/**
 * Reading and editing the configuration.
 *
 * Every write sends the revision that was read. Conflicts stay visible and the
 * form keeps what the operator typed, so a concurrent change is never silently
 * overwritten.
 */

import { HttpErrorResponse } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { Api } from '../core/api';
import type { AddHeaterRequest, ApiErrorDto, ChangeDto, ConfigDto, UpdateHeaterRequest } from '../core/api.types';
import { type Explained, UNREACHABLE, explain, messageFor } from '../core/errors';
import { confirmationText, needsConfirmation } from './electrical-fields';

interface FormEdit { readonly field: string; readonly value: string; }
interface PendingEdit {
  readonly field: string;
  readonly value: string;
  readonly heaterId: string | null;
  readonly formEdits?: readonly FormEdit[];
}

export interface HeaterForm {
  id: string;
  name: string;
  model: string;
  power_kw: string;
  full_charge_hours: string;
  target_charge: string;
  reserve_percent: string;
  priority: string;
  enabled: boolean;
  indoor_topic: string;
  temperature_topic: string;
  target_temperature_topic: string;
  stored_charge_topic: string;
  output: 'simulated' | 'gpio';
  pin: string;
  active_high: boolean;
  target_temperature_c: string;
  design_outdoor_temperature_c: string;
  thermal_factor: string;
  min_charge: string;
  max_charge: string;
  thermal_loss_c_per_hour: string;
}

const HEATER_EDIT_FIELDS = [
  'name', 'model', 'power_kw', 'full_charge_hours', 'target_charge', 'reserve_percent', 'priority',
  'enabled', 'indoor_topic', 'temperature_topic', 'target_temperature_topic', 'stored_charge_topic',
  'output_type', 'pin', 'active_high',
  'target_temperature_c', 'design_outdoor_temperature_c', 'thermal_factor',
  'min_charge', 'max_charge', 'thermal_loss_c_per_hour',
] as const;

const INSTALLATION_GROUPS = [
  { title: 'Parámetros de carga', fields: ['max_total_power_kw', 'slot_minutes', 'retention_days', 'poll_seconds', 'log_level'] },
  { title: 'Política de temperatura interior', fields: ['indoor_max_age_minutes', 'indoor_min_plausible_c', 'indoor_max_plausible_c'] },
] as const;

@Component({
  selector: 'dtc-confirm-dialog',
  imports: [MatButtonModule, MatDialogModule],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <mat-dialog-content>{{ data.message }}</mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="false">Cancelar</button>
      <button mat-flat-button color="warn" type="button" [mat-dialog-close]="true" data-testid="confirm-delete">{{ data.confirmLabel }}</button>
    </mat-dialog-actions>
  `,
})
export class ConfirmDialog {
  readonly data = inject<{ title: string; message: string; confirmLabel: string }>(MAT_DIALOG_DATA);
  readonly dialogRef = inject(MatDialogRef<ConfirmDialog>);
}

@Component({
  selector: 'dtc-config',
  imports: [
    FormsModule, RouterLink, MatButtonModule, MatCardModule, MatDialogModule,
    MatFormFieldModule, MatIconModule, MatInputModule, MatSelectModule, MatTooltipModule,
  ],
  templateUrl: './config.html',
  styleUrl: './config.css',
})
export class Config {
  private readonly api = inject(Api);
  private readonly dialog = inject(MatDialog);

  readonly config = signal<ConfigDto | null>(null);
  readonly banner = signal<Explained | null>(null);
  readonly fieldErrors = signal<Record<string, string>>({});
  private readonly rendered = new Set<string>();
  readonly pending = signal<Record<string, string>>({});
  readonly confirming = signal<PendingEdit | null>(null);
  readonly saved = signal<string>('');
  readonly relayConflict = signal(false);
  readonly heaterForm = signal<HeaterForm | null>(null);
  readonly heaterFormMode = signal<'add' | 'edit' | null>(null);
  readonly heaterFormError = signal('');
  readonly heaterSaving = signal(false);
  readonly installationGroups = INSTALLATION_GROUPS;
  readonly dirty = computed(() => Object.keys(this.pending()).length > 0);

  constructor() { this.load(); }

  load(): void {
    this.api.config().subscribe({
      next: (dto) => {
        this.config.set(dto);
        this.banner.set(null);
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

  register(field: string, heaterId: string | null): string {
    this.rendered.add(this.key(field, heaterId));
    return '';
  }

  label(field: string): string {
    const labels: Record<string, string> = {
      max_total_power_kw: 'Potencia máxima simultánea (kW)', slot_minutes: 'Duración de intervalo (min)',
      retention_days: 'Retención de históricos (días)', poll_seconds: 'Intervalo de sondeo (s)',
      log_level: 'Nivel de registro', indoor_max_age_minutes: 'Antigüedad máxima interior (min)',
      indoor_min_plausible_c: 'Temperatura interior mínima (°C)', indoor_max_plausible_c: 'Temperatura interior máxima (°C)',
      thermal_loss_c_per_hour: 'Pérdida térmica (°C/h)',
      reserve_percent: 'Reserva equivalente (%)',
      temperature_topic: 'Tópico de temperatura',
      target_temperature_topic: 'Tópico de objetivo',
      stored_charge_topic: 'Tópico de carga almacenada',
    };
    return labels[field] ?? field;
  }

  edit(field: string, heaterId: string | null, value: string): void {
    this.pending.update((current) => ({ ...current, [this.key(field, heaterId)]: value }));
  }

  submit(field: string, heaterId: string | null): void {
    const value = this.pending()[this.key(field, heaterId)];
    if (value === undefined) return;
    if (needsConfirmation(field)) {
      this.confirming.set({ field, value, heaterId });
      return;
    }
    this.apply({ field, value, heaterId });
  }

  confirmationMessage(): string {
    const edit = this.confirming();
    return edit === null ? '' : edit.formEdits ? 'Se aplicarán los cambios del acumulador. Revisa especialmente los valores eléctricos.' : confirmationText(edit.field, edit.value);
  }

  confirm(): void {
    const edit = this.confirming();
    this.confirming.set(null);
    if (edit === null) return;
    if (edit.formEdits) {
      this.applyHeaterEdits(edit.heaterId!);
    } else {
      this.apply(edit);
    }
  }

  cancelConfirmation(): void { this.confirming.set(null); }

  discard(field: string, heaterId: string | null): void {
    const target = this.key(field, heaterId);
    this.pending.update((current) => {
      const next = { ...current };
      delete next[target];
      return next;
    });
  }

  asText(config: ConfigDto, field: string): string {
    const value = (config as unknown as Record<string, unknown>)[field];
    if (value === null || value === undefined) return field === 'retention_days' ? 'none' : '';
    return String(value);
  }

  heaterText(heater: ConfigDto['heaters'][number], field: string): string {
    if (field === 'pin') return heater.output.pin === null ? '' : String(heater.output.pin);
    if (field === 'active_high') return String(heater.output.active_high);
    if (field === 'output_type') return heater.output.kind;
    if (['target_temperature_c', 'design_outdoor_temperature_c', 'thermal_factor', 'min_charge', 'max_charge', 'thermal_loss_c_per_hour'].includes(field)) {
      const value = heater.thermal?.[field as 'target_temperature_c' | 'design_outdoor_temperature_c' | 'thermal_factor' | 'min_charge' | 'max_charge' | 'thermal_loss_c_per_hour'];
      return value === null || value === undefined ? '' : String(value);
    }
    const value = (heater as unknown as Record<string, unknown>)[field];
    return value === null || value === undefined ? '' : String(value);
  }

  openAddHeater(): void {
    this.heaterFormMode.set('add');
    this.heaterFormError.set('');
    this.heaterForm.set({ id: '', name: '', model: '', power_kw: '1', full_charge_hours: '8', target_charge: '1', reserve_percent: '0', priority: '0', enabled: true, indoor_topic: '', temperature_topic: '', target_temperature_topic: '', stored_charge_topic: '', output: 'simulated', pin: '', active_high: true, target_temperature_c: '', design_outdoor_temperature_c: '', thermal_factor: '1', min_charge: '0', max_charge: '1', thermal_loss_c_per_hour: '0' });
  }

  openEditHeater(heater: ConfigDto['heaters'][number]): void {
    this.heaterFormMode.set('edit');
    this.heaterFormError.set('');
    this.heaterForm.set({
      id: heater.id, name: heater.name, model: heater.model ?? '', power_kw: String(heater.power_kw), full_charge_hours: String(heater.full_charge_hours),
      target_charge: String(heater.target_charge), reserve_percent: String(heater.reserve_percent), priority: String(heater.priority), enabled: heater.enabled, indoor_topic: heater.indoor_topic ?? '',
      temperature_topic: heater.temperature_topic ?? '', target_temperature_topic: heater.target_temperature_topic ?? '', stored_charge_topic: heater.stored_charge_topic ?? '',
      output: heater.output.kind, pin: heater.output.pin === null ? '' : String(heater.output.pin), active_high: heater.output.active_high,
      target_temperature_c: heater.thermal ? String(heater.thermal.target_temperature_c) : '', design_outdoor_temperature_c: heater.thermal ? String(heater.thermal.design_outdoor_temperature_c) : '',
      thermal_factor: heater.thermal ? String(heater.thermal.thermal_factor) : '', min_charge: heater.thermal ? String(heater.thermal.min_charge) : '', max_charge: heater.thermal ? String(heater.thermal.max_charge) : '', thermal_loss_c_per_hour: heater.thermal ? String(heater.thermal.thermal_loss_c_per_hour) : '',
    });
  }

  cancelHeaterForm(): void { this.heaterForm.set(null); this.heaterFormMode.set(null); this.heaterFormError.set(''); }

  updateHeaterForm(field: keyof HeaterForm, value: unknown): void {
    this.heaterForm.update((current) => current ? { ...current, [field]: value } : current);
  }

  saveHeater(): void {
    const form = this.heaterForm();
    const snapshot = this.config();
    if (!form || !snapshot || this.heaterSaving()) return;
    this.heaterFormError.set('');
    if (!form.id.trim() || !this.validNumber(form.power_kw) || !this.validNumber(form.full_charge_hours)) {
      this.heaterFormError.set('Indica un identificador, una potencia y un tiempo de carga válidos.');
      return;
    }
    const thermalPart = form.target_temperature_c.trim() || form.design_outdoor_temperature_c.trim();
    if (thermalPart && (!this.validNumber(form.target_temperature_c) || !this.validNumber(form.design_outdoor_temperature_c))) {
      this.heaterFormError.set('El perfil térmico necesita temperatura objetivo y exterior de diseño válidas.');
      return;
    }
    this.heaterSaving.set(true);
    if (this.heaterFormMode() === 'add') {
      const payload: AddHeaterRequest = {
        revision: snapshot.config_revision, id: form.id.trim(), name: form.name.trim() || undefined, model: form.model.trim() || undefined,
        power_kw: Number(form.power_kw), full_charge_hours: Number(form.full_charge_hours), target_charge: Number(form.target_charge), reserve_percent: Number(form.reserve_percent), priority: Number(form.priority),
        enabled: form.enabled, indoor_topic: form.indoor_topic.trim() || null, temperature_topic: form.temperature_topic.trim() || null, target_temperature_topic: form.target_temperature_topic.trim() || null, stored_charge_topic: form.stored_charge_topic.trim() || null, output: form.output, pin: form.pin.trim() ? Number(form.pin) : null, active_high: form.active_high,
        target_temperature_c: thermalPart ? Number(form.target_temperature_c) : null, design_outdoor_temperature_c: thermalPart ? Number(form.design_outdoor_temperature_c) : null,
        thermal_factor: Number(form.thermal_factor), min_charge: Number(form.min_charge), max_charge: Number(form.max_charge), thermal_loss_c_per_hour: Number(form.thermal_loss_c_per_hour),
      };
      this.api.addHeater(payload).subscribe({ next: (change) => this.finishHeaterSave(`Acumulador creado: ${change.entity_key ?? form.id}`), error: (error: unknown) => this.rejectHeater(error) });
      return;
    }
    const original = snapshot.heaters.find((heater) => heater.id === form.id);
    if (!original) { this.rejectHeater(new Error('No se encontró el acumulador seleccionado.')); return; }
    const edits = HEATER_EDIT_FIELDS.map((field) => ({ field, value: this.formValue(form, field) })).filter(({ field, value }) => value !== this.heaterText(original, field));
    if (edits.length === 0) { this.cancelHeaterForm(); return; }
    const sensitive = edits.find((edit) => needsConfirmation(edit.field));
    if (sensitive) {
      this.heaterSaving.set(false);
      this.confirming.set({ field: sensitive.field, value: sensitive.value, heaterId: original.id, formEdits: edits });
      return;
    }
    this.applyHeaterEdits(original.id);
  }

  requestRemoveHeater(heater: ConfigDto['heaters'][number]): void {
    this.dialog.open(ConfirmDialog, { width: 'min(28rem, calc(100vw - 2rem))', data: { title: `Eliminar ${heater.name}`, message: 'Se eliminará el acumulador de la configuración. Su histórico se conservará.', confirmLabel: 'Eliminar acumulador' } }).afterClosed().subscribe((confirmed: boolean) => {
      if (confirmed) this.removeHeater(heater.id);
    });
  }

  removeHeater(heaterId: string): void {
    const snapshot = this.config();
    if (!snapshot || this.heaterSaving()) return;
    this.heaterSaving.set(true);
    this.api.removeHeater(heaterId, snapshot.config_revision).subscribe({
      next: (change) => { this.heaterSaving.set(false); this.saved.set(`Acumulador eliminado: ${change.entity_key ?? heaterId}`); this.cancelHeaterForm(); this.load(); },
      error: (error: unknown) => { this.heaterSaving.set(false); this.banner.set(this.describe(error)); },
    });
  }

  private formValue(form: HeaterForm, field: typeof HEATER_EDIT_FIELDS[number]): string {
    if (field === 'output_type') return form.output;
    const value = form[field as keyof HeaterForm];
    return typeof value === 'boolean' ? String(value) : String(value ?? '');
  }

  private validNumber(value: string): boolean { return value.trim() !== '' && Number.isFinite(Number(value)); }

  private apply(edit: PendingEdit): void {
    const current = this.config();
    if (!current) return;
    const body = { revision: current.config_revision, field: edit.field, value: edit.value };
    const call = edit.heaterId === null ? this.api.setField(body) : this.api.setHeaterField(edit.heaterId, body);
    const target = this.key(edit.field, edit.heaterId);
    call.subscribe({
      next: (change) => { this.saved.set(`${edit.field}: ${change.old_value ?? '—'} → ${change.new_value ?? '—'}`); this.fieldErrors.update((errors) => { const next = { ...errors }; delete next[target]; return next; }); this.discard(edit.field, edit.heaterId); this.load(); },
      error: (error: unknown) => this.reject(target, error),
    });
  }

  private applyHeaterEdits(heaterId: string): void {
    const form = this.heaterForm();
    const revision = this.config()?.config_revision;
    if (!form || revision === undefined) return;
    const payload: UpdateHeaterRequest = {
      revision,
      name: form.name.trim(), model: form.model.trim() || null,
      power_kw: Number(form.power_kw), full_charge_hours: Number(form.full_charge_hours),
      target_charge: Number(form.target_charge), reserve_percent: Number(form.reserve_percent), priority: Number(form.priority),
      enabled: form.enabled, indoor_topic: form.indoor_topic.trim() || null,
      temperature_topic: form.temperature_topic.trim() || null,
      target_temperature_topic: form.target_temperature_topic.trim() || null,
      stored_charge_topic: form.stored_charge_topic.trim() || null,
      output: form.output, pin: form.pin.trim() ? Number(form.pin) : null, active_high: form.active_high,
      target_temperature_c: form.target_temperature_c.trim() ? Number(form.target_temperature_c) : null,
      design_outdoor_temperature_c: form.design_outdoor_temperature_c.trim() ? Number(form.design_outdoor_temperature_c) : null,
      thermal_factor: Number(form.thermal_factor), min_charge: Number(form.min_charge), max_charge: Number(form.max_charge),
      thermal_loss_c_per_hour: Number(form.thermal_loss_c_per_hour),
    };
    this.heaterSaving.set(true);
    this.api.updateHeater(heaterId, payload).subscribe({
      next: () => this.finishHeaterSave('Acumulador actualizado.'),
      error: (error: unknown) => { this.heaterSaving.set(false); this.reject(this.key('form', heaterId), error); this.heaterFormError.set('No se pudo guardar el acumulador. El formulario conserva tus cambios.'); },
    });
  }

  private finishHeaterSave(message: string): void { this.heaterSaving.set(false); this.saved.set(message); this.cancelHeaterForm(); this.load(); }

  private rejectHeater(error: unknown): void { this.heaterSaving.set(false); this.heaterFormError.set(error instanceof HttpErrorResponse ? this.describe(error).title : 'No se pudo guardar el acumulador. Revisa los campos.'); }

  private reject(target: string, error: unknown): void {
    if (!(error instanceof HttpErrorResponse)) { this.banner.set(UNREACHABLE); return; }
    const body = error.error as ApiErrorDto | null;
    if (body === null || typeof body !== 'object' || !('code' in body)) { this.banner.set(UNREACHABLE); return; }
    const explained = explain(body);
    this.relayConflict.set(body.code === 'relay_test_active' || body.code === 'relay_test_fault_latched' || (body.code === 'config_conflict' && body.message.includes('relay test')));
    if (explained.fieldScoped && this.rendered.has(target)) { this.fieldErrors.update((errors) => ({ ...errors, [target]: messageFor(body) })); this.banner.set(null); return; }
    if (explained.fieldScoped) { this.banner.set({ ...explained, title: messageFor(body), action: explained.action }); return; }
    this.banner.set(explained);
  }

  private describe(error: unknown): Explained {
    if (error instanceof HttpErrorResponse) {
      const body = error.error as ApiErrorDto | null;
      if (body && typeof body === 'object' && 'code' in body) return explain(body);
    }
    return UNREACHABLE;
  }
}
