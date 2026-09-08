import { describe, expect, it } from 'vitest';

import {
  forecastNextRunLabel,
  forecastSourceLabel,
  normalizePlanStatus,
  planEventLabel,
  planReasonLabel,
  planStatusLabel,
  requirementLabel,
} from './presentation';

describe('operator presentation vocabulary', () => {
  it.each([
    ['FEASIBLE', 'FEASIBLE'],
    ['feasible', 'FEASIBLE'],
    ['Degraded', 'DEGRADED'],
    ['best_effort', 'DEGRADED'],
    ['INVALID', 'INVALID'],
    ['preview', 'INVALID'],
  ])('normalizes %s as %s', (value, expected) => {
    expect(normalizePlanStatus(value)).toBe(expected);
  });

  it('localizes canonical and legacy plan status codes', () => {
    expect(planStatusLabel('FEASIBLE')).toBe('Cumplido');
    expect(planStatusLabel('deficit')).toBe('Degradado');
    expect(planStatusLabel('invalid')).toBe('No válido');
  });

  it('keeps forecast origin and next action distinct', () => {
    expect(forecastSourceLabel('aemet')).toContain('proveedor real');
    expect(forecastSourceLabel('fallback')).toContain('valor de reserva');
    expect(forecastNextRunLabel('retry')).toBe('Próximo reintento');
    expect(forecastNextRunLabel('daily')).toContain('diaria');
  });

  it('localizes event, reason and requirement codes', () => {
    expect(planEventLabel('activated')).toBe('Activación');
    expect(planReasonLabel('missing_required_state')).toContain('telemetría');
    expect(requirementLabel('temperature_comfort')).toBe('Objetivo térmico');
  });
});
