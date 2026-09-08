/**
 * Operator-facing vocabulary shared by the live, planning and history views.
 * API codes remain stable and are intentionally not rendered as primary copy.
 */

export type CanonicalPlanStatus = 'FEASIBLE' | 'DEGRADED' | 'INVALID';

const PLAN_STATUS_ALIASES: Record<string, CanonicalPlanStatus> = {
  feasible: 'FEASIBLE',
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
    case 'FEASIBLE': return 'Cumplido';
    case 'DEGRADED': return 'Degradado';
    case 'INVALID': return 'No válido';
    default: return value ? 'Estado no reconocido' : 'Sin evaluación';
  }
}

export function forecastSourceLabel(value: unknown): string {
  switch (String(value ?? '').trim().toLowerCase()) {
    case 'aemet': return 'proveedor real (AEMET)';
    case 'fallback': return 'valor de reserva (último dato válido)';
    case 'simulated': return 'simulación local';
    default: return 'Origen no disponible';
  }
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
