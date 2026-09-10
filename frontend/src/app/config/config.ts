/**
 * Unified configuration workspace.
 *
 * The page deliberately keeps installation, automatic planning and runtime
 * settings in one route, while using task-oriented areas so an operator does
 * not have to know which backend module owns a setting. Every write still
 * carries the revision that was read and sensitive values never return to the
 * browser after they are saved.
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
import { forkJoin } from 'rxjs';

import { Api } from '../core/api';
import type {
  AlertTypeDto,
  AddHeaterRequest,
  ApiErrorDto,
  ConfigDto,
  DatabaseCandidateDto,
  PlanningSiteConfigDto,
  SecretEditDto,
  SystemConfigurationDto,
  SystemSection,
  TopologyDto,
  UpdateHeaterRequest,
} from '../core/api.types';
import { type Explained, UNREACHABLE, explain, messageFor } from '../core/errors';
import { formatInstant } from '../shared/age/age';
import {
  forecastNextRunLabel,
  forecastStatusLabel,
  outputDriverLabel,
} from '../shared/presentation/presentation';
import { confirmationText, needsConfirmation } from './electrical-fields';
import { ParamHelp } from '../shared/param-help/param-help';

type ConfigArea = 'summary' | 'installation' | 'heaters' | 'planning' | 'integrations' | 'service';
type IntegrationSection = 'mqtt' | 'weather' | 'email';
type ServiceSection = 'database' | 'api' | 'output' | 'logging' | 'operations';

interface FormEdit { readonly field: string; readonly value: string; }
interface PendingEdit {
  readonly field: string;
  readonly value: string;
  readonly heaterId: string | null;
  readonly formEdits?: readonly FormEdit[];
  readonly batchEdits?: readonly FormEdit[];
}

interface Option { readonly value: string; readonly label: string; }
interface FieldDefinition {
  readonly name: string;
  readonly label: string;
  readonly type: 'text' | 'number' | 'boolean' | 'select';
  readonly options?: readonly Option[];
  readonly helpField?: string;
  readonly hint?: string;
  readonly min?: string;
  readonly max?: string;
  readonly step?: string;
}
interface FieldGroup {
  readonly title: string;
  readonly description?: string;
  readonly fields: readonly FieldDefinition[];
}

export interface HeaterForm {
  id: string;
  name: string;
  model: string;
  power_kw: string;
  full_charge_hours: string;
  full_discharge_hours: string;
  static_emission_percent: string;
  room_thermal_capacity_kwh_per_c: string;
  room_heat_loss_kw_per_c: string;
  priority: string;
  enabled: boolean;
  telemetry_topic: string;
  output: 'simulated' | 'gpio';
  pin: string;
  active_high: boolean;
}

const HEATER_EDIT_FIELDS = [
  'name', 'model', 'power_kw', 'full_charge_hours', 'full_discharge_hours', 'static_emission_percent',
  'room_thermal_capacity_kwh_per_c', 'room_heat_loss_kw_per_c', 'priority',
  'enabled', 'telemetry_topic',
  'output_type', 'pin', 'active_high',
] as const;

const INSTALLATION_GROUPS = [
  {
    title: 'Intervalos de carga',
    description: 'Cómo se divide la ventana de carga en intervalos operativos.',
    fields: ['slot_minutes'],
  },
  {
    title: 'Calidad de temperatura interior',
    description: 'Límites para descartar lecturas MQTT que no sean plausibles.',
    fields: ['indoor_max_age_minutes', 'indoor_min_plausible_c', 'indoor_max_plausible_c'],
  },
] as const;

// Kept only so old callers of the component continue to receive the same
// optimistic-lock behavior. These values intentionally have no input in the
// unified UI; their editable source is now the planning/system configuration.
const LEGACY_INSTALLATION_FIELDS = ['max_total_power_kw', 'poll_seconds', 'log_level', 'retention_days'] as const;

interface HeaterFormFieldMeta {
  readonly key: keyof HeaterForm;
  readonly label: string;
  readonly type: 'text' | 'number' | 'select';
  readonly helpField?: string;
  readonly step?: string;
  readonly min?: string;
  readonly max?: string;
  readonly required?: boolean;
  readonly readonlyOnEdit?: boolean;
  readonly hint?: string;
  readonly selectOptions?: ReadonlyArray<{ value: string | boolean; label: string }>;
}

const HEATER_FORM_FIELDS: readonly HeaterFormFieldMeta[] = [
  { key: 'id', label: 'Identificador', type: 'text', required: true, readonlyOnEdit: true },
  { key: 'name', label: 'Nombre visible', type: 'text' },
  { key: 'model', label: 'Modelo', type: 'text' },
  { key: 'power_kw', label: 'Potencia nominal (kW)', type: 'number', step: '0.1', required: true },
  { key: 'full_charge_hours', label: 'Carga completa (horas)', type: 'number', step: '0.1', required: true },
  {
    key: 'full_discharge_hours', label: 'Descarga nominal (horas)', type: 'number', min: '0.1', step: '0.1', required: true,
    hint: 'Horas de descarga del fabricante. Define la potencia de emisión junto con la capacidad.',
  },
  {
    key: 'static_emission_percent', label: 'Emisión residual (%)', type: 'number', min: '0', max: '100', step: '1', required: true,
    hint: 'Porcentaje de la emisión máxima que el acumulador conserva con la carga agotada.',
  },
  {
    key: 'room_thermal_capacity_kwh_per_c', label: 'Capacidad térmica de la sala (kWh/°C)', type: 'number', min: '0.0001', step: '0.1', required: true,
    hint: 'Energía necesaria para elevar un grado la temperatura interior.',
  },
  { key: 'room_heat_loss_kw_per_c', label: 'Pérdida térmica de la sala (kW/°C)', type: 'number', min: '0', step: '0.01', required: true, hint: 'Intercambio térmico firmado frente al exterior.' },
  { key: 'priority', label: 'Prioridad', type: 'number', hint: 'Un número menor significa mayor prioridad.' },
  {
    key: 'enabled', label: 'Estado', type: 'select',
    selectOptions: [{ value: true, label: 'Activo' }, { value: false, label: 'Desactivado' }],
  },
  {
    key: 'output', label: 'Tipo de salida del acumulador', type: 'select', helpField: 'output',
    selectOptions: [{ value: 'simulated', label: 'Simulada' }, { value: 'gpio', label: 'GPIO' }],
  },
  { key: 'pin', label: 'Pin GPIO', type: 'number' },
  {
    key: 'active_high', label: 'Nivel activo', type: 'select',
    selectOptions: [{ value: true, label: 'Alto' }, { value: false, label: 'Bajo' }],
  },
  { key: 'telemetry_topic', label: 'Tópico JSON de telemetría', type: 'text' },
];

const HEATER_FORM_GROUPS = [
  { title: 'Identificación y acumulador', fields: ['id', 'name', 'model', 'power_kw', 'full_charge_hours', 'full_discharge_hours', 'static_emission_percent'] },
  { title: 'Modelo térmico y prioridad', fields: ['room_thermal_capacity_kwh_per_c', 'room_heat_loss_kw_per_c', 'priority', 'enabled'] },
  { title: 'Salida y telemetría', fields: ['output', 'pin', 'active_high', 'telemetry_topic'] },
] as const;

const EMAIL_SECURITY_MODES: readonly Option[] = [
  { value: 'starttls', label: 'STARTTLS' },
  { value: 'tls', label: 'TLS' },
  { value: 'none', label: 'Sin cifrado' },
];

const WEATHER_PROVIDERS: readonly Option[] = [
  { value: 'aemet', label: 'AEMET' },
  { value: 'simulated', label: 'Simulada' },
];
const DATABASE_DRIVERS: readonly Option[] = [
  { value: 'sqlite', label: 'SQLite local' },
  { value: 'postgresql', label: 'PostgreSQL' },
];
const OUTPUT_DRIVERS: readonly Option[] = [
  { value: 'simulated', label: 'Simulada' },
  { value: 'gpio', label: 'GPIO' },
];
const LOG_LEVELS: readonly Option[] = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((value) => ({ value, label: value }));

const PLANNING_FIELDS: readonly FieldDefinition[] = [
  { name: 'replan_minutes', label: 'Frecuencia de replanificación (min)', type: 'number', min: '1', step: '1' },
  { name: 'planning_window_hours', label: 'Ventana visible (horas)', type: 'number', min: '1', step: '1' },
  { name: 'forecast_horizon_hours', label: 'Horizonte de previsión (horas)', type: 'number', min: '1', step: '1' },
  { name: 'solver_time_limit_seconds', label: 'Tiempo máximo del optimizador (s)', type: 'number', min: '1', step: '1' },
  { name: 'aemet_query_hour', label: 'Hora de consulta AEMET (0–23)', type: 'number', min: '0', max: '23', step: '1' },
  { name: 'contracted_power_w', label: 'Potencia total contratada (W)', type: 'number', min: '1', step: '100', hint: 'Fuente única para el optimizador y el indicador de Estado.' },
  { name: 'max_heating_power_w', label: 'Límite de calefacción (W)', type: 'number', min: '1', step: '100' },
  { name: 'base_load_w', label: 'Consumo base estimado (W)', type: 'number', min: '0', step: '100' },
  { name: 'deviation_shortfall_tolerance_c', label: 'Tolerancia de déficit imprevisto (°C)', type: 'number', min: '0.01', step: '0.1', hint: 'Desviación térmica adicional que se tolera antes de solicitar un recálculo inmediato.' },
  { name: 'deviation_surplus_soc_percent', label: 'Tolerancia de excedente de SOC (%)', type: 'number', min: '0.1', step: '0.5', hint: 'Excedente de carga almacenada que se tolera antes de solicitar un recálculo inmediato.' },
  { name: 'mqtt_simulation_enabled', label: 'Activar simulación MQTT', type: 'boolean' },
  { name: 'mqtt_simulation_initial_temperature_c', label: 'Temperatura inicial simulada (°C)', type: 'number', step: '0.1' },
  { name: 'mqtt_simulation_publish_seconds', label: 'Publicación simulada (s)', type: 'number', min: '1', step: '1' },
  { name: 'mqtt_simulation_topic_prefix', label: 'Prefijo de tópicos simulados', type: 'text' },
  { name: 'mqtt_simulation_thermal_loss_c_per_hour', label: 'Pérdida térmica simulada (°C/h)', type: 'number', min: '0', step: '0.1' },
];

const SYSTEM_FIELDS: Record<SystemSection, readonly FieldDefinition[]> = {
  database: [
    { name: 'driver', label: 'Motor de base de datos', type: 'select', options: DATABASE_DRIVERS },
    { name: 'host', label: 'Servidor PostgreSQL', type: 'text', hint: 'No se usa con SQLite.' },
    { name: 'port', label: 'Puerto PostgreSQL', type: 'number', min: '1', max: '65535', step: '1' },
    { name: 'database', label: 'Nombre de la base de datos', type: 'text' },
    { name: 'tls', label: 'Exigir TLS', type: 'boolean' },
    { name: 'trusted_no_tls', label: 'Permitir PostgreSQL sin TLS', type: 'boolean', hint: 'Solo en redes de confianza.' },
  ],
  api: [
    { name: 'host', label: 'Interfaz de escucha', type: 'text' },
    { name: 'port', label: 'Puerto HTTP', type: 'number', min: '1', max: '65535', step: '1' },
    { name: 'cors_origins', label: 'Orígenes CORS', type: 'text', hint: 'Separa varios orígenes con comas.' },
    { name: 'stale_seconds', label: 'Umbral de estado no actualizado (s)', type: 'number', min: '0', step: '1' },
  ],
  mqtt: [
    { name: 'enabled', label: 'Activar MQTT', type: 'boolean' },
    { name: 'host', label: 'Servidor MQTT', type: 'text' },
    { name: 'port', label: 'Puerto MQTT', type: 'number', min: '1', max: '65535', step: '1' },
    { name: 'tls', label: 'Usar TLS', type: 'boolean' },
    { name: 'prefix', label: 'Prefijo de tópicos', type: 'text' },
    { name: 'discovery_prefix', label: 'Prefijo de descubrimiento', type: 'text' },
    { name: 'publish_seconds', label: 'Publicación de estado (s)', type: 'number', min: '1', step: '1' },
    { name: 'fixed_stored_soc_percent', label: 'SOC almacenado fijo (%)', type: 'number', min: '0', max: '100', step: '1' },
    { name: 'fixed_indoor_temperature_c', label: 'Temperatura interior fija (°C)', type: 'number', step: '0.1' },
  ],
  email: [
    { name: 'enabled', label: 'Activar alertas por email', type: 'boolean', hint: 'Al activarlas, el servidor, el remitente y al menos un destinatario son obligatorios.' },
    { name: 'host', label: 'Servidor SMTP', type: 'text' },
    { name: 'port', label: 'Puerto SMTP', type: 'number', min: '1', max: '65535', step: '1' },
    { name: 'security', label: 'Cifrado', type: 'select', options: EMAIL_SECURITY_MODES },
    { name: 'sender', label: 'Remitente', type: 'text' },
    { name: 'recipients', label: 'Destinatarios', type: 'text', hint: 'Separa varias direcciones con comas.' },
    { name: 'timeout_seconds', label: 'Tiempo de espera (s)', type: 'number', min: '1', step: '1' },
  ],
  weather: [
    { name: 'provider', label: 'Proveedor meteorológico', type: 'select', options: WEATHER_PROVIDERS },
    { name: 'municipality_code', label: 'Código de municipio AEMET', type: 'text', hint: 'Código INE de 5 dígitos.' },
    { name: 'timeout_seconds', label: 'Tiempo de espera (s)', type: 'number', min: '1', step: '1' },
    { name: 'simulated_average_temperature_c', label: 'Media simulada (°C)', type: 'number', step: '0.1' },
    { name: 'simulated_minimum_temperature_c', label: 'Mínima simulada (°C)', type: 'number', step: '0.1' },
    { name: 'fallback_average_temperature_c', label: 'Media de respaldo (°C)', type: 'number', step: '0.1' },
    { name: 'fallback_minimum_temperature_c', label: 'Mínima de respaldo (°C)', type: 'number', step: '0.1' },
    { name: 'retry_minutes', label: 'Reintento tras error (min)', type: 'number', min: '1', step: '1' },
    { name: 'refresh_minutes', label: 'Actualización automática (min)', type: 'number', min: '1', step: '1' },
  ],
  output: [{ name: 'driver', label: 'Modo global de salida', type: 'select', options: OUTPUT_DRIVERS, hint: 'Define si el controlador usa salidas simuladas o GPIO.' }],
  logging: [
    { name: 'level', label: 'Nivel mínimo de registro', type: 'select', options: LOG_LEVELS },
    { name: 'max_events', label: 'Eventos retenidos', type: 'number', min: '1', step: '1' },
  ],
  operations: [
    { name: 'controller_poll_seconds', label: 'Intervalo del controlador (s)', type: 'number', min: '1', step: '1' },
    { name: 'heartbeat_stale_multiplier', label: 'Multiplicador de estado obsoleto', type: 'number', min: '1', step: '0.1' },
    { name: 'relay_test_lease_seconds', label: 'Duración de prueba de relés (s)', type: 'number', min: '1', step: '1' },
    { name: 'relay_test_state_poll_seconds', label: 'Lectura durante prueba (s)', type: 'number', min: '1', step: '1' },
    { name: 'relay_test_lease_renew_seconds', label: 'Renovación de prueba (s)', type: 'number', min: '1', step: '1' },
    { name: 'retention_days', label: 'Retención de históricos (días)', type: 'number', min: '1', step: '1', hint: 'Deja vacío para conservarlos indefinidamente.' },
    { name: 'fallback_max_age_minutes', label: 'Antigüedad máxima del fallback (min)', type: 'number', min: '1', step: '1' },
  ],
};

const SECTION_LABELS: Record<SystemSection, string> = {
  database: 'Almacenamiento',
  api: 'Acceso al panel',
  mqtt: 'MQTT',
  weather: 'Meteorología',
  email: 'Alertas por email',
  output: 'Salidas físicas',
  logging: 'Registros',
  operations: 'Operación',
};

const SECRET_LABELS: Record<string, string> = {
  admin_token_digest: 'Credencial de administrador',
  postgres_username: 'Usuario PostgreSQL',
  smtp_username: 'Usuario SMTP',
  smtp_password: 'Contraseña SMTP',
  postgres_password: 'Contraseña PostgreSQL',
  mqtt_username: 'Usuario MQTT',
  mqtt_password: 'Contraseña MQTT',
  aemet_api_key: 'Clave API de AEMET',
};

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
    ParamHelp,
  ],
  templateUrl: './config.html',
  styleUrl: './config.css',
})
export class Config {
  private readonly api = inject(Api);
  private readonly dialog = inject(MatDialog);

  readonly areas = [
    { id: 'summary', label: 'Resumen', description: 'Estado general y accesos rápidos' },
    { id: 'installation', label: 'Instalación', description: 'Intervalos y calidad de lecturas' },
    { id: 'heaters', label: 'Acumuladores', description: 'Equipos, salidas y telemetría' },
    { id: 'planning', label: 'Planificación', description: 'Potencia y optimizador automático' },
    { id: 'integrations', label: 'Integraciones', description: 'MQTT y meteorología' },
    { id: 'service', label: 'Servicio', description: 'Acceso, datos y operación' },
  ] as const;
  readonly integrationSections: readonly IntegrationSection[] = ['mqtt', 'weather', 'email'];
  readonly serviceSections: readonly ServiceSection[] = ['database', 'api', 'output', 'logging', 'operations'];
  readonly heaterFormGroups = HEATER_FORM_GROUPS;
  readonly installationGroups = INSTALLATION_GROUPS;
  readonly heaterFormFields = HEATER_FORM_FIELDS;
  readonly planningFields = PLANNING_FIELDS;

  readonly activeArea = signal<ConfigArea>('summary');
  readonly activeIntegrationSection = signal<IntegrationSection>('mqtt');
  readonly activeServiceSection = signal<ServiceSection>('database');
  readonly config = signal<ConfigDto | null>(null);
  readonly configuration = signal<SystemConfigurationDto | null>(null);
  readonly planningConfig = signal<PlanningSiteConfigDto | null>(null);
  readonly topology = signal<TopologyDto | null>(null);
  readonly banner = signal<Explained | null>(null);
  readonly systemError = signal('');
  readonly fieldErrors = signal<Record<string, string>>({});
  private readonly rendered = new Set<string>();
  readonly pending = signal<Record<string, string>>({});
  readonly systemDraft = signal<Record<string, unknown>>({});
  readonly planningDraft = signal<Record<string, unknown>>({});
  readonly secretActions = signal<Record<string, SecretEditDto['action']>>({});
  readonly secretValues = signal<Record<string, string>>({});
  readonly confirming = signal<PendingEdit | null>(null);
  readonly systemConfirming = signal<SystemSection | null>(null);
  readonly saved = signal('');
  readonly systemMessage = signal('');
  readonly relayConflict = signal(false);
  readonly heaterForm = signal<HeaterForm | null>(null);
  readonly heaterFormMode = signal<'add' | 'edit' | null>(null);
  readonly heaterFormError = signal('');
  readonly heaterSaving = signal(false);
  readonly installationSaving = signal(false);
  readonly planningSaving = signal(false);
  readonly systemSaving = signal(false);
  readonly configLoading = signal(true);
  readonly systemLoading = signal(true);
  readonly operation = signal('');
  readonly weatherRefreshLoading = signal(false);
  readonly weatherRefreshMessage = signal('');
  readonly weatherRefreshError = signal('');
  readonly dirty = computed(() => Object.keys(this.pending()).length > 0);
  readonly planningDirty = computed(() => Object.keys(this.planningDraft()).length > 0);
  readonly loading = computed(() => this.configLoading() || this.systemLoading());

  constructor() { this.load(); }

  chooseArea(area: ConfigArea): void { this.activeArea.set(area); }
  chooseIntegration(section: IntegrationSection): void {
    this.activeIntegrationSection.set(section);
    // The catalogue is only needed by the alert section, so it is read on
    // demand instead of on every panel load.
    if (section === 'email' && !this.alertCatalogue().length) this.loadAlertCatalogue();
  }
  chooseService(section: ServiceSection): void { this.activeServiceSection.set(section); }

  areaIs(area: ConfigArea): boolean { return this.activeArea() === area; }
  sectionLabel(section: SystemSection): string { return SECTION_LABELS[section]; }
  secretLabel(secret: string): string { return SECRET_LABELS[secret] ?? secret; }
  activationLabel(value: string | undefined): string {
    return ({ hot: 'inmediato', next_cycle: 'próximo ciclo', restart: 'requiere reinicio' } as Record<string, string>)[value ?? ''] ?? '';
  }

  load(preserveWorkspaceDrafts = false): void {
    this.configLoading.set(true);
    this.systemLoading.set(true);
    this.systemError.set('');
    this.api.config().subscribe({
      next: (dto) => {
        this.config.set(dto);
        this.banner.set(null);
        this.fieldErrors.set({});
        this.pending.set({});
        this.relayConflict.set(false);
        this.configLoading.set(false);
      },
      error: (error: unknown) => {
        this.configLoading.set(false);
        this.banner.set(this.describe(error));
      },
    });
    forkJoin({
      configuration: this.api.systemConfiguration(),
      topology: this.api.topology(),
      planningConfig: this.api.planningConfig(),
    }).subscribe({
      next: ({ configuration, topology, planningConfig }) => {
        this.configuration.set(configuration);
        this.topology.set(topology);
        this.planningConfig.set(planningConfig);
        if (!preserveWorkspaceDrafts) {
          this.systemDraft.set({});
          this.planningDraft.set({});
          this.secretActions.set({});
          this.secretValues.set({});
        }
        this.systemLoading.set(false);
      },
      error: () => {
        this.systemLoading.set(false);
        this.systemError.set('No se pudo cargar la configuración del sistema. Puedes seguir consultando la instalación.');
      },
    });
  }

  writable(): boolean { return this.topology()?.administrative_writes_allowed === true; }
  topologyMode(): string {
    const mode = this.topology()?.mode;
    return ({ bootstrap: 'inicialización', normal: 'normal', fallback: 'respaldo', migrating: 'migración', incompatible: 'incompatible' } as Record<string, string>)[mode ?? ''] ?? 'desconocido';
  }
  topologyDriver(): string { return this.topology()?.canonical_driver === 'postgresql' ? 'PostgreSQL' : this.topology()?.canonical_driver === 'sqlite' ? 'SQLite' : 'Sin determinar'; }
  formatPower(value: number | null | undefined): string { return value === null || value === undefined ? '—' : `${(value / 1000).toLocaleString('es-ES', { maximumFractionDigits: 1 })} kW`; }
  installationTimezone(): string { return this.config()?.schedule?.timezone ?? 'Europe/Madrid'; }
  dateTime(value: unknown): string {
    if (typeof value !== 'string' || !value) return 'no disponible';
    const formatted = formatInstant(value, this.installationTimezone());
    return formatted === '—' ? 'no disponible' : formatted;
  }
  weatherStatusText(value: unknown): string { return forecastStatusLabel(value); }
  weatherNextText(value: unknown): string { return forecastNextRunLabel(value); }
  configuredOutputDriver(): string { return outputDriverLabel(this.systemValue('output', 'configured_driver') || this.systemValue('output', 'driver')); }
  effectiveOutputDriver(): string { return outputDriverLabel(this.systemValue('output', 'effective_driver') || this.systemValue('output', 'driver')); }
  effectiveOutputReason(): string { return String(this.systemValue('output', 'effective_driver_reason') || 'El driver global seleccionado controla las salidas habilitadas.'); }
  overriddenGpioHeaters(): string[] {
    const value = this.systemValue('output', 'overridden_gpio_heaters');
    return Array.isArray(value) ? value.map(String) : [];
  }
  canonicalPower(): number | null { return this.planningConfig()?.contracted_power_w ?? null; }
  enabledText(value: unknown): string { return value === true || value === 'true' ? 'Activado' : 'Desactivado'; }
  readonly alertCatalogue = signal<AlertTypeDto[]>([]);
  readonly alertSaving = signal<string | null>(null);
  readonly alertError = signal('');
  readonly emailTestLoading = signal(false);
  readonly emailTestMessage = signal('');
  readonly emailTestError = signal('');

  loadAlertCatalogue(): void {
    this.alertError.set('');
    this.api.alertCatalogue().subscribe({
      next: (dto) => this.alertCatalogue.set(dto.alerts),
      error: () => this.alertError.set('No se pudo leer el catálogo de alertas.'),
    });
  }

  toggleAlert(name: string, enabled: boolean): void {
    this.alertSaving.set(name);
    this.alertError.set('');
    this.api.setAlertEnabled(name, enabled).subscribe({
      next: (dto) => { this.alertSaving.set(null); this.alertCatalogue.set(dto.alerts); },
      error: () => { this.alertSaving.set(null); this.alertError.set('No se pudo cambiar la activación de la alerta.'); },
    });
  }

  testEmail(): void {
    this.emailTestLoading.set(true);
    this.emailTestMessage.set('');
    this.emailTestError.set('');
    this.api.testEmail().subscribe({
      next: () => { this.emailTestLoading.set(false); this.emailTestMessage.set('Mensaje de prueba entregado al servidor de correo.'); },
      error: (error: unknown) => {
        this.emailTestLoading.set(false);
        const body = error instanceof HttpErrorResponse ? error.error as { message?: unknown } : null;
        this.emailTestError.set(typeof body?.message === 'string' ? body.message : 'No se pudo enviar el mensaje de prueba.');
      },
    });
  }

  systemValue(section: SystemSection, field: string): unknown {
    const key = this.systemKey(section, field);
    return this.systemDraft()[key] ?? this.configuration()?.sections[section]?.[field] ?? '';
  }
  planningValue(field: string): unknown {
    return this.planningDraft()[field] ?? this.planningConfig()?.[field as keyof PlanningSiteConfigDto] ?? '';
  }
  systemKey(section: SystemSection, field: string): string { return `${section}.${field}`; }
  systemEdit(section: SystemSection, field: string, value: unknown): void {
    this.systemDraft.update((draft) => ({ ...draft, [this.systemKey(section, field)]: value }));
  }
  planningEdit(field: string, value: unknown): void { this.planningDraft.update((draft) => ({ ...draft, [field]: value })); }
  systemFields(section: SystemSection): readonly FieldDefinition[] { return SYSTEM_FIELDS[section]; }
  systemGroups(section: SystemSection): readonly FieldGroup[] {
    const fields = SYSTEM_FIELDS[section];
    if (section === 'mqtt') {
      const enabled = fields[0];
      return this.mqttEnabled()
        ? [{ title: 'Conexión MQTT', description: 'Broker y publicación de temperatura interior y SOC de los acumuladores.', fields: [enabled, ...fields.slice(1, 7)] }, { title: 'Valores fijos de prueba', description: 'Se conservan para pruebas cuando MQTT está desactivado.', fields: fields.slice(7) }]
        : [{ title: 'Modo de integración', fields: [enabled] }, { title: 'Valores fijos de prueba', description: 'Se usan para todos los acumuladores mientras MQTT está desactivado.', fields: fields.slice(7) }];
    }
    if (section === 'weather') {
      return [
        { title: 'Proveedor y ubicación', fields: fields.slice(0, 3) },
        { title: 'Temperaturas simuladas y respaldo', fields: fields.slice(3, 7) },
        { title: 'Actualización', fields: fields.slice(7) },
      ];
    }
    return [{ title: 'Parámetros', fields }];
  }
  planningGroups(): readonly FieldGroup[] {
    return [
      { title: 'Cadencia y horizonte', description: 'Define cuánto mira el optimizador y cuándo vuelve a calcular.', fields: PLANNING_FIELDS.slice(0, 5) },
      { title: 'Límites y sensibilidad', description: 'La potencia contratada total es la fuente única que usa el optimizador y Estado. Las tolerancias gobiernan los recálculos por desviación.', fields: PLANNING_FIELDS.slice(5, 10) },
      { title: 'Simulación MQTT de acumuladores', description: 'Solo se usa para pruebas controladas.', fields: PLANNING_FIELDS.slice(10) },
    ];
  }
  mqttEnabled(): boolean {
    const value = this.systemValue('mqtt', 'enabled');
    return value === true || value === 'true';
  }
  secrets(section: SystemSection): string[] {
    if (section === 'mqtt' && !this.mqttEnabled()) return [];
    return ({ api: ['admin_token_digest'], database: ['postgres_username', 'postgres_password'], mqtt: ['mqtt_username', 'mqtt_password'], weather: ['aemet_api_key'], email: ['smtp_username', 'smtp_password'] } as Partial<Record<SystemSection, string[]>>)[section] ?? [];
  }
  secretAction(name: string): SecretEditDto['action'] { return this.secretActions()[name] ?? 'keep'; }
  setSecretAction(name: string, action: SecretEditDto['action']): void {
    this.secretActions.update((current) => ({ ...current, [name]: action }));
    if (action !== 'replace') this.setSecretValue(name, '');
  }
  setSecretValue(name: string, value: string): void { this.secretValues.update((current) => ({ ...current, [name]: value })); }
  systemHasChanges(section: SystemSection): boolean {
    const draft = this.systemDraft();
    return SYSTEM_FIELDS[section].some((field) => this.systemKey(section, field.name) in draft) || this.secrets(section).some((secret) => this.secretAction(secret) !== 'keep');
  }

  key(field: string, heaterId: string | null): string { return heaterId === null ? field : `${heaterId}.${field}`; }
  register(field: string, heaterId: string | null): string { this.rendered.add(this.key(field, heaterId)); return ''; }
  label(field: string): string {
    const labels: Record<string, string> = {
      max_total_power_kw: 'Potencia máxima simultánea (kW)', slot_minutes: 'Duración de intervalo (min)', retention_days: 'Retención de históricos (días)', poll_seconds: 'Intervalo de sondeo (s)', log_level: 'Nivel de registro',
      indoor_max_age_minutes: 'Antigüedad máxima interior (min)', indoor_min_plausible_c: 'Temperatura interior mínima (°C)', indoor_max_plausible_c: 'Temperatura interior máxima (°C)',
    };
    return labels[field] ?? field;
  }
  helpField(meta: HeaterFormFieldMeta): string { return meta.helpField ?? meta.key; }
  heaterMeta(key: string): HeaterFormFieldMeta | undefined { return HEATER_FORM_FIELDS.find((field) => field.key === key); }
  edit(field: string, heaterId: string | null, value: string): void { this.pending.update((current) => ({ ...current, [this.key(field, heaterId)]: value })); }

  installationEdits(): readonly FormEdit[] {
    const pending = this.pending();
    const fields = [...INSTALLATION_GROUPS.flatMap((group) => group.fields), ...LEGACY_INSTALLATION_FIELDS];
    return fields.filter((field) => this.key(field, null) in pending).map((field) => ({ field, value: pending[this.key(field, null)] }));
  }
  saveInstallation(): void {
    const edits = this.installationEdits();
    if (edits.length === 0 || this.installationSaving()) return;
    if (edits.some((edit) => needsConfirmation(edit.field))) {
      this.confirming.set({ field: edits[0].field, value: edits[0].value, heaterId: null, batchEdits: edits });
      return;
    }
    this.applyInstallation(edits);
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
    if (edit === null) return '';
    if (edit.batchEdits?.length) {
      const electrical = edit.batchEdits.filter((item) => needsConfirmation(item.field));
      if (electrical.length === 1) return confirmationText(electrical[0].field, electrical[0].value);
      if (electrical.length > 1) return 'Se aplicarán varios cambios, incluidos parámetros eléctricos. Revisa los valores antes de continuar.';
      return `Se aplicarán ${edit.batchEdits.length} cambios en la instalación. ¿Continuar?`;
    }
    return edit.formEdits ? 'Se aplicarán los cambios del acumulador. Revisa especialmente los valores eléctricos.' : confirmationText(edit.field, edit.value);
  }
  confirm(): void {
    const edit = this.confirming();
    this.confirming.set(null);
    if (edit === null) return;
    if (edit.formEdits) this.applyHeaterEdits(edit.heaterId!);
    else if (edit.batchEdits) this.applyInstallation(edit.batchEdits);
    else this.apply(edit);
  }
  cancelConfirmation(): void { this.confirming.set(null); }
  confirmSystemSave(): void {
    const section = this.systemConfirming();
    this.systemConfirming.set(null);
    if (section !== null) this.saveSystem(section);
  }
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
    const value = (heater as unknown as Record<string, unknown>)[field];
    return value === null || value === undefined ? '' : String(value);
  }

  openAddHeater(): void {
    this.activeArea.set('heaters');
    this.heaterFormMode.set('add');
    this.heaterFormError.set('');
    this.heaterForm.set({ id: '', name: '', model: '', power_kw: '1', full_charge_hours: '8', full_discharge_hours: '10', static_emission_percent: '20', room_thermal_capacity_kwh_per_c: '2.5', room_heat_loss_kw_per_c: '0.12', priority: '0', enabled: true, telemetry_topic: '', output: 'simulated', pin: '', active_high: true });
  }
  openEditHeater(heater: ConfigDto['heaters'][number]): void {
    this.activeArea.set('heaters');
    this.heaterFormMode.set('edit');
    this.heaterFormError.set('');
    this.heaterForm.set({
      id: heater.id, name: heater.name, model: heater.model ?? '', power_kw: String(heater.power_kw), full_charge_hours: String(heater.full_charge_hours), full_discharge_hours: String(heater.full_discharge_hours), static_emission_percent: String(heater.static_emission_percent), room_thermal_capacity_kwh_per_c: String(heater.room_thermal_capacity_kwh_per_c), room_heat_loss_kw_per_c: String(heater.room_heat_loss_kw_per_c), priority: String(heater.priority), enabled: heater.enabled, telemetry_topic: heater.telemetry_topic ?? '', output: heater.output.kind, pin: heater.output.pin === null ? '' : String(heater.output.pin), active_high: heater.output.active_high,
    });
  }
  cancelHeaterForm(): void { this.heaterForm.set(null); this.heaterFormMode.set(null); this.heaterFormError.set(''); }
  updateHeaterForm(field: keyof HeaterForm, value: unknown): void { this.heaterForm.update((current) => current ? { ...current, [field]: value } : current); }
  saveHeater(): void {
    const form = this.heaterForm();
    const snapshot = this.config();
    if (!form || !snapshot || this.heaterSaving()) return;
    this.heaterFormError.set('');
    if (!form.id.trim() || !this.validNumber(form.power_kw) || !this.validNumber(form.full_charge_hours)) {
      this.heaterFormError.set('Indica un identificador, una potencia y un tiempo de carga válidos.');
      return;
    }
    if (!this.validNumber(form.room_thermal_capacity_kwh_per_c) || Number(form.room_thermal_capacity_kwh_per_c) <= 0 || !this.validNumber(form.room_heat_loss_kw_per_c) || Number(form.room_heat_loss_kw_per_c) < 0) {
      this.heaterFormError.set('La capacidad térmica debe ser positiva y la pérdida térmica no negativa.');
      return;
    }
    if (!this.validNumber(form.full_discharge_hours) || Number(form.full_discharge_hours) <= 0) {
      this.heaterFormError.set('Indica unas horas de descarga nominal positivas.');
      return;
    }
    if (!this.validNumber(form.static_emission_percent) || Number(form.static_emission_percent) < 0 || Number(form.static_emission_percent) > 100) {
      this.heaterFormError.set('La emisión residual debe estar entre 0 y 100.');
      return;
    }
    this.heaterSaving.set(true);
    if (this.heaterFormMode() === 'add') {
      const payload: AddHeaterRequest = {
        revision: snapshot.config_revision, id: form.id.trim(), name: form.name.trim() || undefined, model: form.model.trim() || undefined,
        power_kw: Number(form.power_kw), full_charge_hours: Number(form.full_charge_hours), full_discharge_hours: Number(form.full_discharge_hours), static_emission_percent: Number(form.static_emission_percent), room_thermal_capacity_kwh_per_c: Number(form.room_thermal_capacity_kwh_per_c), room_heat_loss_kw_per_c: Number(form.room_heat_loss_kw_per_c), priority: Number(form.priority), enabled: form.enabled,
        telemetry_topic: form.telemetry_topic.trim() || null, output: form.output, pin: form.pin.trim() ? Number(form.pin) : null, active_high: form.active_high,
        temperature_targets: [],
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
      this.dialog.open(ConfirmDialog, {
        width: 'min(28rem, calc(100vw - 2rem))',
        data: {
          title: `Confirmar cambios en ${original.name}`,
          message: 'Se aplicarán los cambios del acumulador. Revisa especialmente los valores eléctricos.',
          confirmLabel: 'Sí, guardar',
        },
      }).afterClosed().subscribe((confirmed: boolean) => {
        if (confirmed) this.applyHeaterEdits(original.id);
      });
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
      next: (change) => { this.heaterSaving.set(false); this.saved.set(`Acumulador eliminado: ${change.entity_key ?? heaterId}`); this.cancelHeaterForm(); this.load(true); },
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
      next: (change) => { this.saved.set(`${edit.field}: ${change.old_value ?? '—'} → ${change.new_value ?? '—'}`); this.fieldErrors.update((errors) => { const next = { ...errors }; delete next[target]; return next; }); this.discard(edit.field, edit.heaterId); this.load(true); },
      error: (error: unknown) => this.reject(target, error),
    });
  }
  private applyInstallation(edits: readonly FormEdit[]): void {
    const current = this.config();
    if (!current || edits.length === 0) return;
    this.installationSaving.set(true);
    const values = Object.fromEntries(edits.map((edit) => [edit.field, edit.value]));
    this.api.patchInstallation(current.config_revision, values).subscribe({
      next: (response) => {
        this.installationSaving.set(false);
        const count = response.changes.length;
        if (count === 1 && response.changes[0].field) {
          const change = response.changes[0];
          this.saved.set(`${change.field}: ${change.old_value ?? '—'} → ${change.new_value ?? '—'}`);
        } else this.saved.set(`Configuración guardada (${count} cambios).`);
        this.fieldErrors.update((errors) => { const next = { ...errors }; for (const edit of edits) delete next[this.key(edit.field, null)]; return next; });
        for (const edit of edits) this.discard(edit.field, null);
        this.load(true);
      },
      error: (error: unknown) => {
        this.installationSaving.set(false);
        const field = error instanceof HttpErrorResponse && error.error !== null && typeof error.error === 'object' && 'field' in error.error && typeof error.error.field === 'string' ? error.error.field : null;
        this.reject(field === null ? 'installation' : this.key(field, null), error);
      },
    });
  }
  private applyHeaterEdits(heaterId: string): void {
    const form = this.heaterForm();
    const revision = this.config()?.config_revision;
    if (!form || revision === undefined) return;
    const payload: UpdateHeaterRequest = {
      revision, name: form.name.trim(), model: form.model.trim() || null, power_kw: Number(form.power_kw), full_charge_hours: Number(form.full_charge_hours), full_discharge_hours: Number(form.full_discharge_hours), static_emission_percent: Number(form.static_emission_percent), room_thermal_capacity_kwh_per_c: Number(form.room_thermal_capacity_kwh_per_c), room_heat_loss_kw_per_c: Number(form.room_heat_loss_kw_per_c), priority: Number(form.priority), enabled: form.enabled,
      telemetry_topic: form.telemetry_topic.trim() || null, output: form.output, pin: form.pin.trim() ? Number(form.pin) : null, active_high: form.active_high,
    };
    this.heaterSaving.set(true);
    this.api.updateHeater(heaterId, payload).subscribe({
      next: () => this.finishHeaterSave('Acumulador actualizado.'),
      error: (error: unknown) => { this.heaterSaving.set(false); this.reject(this.key('form', heaterId), error); this.heaterFormError.set('No se pudo guardar el acumulador. El formulario conserva tus cambios.'); },
    });
  }
  private finishHeaterSave(message: string): void { this.heaterSaving.set(false); this.saved.set(message); this.cancelHeaterForm(); this.load(true); }
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

  requestSystemSave(section: SystemSection): void {
    if (!this.writable() || !this.systemHasChanges(section) || this.systemSaving()) return;
    if (section === 'database' || section === 'output' || this.secrets(section).some((secret) => this.secretAction(secret) !== 'keep')) this.systemConfirming.set(section);
    else this.saveSystem(section);
  }
  savePlanning(): void {
    this.systemError.set('');
    if (!this.writable() || !this.planningDirty() || this.planningSaving()) return;
    const snapshot = this.planningConfig();
    if (!snapshot) return;
    const number = (name: string): number => Number(this.planningValue(name));
    const values = {
      replan_minutes: number('replan_minutes'), planning_window_hours: number('planning_window_hours'), forecast_horizon_hours: number('forecast_horizon_hours'), aemet_query_hour: number('aemet_query_hour'), solver_time_limit_seconds: number('solver_time_limit_seconds'),
      contracted_power_w: number('contracted_power_w'), max_heating_power_w: number('max_heating_power_w'), base_load_w: number('base_load_w'), deviation_shortfall_tolerance_c: number('deviation_shortfall_tolerance_c'), deviation_surplus_soc_percent: number('deviation_surplus_soc_percent'),
      mqtt_simulation_enabled: this.planningValue('mqtt_simulation_enabled') === true || this.planningValue('mqtt_simulation_enabled') === 'true', mqtt_simulation_initial_temperature_c: number('mqtt_simulation_initial_temperature_c'), mqtt_simulation_publish_seconds: number('mqtt_simulation_publish_seconds'), mqtt_simulation_topic_prefix: String(this.planningValue('mqtt_simulation_topic_prefix')), mqtt_simulation_thermal_loss_c_per_hour: number('mqtt_simulation_thermal_loss_c_per_hour'),
    };
    this.planningSaving.set(true);
    this.api.patchPlanningConfig(snapshot.revision, values).subscribe({
      next: (updated) => { this.planningSaving.set(false); this.planningConfig.set(updated); this.planningDraft.set({}); this.saved.set('Parámetros de planificación guardados.'); },
      error: (error: unknown) => { this.planningSaving.set(false); this.systemError.set(error instanceof HttpErrorResponse && error.status === 409 ? 'La configuración de planificación cambió. Tus valores siguen aquí; vuelve a leer antes de guardar.' : 'No se pudo guardar la planificación. Revisa los campos.'); },
    });
  }
  private saveSystem(section: SystemSection): void {
    this.systemError.set('');
    if (!this.writable() || this.systemSaving()) return;
    const snapshot = this.configuration();
    if (!snapshot) return;
    const values: Record<string, unknown> = {};
    for (const field of SYSTEM_FIELDS[section]) {
      const key = this.systemKey(section, field.name);
      if (key in this.systemDraft()) values[field.name] = this.coerce(field, this.systemDraft()[key]);
    }
    const secrets: Record<string, SecretEditDto> = {};
    const sectionSecrets = this.secrets(section);
    for (const name of sectionSecrets) {
      const action = this.secretAction(name);
      secrets[name] = action === 'replace' ? { action, value: this.secretValues()[name] ?? '' } : { action };
    }
    this.systemSaving.set(true);
    this.api.patchSystem(section, snapshot.revision, values, secrets).subscribe({
      next: (updated) => {
        this.systemSaving.set(false);
        this.configuration.set(updated);
        this.systemDraft.update((draft) => { const next = { ...draft }; for (const field of SYSTEM_FIELDS[section]) delete next[this.systemKey(section, field.name)]; return next; });
        this.secretValues.update((values) => { const next = { ...values }; for (const secret of sectionSecrets) delete next[secret]; return next; });
        this.secretActions.update((actions) => { const next = { ...actions }; for (const secret of sectionSecrets) delete next[secret]; return next; });
        this.saved.set(updated.pending_restart?.length ? 'Guardado. Reinicia el proceso indicado para aplicar todos los cambios.' : `${SECTION_LABELS[section]} actualizado.`);
      },
      error: (error: unknown) => { this.systemSaving.set(false); this.systemError.set(error instanceof HttpErrorResponse && error.status === 409 ? 'La configuración cambió. Tus valores siguen aquí; vuelve a leer antes de guardar.' : 'No se pudo guardar. Tus cambios siguen en pantalla.'); },
    });
  }
  testDatabase(): void {
    this.api.testDatabase(this.databaseCandidate()).subscribe({
      next: () => { this.systemMessage.set('Conexión de base de datos verificada sin guardar cambios.'); this.systemError.set(''); },
      error: () => this.systemError.set('No se pudo conectar con el destino; no se guardó ningún cambio.'),
    });
  }
  migrateDatabase(): void {
    const topology = this.topology();
    if (!topology?.locator_revision || !this.writable()) return;
    this.systemConfirming.set(null);
    this.operation.set('Migración en curso…');
    this.api.migrateDatabase(topology.locator_revision, this.databaseCandidate()).subscribe({
      next: (operation) => this.operation.set(`Migración ${operation.status}: ${operation.phase}`),
      error: () => { this.operation.set(''); this.systemError.set('La migración no se pudo completar; el backend activo no ha cambiado.'); },
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
        this.configuration.update((current) => current ? ({ ...current, sections: { ...current.sections, weather: { ...current.sections.weather, forecast_status: result.forecast_status, forecast_last_attempt_at: result.forecast_last_attempt_at, forecast_last_error: result.forecast_last_error, forecast_next_run_at: result.forecast_next_run_at, forecast_next_run_kind: result.forecast_next_run_kind } } }) : current);
      },
      error: (error: unknown) => {
        this.weatherRefreshLoading.set(false);
        this.weatherRefreshMessage.set('');
        const body = error instanceof HttpErrorResponse ? error.error as { message?: unknown } : null;
        this.weatherRefreshError.set(typeof body?.message === 'string' ? body.message : 'No se pudo consultar AEMET.');
      },
    });
  }
  private coerce(field: FieldDefinition, value: unknown): unknown {
    if (field.name === 'cors_origins' || field.name === 'recipients') return String(value).split(',').map((item) => item.trim()).filter(Boolean);
    if (value === '' && ['host', 'database', 'municipality_code', 'stale_seconds', 'retention_days', 'sender'].includes(field.name)) return null;
    if (field.type === 'number') return Number(value);
    if (field.type === 'boolean') return value === true || value === 'true';
    return String(value);
  }
  private databaseCandidate(): DatabaseCandidateDto {
    const section = this.configuration()?.sections.database ?? {};
    const draft = this.systemDraft();
    const value = (name: string): unknown => {
      const key = this.systemKey('database', name);
      return key in draft ? draft[key] : section[name];
    };
    return {
      driver: String(value('driver') || 'sqlite') as 'sqlite' | 'postgresql', host: String(value('host') || '') || undefined, port: Number(value('port')) || undefined, database: String(value('database') || '') || undefined,
      username: this.secretValues()['postgres_username'], password: this.secretValues()['postgres_password'], tls: Boolean(value('tls')), trusted_no_tls: Boolean(value('trusted_no_tls')),
    };
  }
  private describe(error: unknown): Explained {
    if (error instanceof HttpErrorResponse) {
      const body = error.error as ApiErrorDto | null;
      if (body && typeof body === 'object' && 'code' in body) return explain(body);
    }
    return UNREACHABLE;
  }
}
