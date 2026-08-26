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
  TransitionHistoryDto,
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
