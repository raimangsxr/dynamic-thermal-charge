import type { Page, Route } from '@playwright/test';

export const FIXTURE_TOKEN = 'fixture-only-token';

const now = '2026-01-16T01:00:00Z';
const horizonEnd = '2026-01-17T01:00:00Z';

export interface FixtureState {
  unauthorizedStatus: boolean;
  activated: boolean;
}

export function statusFixture() {
  return {
    observed_at: now,
    timezone: 'Europe/Madrid',
    controller: {
      liveness: 'live', state_is_current: true, last_seen_at: now, age_seconds: 1,
      started_at: '2026-01-15T22:00:00Z', degraded: false, driver_kind: 'simulated',
      tolerance_seconds: 30, multiple_controllers_suspected: false,
    },
    power: null,
    heaters: [{ id: 'salon', name: 'Salón', enabled: true, power_w: 2800, output_on: false, last_known_output_on: false, changed_at: now }],
    plan: null,
    forecast: { date: '2026-01-16', source: 'aemet', average_temperature_c: 8, minimum_temperature_c: 3, maximum_temperature_c: 13, municipality: 'Fixture' },
    allocations: [],
    telemetry: [{ heater_id: 'salon', state: 'telemetry_stale', missing_fields: ['stored_soc_percent'], indoor_temperature_c: 18, stored_soc_percent: null, indoor_received_at: now, stored_soc_received_at: null, oldest_age_seconds: 0, stored_energy_kwh: null }],
    plan_status: 'INVALID', optimization_quality: null,
    deficits: [{ heater_id: null, requirement: 'safe_planning_input', achievable_value: null, shortfall: null, at: now, reason: 'missing_required_state', target_temperature_c: null, projected_temperature_c: null, shortfall_c: null, stored_energy_kwh: null, stored_soc_percent: null }],
    recovery: { primary: { code: 'missing_required_state', action_code: 'check_telemetry', destination: '/estado#telemetry-title', detail: 'missing_required_state: stored_soc_percent', heater_ids: ['salon'] }, secondary: [], safe_state: 'outputs_off' },
    convergence_by_heater: {}, convergence_at: null, guaranteed_until: null,
    horizon_start: now, horizon_end: horizonEnd, absence_reason: 'invalid_automatic_plan',
    forecast_status: 'success', forecast_last_success_at: now, forecast_last_attempt_at: now,
    forecast_last_error: null, forecast_next_run_at: horizonEnd, forecast_next_run_kind: 'daily', forecast_stale: false,
    forecast_points_received: 2, forecast_coverage_start: now, forecast_coverage_end: '2026-01-16T02:00:00Z', forecast_required_hours: 24, forecast_automatic_eligible: true,
  };
}

function planningForecast() {
  return {
    date: '2026-01-16', source: 'aemet', average_temperature_c: 8, minimum_temperature_c: 3, maximum_temperature_c: 13, municipality: 'Fixture',
    hourly_points: [
      { timestamp: now, temperature_c: 8, interpolated: false },
      { timestamp: '2026-01-16T02:00:00Z', temperature_c: 7.5, interpolated: false },
    ],
    points_received: 2, coverage_start: now, coverage_end: '2026-01-16T02:00:00Z', required_hours: 24, automatic_eligible: true, stale: false,
  };
}

function target() {
  return { id: 1, heater_id: 'salon', target_temperature_c: 21, start_time: '07:00', end_time: '09:00', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true };
}

export function planningFixture(state: FixtureState) {
  const active = state.activated;
  return {
    observed_at: now, timezone: 'Europe/Madrid', max_total_power_w: 5200, max_heating_power_w: 4200, base_load_w: 600,
    plan: active ? { id: 1, source: 'automatic', window_start: now, window_end: horizonEnd, slot_minutes: 30, installation_revision: 1, created_at: now, slots: [] } : null,
    forecast: planningForecast(), allocations: [],
    heaters: [{ id: 'salon', name: 'Salón', power_w: 2800, capacity_kwh: 22.4, priority: 90, enabled: true }],
    horizon_start: now, horizon_end: horizonEnd, timeline: [],
    absence_reason: active ? null : 'invalid_automatic_plan', telemetry: [],
    plan_status: active ? 'VALID' : 'INVALID', deficits: [], recovery: active ? null : statusFixture().recovery,
    convergence_by_heater: {}, convergence_at: null, guaranteed_until: null, preview_token: null,
    temperature_targets_revision: 1, temperature_targets: [target()],
    forecast_status: 'success', forecast_last_attempt_at: now, forecast_last_error: null, forecast_next_run_at: horizonEnd, forecast_next_run_kind: 'daily', forecast_stale: false,
    preview_job: null,
  };
}

function previewResult(targets: Array<Record<string, unknown>>) {
  return {
    token: 'fixture-preview-token', status: 'VALID', optimization_quality: 'OPTIMAL', score: [],
    window_start: now, window_end: horizonEnd, horizon_start: now, horizon_end: horizonEnd, slot_minutes: 30,
    slots: [], deficits: [], violations: [], convergence_by_heater: {}, convergence_at: now, guaranteed_until: horizonEnd,
    explanations: [], demand: [], temperature_targets: targets, operator_summary: {
      forecast: { source: 'aemet', automatic_eligible: true }, recommended_action: 'Vista previa válida y lista para revisar.',
    }, already_active: false,
  };
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

export async function installFixture(page: Page): Promise<FixtureState> {
  const state: FixtureState = { unauthorizedStatus: false, activated: false };
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const protectedRequest = path !== '/api/v1/onboarding/status';
    if (protectedRequest && request.headers().authorization !== `Bearer ${FIXTURE_TOKEN}`) {
      await json(route, { detail: 'Unauthorized' }, 401);
      return;
    }
    if (path.endsWith('/status')) {
      if (state.unauthorizedStatus) {
        state.unauthorizedStatus = false;
        await json(route, { detail: 'Unauthorized' }, 401);
      } else {
        await json(route, statusFixture());
      }
      return;
    }
    if (path.endsWith('/planning') && request.method() === 'GET') {
      await json(route, planningFixture(state));
      return;
    }
    if (path.endsWith('/history/plans')) {
      await json(route, { items: [], limit_applied: 10, has_more: false, next_cursor: null });
      return;
    }
    if (path.endsWith('/system/topology')) {
      await json(route, { mode: 'normal', pending_events: 0, driver: 'simulated', application_database: 'sqlite' });
      return;
    }
    if (path.endsWith('/relay-test')) {
      await json(route, null);
      return;
    }
    if (path.endsWith('/planning/preview/jobs') && request.method() === 'POST') {
      const body = request.postDataJSON() as { temperature_targets?: Array<Record<string, unknown>> };
      const result = previewResult(body.temperature_targets ?? [target()]);
      await json(route, { job_id: 'fixture-job', status: 'completed', cancellation_requested: false, requested_at: now, started_at: now, finished_at: now, checks: [], result, operator_summary: result.operator_summary, error_code: null, error_detail: null, already_active: false });
      return;
    }
    if (path.includes('/planning/preview/jobs/') && request.method() === 'GET') {
      await json(route, { job_id: 'fixture-job', status: 'completed', cancellation_requested: false, requested_at: now, started_at: now, finished_at: now, checks: [], result: previewResult([target()]), operator_summary: {}, error_code: null, error_detail: null, already_active: false });
      return;
    }
    if (path.endsWith('/planning/activate') && request.method() === 'POST') {
      state.activated = true;
      await json(route, previewResult([target()]));
      return;
    }
    await json(route, {});
  });
  return state;
}

export async function signIn(page: Page): Promise<void> {
  await page.goto('/');
  await page.locator('#token').fill(FIXTURE_TOKEN);
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expectUrl(page, /\/estado$/);
}

async function expectUrl(page: Page, url: RegExp): Promise<void> {
  await page.waitForURL(url);
}
