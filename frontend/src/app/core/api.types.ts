/**
 * Types of the API responses, derived from
 * specs/002-config-api/contracts/http-api.md.
 *
 * `output_on` is `boolean | null` and NOT `boolean`. That is not an oversight of
 * the API: `null` means "there is no proof either way", which is a different
 * thing from "it is off". Typing it as `boolean` here would collapse the
 * distinction at the boundary and everything downstream would be a lie.
 */

export type Liveness = 'live' | 'live_degraded' | 'stale' | 'never_seen';

export interface ControllerHealthDto {
  liveness: Liveness;
  state_is_current: boolean;
  last_seen_at: string | null;
  age_seconds: number | null;
  started_at: string | null;
  degraded: boolean;
  driver_kind: 'simulated' | 'gpio' | null;
  tolerance_seconds: number | null;
  multiple_controllers_suspected: boolean;
}

export interface PowerDto {
  instant_w: number;
  limit_w: number;
  percent_of_limit: number;
}

export interface HeaterStateDto {
  id: string;
  name: string;
  enabled: boolean;
  power_w: number;
  /** Null when the state is not current. Never coerce this to a boolean. */
  output_on: boolean | null;
  last_known_output_on: boolean;
  changed_at: string | null;
}

export interface PlanSlotDto {
  start: string;
  end: string;
  heater_ids: string[];
}

export interface PlanDto {
  window_start: string;
  window_end: string;
  slot_minutes: number;
  installation_revision: number;
  created_at: string;
  slots: PlanSlotDto[];
}

export type ForecastSource = 'aemet' | 'simulated' | 'fallback';

export interface ForecastDto {
  date: string;
  source: ForecastSource;
  average_temperature_c: number;
  minimum_temperature_c: number | null;
  maximum_temperature_c: number | null;
  municipality: string | null;
}

export interface AllocationDto {
  heater_id: string;
  requested_minutes: number;
  allocated_minutes: number;
  unmet_minutes: number;
}

export interface StatusDto {
  observed_at: string;
  controller: ControllerHealthDto;
  /** Null when the state is not current: an unconfirmable figure is not published. */
  power: PowerDto | null;
  heaters: HeaterStateDto[];
  /** Null when no window contains the moment of the query. */
  plan: PlanDto | null;
  forecast: ForecastDto | null;
  allocations: AllocationDto[];
}

export type ControllerLogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';
export interface ControllerLogEventDto { id: number; occurred_at: string; level: ControllerLogLevel; logger: string; message: string; }
export interface ControllerLogPageDto { items: ControllerLogEventDto[]; limit_applied: number; has_more: boolean; next_before_id: number | null; }

/* --------------------------------------------------------------------------
 * Configuration
 * -------------------------------------------------------------------------- */

export interface OutputDto {
  kind: 'simulated' | 'gpio';
  pin: number | null;
  active_high: boolean;
}

export interface ThermalDto {
  target_temperature_c: number;
  design_outdoor_temperature_c: number;
  thermal_factor: number;
  min_charge: number;
  max_charge: number;
}

export interface HeaterDto {
  id: string;
  name: string;
  model: string | null;
  power_kw: number;
  full_charge_hours: number;
  target_charge: number;
  priority: number;
  enabled: boolean;
  indoor_topic: string | null;
  output: OutputDto;
  thermal: ThermalDto | null;
}

export interface ScheduleDto {
  timezone: string;
  start_time: string;
  end_time: string;
  weekdays: number[];
}

export interface WeatherDto {
  provider: 'simulated' | 'aemet';
  municipality_code: string | null;
  /** The NAME of the environment variable. Never its value. */
  api_key_env: string | null;
  timeout_seconds: number | null;
  simulated_average_temperature_c: number | null;
  simulated_minimum_temperature_c: number | null;
  fallback_average_temperature_c: number | null;
  fallback_minimum_temperature_c: number | null;
  retry_minutes: number;
  refresh_minutes: number;
}

export interface ConfigDto {
  config_revision: number;
  schema_revision: string;
  max_total_power_kw: number;
  slot_minutes: number;
  window_minutes: number;
  indoor_max_age_minutes: number;
  indoor_min_plausible_c: number;
  indoor_max_plausible_c: number;
  log_level: string;
  state_file: string;
  poll_seconds: number;
  retention_days: number | null;
  schedule: ScheduleDto | null;
  weather: WeatherDto | null;
  heaters: HeaterDto[];
}

export interface SetFieldRequest {
  /** Mandatory: the optimistic lock. Never omit it. */
  revision: number;
  field: string;
  value: string;
}

export interface AddHeaterRequest {
  revision: number;
  id: string;
  power_kw: number;
  full_charge_hours: number;
  name?: string;
  model?: string;
  target_charge?: number;
  priority?: number;
  enabled?: boolean;
  indoor_topic?: string | null;
  output?: 'simulated' | 'gpio';
  pin?: number | null;
  active_high?: boolean;
  target_temperature_c?: number | null;
  design_outdoor_temperature_c?: number | null;
  thermal_factor?: number;
  min_charge?: number;
  max_charge?: number;
}

export interface ChangeDto {
  entity: string;
  entity_key: string | null;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  action: 'set' | 'add' | 'remove';
  revision_before: number;
  revision_after: number;
}

/* --------------------------------------------------------------------------
 * History
 * -------------------------------------------------------------------------- */

export interface PageDto<T> {
  items: T[];
  limit_applied: number;
  has_more: boolean;
  /** Opaque. Sent back verbatim; never parsed nor constructed. */
  next_cursor: string | null;
}

export interface PlanHistoryDto {
  id: number;
  created_at: string;
  window_start: string;
  window_end: string;
  slot_minutes: number;
  installation_revision: number;
  forecast_id: number | null;
}

export interface ForecastHistoryDto {
  id: number;
  forecast_date: string;
  source: ForecastSource;
  average_temperature_c: number;
  minimum_temperature_c: number | null;
  maximum_temperature_c: number | null;
  municipality: string | null;
  retrieved_at: string;
}

export interface TransitionHistoryDto {
  id: number;
  heater_id: string;
  state: boolean;
  occurred_at: string;
  plan_id: number | null;
}

export interface PruneDto {
  deleted: Record<string, number>;
  total: number;
  retention_days: number | null;
  unlimited: boolean;
}

export interface RelayTestHeaterDto { id: string; name: string; position: number; power_w: number; desired_state: boolean; confirmed_state: boolean | null; result: 'idle' | 'pending' | 'confirmed' | 'rejected' | 'unknown'; result_code: string | null; confirmed_at: string | null; }
export interface RelayTestViewDto { session: { id: string; status: 'starting' | 'active' | 'ending' | 'ended' | 'failed'; owner: boolean; requested_at: string; activated_at: string | null; ended_at: string | null; lease_expires_at: string | null; end_reason: string | null } | null; controller: { state_is_current: boolean; last_seen_at: string | null }; safety: { automatic_control_blocked: boolean; fault_latched: boolean; fault_session_id: string | null; fault_reason: string | null; fault_latched_at: string | null; fault_recovery_attempted_at: string | null; fault_recovered_at: string | null }; audit: { degraded: boolean; degraded_since: string | null }; heaters: RelayTestHeaterDto[]; }
export interface RelayTestStartDto { session_id: string; client_credential: string; status: string; lease_expires_at: string; state_poll_seconds: number; lease_renew_seconds: number; }

export type SystemSection = 'database' | 'api' | 'mqtt' | 'weather' | 'output' | 'logging' | 'operations';
export type ActivationPolicy = 'hot' | 'next_cycle' | 'restart';
export interface SecretStatusDto { configured: boolean; rotated_at: string | null; }
export interface SystemConfigurationDto {
  revision: number;
  format_version: number;
  sections: Record<SystemSection, Record<string, unknown>>;
  secrets: Record<string, SecretStatusDto>;
  activation: Record<string, ActivationPolicy>;
  pending_restart?: string[];
}
export interface TopologyDto {
  mode: 'bootstrap' | 'normal' | 'fallback' | 'migrating' | 'incompatible';
  canonical_driver: 'sqlite' | 'postgresql' | null;
  connected: boolean;
  locator_revision?: number | null;
  configuration_revision: number | null;
  fallback_captured_at: string | null;
  last_reconciled_at: string | null;
  pending_events: number;
  administrative_writes_allowed: boolean;
}
export interface OnboardingStatusDto { required: boolean; state: string; }
export interface SecretEditDto { action: 'keep' | 'replace' | 'clear'; value?: string; }
export interface DatabaseCandidateDto {
  driver: 'sqlite' | 'postgresql'; host?: string; port?: number; database?: string;
  username?: string; password?: string; tls?: boolean; trusted_no_tls?: boolean;
}
export interface MigrationDto { operation_id: string; phase: string; status: string; detail: string | null; }
export interface ConnectionTestDto { ok: boolean; driver: string; provider?: string; host?: string; port?: number; tls?: boolean | null; }

/* --------------------------------------------------------------------------
 * Errors. A closed union, not a free string: an unhandled code must be a
 * compile error, not a silent fallthrough to a generic message.
 * -------------------------------------------------------------------------- */

export type ApiErrorCode =
  | 'unauthorized'
  | 'not_found'
  | 'already_exists'
  | 'config_conflict'
  | 'validation_failed'
  | 'secret_rejected'
  | 'bad_request'
  | 'no_configuration'
  | 'schema_unusable'
  | 'store_unavailable'
  | 'relay_test_active'
  | 'relay_test_fault_latched'
  | 'degraded_mode'
  | 'operation_in_progress'
  | 'connection_test_failed'
  | 'internal_error';

export interface ApiErrorDto {
  code: ApiErrorCode;
  message: string;
  field: string | null;
  heater_id: string | null;
}
