/**
 * The only module that knows the API's addresses.
 *
 * Everything else asks this. The credential is added by the interceptor, so it
 * appears nowhere here -- which is also why no call can accidentally put it in a
 * query string.
 *
 * There is no method to switch an output, because the API offers none. The panel
 * cannot energise a relay and must not suggest otherwise.
 */

import { HttpClient, type HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type {
  AlertCatalogueDto,
  AddHeaterRequest,
  UpdateHeaterRequest,
  ChangeDto,
  ChangesDto,
  ConfigDto,
  ForecastHistoryDto,
  HeaterDto,
  PageDto,
  PlanHistoryDto,
  PlanExplanationDto,
  PruneDto,
  SetFieldRequest,
  StatusDto,
  PlanningDto,
  PlanningSiteConfigDto,
  TemperatureTargetRequest, PlanningPreviewDto, PlanningPreviewJobDto, AutomaticPlanAuditPage,
  ControllerLogPageDto, ControllerLogLevel,
  TransitionHistoryDto,
  HistorySeriesPageDto, HistorySeriesScope,
  RelayTestStartDto, RelayTestViewDto,
  DatabaseCandidateDto, MigrationDto, OnboardingStatusDto, SecretEditDto,
  SystemConfigurationDto, SystemSection, TopologyDto, ConnectionTestDto,
  WeatherRefreshDto,
  RoomDto, RoomPatchRequest, RoomEstimateRequest, CalibrationActionDto,
  OperatorNotificationPageDto, PushRegistrationRequest, PushRegistrationDto,
  AlertPageDto,
} from './api.types';

const BASE = '/api/v1';

export interface HistoryQuery {
  from?: string;
  to?: string;
  limit?: number;
  /** Opaque: passed back exactly as the API gave it. */
  cursor?: string;
  heaterId?: string;
}

export interface HistorySeriesQuery {
  from: string;
  to: string;
  scope: HistorySeriesScope;
  heaterId?: string;
  limit?: number;
  cursor?: string;
}

@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  status(): Observable<StatusDto> {
    return this.http.get<StatusDto>(`${BASE}/status`);
  }

  planning(): Observable<PlanningDto> {
    return this.http.get<PlanningDto>(`${BASE}/planning`);
  }

  planningConfig(): Observable<PlanningSiteConfigDto> {
    return this.http.get<PlanningSiteConfigDto>(`${BASE}/planning/config`);
  }

  patchPlanningConfig(expectedRevision: number, values: Omit<PlanningSiteConfigDto, 'revision'>): Observable<PlanningSiteConfigDto> {
    return this.http.patch<PlanningSiteConfigDto>(`${BASE}/planning/config`, {
      expected_revision: expectedRevision,
      ...values,
    });
  }

  alertCatalogue(): Observable<AlertCatalogueDto> {
    return this.http.get<AlertCatalogueDto>(`${BASE}/system/alerts`);
  }
  setAlertEnabled(name: string, enabled: boolean): Observable<AlertCatalogueDto> {
    return this.http.patch<AlertCatalogueDto>(`${BASE}/system/alerts/${encodeURIComponent(name)}`, { enabled });
  }
  testEmail(): Observable<{ ok: boolean; host: string | null; port: number }> {
    return this.http.post<{ ok: boolean; host: string | null; port: number }>(`${BASE}/system/tests/email`, {});
  }
  planningPreview(temperatureTargets: TemperatureTargetRequest[], expectedRevision?: number): Observable<PlanningPreviewDto> {
    return this.http.post<PlanningPreviewDto>(`${BASE}/planning/preview`, { temperature_targets: temperatureTargets, expected_revision: expectedRevision });
  }
  planningPreviewJobStart(temperatureTargets: TemperatureTargetRequest[], expectedRevision?: number): Observable<PlanningPreviewJobDto> {
    return this.http.post<PlanningPreviewJobDto>(`${BASE}/planning/preview/jobs`, { temperature_targets: temperatureTargets, expected_revision: expectedRevision });
  }
  planningPreviewJob(jobId: string): Observable<PlanningPreviewJobDto> {
    return this.http.get<PlanningPreviewJobDto>(`${BASE}/planning/preview/jobs/${encodeURIComponent(jobId)}`);
  }
  planningPreviewJobCancel(jobId: string): Observable<PlanningPreviewJobDto> {
    return this.http.post<PlanningPreviewJobDto>(`${BASE}/planning/preview/jobs/${encodeURIComponent(jobId)}/cancel`, {});
  }
  planningActivate(token: string, temperatureTargets: TemperatureTargetRequest[], expectedRevision: number, bestEffort = false): Observable<PlanningPreviewDto> {
    const body: Record<string, unknown> = { token, temperature_targets: temperatureTargets, expected_revision: expectedRevision };
    if (bestEffort) body['best_effort'] = true;
    return this.http.post<PlanningPreviewDto>(`${BASE}/planning/activate`, body);
  }

  controllerLog(query: { limit?: number; beforeId?: number; afterId?: number; level?: ControllerLogLevel; q?: string } = {}): Observable<ControllerLogPageDto> {
    const params: Record<string, string | number> = {};
    if (query.limit !== undefined) params['limit'] = query.limit;
    if (query.beforeId !== undefined) params['before_id'] = query.beforeId;
    if (query.afterId !== undefined) params['after_id'] = query.afterId;
    if (query.level) params['level'] = query.level;
    if (query.q) params['q'] = query.q;
    return this.http.get<ControllerLogPageDto>(`${BASE}/controller-log`, { params });
  }

  config(): Observable<ConfigDto> {
    return this.http.get<ConfigDto>(`${BASE}/config`);
  }

  room(id: string): Observable<RoomDto> {
    return this.http.get<RoomDto>(`${BASE}/rooms/${encodeURIComponent(id)}`);
  }

  patchRoom(id: string, body: RoomPatchRequest): Observable<RoomDto> {
    return this.http.patch<RoomDto>(`${BASE}/rooms/${encodeURIComponent(id)}`, body);
  }

  startCalibration(id: string): Observable<CalibrationActionDto> {
    return this.http.post<CalibrationActionDto>(`${BASE}/rooms/${encodeURIComponent(id)}/calibration`, {});
  }

  cancelCalibration(id: string): Observable<CalibrationActionDto> {
    return this.http.delete<CalibrationActionDto>(`${BASE}/rooms/${encodeURIComponent(id)}/calibration`);
  }

  estimateRoom(id: string, body: RoomEstimateRequest): Observable<{ room: RoomDto; revision: number }> {
    return this.http.post<{ room: RoomDto; revision: number }>(`${BASE}/rooms/${encodeURIComponent(id)}/estimate`, body);
  }

  notifications(): Observable<OperatorNotificationPageDto> {
    return this.http.get<OperatorNotificationPageDto>(`${BASE}/notifications`);
  }

  acknowledgeNotification(id: number): Observable<OperatorNotificationPageDto> {
    return this.http.post<OperatorNotificationPageDto>(`${BASE}/notifications/${id}/ack`, {});
  }

  alerts(view: 'active' | 'history' | 'all' = 'active', limit = 50, cursor?: string): Observable<AlertPageDto> {
    const params: Record<string, string | number> = { view, limit };
    if (cursor) params['cursor'] = cursor;
    return this.http.get<AlertPageDto>(`${BASE}/alerts`, { params });
  }

  acknowledgeAlert(id: number, view: 'active' | 'history' | 'all' = 'active', limit = 50): Observable<AlertPageDto> {
    return this.http.post<AlertPageDto>(`${BASE}/alerts/${id}/ack`, {}, { params: { view, limit } });
  }

  pushPublicKey(): Observable<{ public_key: string | null }> {
    return this.http.get<{ public_key: string | null }>(`${BASE}/push/public-key`);
  }

  registerPush(body: PushRegistrationRequest): Observable<PushRegistrationDto> {
    return this.http.post<PushRegistrationDto>(`${BASE}/push/subscriptions`, body);
  }

  revokePush(browserId: string): Observable<PushRegistrationDto> {
    return this.http.delete<PushRegistrationDto>(`${BASE}/push/subscriptions`, { body: { browser_id: browserId } });
  }

  heater(id: string): Observable<HeaterDto> {
    return this.http.get<HeaterDto>(`${BASE}/config/heaters/${encodeURIComponent(id)}`);
  }

  setField(body: SetFieldRequest): Observable<ChangeDto> {
    return this.http.patch<ChangeDto>(`${BASE}/config`, body);
  }

  patchInstallation(revision: number, values: Record<string, string>): Observable<ChangesDto> {
    return this.http.patch<ChangesDto>(`${BASE}/config/batch`, { revision, values });
  }

  setHeaterField(id: string, body: SetFieldRequest): Observable<ChangeDto> {
    return this.http.patch<ChangeDto>(
      `${BASE}/config/heaters/${encodeURIComponent(id)}`,
      body,
    );
  }

  updateHeater(id: string, body: UpdateHeaterRequest): Observable<ChangeDto> {
    return this.http.put<ChangeDto>(
      `${BASE}/config/heaters/${encodeURIComponent(id)}`,
      body,
    );
  }

  addHeater(body: AddHeaterRequest): Observable<ChangeDto> {
    return this.http.post<ChangeDto>(`${BASE}/config/heaters`, body);
  }

  removeHeater(id: string, revision: number): Observable<ChangeDto> {
    return this.http.delete<ChangeDto>(
      `${BASE}/config/heaters/${encodeURIComponent(id)}`,
      { params: { revision } },
    );
  }

  plans(query: HistoryQuery = {}): Observable<PageDto<PlanHistoryDto>> {
    return this.http.get<PageDto<PlanHistoryDto>>(`${BASE}/history/plans`, {
      params: this.historyParams(query),
    });
  }

  planExplanation(source: string, planId: number): Observable<PlanExplanationDto> {
    return this.http.get<PlanExplanationDto>(`${BASE}/history/plans/${encodeURIComponent(source)}/${planId}/explanation`);
  }

  planDiagnostic(source: string, planId: number): Observable<Blob> {
    return this.http.get(`${BASE}/history/plans/${encodeURIComponent(source)}/${planId}/diagnostic`, { responseType: 'blob' });
  }

  forecasts(query: HistoryQuery = {}): Observable<PageDto<ForecastHistoryDto>> {
    return this.http.get<PageDto<ForecastHistoryDto>>(`${BASE}/history/forecasts`, {
      params: this.historyParams(query),
    });
  }

  transitions(query: HistoryQuery = {}): Observable<PageDto<TransitionHistoryDto>> {
    return this.http.get<PageDto<TransitionHistoryDto>>(`${BASE}/history/transitions`, {
      params: this.historyParams(query),
    });
  }
  historySeries(query: HistorySeriesQuery): Observable<HistorySeriesPageDto> {
    const params: Record<string, string | number> = {
      from: query.from,
      to: query.to,
      scope: query.scope,
    };
    if (query.heaterId) params['heater_id'] = query.heaterId;
    if (query.limit !== undefined) params['limit'] = query.limit;
    if (query.cursor) params['cursor'] = query.cursor;
    return this.http.get<HistorySeriesPageDto>(`${BASE}/history/series`, { params });
  }
  planningAudit(query: Pick<HistoryQuery, 'from' | 'to' | 'limit'> = {}): Observable<AutomaticPlanAuditPage> {
    return this.http.get<AutomaticPlanAuditPage>(`${BASE}/history/planning-audit`, { params: this.historyParams(query) });
  }

  prune(): Observable<PruneDto> {
    return this.http.post<PruneDto>(`${BASE}/history/prune`, {});
  }
  onboardingStatus(): Observable<OnboardingStatusDto> { return this.http.get<OnboardingStatusDto>(`${BASE}/onboarding/status`); }
  completeOnboarding(onboardingCredential: string, administratorToken: string): Observable<void> {
    return this.http.post<void>(`${BASE}/onboarding/complete`, {
      onboarding_credential: onboardingCredential, administrator_token: administratorToken,
    });
  }
  systemConfiguration(): Observable<SystemConfigurationDto> { return this.http.get<SystemConfigurationDto>(`${BASE}/system/configuration`); }
  topology(): Observable<TopologyDto> { return this.http.get<TopologyDto>(`${BASE}/system/topology`); }
  patchSystem(section: SystemSection, expectedRevision: number, values: Record<string, unknown>, secrets: Record<string, SecretEditDto>): Observable<SystemConfigurationDto> {
    return this.http.patch<SystemConfigurationDto>(`${BASE}/system/configuration/${section}`, {
      expected_revision: expectedRevision, values, secrets,
    });
  }
  testDatabase(candidate: DatabaseCandidateDto): Observable<{ ok: boolean; driver: string; tls: boolean | null }> {
    return this.http.post<{ ok: boolean; driver: string; tls: boolean | null }>(`${BASE}/system/tests/database`, candidate);
  }
  testMqtt(): Observable<ConnectionTestDto> { return this.http.post<ConnectionTestDto>(`${BASE}/system/tests/mqtt`, {}); }
  testWeather(): Observable<ConnectionTestDto> { return this.http.post<ConnectionTestDto>(`${BASE}/system/tests/weather`, {}); }
  refreshWeather(): Observable<WeatherRefreshDto> { return this.http.post<WeatherRefreshDto>(`${BASE}/system/weather/refresh`, {}); }
  migrateDatabase(expectedLocatorRevision: number, candidate: DatabaseCandidateDto): Observable<MigrationDto> {
    return this.http.post<MigrationDto>(`${BASE}/system/migrations`, {
      expected_locator_revision: expectedLocatorRevision, confirmed: true, destination: candidate,
    });
  }
  relayTestStart(): Observable<RelayTestStartDto> { return this.http.post<RelayTestStartDto>(`${BASE}/relay-test`, {}); }
  relayTest(credential?: string | null): Observable<RelayTestViewDto | null> { return this.http.get<RelayTestViewDto | null>(`${BASE}/relay-test`, credential ? { headers: { 'X-Relay-Test-Credential': credential } } : {}); }
  relayTestById(id: string, credential?: string | null): Observable<RelayTestViewDto> { return this.http.get<RelayTestViewDto>(`${BASE}/relay-test/${encodeURIComponent(id)}`, credential ? { headers: { 'X-Relay-Test-Credential': credential } } : {}); }
  relayTestSet(id: string, heaterId: string, state: boolean, credential: string): Observable<unknown> { return this.http.put(`${BASE}/relay-test/${encodeURIComponent(id)}/heaters/${encodeURIComponent(heaterId)}`, { state }, { headers: { 'X-Relay-Test-Credential': credential } }); }
  relayTestLease(id: string, credential: string): Observable<RelayTestViewDto> { return this.http.post<RelayTestViewDto>(`${BASE}/relay-test/${encodeURIComponent(id)}/lease`, {}, { headers: { 'X-Relay-Test-Credential': credential } }); }
  relayTestEnd(id: string, credential: string): Observable<unknown> { return this.http.delete(`${BASE}/relay-test/${encodeURIComponent(id)}`, { headers: { 'X-Relay-Test-Credential': credential } }); }

  private historyParams(query: HistoryQuery): Record<string, string | number> {
    const params: Record<string, string | number> = {};
    if (query.from) params['from'] = query.from;
    if (query.to) params['to'] = query.to;
    if (query.limit !== undefined) params['limit'] = query.limit;
    if (query.cursor) params['cursor'] = query.cursor;
    if (query.heaterId) params['heater_id'] = query.heaterId;
    return params;
  }
}
