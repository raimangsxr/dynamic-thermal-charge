/** Every API error becomes something actionable: FR-031, FR-032. */

import { describe, expect, it } from 'vitest';

import type { ApiErrorCode, ApiErrorDto } from './api.types';
import { UNREACHABLE, allCodes, explain, messageFor } from './errors';

/** The codes the phase-2 contract declares. Kept literal on purpose: if the API
 *  gains one, this list is where somebody has to notice. */
const CONTRACT_CODES: ApiErrorCode[] = [
  'unauthorized',
  'not_found',
  'already_exists',
  'config_conflict',
  'validation_failed',
  'secret_rejected',
  'bad_request',
  'no_configuration',
  'schema_unusable',
  'store_unavailable',
  'relay_test_active',
  'relay_test_fault_latched',
  'degraded_mode',
  'operation_in_progress',
  'connection_test_failed',
  'internal_error',
];

function error(code: ApiErrorCode, message = 'algo'): ApiErrorDto {
  return { code, message, field: null, heater_id: null };
}

describe('the translation table', () => {
  it('covers every code in the phase-2 contract', () => {
    expect(new Set(allCodes())).toEqual(new Set(CONTRACT_CODES));
  });

  it('gives every code a title', () => {
    for (const code of CONTRACT_CODES) {
      expect(explain(error(code)).title.length).toBeGreaterThan(0);
    }
  });

  it('uses no technical jargon and no stack traces', () => {
    const forbidden = [
      'traceback',
      'exception',
      'null pointer',
      'stack',
      '500',
      'http',
      'sqlalchemy',
      'sqlite',
    ];
    for (const code of CONTRACT_CODES) {
      const explained = explain(error(code));
      const text = `${explained.title} ${explained.action}`.toLowerCase();
      for (const word of forbidden) {
        expect(text).not.toContain(word);
      }
    }
  });
});

describe('the schema and configuration cases (FR-032)', () => {
  it.each(['schema_unusable', 'no_configuration'] as ApiErrorCode[])(
    '%s says to act on the device and that the panel cannot',
    (code) => {
      const explained = explain(error(code));
      expect(explained.onDevice).toBe(true);
      expect(explained.action).toContain('dispositivo');
      expect(explained.action.toLowerCase()).toContain('no puede');
    },
  );

  it('names the exact command for a pending migration', () => {
    expect(explain(error('schema_unusable')).action).toContain('dtc db upgrade');
  });

  it('names the exact command for a missing installation', () => {
    expect(explain(error('no_configuration')).action).toContain('dtc db init');
  });
});

describe('field-scoped errors', () => {
  it.each([
    'validation_failed',
    'secret_rejected',
    'not_found',
    'already_exists',
    'bad_request',
  ] as ApiErrorCode[])('%s belongs next to a field', (code) => {
    expect(explain(error(code)).fieldScoped).toBe(true);
  });

  it("prefers the API's own words for a field-scoped error", () => {
    const message = messageFor(
      error('validation_failed', 'slot_minutes must be a divisor of 60'),
    );
    expect(message).toBe('slot_minutes must be a divisor of 60');
  });

  it('falls back to its own title when the API said nothing useful', () => {
    const message = messageFor({
      code: 'config_conflict',
      message: '',
      field: null,
      heater_id: null,
    });
    expect(message).toContain('cambió');
  });
});

describe('a conflict is presented as protection, not as a failure', () => {
  it('says nothing was overwritten and offers to re-read', () => {
    const explained = explain(error('config_conflict'));
    expect(explained.action).toContain('leerla');
    expect(explained.action).toContain('No se ha sobrescrito');
  });
});

describe('an unreachable API', () => {
  it('is explained without a code', () => {
    expect(explain(null)).toBe(UNREACHABLE);
  });

  it('says the shown information is no longer current', () => {
    expect(UNREACHABLE.action).toContain('no es actual');
  });
});

describe('an unknown code', () => {
  it('is admitted rather than dressed up', () => {
    const explained = explain({
      code: 'brand_new_code' as ApiErrorCode,
      message: 'x',
      field: null,
      heater_id: null,
    });
    expect(explained.title).toContain('no reconoce');
  });
});
