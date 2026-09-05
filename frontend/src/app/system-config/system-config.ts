import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { Api } from '../core/api';
import type { PlanningSiteConfigDto, SecretEditDto, SystemConfigurationDto, SystemSection, TopologyDto } from '../core/api.types';
import { ParamHelp } from '../shared/param-help/param-help';

type ConfigSection = SystemSection | 'planning';

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
const PLANNING_FIELDS: FieldDefinition[] = [
  { name: 'replan_minutes', type: 'number' },
  { name: 'planning_window_hours', type: 'number' },
  { name: 'forecast_horizon_hours', type: 'number' },
  { name: 'aemet_query_hour', type: 'number' },
  { name: 'contracted_power_w', type: 'number' },
  { name: 'max_heating_power_w', type: 'number' },
  { name: 'base_load_w', type: 'number' },
  { name: 'design_indoor_temperature_c', type: 'number' },
  { name: 'design_outdoor_temperature_c', type: 'number' },
  { name: 'feedback_horizon_hours', type: 'number' },
  { name: 'mqtt_simulation_enabled', type: 'boolean' },
  { name: 'mqtt_simulation_initial_temperature_c', type: 'number' },
  { name: 'mqtt_simulation_publish_seconds', type: 'number' },
  { name: 'mqtt_simulation_topic_prefix', type: 'text' },
  { name: 'mqtt_simulation_thermal_loss_c_per_hour', type: 'number' },
];
const FIELDS: Record<SystemSection, FieldDefinition[]> = {
  database: [{ name: 'driver', type: 'select', options: DATABASE_DRIVERS }, { name: 'host', type: 'text' }, { name: 'port', type: 'number' }, { name: 'database', type: 'text' }, { name: 'tls', type: 'boolean' }, { name: 'trusted_no_tls', type: 'boolean' }],
  api: [{ name: 'host', type: 'text' }, { name: 'port', type: 'number' }, { name: 'cors_origins', type: 'text' }, { name: 'stale_seconds', type: 'number' }],
  mqtt: [
    { name: 'enabled', type: 'boolean' }, { name: 'host', type: 'text' },
    { name: 'port', type: 'number' }, { name: 'tls', type: 'boolean' },
    { name: 'prefix', type: 'text' }, { name: 'discovery_prefix', type: 'text' },
    { name: 'publish_seconds', type: 'number' },
    { name: 'fixed_temperature_c', type: 'number' },
    { name: 'fixed_target_temperature_c', type: 'number' },
    { name: 'fixed_stored_charge_percent', type: 'number' },
    { name: 'fixed_indoor_temperature_c', type: 'number' },
  ],
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
const SECTION_LABELS: Record<ConfigSection, string> = {
  database: 'database',
  api: 'api',
  mqtt: 'mqtt',
  weather: 'weather',
  planning: 'planning',
  output: 'output',
  logging: 'logging',
  operations: 'operations',
};

@Component({ selector: 'dtc-system-config', imports: [FormsModule, ParamHelp], templateUrl: './system-config.html', styleUrl: './system-config.css' })
export class SystemConfig {
  private readonly api = inject(Api);
  readonly sections: ConfigSection[] = ['database', 'api', 'mqtt', 'weather', 'planning', 'output', 'logging', 'operations'];
  readonly selected = signal<ConfigSection>('database');
  readonly configuration = signal<SystemConfigurationDto | null>(null);
  readonly planningConfig = signal<PlanningSiteConfigDto | null>(null);
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
  sectionLabel(section: ConfigSection): string { return SECTION_LABELS[section]; }
  fields(): FieldDefinition[] {
    if (this.selected() === 'planning') return PLANNING_FIELDS;
    return FIELDS[this.selected() as SystemSection];
  }
  groups(): FieldGroup[] {
    const fields = this.fields();
    if (this.selected() === 'planning') {
      return [
        { title: 'Replanificación y horizonte', fields: fields.slice(0, 4) },
        { title: 'Límites de potencia', fields: fields.slice(4, 6) },
        { title: 'Modelo de demanda', fields: fields.slice(6, 10) },
        { title: 'Simulación MQTT de acumuladores', fields: fields.slice(10) },
      ];
    }
    if (this.selected() === 'mqtt') {
      const enabled = fields[0];
      return this.mqttEnabled()
        ? [{ title: 'MQTT', fields: [enabled] }, { title: 'Conexión MQTT', fields: fields.slice(1, 7) }]
        : [{ title: 'MQTT', fields: [enabled] }, { title: 'Valores fijos de prueba', fields: fields.slice(7) }];
    }
    if (this.selected() !== 'weather') return [{ title: 'Parámetros', fields }];
    return [
      { title: 'Proveedor y ubicación', fields: fields.slice(0, 3) },
      { title: 'Temperaturas simuladas y fallback', fields: fields.slice(3, 7) },
      { title: 'Política de actualización', fields: fields.slice(7) },
    ];
  }
  secrets(): string[] {
    if (this.selected() === 'planning') return [];
    if (this.selected() === 'mqtt' && !this.mqttEnabled()) return [];
    return SECRETS[this.selected() as SystemSection] ?? [];
  }
  writable(): boolean { return this.topology()?.administrative_writes_allowed === true; }
  mqttEnabled(): boolean { return this.value('enabled') === true || this.value('enabled') === 'true'; }

  load(): void {
    forkJoin({
      configuration: this.api.systemConfiguration(),
      topology: this.api.topology(),
      planningConfig: this.api.planningConfig(),
    }).subscribe({
      next: ({ configuration, topology, planningConfig }) => {
        this.configuration.set(configuration);
        this.topology.set(topology);
        this.planningConfig.set(planningConfig);
        this.resetDraft();
      },
      error: () => this.error.set('No se pudo cargar la configuración del sistema.'),
    });
  }
  choose(section: ConfigSection): void { this.selected.set(section); this.resetDraft(); }
  value(field: string): unknown {
    if (this.selected() === 'planning') {
      const planning = this.planningConfig();
      return this.draft()[field] ?? planning?.[field as keyof PlanningSiteConfigDto] ?? '';
    }
    return this.draft()[field] ?? this.configuration()?.sections[this.selected() as SystemSection][field] ?? '';
  }
  edit(field: string, value: unknown): void { this.draft.update((draft) => ({ ...draft, [field]: value })); }
  secretAction(name: string): SecretEditDto['action'] { return this.secretActions()[name] ?? 'keep'; }
  setSecretAction(name: string, action: SecretEditDto['action']): void { this.secretActions.update((current) => ({ ...current, [name]: action })); if (action !== 'replace') this.setSecretValue(name, ''); }
  setSecretValue(name: string, value: string): void { this.secretValues.update((current) => ({ ...current, [name]: value })); }

  requestSave(): void {
    const section = this.selected();
    if (section === 'planning') this.save();
    else if (section === 'database' || section === 'output' || Object.values(this.secretActions()).some((action) => action !== 'keep')) this.confirming.set(true);
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
    if (!this.writable()) return;
    if (this.selected() === 'planning') {
      const snapshot = this.planningConfig();
      if (!snapshot) return;
      const number = (name: string): number => Number(this.value(name));
      const values = {
        replan_minutes: number('replan_minutes'), planning_window_hours: number('planning_window_hours'), forecast_horizon_hours: number('forecast_horizon_hours'), aemet_query_hour: number('aemet_query_hour'),
        contracted_power_w: number('contracted_power_w'), max_heating_power_w: number('max_heating_power_w'),
        base_load_w: number('base_load_w'), design_indoor_temperature_c: number('design_indoor_temperature_c'),
        design_outdoor_temperature_c: number('design_outdoor_temperature_c'), feedback_horizon_hours: number('feedback_horizon_hours'),
        mqtt_simulation_enabled: this.value('mqtt_simulation_enabled') === true || this.value('mqtt_simulation_enabled') === 'true',
        mqtt_simulation_initial_temperature_c: number('mqtt_simulation_initial_temperature_c'), mqtt_simulation_publish_seconds: number('mqtt_simulation_publish_seconds'),
        mqtt_simulation_topic_prefix: String(this.value('mqtt_simulation_topic_prefix')), mqtt_simulation_thermal_loss_c_per_hour: number('mqtt_simulation_thermal_loss_c_per_hour'),
      };
      this.api.patchPlanningConfig(snapshot.revision, values).subscribe({
        next: (updated) => {
          this.planningConfig.set(updated);
          this.draft.set({});
          this.message.set('Parámetros de planificación guardados.');
        },
        error: (error: unknown) => this.error.set(error instanceof HttpErrorResponse && error.status === 409 ? 'La configuración de planificación cambió. Tus valores siguen aquí; recarga antes de guardar.' : 'No se pudo guardar. Revisa los campos.'),
      });
      return;
    }
    const snapshot = this.configuration();
    if (!snapshot) return;
    const values: Record<string, unknown> = {};
    for (const field of this.groups().flatMap((group) => group.fields)) if (field.name in this.draft()) values[field.name] = this.coerce(field, this.draft()[field.name]);
    const secrets: Record<string, SecretEditDto> = {};
    for (const name of this.secrets()) {
      const action = this.secretAction(name); secrets[name] = action === 'replace' ? { action, value: this.secretValues()[name] ?? '' } : { action };
    }
    this.api.patchSystem(this.selected() as SystemSection, snapshot.revision, values, secrets).subscribe({
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
