import { describe, expect, it } from 'vitest';

import {
  chargeReasonLabel,
  checkStatusLabel,
  controllerLogLevelLabel,
  forecastNextRunLabel,
  forecastSourceLabel,
  normalizePlanStatus,
  planningActionForCause,
  planningRecoveryActionLabel,
  planningRecoveryCauseLabel,
  planningStepLabel,
  planEventLabel,
  planReasonLabel,
  planStatusLabel,
  requirementLabel,
  relaySessionStatusLabel,
  severityLabel,
} from './presentation';

describe('operator presentation vocabulary', () => {
  it.each([
    ['VALID', 'VALID'],
    ['valid', 'VALID'],
    ['FEASIBLE', 'VALID'],
    ['feasible', 'VALID'],
    ['converging', 'CONVERGING'],
    ['Degraded', 'DEGRADED'],
    ['best_effort', 'DEGRADED'],
    ['INVALID', 'INVALID'],
    ['preview', 'INVALID'],
  ])('normalizes %s as %s', (value, expected) => {
    expect(normalizePlanStatus(value)).toBe(expected);
  });

  it('localizes canonical and legacy plan status codes', () => {
    expect(planStatusLabel('VALID')).toBe('Cumplido');
    expect(planStatusLabel('converging')).toBe('Convergiendo');
    expect(planStatusLabel('deficit')).toBe('Degradado');
    expect(planStatusLabel('invalid')).toBe('No válido');
  });

  it('keeps forecast origin and next action distinct', () => {
    expect(forecastSourceLabel('aemet')).toContain('proveedor real');
    expect(forecastSourceLabel('unsupported')).toBe('Origen no disponible');
    expect(forecastNextRunLabel('retry')).toBe('Próximo reintento');
    expect(forecastNextRunLabel('daily')).toContain('diaria');
  });

  it('localizes event, reason and requirement codes', () => {
    expect(planEventLabel('activated')).toBe('Activación');
    expect(planReasonLabel('missing_required_state')).toContain('telemetría');
    expect(requirementLabel('temperature_comfort')).toBe('Objetivo térmico');
  });

  it('centralizes steps, states, severities and actions with neutral fallbacks', () => {
    expect(planningStepLabel('room_model')).toBe('Modelo energético');
    expect(checkStatusLabel('running')).toBe('en curso');
    expect(relaySessionStatusLabel('failed')).toBe('Recuperación necesaria');
    expect(severityLabel('warn')).toBe('Aviso');
    expect(planningStepLabel('future_step')).toBe('Paso no reconocido');
    expect(checkStatusLabel('future_status')).toBe('Estado no reconocido');
    expect(planningActionForCause('missing_required_state')).toContain('temperatura');
    expect(planningRecoveryCauseLabel('missing_aemet_coverage')).toContain('Cobertura');
    expect(planningRecoveryActionLabel('check_telemetry')).toBe('Comprobar telemetría');
    expect(planningActionForCause('no_plan_available')).toContain('nuevo cálculo');
    expect(planningRecoveryCauseLabel('future_cause')).toBe('Causa no reconocida');
    expect(planningActionForCause('unknown_cause')).toBeNull();
  });

  it('centralizes technical log and charge labels without changing their codes', () => {
    expect(controllerLogLevelLabel('WARNING')).toBe('Aviso');
    expect(controllerLogLevelLabel('future')).toBe('Nivel no reconocido');
    expect(chargeReasonLabel('necessary_for_target')).toContain('consigna');
  });
});
