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
  ControllerLogPageDto, ControllerLogLevel,
  TransitionHistoryDto,
  RelayTestStartDto, RelayTestViewDto,
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

  prune(): Observable<PruneDto> {
    return this.http.post<PruneDto>(`${BASE}/history/prune`, {});
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
