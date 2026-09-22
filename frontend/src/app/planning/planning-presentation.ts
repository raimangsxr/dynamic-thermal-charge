import type { PlanningDeficitDto, PlanningPreviewDto } from '../core/api.types';

export function previewProblems(preview: PlanningPreviewDto): PlanningDeficitDto[] {
  return preview.deficits.length ? preview.deficits : preview.violations;
}

export function explainPlanningDeficit(item: PlanningDeficitDto): string {
  const detail = item.reason.includes(':') ? item.reason.split(':', 2)[1].trim() : item.reason;
  if (item.reason.startsWith('forecast_not_eligible')) return 'La previsión activa no es de AEMET. La planificación automática solo usa forecast horario AEMET.';
  if (item.reason.startsWith('missing_aemet_coverage')) return 'No hay cobertura horaria AEMET continua desde el inicio del horizonte planificado.';
  if (item.reason.startsWith('missing_required_state')) return `Falta telemetría MQTT completa y reciente: ${detail}.`;
  if (item.reason.startsWith('invalid_configuration')) return `Configuración o consigna térmica inválida: ${detail}.`;
  if (item.reason.startsWith('insufficient_capacity_or_power')) return 'No hay suficiente potencia o capacidad disponible para cumplir el objetivo térmico.';
  if (item.reason.startsWith('insufficient_stored_energy_or_power')) return 'La energía almacenada o la potencia disponible no cubren la demanda térmica prevista.';
  if (item.reason.startsWith('heater_power_exceeds_global_limit')) return 'La potencia nominal del acumulador supera el límite disponible de calefacción.';
  if (item.reason.startsWith('solver_time_limit')) return 'El optimizador alcanzó su límite de tiempo y entregó una solución degradada.';
  if (item.reason.startsWith('solver_failure') || item.reason.startsWith('solver_unavailable')) return 'El optimizador no pudo resolver el plan; revisa la instalación o contacta soporte.';
  if (item.reason.startsWith('projected_deficit')) return 'La proyección actual muestra un déficit térmico que el plan anterior no contemplaba.';
  if (item.reason.startsWith('surplus_stored_energy')) return 'La proyección actual conserva más energía almacenada de la prevista y el plan puede adaptarse.';
  return detail || item.reason;
}

export function recommendedPlanningAction(cause: string): string | null {
  if (cause === 'missing_aemet_coverage') return 'Espera una previsión AEMET horaria completa de 24 horas o revisa la conexión meteorológica.';
  if (cause === 'missing_required_state') return 'Comprueba que cada acumulador publica temperatura interior y SOC reciente.';
  if (cause === 'insufficient_capacity_or_power' || cause === 'insufficient_stored_energy_or_power') return 'Revisa potencia disponible, capacidad térmica y la consigna programada.';
  if (cause.startsWith('solver')) return 'Revisa la configuración del optimizador o contacta con soporte.';
  return null;
}
