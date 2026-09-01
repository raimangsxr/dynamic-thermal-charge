import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { Api } from '../core/api';
import type { SecretEditDto, SystemConfigurationDto, SystemSection, TopologyDto } from '../core/api.types';

interface Option { value: string; label: string; }
interface FieldDefinition { name: string; type: 'text' | 'number' | 'boolean' | 'select'; options?: readonly Option[]; }
interface FieldGroup { title: string; fields: FieldDefinition[]; }
const WEATHER_PROVIDERS = [
  { value: 'aemet', label: 'AEMET' },
  { value: 'simulated', label: 'Simulado' },
] as const;
const DATABASE_DRIVERS = [
  { value: 'sqlite', label: 'SQLite' },
  { value: 'postgresql', label: 'PostgreSQL' },
] as const;
const OUTPUT_DRIVERS = [
  { value: 'simulated', label: 'Simulada' },
  { value: 'gpio', label: 'GPIO' },
] as const;
const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((value) => ({ value, label: value }));
const FIELDS: Record<SystemSection, FieldDefinition[]> = {
  database: [{ name: 'driver', type: 'select', options: DATABASE_DRIVERS }, { name: 'host', type: 'text' }, { name: 'port', type: 'number' }, { name: 'database', type: 'text' }, { name: 'tls', type: 'boolean' }, { name: 'trusted_no_tls', type: 'boolean' }],
  api: [{ name: 'host', type: 'text' }, { name: 'port', type: 'number' }, { name: 'cors_origins', type: 'text' }, { name: 'stale_seconds', type: 'number' }],
  mqtt: [{ name: 'enabled', type: 'boolean' }, { name: 'host', type: 'text' }, { name: 'port', type: 'number' }, { name: 'tls', type: 'boolean' }, { name: 'prefix', type: 'text' }, { name: 'discovery_prefix', type: 'text' }, { name: 'publish_seconds', type: 'number' }],
  weather: [
    { name: 'provider', type: 'select', options: WEATHER_PROVIDERS },
    { name: 'municipality_code', type: 'text' },
    { name: 'timeout_seconds', type: 'number' },
    { name: 'simulated_average_temperature_c', type: 'number' },
    { name: 'simulated_minimum_temperature_c', type: 'number' },
    { name: 'fallback_average_temperature_c', type: 'number' },
    { name: 'fallback_minimum_temperature_c', type: 'number' },
    { name: 'retry_minutes', type: 'number' },
    { name: 'refresh_minutes', type: 'number' },
  ],
  output: [{ name: 'driver', type: 'select', options: OUTPUT_DRIVERS }],
  logging: [{ name: 'level', type: 'select', options: LOG_LEVELS }, { name: 'max_events', type: 'number' }],
  operations: [{ name: 'controller_poll_seconds', type: 'number' }, { name: 'heartbeat_stale_multiplier', type: 'number' }, { name: 'relay_test_lease_seconds', type: 'number' }, { name: 'relay_test_state_poll_seconds', type: 'number' }, { name: 'relay_test_lease_renew_seconds', type: 'number' }, { name: 'retention_days', type: 'number' }, { name: 'fallback_max_age_minutes', type: 'number' }],
};
const SECRETS: Partial<Record<SystemSection, string[]>> = {
  api: ['admin_token_digest'], database: ['postgres_username', 'postgres_password'],
  mqtt: ['mqtt_username', 'mqtt_password'], weather: ['aemet_api_key'],
};

@Component({ selector: 'dtc-system-config', imports: [FormsModule], templateUrl: './system-config.html', styleUrl: './system-config.css' })
export class SystemConfig {
  private readonly api = inject(Api);
  readonly sections = Object.keys(FIELDS) as SystemSection[];
  readonly selected = signal<SystemSection>('database');
  readonly configuration = signal<SystemConfigurationDto | null>(null);
  readonly topology = signal<TopologyDto | null>(null);
  readonly draft = signal<Record<string, unknown>>({});
  readonly secretActions = signal<Record<string, SecretEditDto['action']>>({});
  readonly secretValues = signal<Record<string, string>>({});
  readonly message = signal('');
  readonly error = signal('');
  readonly confirming = signal(false);
  readonly operation = signal('');
  readonly weatherRefreshLoading = signal(false);
  readonly weatherRefreshMessage = signal('');
  readonly weatherRefreshError = signal('');

  constructor() { this.load(); }
  fields(): FieldDefinition[] { return FIELDS[this.selected()]; }
  groups(): FieldGroup[] {
    const fields = this.fields();
    if (this.selected() !== 'weather') return [{ title: 'Parámetros', fields }];
    return [
      { title: 'Proveedor y ubicación', fields: fields.slice(0, 3) },
      { title: 'Temperaturas simuladas y fallback', fields: fields.slice(3, 7) },
      { title: 'Política de actualización', fields: fields.slice(7) },
    ];
  }
  secrets(): string[] { return SECRETS[this.selected()] ?? []; }
  writable(): boolean { return this.topology()?.administrative_writes_allowed === true; }

  load(): void {
    forkJoin({ configuration: this.api.systemConfiguration(), topology: this.api.topology() }).subscribe({
      next: ({ configuration, topology }) => { this.configuration.set(configuration); this.topology.set(topology); this.resetDraft(); },
      error: () => this.error.set('No se pudo cargar la configuración del sistema.'),
    });
  }
  choose(section: SystemSection): void { this.selected.set(section); this.resetDraft(); }
  value(field: string): unknown { return this.draft()[field] ?? this.configuration()?.sections[this.selected()][field] ?? ''; }
  edit(field: string, value: unknown): void { this.draft.update((draft) => ({ ...draft, [field]: value })); }
  secretAction(name: string): SecretEditDto['action'] { return this.secretActions()[name] ?? 'keep'; }
  setSecretAction(name: string, action: SecretEditDto['action']): void { this.secretActions.update((current) => ({ ...current, [name]: action })); if (action !== 'replace') this.setSecretValue(name, ''); }
  setSecretValue(name: string, value: string): void { this.secretValues.update((current) => ({ ...current, [name]: value })); }

  requestSave(): void {
    const section = this.selected();
    if (section === 'database' || section === 'output' || Object.values(this.secretActions()).some((action) => action !== 'keep')) this.confirming.set(true);
    else this.save();
  }
  testDatabase(): void {
    const values = this.databaseCandidate();
    this.api.testDatabase(values).subscribe({
      next: () => this.message.set('Conexión de base de datos verificada sin guardar cambios.'),
      error: () => this.error.set('No se pudo conectar con el destino; no se guardó ningún cambio.'),
    });
  }
  migrateDatabase(): void {
    const topology = this.topology();
    if (!topology?.locator_revision) return;
    this.confirming.set(false);
    this.operation.set('Migración en curso…');
    this.api.migrateDatabase(topology.locator_revision, this.databaseCandidate()).subscribe({
      next: (operation) => this.operation.set(`Migración ${operation.status}: ${operation.phase}`),
      error: () => { this.operation.set(''); this.error.set('La migración no se pudo completar; el backend activo no ha cambiado.'); },
    });
  }
  refreshWeather(): void {
    if (this.weatherRefreshLoading() || !this.writable()) return;
    this.weatherRefreshLoading.set(true);
    this.weatherRefreshMessage.set('Consultando AEMET…');
    this.weatherRefreshError.set('');
    this.api.refreshWeather().subscribe({
      next: (result) => {
        this.weatherRefreshLoading.set(false);
        this.weatherRefreshMessage.set('Consulta AEMET completada correctamente.');
        this.configuration.update((current) => current ? ({
          ...current,
          sections: {
            ...current.sections,
            weather: {
              ...current.sections.weather,
              forecast_status: result.forecast_status,
              forecast_last_attempt_at: result.forecast_last_attempt_at,
              forecast_last_error: result.forecast_last_error,
              forecast_next_run_at: result.forecast_next_run_at,
            },
          },
        }) : current);
      },
      error: (error: unknown) => {
        this.weatherRefreshLoading.set(false);
        this.weatherRefreshMessage.set('');
        const body = error instanceof HttpErrorResponse ? error.error as { message?: unknown } : null;
        this.weatherRefreshError.set(typeof body?.message === 'string' ? body.message : 'No se pudo consultar AEMET.');
      },
    });
  }
  save(): void {
    this.confirming.set(false); this.error.set('');
    const snapshot = this.configuration(); if (!snapshot || !this.writable()) return;
    const values: Record<string, unknown> = {};
    for (const field of this.fields()) if (field.name in this.draft()) values[field.name] = this.coerce(field, this.draft()[field.name]);
    const secrets: Record<string, SecretEditDto> = {};
    for (const name of this.secrets()) {
      const action = this.secretAction(name); secrets[name] = action === 'replace' ? { action, value: this.secretValues()[name] ?? '' } : { action };
    }
    this.api.patchSystem(this.selected(), snapshot.revision, values, secrets).subscribe({
      next: (updated) => { this.configuration.set(updated); this.secretValues.set({}); this.secretActions.set({}); this.draft.set({}); this.message.set(updated.pending_restart?.length ? 'Guardado. Reinicia el proceso indicado para aplicar todos los cambios.' : 'Configuración guardada.'); },
      error: (error: unknown) => this.error.set(error instanceof HttpErrorResponse && error.status === 409 ? 'La configuración cambió. Tus valores siguen aquí; recarga antes de guardar.' : 'No se pudo guardar. Revisa los campos.'),
    });
  }
  private resetDraft(): void { this.draft.set({}); this.secretActions.set({}); this.secretValues.set({}); this.message.set(''); this.error.set(''); }
  private coerce(field: FieldDefinition, value: unknown): unknown {
    if (field.name === 'cors_origins') return String(value).split(',').map((item) => item.trim()).filter(Boolean);
    if (value === '' && ['host', 'database', 'municipality_code', 'stale_seconds', 'retention_days'].includes(field.name)) return null;
    if (field.type === 'number') return Number(value);
    if (field.type === 'boolean') return value === true || value === 'true';
    return String(value);
  }
  private databaseCandidate(): import('../core/api.types').DatabaseCandidateDto {
    const section = this.configuration()?.sections.database ?? {};
    const value = (name: string): unknown => this.draft()[name] ?? section[name];
    return {
      driver: String(value('driver') || 'sqlite') as 'sqlite' | 'postgresql',
      host: String(value('host') || '') || undefined,
      port: Number(value('port')) || undefined,
      database: String(value('database') || '') || undefined,
      username: this.secretValues()['postgres_username'],
      password: this.secretValues()['postgres_password'],
      tls: Boolean(value('tls')),
      trusted_no_tls: Boolean(value('trusted_no_tls')),
    };
  }
}
