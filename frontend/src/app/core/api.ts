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
  AddHeaterRequest,
  ChangeDto,
  ConfigDto,
  ForecastHistoryDto,
  HeaterDto,
  PageDto,
  PlanHistoryDto,
  PruneDto,
  SetFieldRequest,
  StatusDto,
  PlanningDto,
  PlanningConstraintRequest, PlanningPreviewDto, AutomaticPlanAuditPage,
  ControllerLogPageDto, ControllerLogLevel,
  TransitionHistoryDto,
  RelayTestStartDto, RelayTestViewDto,
  DatabaseCandidateDto, MigrationDto, OnboardingStatusDto, SecretEditDto,
  SystemConfigurationDto, SystemSection, TopologyDto, ConnectionTestDto,
  WeatherRefreshDto,
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

@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  status(): Observable<StatusDto> {
    return this.http.get<StatusDto>(`${BASE}/status`);
  }

  planning(): Observable<PlanningDto> {
    return this.http.get<PlanningDto>(`${BASE}/planning`);
  }

  planningPreview(constraints: PlanningConstraintRequest[], expectedRevision?: number): Observable<PlanningPreviewDto> {
    return this.http.post<PlanningPreviewDto>(`${BASE}/planning/preview`, { constraints, expected_revision: expectedRevision });
  }
  planningActivate(token: string, constraints: PlanningConstraintRequest[], expectedRevision: number): Observable<PlanningPreviewDto> {
    return this.http.post<PlanningPreviewDto>(`${BASE}/planning/activate`, { token, constraints, expected_revision: expectedRevision });
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

  heater(id: string): Observable<HeaterDto> {
    return this.http.get<HeaterDto>(`${BASE}/config/heaters/${encodeURIComponent(id)}`);
  }

  setField(body: SetFieldRequest): Observable<ChangeDto> {
    return this.http.patch<ChangeDto>(`${BASE}/config`, body);
  }

  setHeaterField(id: string, body: SetFieldRequest): Observable<ChangeDto> {
    return this.http.patch<ChangeDto>(
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
  relayTestLease(id: string, credential: string): Observable<unknown> { return this.http.post(`${BASE}/relay-test/${encodeURIComponent(id)}/lease`, {}, { headers: { 'X-Relay-Test-Credential': credential } }); }
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
