/**
 * Operator-facing vocabulary shared by the live, planning and history views.
 * API codes remain stable and are intentionally not rendered as primary copy.
 */

export type CanonicalPlanStatus = 'VALID' | 'CONVERGING' | 'DEGRADED' | 'INVALID';

export type PresentationSeverity = 'info' | 'success' | 'warning' | 'error';

const PLANNING_STEP_LABELS: Record<string, string> = {
  input_validation: 'Validación de entradas',
  telemetry: 'Telemetría',
  aemet_coverage: 'Cobertura AEMET',
  demand_estimation: 'Balance energético',
  room_model: 'Modelo energético',
  constraints: 'Materialización de consignas',
  resolution: 'Resolución',
  safety_validation: 'Validación de seguridad',
  operator_summary: 'Resumen final',
};

const CHECK_STATUS_LABELS: Record<string, string> = {
  pending: 'pendiente',
  running: 'en curso',
  completed: 'completado',
  error: 'error',
  cancelled: 'cancelado',
  skipped: 'omitido',
};

const RELAY_SESSION_STATUS_LABELS: Record<string, string> = {
  starting: 'Preparando la prueba',
  active: 'Prueba activa',
  ending: 'Apagando las salidas',
  ended: 'Prueba finalizada',
  failed: 'Recuperación necesaria',
};

const CHARGE_REASON_LABELS: Record<string, string> = {
  necessary_for_target: 'Carga necesaria para la consigna',
  preheating_for_next_target: 'Precalentamiento para la siguiente consigna',
  residual_storage: 'Carga residual',
};

const LOG_LEVEL_LABELS: Record<string, string> = {
  debug: 'Depuración',
  info: 'Información',
  warning: 'Aviso',
  error: 'Error',
  critical: 'Crítico',
};

const PLANNING_ACTION_LABELS: Record<string, string> = {
  check_telemetry: 'Comprobar telemetría',
  check_weather: 'Comprobar conexión meteorológica',
  review_configuration: 'Revisar configuración',
  review_power: 'Revisar potencia y consignas',
  contact_support: 'Contactar con soporte',
};

const PLANNING_RECOVERY_CAUSE_LABELS: Record<string, string> = {
  missing_aemet_coverage: 'Cobertura meteorológica insuficiente',
  missing_required_state: 'Falta telemetría reciente',
  invalid_configuration: 'Configuración no válida',
  insufficient_capacity_or_power: 'Capacidad o potencia insuficiente',
  solver_failure: 'Cálculo no disponible',
  no_plan_available: 'No hay un plan utilizable',
  unknown: 'Causa no reconocida',
};

export function planningStepLabel(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase();
  return PLANNING_STEP_LABELS[key] ?? (key ? 'Paso no reconocido' : 'Trabajo de vista previa');
}

export function checkStatusLabel(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase();
  return CHECK_STATUS_LABELS[key] ?? (key ? 'Estado no reconocido' : 'Sin estado');
}

export function relaySessionStatusLabel(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase();
  return RELAY_SESSION_STATUS_LABELS[key] ?? (key ? 'Estado de prueba no reconocido' : 'Sin estado de prueba');
}

export function chargeReasonLabel(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase();
  return CHARGE_REASON_LABELS[key] ?? 'Motivo no disponible';
}

export function controllerLogLevelLabel(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase();
  return LOG_LEVEL_LABELS[key] ?? (key ? 'Nivel no reconocido' : 'Sin nivel');
}

export function severityLabel(value: unknown): string {
  switch (String(value ?? '').trim().toLowerCase()) {
    case 'info': return 'Información';
    case 'success':
    case 'ok': return 'Correcto';
    case 'warning':
    case 'warn': return 'Aviso';
    case 'error':
    case 'alert': return 'Error';
    default: return 'Severidad no reconocida';
  }
}

export function planningActionLabel(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase();
  return PLANNING_ACTION_LABELS[key] ?? (key ? 'Acción no reconocida' : 'Sin acción recomendada');
}

export function planningRecoveryCauseLabel(value: unknown): string {
  const key = String(value ?? '').trim().toLowerCase();
  return PLANNING_RECOVERY_CAUSE_LABELS[key] ?? (key ? 'Causa no reconocida' : 'Causa no disponible');
}

export function planningRecoveryActionLabel(value: unknown): string {
  return planningActionLabel(value);
}

export function planningActionForCause(value: unknown): string | null {
  const cause = String(value ?? '').trim().toLowerCase();
  if (cause === 'missing_aemet_coverage' || cause === 'missing_forecast_coverage' || cause === 'missing_guard_forecast_coverage' || cause === 'forecast_not_eligible') return 'Espera una previsión AEMET horaria completa de 24 horas o revisa la conexión meteorológica.';
  if (cause === 'missing_required_state') return 'Comprueba que cada acumulador publica temperatura interior y SOC reciente.';
  if (cause === 'invalid_configuration') return 'Revisa las consignas y los parámetros de planificación antes de recalcular.';
  if (cause === 'insufficient_capacity_or_power' || cause === 'insufficient_stored_energy_or_power') return 'Revisa potencia disponible, capacidad térmica y la consigna programada.';
  if (cause === 'no_plan_available') return 'Revisa la configuración y solicita un nuevo cálculo del plan.';
  if (cause === 'solver_failure' || cause.startsWith('solver')) return 'Revisa la configuración del optimizador o contacta con soporte.';
  return null;
}

const PLAN_STATUS_ALIASES: Record<string, CanonicalPlanStatus> = {
  valid: 'VALID',
  feasible: 'VALID',
  converging: 'CONVERGING',
  degraded: 'DEGRADED',
  deficit: 'DEGRADED',
  best_effort: 'DEGRADED',
  invalid: 'INVALID',
  preview: 'INVALID',
};

export function normalizePlanStatus(value: unknown): CanonicalPlanStatus | null {
  if (typeof value !== 'string') return null;
  return PLAN_STATUS_ALIASES[value.trim().toLowerCase()] ?? null;
}

export function planStatusLabel(value: unknown): string {
  switch (normalizePlanStatus(value)) {
    case 'VALID': return 'Cumplido';
    case 'CONVERGING': return 'Convergiendo';
    case 'DEGRADED': return 'Degradado';
    case 'INVALID': return 'No válido';
    default: return value ? 'Estado no reconocido' : 'Sin evaluación';
  }
}

export function forecastSourceLabel(value: unknown): string {
  return String(value ?? '').trim().toLowerCase() === 'aemet'
    ? 'proveedor real (AEMET)'
    : 'Origen no disponible';
}

export function forecastStatusLabel(value: unknown): string {
  switch (String(value ?? '').trim().toLowerCase()) {
    case 'success': return 'Consulta correcta';
    case 'error': return 'Error de consulta';
    default: return 'Sin consulta';
  }
}

export function forecastNextRunLabel(kind: unknown): string {
  switch (String(kind ?? '').trim().toLowerCase()) {
    case 'retry': return 'Próximo reintento';
    case 'daily': return 'Próxima actualización diaria';
    case 'refresh': return 'Próxima actualización';
    default: return 'Próxima consulta';
  }
}

const PLAN_REASON_LABELS: Record<string, string> = {
  activated: 'Plan activado',
  periodic: 'Replanificación periódica',
  deviation: 'Replanificación por desviación',
  startup: 'Arranque del controlador',
  manual: 'Solicitud manual',
  invalid_configuration: 'Configuración no válida',
  forecast_not_eligible: 'Previsión no apta para automático',
  missing_aemet_coverage: 'Cobertura AEMET insuficiente',
  missing_forecast_coverage: 'Cobertura meteorológica insuficiente',
  missing_required_state: 'Falta telemetría necesaria',
  insufficient_capacity_or_power: 'Capacidad o potencia insuficiente',
  insufficient_stored_energy_or_power: 'Energía almacenada o potencia insuficiente',
  heater_power_exceeds_global_limit: 'Potencia del acumulador sobre el límite',
  solver_time_limit: 'Tiempo del optimizador agotado',
  solver_failure: 'Fallo del optimizador',
  solver_unavailable: 'Optimizador no disponible',
  projected_deficit: 'Déficit térmico no previsto',
  surplus_stored_energy: 'Excedente de energía almacenada',
};

const PLAN_EVENT_LABELS: Record<string, string> = {
  activated: 'Activación',
  preview: 'Vista previa',
  generated: 'Generación',
  invalid: 'Plan no válido',
  replaced: 'Reemplazo',
};

export function planReasonLabel(value: unknown): string {
  const raw = String(value ?? '').trim();
  if (!raw) return 'Sin motivo indicado';
  const key = raw.split(':', 1)[0].toLowerCase();
  return PLAN_REASON_LABELS[key] ?? 'Motivo de planificación';
}

export function planEventLabel(value: unknown): string {
  const raw = String(value ?? '').trim();
  return PLAN_EVENT_LABELS[raw.toLowerCase()] ?? 'Decisión automática';
}

const DEFICIT_REQUIREMENT_LABELS: Record<string, string> = {
  charge: 'Carga solicitada',
  temperature: 'Objetivo térmico',
  temperature_comfort: 'Objetivo térmico',
  energy: 'Energía almacenada',
  minimum_soc: 'Reserva mínima de carga',
  power: 'Límite de potencia',
};

export function requirementLabel(value: unknown): string {
  const raw = String(value ?? '').trim();
  return DEFICIT_REQUIREMENT_LABELS[raw.toLowerCase()] ?? (raw ? 'Objetivo de planificación' : 'Incumplimiento');
}

export function outputDriverLabel(value: unknown): string {
  return String(value ?? '').trim().toLowerCase() === 'gpio' ? 'GPIO' : 'Simulado';
}
