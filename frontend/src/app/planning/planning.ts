import { HttpErrorResponse } from '@angular/common/http';
import { AfterViewInit, Component, ElementRef, Injector, OnDestroy, ViewChild, afterNextRender, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { FormsModule } from '@angular/forms';
import { Chart } from 'chart.js/auto';
import type { ChartOptions, TooltipItem } from 'chart.js';

import { Api } from '../core/api';
import { Poller } from '../core/poll';
import type { ApiErrorDto, HourlyForecastPointDto, PlanningCheckDto, TemperatureTargetRequest, PlanningDto, PlanningDeficitDto, PlanningPreviewDto, PlanningPreviewJobDto, PlanningSlotDto, PlanningTimelineSlotDto } from '../core/api.types';
import { type Explained, UNREACHABLE, explain, messageFor } from '../core/errors';
import { formatDateOnly, formatInstant } from '../shared/age/age';
import { formatTemperature, truncateTemperature } from '../shared/temperature/temperature';
import {
  forecastNextRunLabel,
  forecastSourceLabel,
  forecastStatusLabel,
  planReasonLabel,
  planStatusLabel,
  requirementLabel,
} from '../shared/presentation/presentation';

interface PlanningDetailDialogData {
  kind: 'forecast' | 'planning' | 'failure' | 'problems' | 'preview' | 'planning-table' | 'chart';
  planning?: PlanningDto;
  check?: PlanningCheckDto;
  job?: PlanningPreviewJobDto;
  preview?: PlanningPreviewDto;
  table?: PlanningTableDetail;
  chart?: ChartDetail;
}

interface PlanningTableDetail {
  title: string;
  ariaLabel: string;
  headers: string[];
  rows: string[][];
}

interface ChartDetailDataset {
  label: string;
  data: unknown[];
  borderColor?: string;
  backgroundColor?: string;
  borderDash?: number[];
  pointRadius?: number;
  tension?: number;
  stepped?: boolean;
}

interface ChartDetail {
  title: string;
  ariaLabel: string;
  type: 'line' | 'bar';
  labels: string[];
  datasets: ChartDetailDataset[];
  yAxisTitle?: string;
}

type TemperatureTargetDraft = TemperatureTargetRequest;

const WEEKDAY_NAMES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'] as const;
const WEEKDAY_SHORT_NAMES = ['L', 'M', 'X', 'J', 'V', 'S', 'D'] as const;

interface PlanningRefreshOptions {
  restorePreview?: boolean;
}

interface PreviewChartPoint {
  x: number;
  y: number;
  power_w: number;
  stored_energy_kwh: number;
  stored_energy_next_kwh: number;
  indoor_temperature_c: number;
  indoor_temperature_next_c: number;
  target_temperature_c: number | null;
  heat_delivered_kwh: number;
  thermal_loss_kwh: number;
  temperature_shortfall_start_c: number;
  temperature_shortfall_c: number;
  charge_energy_kwh: number;
}

function previewProblems(preview: PlanningPreviewDto): PlanningDeficitDto[] {
  return preview.deficits.length ? preview.deficits : preview.violations;
}

function explainPlanningDeficit(item: PlanningDeficitDto): string {
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
  return detail || item.reason;
}

function recommendedPlanningAction(cause: string): string | null {
  if (cause === 'missing_aemet_coverage') return 'Espera una previsión AEMET horaria completa de 24 horas o revisa la conexión meteorológica.';
  if (cause === 'missing_required_state') return 'Comprueba que cada acumulador publica temperatura interior y SOC reciente.';
  if (cause === 'insufficient_capacity_or_power' || cause === 'insufficient_stored_energy_or_power') return 'Revisa potencia disponible, capacidad térmica y la consigna programada.';
  if (cause.startsWith('solver')) return 'Revisa la configuración del optimizador o contacta con soporte.';
  return null;
}

@Component({
  selector: 'dtc-planning-detail-dialog',
  imports: [MatButtonModule, MatDialogModule, MatTabsModule],
  template: `
    <h2 mat-dialog-title>{{ data.kind === 'forecast' ? 'Detalle de la previsión' : data.kind === 'failure' ? 'Detalle del fallo de la vista previa' : data.kind === 'problems' ? 'Problemas de la vista previa' : data.kind === 'preview' ? 'Detalle de la vista previa' : data.kind === 'planning-table' ? data.table?.title : data.kind === 'chart' ? data.chart?.title : 'Detalle de la planificación' }}</h2>
    <mat-dialog-content>
      @if (data.kind === 'failure') {
        <dl class="detail-list">
          <div><dt>Paso</dt><dd>{{ data.check ? checkText(data.check.name) : 'Trabajo de vista previa' }}</dd></div>
          <div><dt>Estado</dt><dd>{{ data.check ? checkStatusText(data.check.status) : 'error' }}</dd></div>
          <div><dt>Detalle</dt><dd>{{ data.check?.detail || 'No hay detalle adicional.' }}</dd></div>
          @if (data.job?.error_detail) { <div><dt>Error general</dt><dd>{{ data.job?.error_detail }}</dd></div> }
        </dl>
      } @else if (data.kind === 'problems' && data.preview; as preview) {
        <p data-testid="preview-problems-dialog-intro">Se encontraron {{ previewProblems(preview).length }} problemas en la ventana planificada.</p>
        <div class="problem-list" data-testid="preview-problems-dialog">
          @for (item of previewProblems(preview); track $index) {
            <article class="problem" data-testid="preview-problem">
              <h3>{{ requirementText(item.requirement) }} @if (item.requirement) { <small class="technical-id">{{ item.requirement }}</small> }</h3>
              <dl class="detail-list">
                <div><dt>Acumulador</dt><dd>{{ heaterText(item.heater_id, data.planning) }}</dd></div>
                <div><dt>Momento</dt><dd>{{ dateTime(item.at) }}</dd></div>
                <div><dt>Objetivo térmico</dt><dd>{{ temperature(item.target_temperature_c) }}</dd></div>
                <div><dt>Temperatura proyectada</dt><dd>{{ temperature(item.projected_temperature_c) }}</dd></div>
                <div><dt>Déficit térmico</dt><dd>{{ temperature(item.shortfall_c) }}</dd></div>
                <div><dt>Energía almacenada</dt><dd>{{ energy(item.stored_energy_kwh) }}</dd></div>
                <div><dt>Causa</dt><dd>{{ problemExplanation(item) }}</dd></div>
                @if (problemAction(item, preview); as action) { <div><dt>Acción recomendada</dt><dd>{{ action }}</dd></div> }
              </dl>
            </article>
          }
        </div>
      } @else if (data.kind === 'preview' && data.preview; as preview) {
        <p class="hint">Detalle por intervalo y acumulador de la ventana planificada.</p>
        <div class="table-scroll preview-slot-summary" data-testid="preview-slots-detail-table">
          <table aria-label="Intervalos con carga de la vista previa"><caption>Intervalos con carga</caption><thead><tr><th scope="col">Intervalo</th><th scope="col">Acumuladores</th><th scope="col">Potencia (W)</th></tr></thead><tbody>
            @for (slot of previewChargingSlots(preview); track $index) {
              <tr><th scope="row">{{ previewSlotRangeLabel(slot) }}</th><td>{{ previewSlotHeaters(slot) }}</td><td>{{ previewSlotPower(slot) }}</td></tr>
            }
          </tbody></table>
        </div>
        <p class="hint preview-detail-tabs-hint">Selecciona una pestaña para consultar potencia, energía almacenada, temperatura, pérdidas y déficit por acumulador.</p>
        @if (data.planning; as planning) {
          @if (planning.heaters.length) {
            <mat-tab-group class="preview-detail-tabs" data-testid="preview-detail-tabs" animationDuration="0ms">
              @for (heater of planning.heaters; track heater.id) {
              <mat-tab [label]="heater.name">
                <section class="preview-detail-table" data-testid="preview-detail-heater-table" [attr.aria-labelledby]="'preview-detail-heater-title-' + heater.id">
                  <h3 [id]="'preview-detail-heater-title-' + heater.id">{{ heater.name }}</h3>
                  <div class="table-scroll"><table [attr.aria-label]="'Detalle de planificación de ' + heater.name"><thead><tr><th scope="col">Intervalo</th><th scope="col">Potencia (W)</th><th scope="col">Energía inicio</th><th scope="col">Energía fin</th><th scope="col">Interior inicio</th><th scope="col">Interior fin</th><th scope="col">Objetivo</th><th scope="col">Déficit inicio</th><th scope="col">Déficit fin</th><th scope="col">Calor entregado</th><th scope="col">Intercambio térmico</th></tr></thead><tbody>
                    @for (slot of previewWindowSlots(preview); track $index) { <tr><th scope="row">{{ previewSlotRangeLabel(slot) }}</th><td>{{ previewPower(slot, heater.id, heater.power_w) }}</td><td>{{ previewStoredEnergy(slot, heater.id).toFixed(2) }} kWh</td><td>{{ previewStoredEnergyNext(slot, heater.id).toFixed(2) }} kWh</td><td>{{ temperature(previewIndoorTemperature(slot, heater.id)) }}</td><td>{{ temperature(previewIndoorTemperatureNext(slot, heater.id)) }}</td><td>{{ temperature(previewTargetTemperature(slot, heater.id)) }}</td><td>{{ temperature(previewShortfallStart(slot, heater.id)) }}</td><td>{{ temperature(previewShortfall(slot, heater.id)) }}</td><td>{{ previewHeatDelivered(slot, heater.id).toFixed(2) }} kWh</td><td>{{ previewThermalLoss(slot, heater.id).toFixed(2) }} kWh</td></tr> }
                  </tbody></table></div>
                </section>
              </mat-tab>
              }
            </mat-tab-group>
          } @else {
            <p>No hay acumuladores configurados.</p>
          }
        }
      } @else if (data.kind === 'planning-table' && data.table; as table) {
        <div class="table-scroll planning-detail-table-scroll" data-testid="planning-detail-table-scroll">
          <table class="planning-detail-table" [attr.aria-label]="table.ariaLabel" data-testid="planning-detail-table">
            <caption>{{ table.title }}</caption>
            <thead><tr>@for (header of table.headers; track $index) { <th scope="col">{{ header }}</th> }</tr></thead>
            <tbody>@for (row of table.rows; track $index) { <tr>@for (cell of row; track $index) { @if ($index === 0) { <th scope="row">{{ cell }}</th> } @else { <td>{{ cell }}</td> } }</tr> }</tbody>
          </table>
        </div>
      } @else if (data.kind === 'chart' && data.chart; as chart) {
        <div class="detail-chart-wrap"><canvas #detailChart [attr.aria-label]="chart.ariaLabel"></canvas></div>
      } @else if (data.kind === 'forecast' && data.planning?.forecast; as forecast) {
        <dl class="detail-list">
          <div><dt>Origen</dt><dd>{{ sourceText(forecast.source) }}</dd></div>
          <div><dt>Fecha</dt><dd>{{ dateText(forecast.date) }}</dd></div>
          <div><dt>Municipio</dt><dd>{{ forecast.municipality || 'no disponible' }}</dd></div>
          <div><dt>Rango horario</dt><dd>{{ forecastRange(forecast.hourly_points) }}</dd></div>
          <div><dt>Registros horarios</dt><dd>{{ forecast.hourly_points.length }}</dd></div>
          <div><dt>Temperaturas</dt><dd>{{ temperatures(forecast) }}</dd></div>
          <div><dt>Estado de consulta</dt><dd>{{ forecastStatusText(data.planning?.forecast_status) }}</dd></div>
          <div><dt>Última consulta</dt><dd>{{ dateTime(data.planning?.forecast_last_attempt_at) }}</dd></div>
          <div><dt>{{ forecastNextText(data.planning?.forecast_next_run_kind) }}</dt><dd>{{ dateTime(data.planning?.forecast_next_run_at) }}</dd></div>
        </dl>
        @if (forecast.hourly_points.length) {
          <div class="table-scroll">
            <table><caption>Registros horarios recibidos</caption><thead><tr><th>Hora</th><th>Temperatura</th></tr></thead><tbody>
              @for (point of forecast.hourly_points; track point.timestamp) {
                <tr><th scope="row">{{ dateTime(point.timestamp) }}</th><td>{{ formatTemperature(point.temperature_c) }} °C</td></tr>
              }
            </tbody></table>
          </div>
        }
      } @else if (data.kind === 'forecast') {
        <p>No hay datos de previsión horaria disponibles.</p>
        <p>Estado: {{ forecastStatusText(data.planning?.forecast_status) }} · Última consulta: {{ dateTime(data.planning?.forecast_last_attempt_at) }} · {{ forecastNextText(data.planning?.forecast_next_run_kind) }}: {{ dateTime(data.planning?.forecast_next_run_at) }}</p>
      } @else if (data.planning?.plan; as plan) {
        <dl class="detail-list">
          <div><dt>Ventana</dt><dd>{{ dateTime(plan.window_start) }}–{{ dateTime(plan.window_end) }}</dd></div>
          <div><dt>Horizonte</dt><dd>{{ dateTime(data.planning?.horizon_start) }}–{{ dateTime(data.planning?.horizon_end) }}</dd></div>
          <div><dt>Intervalo</dt><dd>intervalos de {{ plan.slot_minutes }} minutos</dd></div>
          <div><dt>Registros de planificación</dt><dd>{{ plan.slots.length }}</dd></div>
          <div><dt>Creado</dt><dd>{{ dateTime(plan.created_at) }}</dd></div>
          <div><dt>Revisión de configuración</dt><dd>{{ plan.installation_revision }}</dd></div>
        </dl>
        <div class="table-scroll">
          <table><caption>Intervalos planificados</caption><thead><tr><th>Intervalo</th><th>Acumuladores</th><th>Potencia</th></tr></thead><tbody>
            @for (slot of plan.slots; track slot.start) {
              <tr><th scope="row">{{ dateTime(slot.start) }}–{{ dateTime(slot.end) }}</th><td>{{ heaterTexts(slot.heater_ids, data.planning) }}</td><td>{{ slot.total_power_w }} W</td></tr>
            }
          </tbody></table>
        </div>
      } @else {
        <p>No hay un plan actual ni próximo.</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close type="button" data-testid="detail-dialog-close">Cerrar</button>
    </mat-dialog-actions>
  `,
  styles: `
    .detail-list { display: grid; gap: .6rem; margin: 0; }
    .detail-list div { display: grid; grid-template-columns: minmax(9rem, .7fr) 1fr; gap: 1rem; }
    dt { color: var(--muted); font-weight: 600; } dd { margin: 0; }
    .problem-list { display: grid; gap: 1rem; }
    .problem { padding: .75rem; border: 1px solid var(--border); border-radius: .45rem; }
    .problem h3 { margin: 0 0 .75rem; font-size: 1rem; }
    .detail-chart-wrap { height: min(62vh, 34rem); min-height: 20rem; }
    .preview-detail-tabs { margin-top: .75rem; }
    .preview-detail-tabs-hint { margin-top: 1.25rem; }
    .preview-detail-table { padding-top: .75rem; }
    .preview-detail-table h3 { margin: 0; font-size: 1rem; }
    .preview-detail-table table { min-width: 42rem; }
    .preview-slot-summary table { min-width: 36rem; }
    .table-scroll { overflow-x: auto; margin-top: 1.25rem; }
    .planning-detail-table-scroll { max-height: min(70vh, 52rem); overflow: auto; margin-top: 0; }
    .planning-detail-table { width: max-content; min-width: 100%; }
    .planning-detail-table th, .planning-detail-table td { padding: .4rem .55rem; white-space: nowrap; }
    .planning-detail-table thead th { position: sticky; top: 0; z-index: 2; background: var(--surface); }
    .planning-detail-table tbody th { position: sticky; left: 0; z-index: 1; background: var(--surface); }
    .planning-detail-table thead th:first-child { left: 0; z-index: 3; }
    table { border-collapse: collapse; width: 100%; min-width: 30rem; }
    th, td { padding: .5rem .65rem; border-bottom: 1px solid var(--border); text-align: left; }
    caption { text-align: left; padding: .5rem 0; font-weight: 600; }
    @media (max-width: 36rem) { .detail-list div { grid-template-columns: 1fr; gap: .1rem; } }
  `,
})
export class PlanningDetailDialog implements AfterViewInit, OnDestroy {
  readonly data = inject<PlanningDetailDialogData>(MAT_DIALOG_DATA);
  @ViewChild('detailChart') private detailCanvas?: ElementRef<HTMLCanvasElement>;
  private detailChart?: Chart;

  ngAfterViewInit(): void {
    if (this.data.kind !== 'chart' || !this.data.chart || !this.detailCanvas) return;
    try {
      const chart = this.data.chart;
      this.detailChart = new Chart(this.detailCanvas.nativeElement, {
        type: chart.type,
        data: { labels: chart.labels, datasets: chart.datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: { legend: { display: true } },
          scales: { x: { ticks: { autoSkip: true, maxTicksLimit: 12 } }, y: { beginAtZero: false, ...(chart.yAxisTitle ? { title: { display: true, text: chart.yAxisTitle } } : {}) } },
        } as never,
      }) as unknown as Chart;
    } catch {
      // The dialog remains usable through its explicit close action if Canvas is unavailable.
    }
  }

  ngOnDestroy(): void {
    this.detailChart?.destroy();
  }

  previewProblems(preview: PlanningPreviewDto): PlanningDeficitDto[] {
    return previewProblems(preview);
  }

  heaterText(heaterId: string | null, planning: PlanningDto | undefined): string {
    if (!heaterId) return 'Instalación';
    return planning?.heaters.find((heater) => heater.id === heaterId)?.name ?? heaterId;
  }

  heaterTexts(heaterIds: string[], planning: PlanningDto | undefined): string {
    return heaterIds.length ? heaterIds.map((heaterId) => this.heaterText(heaterId, planning)).join(', ') : 'ninguno';
  }

  requirementText(requirement: string): string {
    return requirementLabel(requirement);
  }

  temperature(value: number | null | undefined): string {
    return value === null || value === undefined ? 'no disponible' : `${formatTemperature(value)} °C`;
  }

  energy(value: number | null | undefined): string {
    return value === null || value === undefined ? 'no disponible' : `${value.toFixed(2)} kWh`;
  }

  problemExplanation(item: PlanningDeficitDto): string {
    return explainPlanningDeficit(item);
  }

  problemAction(item: PlanningDeficitDto, preview: PlanningPreviewDto): string | null {
    const cause = item.reason.split(':', 1)[0];
    const warnings = preview.operator_summary['warnings'];
    if (Array.isArray(warnings)) {
      const warning = warnings.find((value): value is Record<string, unknown> => typeof value === 'object' && value !== null && value['cause'] === cause);
      if (typeof warning?.['recommended_action'] === 'string') return warning['recommended_action'];
    }
    return recommendedPlanningAction(cause);
  }

  sourceText(source: string): string {
    return forecastSourceLabel(source);
  }

  dateText(value: string | null | undefined): string {
    if (!value) return 'no disponible';
    const formatted = formatDateOnly(value);
    return formatted === '—' ? 'no disponible' : formatted;
  }

  dateTime(value: string | null | undefined): string {
    if (!value) return 'no disponible';
    const formatted = formatInstant(value, this.data.planning?.timezone ?? 'Europe/Madrid');
    return formatted === '—' ? 'no disponible' : formatted;
  }

  forecastStatusText(status: string | null | undefined): string {
    return forecastStatusLabel(status);
  }

  forecastNextText(kind: string | null | undefined): string {
    return forecastNextRunLabel(kind);
  }

  forecastRange(points: HourlyForecastPointDto[]): string {
    if (!points.length) return 'no disponible';
    return `${this.dateTime(points[0].timestamp)}–${this.dateTime(points[points.length - 1].timestamp)}`;
  }

  formatTemperature(value: number | null | undefined): string {
    return formatTemperature(value);
  }

  temperatures(forecast: NonNullable<PlanningDto['forecast']>): string {
    const minimum = forecast.minimum_temperature_c === null ? 'no disponible' : `${formatTemperature(forecast.minimum_temperature_c)} °C`;
    const maximum = forecast.maximum_temperature_c === null ? 'no disponible' : `${formatTemperature(forecast.maximum_temperature_c)} °C`;
    return `media ${formatTemperature(forecast.average_temperature_c)} °C · mínima ${minimum} · máxima ${maximum}`;
  }

  previewSlotLabel(slot: Record<string, unknown>): string {
    return this.dateTime(String(slot['start'] ?? ''));
  }

  previewSlotRangeLabel(slot: Record<string, unknown>): string {
    return `${this.dateTime(String(slot['start'] ?? ''))}–${this.dateTime(String(slot['end'] ?? ''))}`;
  }

  previewSlotPower(slot: Record<string, unknown>): number {
    return Number(slot['power_w'] ?? 0);
  }

  previewSlotHeaters(slot: Record<string, unknown>): string {
    const ids = Array.isArray(slot['heater_ids']) ? slot['heater_ids'].map(String) : [];
    return this.heaterTexts(ids, this.data.planning);
  }

  previewChargingSlots(result: PlanningPreviewDto): Array<Record<string, unknown>> {
    return this.previewWindowSlots(result).filter((slot) => this.previewSlotPower(slot) > 0);
  }

  previewWindowSlots(result: PlanningPreviewDto): Array<Record<string, unknown>> {
    const windowStart = Date.parse(result.window_start);
    const windowEnd = Date.parse(result.window_end);
    if (!Number.isFinite(windowStart) || !Number.isFinite(windowEnd)) return result.slots;
    return result.slots.filter((slot) => {
      const start = Date.parse(String(slot['start'] ?? ''));
      return Number.isFinite(start) && start >= windowStart && start < windowEnd;
    });
  }

  previewSlotMetric(slot: Record<string, unknown>, key: 'heater_power_w' | 'stored_energy_kwh' | 'stored_energy_next_kwh' | 'indoor_temperature_c' | 'indoor_temperature_next_c' | 'target_temperature_c' | 'heat_delivered_kwh' | 'thermal_loss_kwh' | 'temperature_shortfall_start_c' | 'temperature_shortfall_c' | 'charge_energy_kwh', heaterId: string): number {
    const values = slot[key] as Record<string, number> | undefined;
    return typeof values?.[heaterId] === 'number' ? values[heaterId] : 0;
  }

  previewPower(slot: Record<string, unknown>, heaterId: string, fallbackPowerW = 0): number {
    const values = slot['heater_power_w'] as Record<string, number> | undefined;
    const value = values?.[heaterId];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const heaterIds = slot['heater_ids'];
    if (!Array.isArray(heaterIds) || !heaterIds.some((id) => String(id) === heaterId)) return 0;
    if (fallbackPowerW > 0) return fallbackPowerW;
    return heaterIds.length === 1 ? this.previewSlotPower(slot) : 0;
  }

  previewStoredEnergy(slot: Record<string, unknown>, heaterId: string): number {
    return this.previewSlotMetric(slot, 'stored_energy_kwh', heaterId);
  }
  previewStoredEnergyNext(slot: Record<string, unknown>, heaterId: string): number {
    return this.previewSlotMetric(slot, 'stored_energy_next_kwh', heaterId);
  }
  previewIndoorTemperature(slot: Record<string, unknown>, heaterId: string): number {
    return this.previewSlotMetric(slot, 'indoor_temperature_c', heaterId);
  }
  previewIndoorTemperatureNext(slot: Record<string, unknown>, heaterId: string): number {
    return this.previewSlotMetric(slot, 'indoor_temperature_next_c', heaterId);
  }
  previewTargetTemperature(slot: Record<string, unknown>, heaterId: string): number | null {
    const values = slot['target_temperature_c'] as Record<string, number> | undefined;
    return typeof values?.[heaterId] === 'number' ? values[heaterId] : null;
  }
  previewHeatDelivered(slot: Record<string, unknown>, heaterId: string): number {
    return this.previewSlotMetric(slot, 'heat_delivered_kwh', heaterId);
  }
  previewThermalLoss(slot: Record<string, unknown>, heaterId: string): number {
    return this.previewSlotMetric(slot, 'thermal_loss_kwh', heaterId);
  }
  previewShortfall(slot: Record<string, unknown>, heaterId: string): number {
    return this.previewSlotMetric(slot, 'temperature_shortfall_c', heaterId);
  }
  previewShortfallStart(slot: Record<string, unknown>, heaterId: string): number {
    return this.previewSlotMetric(slot, 'temperature_shortfall_start_c', heaterId);
  }

  checkText(name: string): string {
    return ({ input_validation: 'Validación de inputs', telemetry: 'Telemetría', aemet_coverage: 'Cobertura AEMET', demand_estimation: 'Estimación de demanda', constraints: 'Materialización de constraints', resolution: 'Resolución', safety_validation: 'Validación de seguridad', operator_summary: 'Resumen final' } as Record<string, string>)[name] ?? name;
  }

  checkStatusText(status: string): string {
    return ({ pending: 'pendiente', running: 'en curso', completed: 'completado', error: 'error', cancelled: 'cancelado', skipped: 'omitido' } as Record<string, string>)[status] ?? status;
  }
}

@Component({
  selector: 'dtc-planning',
  imports: [FormsModule, MatButtonModule, MatIconModule, MatTabsModule],
  templateUrl: './planning.html',
  styleUrl: './planning.css',
})
export class Planning implements AfterViewInit, OnDestroy {
  private readonly api = inject(Api);
  private readonly dialog = inject(MatDialog);
  private readonly injector = inject(Injector);
  readonly snapshot = signal<PlanningDto | null>(null);
  readonly failure = signal<Explained | null>(null);
  readonly loading = signal(true);
  readonly draftTargets = signal<TemperatureTargetDraft[]>([]);
  readonly preview = signal<PlanningPreviewDto | null>(null);
  readonly actionMessage = signal('');
  readonly actionError = signal('');
  readonly activationInFlight = signal(false);
  readonly previewJob = signal<PlanningPreviewJobDto | null>(null);
  readonly selectedTab = signal(0);

  @ViewChild('temperatureChart') private temperatureCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('forecastChart') private forecastCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('heaterChart') private heaterCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('aggregateChart') private aggregateCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('cumulativeChart') private cumulativeCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('previewChart') private previewCanvas?: ElementRef<HTMLCanvasElement>;
  private charts: Chart[] = [];
  private readonly previewPoller = new Poller(() => this.pollPreviewJob());
  private readonly previewStorageKey = 'dtc.planning.preview-job';
  private previewPollInFlight = false;
  private dismissedPreviewJobId: string | null = null;

  constructor() {
    this.refresh();
    this.restorePreviewJob();
  }

  ngAfterViewInit(): void {
    this.scheduleChartRender();
  }

  ngOnDestroy(): void {
    this.destroyCharts();
    this.previewPoller.stop();
  }

  onTabChange(index: number): void {
    this.selectedTab.set(index);
    this.scheduleChartRender();
  }

  refresh(options: PlanningRefreshOptions = {}): void {
    const restorePreview = options.restorePreview ?? true;
    this.api.planning().subscribe({
      next: (planning) => {
        this.snapshot.set(planning);
        this.draftTargets.set(this.draftTargetsFrom(planning));
        this.failure.set(null);
        this.loading.set(false);
        if (restorePreview && planning.preview_job) this.acceptPreviewJob(planning.preview_job);
        if (!restorePreview) this.clearPreviewState();
        this.scheduleChartRender();
      },
      error: (error: unknown) => {
        this.loading.set(false);
        this.failure.set(this.describe(error));
      },
    });
  }

  private draftTargetsFrom(planning: PlanningDto): TemperatureTargetDraft[] {
    return (planning.temperature_targets ?? []).map((item) => ({ heater_id: item.heater_id, target_temperature_c: item.target_temperature_c, start_time: item.start_time, end_time: item.end_time, weekdays: [...item.weekdays], enabled: item.enabled }));
  }

  addTarget(heaterId = ''): void { this.draftTargets.update((items) => [...items, { heater_id: heaterId || this.snapshot()?.heaters[0]?.id || '', target_temperature_c: 21, start_time: '07:00', end_time: '09:00', weekdays: [0, 1, 2, 3, 4, 5, 6], enabled: true }]); }
  duplicateTarget(index: number): void {
    this.draftTargets.update((items) => {
      const source = items[index];
      if (!source) return items;
      const copy = { ...source, weekdays: [...source.weekdays] };
      return [...items.slice(0, index + 1), copy, ...items.slice(index + 1)];
    });
  }
  removeTarget(index: number): void { this.draftTargets.update((items) => items.filter((_item, itemIndex) => itemIndex !== index)); }
  editTarget(index: number, field: keyof TemperatureTargetDraft, value: unknown): void {
    this.draftTargets.update((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: field === 'target_temperature_c' ? Number(value) : value } as TemperatureTargetDraft : item));
  }
  toggleDay(index: number, day: number): void {
    this.draftTargets.update((items) => items.map((item, itemIndex) => {
      if (itemIndex !== index) return item;
      const weekdays = item.weekdays.includes(day) ? item.weekdays.filter((value) => value !== day) : [...item.weekdays, day].sort((a, b) => a - b);
      return { ...item, weekdays };
    }));
  }

  weekdayName(day: number): string {
    return WEEKDAY_NAMES[day] ?? `Día ${day + 1}`;
  }

  weekdayShortName(day: number): string {
    return WEEKDAY_SHORT_NAMES[day] ?? '?';
  }

  targetDaysSummary(target: TemperatureTargetDraft): string {
    const selectedDays = WEEKDAY_NAMES.filter((_name, day) => target.weekdays.includes(day));
    if (selectedDays.length === WEEKDAY_NAMES.length) return 'Todos los días';
    if (!selectedDays.length) return 'Ningún día seleccionado';
    return selectedDays.join(', ');
  }

  targetEndLabel(endTime: string): string {
    return endTime === '24:00' ? '24:00 (medianoche)' : endTime;
  }

  targetTimeSummary(target: TemperatureTargetDraft): string {
    return `${target.start_time}–${this.targetEndLabel(target.end_time)}`;
  }

  targetCrossesMidnight(target: TemperatureTargetDraft): boolean {
    return target.end_time !== '24:00' && target.start_time > target.end_time;
  }

  targetScheduleDescription(target: TemperatureTargetDraft): string {
    if (this.targetCrossesMidnight(target)) return `Cruza medianoche: comienza a las ${target.start_time} y termina a las ${target.end_time}.`;
    if (target.end_time === '24:00') return `Termina en medianoche (24:00), después de las ${target.start_time}.`;
    return `Intervalo local de ${target.start_time} a ${target.end_time}.`;
  }

  isMidnight(target: TemperatureTargetDraft): boolean {
    return target.end_time === '24:00';
  }

  targetEndInputValue(target: TemperatureTargetDraft): string {
    return this.isMidnight(target) ? '00:00' : target.end_time;
  }

  toggleMidnight(index: number, enabled: boolean): void {
    this.editTarget(index, 'end_time', enabled ? '24:00' : '00:00');
  }

  isTargetEnabled(target: TemperatureTargetDraft): boolean {
    return target.enabled !== false;
  }

  recalculate(): void {
    this.dismissedPreviewJobId = null;
    this.actionError.set(''); this.actionMessage.set('Iniciando vista previa…'); this.preview.set(null);
    this.api.planningPreviewJobStart(this.apiTargets(), this.snapshot()?.temperature_targets_revision).subscribe({
      next: (job) => { this.acceptPreviewJob(job); this.actionMessage.set('Vista previa en curso. Puedes seguir sus comprobaciones o cancelarla.'); },
      error: (error: unknown) => { this.actionMessage.set(''); this.actionError.set(this.previewStartError(error)); },
    });
  }
  cancelPreview(): void {
    const job = this.previewJob();
    if (!job || ['completed', 'error', 'cancelled', 'interrupted'].includes(job.status)) return;
    this.actionMessage.set('Solicitando cancelación…');
    this.api.planningPreviewJobCancel(job.job_id).subscribe({
      next: (value) => { this.acceptPreviewJob(value); this.actionMessage.set('La vista previa está cancelando; terminará al cerrar la fase activa.'); },
      error: () => this.actionError.set('No se pudo solicitar la cancelación. Vuelve a consultar el estado del trabajo.'),
    });
  }
  activate(): void {
    const preview = this.preview(); const revision = this.snapshot()?.temperature_targets_revision;
    if (!preview || revision === undefined || this.activationInFlight()) return;
    this.activationInFlight.set(true);
    this.actionError.set(''); this.actionMessage.set('Guardando y activando…');
    this.api.planningActivate(preview.token, this.apiTargets(), revision).subscribe({
      next: () => {
        this.activationInFlight.set(false);
        this.clearPreviewState();
        this.refresh({ restorePreview: false });
        this.actionMessage.set('Planificación guardada y activada correctamente.');
      },
      error: (error: unknown) => {
        this.activationInFlight.set(false);
        this.actionMessage.set('');
        this.actionError.set(this.activationError(error));
      },
    });
  }

  discardChanges(): void {
    if (this.activationInFlight()) return;
    const planning = this.snapshot();
    if (!planning) return;
    this.draftTargets.set(this.draftTargetsFrom(planning));
    this.clearPreviewState();
    this.actionError.set('');
    this.actionMessage.set('Cambios descartados. Se han restaurado las consignas guardadas.');
  }

  private apiTargets(): TemperatureTargetRequest[] {
    return this.draftTargets().map((item) => ({ ...item, target_temperature_c: Number(item.target_temperature_c), enabled: item.enabled ?? true }));
  }

  sourceText(source: string): string {
    return forecastSourceLabel(source);
  }

  planStatus(status: string | null | undefined): string {
    return planStatusLabel(status);
  }

  heaterText(heaterId: string | null | undefined): string {
    if (!heaterId) return 'Instalación';
    return this.snapshot()?.heaters.find((heater) => heater.id === heaterId)?.name ?? heaterId;
  }

  requirementText(requirement: string): string {
    return requirementLabel(requirement);
  }

  slotLabel(slot: PlanningSlotDto): string {
    return this.dateTime(slot.start);
  }

  slotRangeLabel(slot: { start: string; end: string }): string {
    return `${this.dateTime(slot.start)}–${this.dateTime(slot.end)}`;
  }

  dateTime(value: string | null | undefined): string {
    if (!value) return 'no disponible';
    const formatted = formatInstant(value, this.snapshot()?.timezone ?? 'Europe/Madrid');
    return formatted === '—' ? 'no disponible' : formatted;
  }

  dateText(value: string | null | undefined): string {
    if (!value) return 'no disponible';
    const formatted = formatDateOnly(value);
    return formatted === '—' ? 'no disponible' : formatted;
  }

  forecastRange(points: HourlyForecastPointDto[]): string {
    if (!points.length) return 'no disponible';
    return `${this.dateTime(points[0].timestamp)}–${this.dateTime(points[points.length - 1].timestamp)}`;
  }

  temperatures(forecast: NonNullable<PlanningDto['forecast']>): string {
    const minimum = forecast.minimum_temperature_c === null ? 'no disponible' : `${formatTemperature(forecast.minimum_temperature_c)} °C`;
    const maximum = forecast.maximum_temperature_c === null ? 'no disponible' : `${formatTemperature(forecast.maximum_temperature_c)} °C`;
    return `media ${formatTemperature(forecast.average_temperature_c)} °C · mínima ${minimum} · máxima ${maximum}`;
  }

  forecastStatusText(status: string | null | undefined): string {
    return forecastStatusLabel(status);
  }

  forecastNextText(kind: string | null | undefined): string {
    return forecastNextRunLabel(kind);
  }

  operatorForecastText(summary: Record<string, unknown>): string {
    const forecast = summary['forecast'];
    if (!forecast || typeof forecast !== 'object' || Array.isArray(forecast)) return 'no disponible';
    const value = forecast as Record<string, unknown>;
    const source = typeof value['source'] === 'string' ? forecastSourceLabel(value['source']) : 'origen no disponible';
    if (value['automatic_eligible'] === true) return `${source} (apta para automático)`;
    if (value['available'] === true) return `${source} (solo contexto)`;
    return 'no disponible';
  }

  formatTemperature(value: number | null | undefined): string {
    return formatTemperature(value);
  }

  openForecastDetails(): void {
    const planning = this.snapshot();
    if (planning) this.dialog.open(PlanningDetailDialog, { width: 'min(92vw, 72rem)', data: { kind: 'forecast', planning }, ariaLabel: 'Detalle de la previsión', ariaModal: true });
  }

  openPlanningDetails(): void {
    const planning = this.snapshot();
    if (planning) this.dialog.open(PlanningDetailDialog, { width: 'min(92vw, 72rem)', data: { kind: 'planning', planning }, ariaLabel: 'Detalle de la planificación', ariaModal: true });
  }

  hasPreviewFailure(job: PlanningPreviewJobDto): boolean {
    return job.status === 'error' || job.checks.some((check) => check.status === 'error');
  }

  openPreviewFailure(job: PlanningPreviewJobDto, check?: PlanningCheckDto): void {
    const failed = check ?? job.checks.find((item) => item.status === 'error');
    const fallback: PlanningCheckDto = {
      name: 'preview_job', status: 'error', detail: job.error_detail,
      started_at: null, finished_at: job.finished_at,
    };
    this.dialog.open(PlanningDetailDialog, {
      width: 'min(92vw, 42rem)',
      data: { kind: 'failure', check: failed ?? fallback, job },
      ariaLabel: 'Detalle del fallo de la vista previa', ariaModal: true,
    });
  }

  openPreviewProblems(preview: PlanningPreviewDto): void {
    this.dialog.open(PlanningDetailDialog, {
      width: 'min(92vw, 58rem)',
      data: { kind: 'problems', planning: this.snapshot(), preview },
      ariaLabel: 'Problemas de la vista previa', ariaModal: true,
    });
  }

  openPreviewChartDetails(): void {
    const planning = this.snapshot();
    const preview = this.preview() ?? planning?.preview_job?.result;
    if (!planning || !preview) return;
    this.dialog.open(PlanningDetailDialog, {
      width: 'min(96vw, 72rem)',
      data: { kind: 'preview', planning, preview },
      ariaLabel: 'Detalle de la vista previa por acumulador', ariaModal: true,
    });
  }

  openTemperatureChartDetails(): void {
    const active = this.activeTimeline();
    if (!active) return;
    const { data, slots } = active;
    this.openPlanningTableDetails({
      title: 'Balance térmico por acumulador',
      ariaLabel: 'Valores de temperatura interior en los bordes, objetivo y temperatura exterior por intervalo',
      headers: ['Intervalo', ...data.heaters.map((heater) => `${heater.name} interior inicio (°C)`), ...data.heaters.map((heater) => `${heater.name} interior fin (°C)`), ...data.heaters.map((heater) => `${heater.name} objetivo (°C)`), 'Exterior (°C)'],
      rows: slots.map((slot) => [
        this.slotRangeLabel(slot),
        ...data.heaters.map((heater) => this.formatTemperature(slot.indoor_temperature_c_by_heater?.[heater.id])),
        ...data.heaters.map((heater) => this.formatTemperature(slot.indoor_temperature_next_c_by_heater?.[heater.id])),
        ...data.heaters.map((heater) => this.formatTemperature(slot.target_temperature_c_by_heater?.[heater.id])),
        this.formatTemperature(slot.temperature_c),
      ]),
    });
  }

  openHeaterChartDetails(): void {
    const active = this.activeTimeline();
    if (!active) return;
    const { data, slots } = active;
    this.openPlanningTableDetails({
      title: 'Carga por acumulador',
      ariaLabel: 'Potencia por acumulador y potencia total por intervalo',
      headers: ['Intervalo', ...data.heaters.map((heater) => `${heater.name} (W)`), 'Total (W)'],
      rows: slots.map((slot, index) => [
        this.slotRangeLabel(slot),
        ...data.heaters.map((heater) => this.powerValue(this.heaterActiveInSlot(data, index, heater.id) ? heater.power_w : 0)),
        this.powerValue(this.aggregatePowerKw(data, index) * 1000),
      ]),
    });
  }

  openAggregateChartDetails(): void {
    const active = this.activeTimeline();
    if (!active) return;
    const { data, slots } = active;
    this.openPlanningTableDetails({
      title: 'Potencia agregada frente al límite',
      ariaLabel: 'Potencia agregada, carga base y límites por intervalo',
      headers: ['Intervalo', 'Total (W)', 'Carga base (W)', 'Límite contratado (W)', 'Límite calefacción (W)'],
      rows: slots.map((slot, index) => [
        this.slotRangeLabel(slot),
        this.powerValue(this.aggregatePowerKw(data, index) * 1000),
        this.powerValue(data.base_load_w),
        this.powerValue(data.max_total_power_w),
        this.powerValue(data.max_heating_power_w || data.max_total_power_w),
      ]),
    });
  }

  openCumulativeChartDetails(): void {
    const active = this.activeTimeline();
    if (!active) return;
    const { data, slots } = active;
    this.openPlanningTableDetails({
      title: 'Energía almacenada por acumulador',
      ariaLabel: 'Energía almacenada en kWh en los bordes por acumulador y por intervalo',
      headers: ['Intervalo', ...data.heaters.map((heater) => `${heater.name} inicio (kWh)`), ...data.heaters.map((heater) => `${heater.name} fin (kWh)`)],
      rows: slots.map((slot, index) => [
        this.slotRangeLabel(slot),
        ...data.heaters.map((heater) => `${(slot.stored_energy_kwh_by_heater?.[heater.id] ?? 0).toFixed(2)} kWh`),
        ...data.heaters.map((heater) => `${(slot.stored_energy_next_kwh_by_heater?.[heater.id] ?? 0).toFixed(2)} kWh`),
      ]),
    });
  }

  openForecastChartDetails(): void {
    const data = this.snapshot();
    const points = data?.forecast?.hourly_points;
    if (!data || !points?.length) return;
    this.openChartDetails({
      title: 'Detalle de la previsión horaria',
      ariaLabel: 'Gráfico ampliado de previsión horaria de temperatura',
      type: 'line',
      labels: points.map((point) => this.dateTime(point.timestamp)),
      datasets: [{ label: 'Temperatura exterior (°C)', data: this.forecastTemperatures(points), borderColor: '#2457a6', backgroundColor: '#2457a622', tension: 0.25 }],
    });
  }

  private activeTimeline(): { data: PlanningDto; slots: PlanningTimelineSlotDto[] } | null {
    const data = this.snapshot();
    const slots = data ? this.displayTimeline(data) : [];
    if (!data?.plan || !slots.length) return null;
    return { data, slots };
  }

  private powerValue(value: number): string {
    return String(Math.round(value));
  }

  private openPlanningTableDetails(table: PlanningTableDetail): void {
    this.dialog.open(PlanningDetailDialog, {
      width: 'min(98vw, 192rem)',
      maxWidth: '98vw',
      data: { kind: 'planning-table', table },
      ariaLabel: `Detalle tabular: ${table.title}`,
      ariaModal: true,
    });
  }

  private openChartDetails(chart: ChartDetail): void {
    this.dialog.open(PlanningDetailDialog, { width: 'min(96vw, 96rem)', data: { kind: 'chart', chart }, ariaLabel: chart.title, ariaModal: true });
  }

  intervalLabels(labels: string[]): string[] {
    return labels.map((label, index) => index % 5 === 0 ? label : '');
  }

  intervalTooltipLabel(labels: string[], index: number): string {
    return labels[index] ?? '';
  }

  forecastTemperatures(points: HourlyForecastPointDto[]): number[] {
    return points.map((point) => truncateTemperature(point.temperature_c));
  }

  time(value: string): string {
    return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  hours(minutes: number): string {
    return (minutes / 60).toFixed(1).replace('.0', '');
  }

  hasUnmet(data: PlanningDto): boolean {
    return data.allocations.some((allocation) => allocation.unmet_minutes > 0);
  }

  hasDeficits(data: PlanningDto): boolean {
    return Boolean(data.deficits?.length);
  }

  deficitText(item: PlanningDeficitDto): string {
    return `${this.heaterText(item.heater_id)}: ${requirementLabel(item.requirement)} · ${planReasonLabel(item.reason)}`;
  }

  deficitExplanation(item: PlanningDeficitDto): string {
    return explainPlanningDeficit(item);
  }

  previewProblems(result: PlanningPreviewDto): PlanningDeficitDto[] {
    return previewProblems(result);
  }

  previewProblemAction(item: PlanningDeficitDto, result: PlanningPreviewDto): string | null {
    const cause = item.reason.split(':', 1)[0];
    const warnings = result.operator_summary['warnings'];
    if (Array.isArray(warnings)) {
      const warning = warnings.find((value): value is Record<string, unknown> => typeof value === 'object' && value !== null && value['cause'] === cause);
      if (typeof warning?.['recommended_action'] === 'string') return warning['recommended_action'];
    }
    return recommendedPlanningAction(cause);
  }

  storedEnergyKwh(data: PlanningDto, heaterId: string, slotIndex: number): number {
    const fromPlan = data.plan?.slots[slotIndex]?.stored_energy_kwh_by_heater?.[heaterId];
    if (fromPlan !== undefined) return fromPlan;
    return data.timeline[slotIndex]?.stored_energy_kwh_by_heater[heaterId] ?? 0;
  }

  storedEnergyNextKwh(data: PlanningDto, heaterId: string, slotIndex: number): number {
    const fromPlan = data.plan?.slots[slotIndex]?.stored_energy_next_kwh_by_heater?.[heaterId];
    if (fromPlan !== undefined) return fromPlan;
    return data.timeline[slotIndex]?.stored_energy_next_kwh_by_heater[heaterId] ?? 0;
  }

  storedEnergyPercent(data: PlanningDto, heaterId: string, slotIndex: number): number {
    const capacity = data.heaters.find((heater) => heater.id === heaterId)?.capacity_kwh ?? 0;
    if (capacity <= 0) return 0;
    return Math.max(0, Math.min(100, this.storedEnergyKwh(data, heaterId, slotIndex) / capacity * 100));
  }

  storedEnergyNextPercent(data: PlanningDto, heaterId: string, slotIndex: number): number {
    const capacity = data.heaters.find((heater) => heater.id === heaterId)?.capacity_kwh ?? 0;
    if (capacity <= 0) return 0;
    return Math.max(0, Math.min(100, this.storedEnergyNextKwh(data, heaterId, slotIndex) / capacity * 100));
  }

  kilowatts(watts: number): number {
    return watts / 1000;
  }

  private planSlotAt(data: PlanningDto, slotIndex: number) {
    return data.plan?.slots[slotIndex];
  }

  private heaterActiveInSlot(data: PlanningDto, slotIndex: number, heaterId: string): boolean {
    const heaterIds = this.planSlotAt(data, slotIndex)?.heater_ids ?? data.timeline[slotIndex]?.heater_ids ?? [];
    return heaterIds.includes(heaterId);
  }

  private aggregatePowerKw(data: PlanningDto, slotIndex: number): number {
    const watts = this.planSlotAt(data, slotIndex)?.total_power_w ?? data.timeline[slotIndex]?.total_power_w ?? 0;
    return this.kilowatts(watts);
  }

  cumulativeLabel(data: PlanningDto, slotIndex: number): string {
    return data.heaters
      .map((heater) => `${heater.name}: ${this.storedEnergyKwh(data, heater.id, slotIndex).toFixed(2)} kWh`)
      .join(' · ');
  }

  jobStatusText(status: string): string {
    return ({ queued: 'pendiente', running: 'en curso', cancelling: 'cancelando', completed: 'completado', error: 'error', cancelled: 'cancelado', interrupted: 'interrumpido' } as Record<string, string>)[status] ?? status;
  }

  checkStatusText(status: string): string {
    return ({ pending: 'pendiente', running: 'en curso', completed: 'completado', error: 'error', cancelled: 'cancelado', skipped: 'omitido' } as Record<string, string>)[status] ?? status;
  }

  checkText(name: string): string {
    return ({ input_validation: 'Validación de entradas', telemetry: 'Telemetría', aemet_coverage: 'Cobertura AEMET', demand_estimation: 'Balance energético', constraints: 'Materialización de consignas', resolution: 'Resolución', safety_validation: 'Validación de seguridad', operator_summary: 'Resumen final' } as Record<string, string>)[name] ?? name;
  }

  previewSlotLabel(slot: Record<string, unknown>): string { return this.dateTime(String(slot['start'] ?? '')); }
  previewSlotRangeLabel(slot: Record<string, unknown>): string { return `${this.dateTime(String(slot['start'] ?? ''))}–${this.dateTime(String(slot['end'] ?? ''))}`; }
  previewSlotPower(slot: Record<string, unknown>): number { return Number(slot['power_w'] ?? 0); }
  previewSlotHeaters(slot: Record<string, unknown>): string {
    const ids = Array.isArray(slot['heater_ids']) ? slot['heater_ids'].map(String) : [];
    return ids.length ? ids.map((heaterId) => this.heaterText(heaterId)).join(', ') : 'ninguno';
  }
  previewChargingSlots(result: PlanningPreviewDto): Array<Record<string, unknown>> {
    return this.previewWindowSlots(result).filter((slot) => this.previewSlotPower(slot) > 0);
  }
  previewWindowSlots(result: PlanningPreviewDto): Array<Record<string, unknown>> {
    const windowStart = Date.parse(result.window_start);
    const windowEnd = Date.parse(result.window_end);
    if (!Number.isFinite(windowStart) || !Number.isFinite(windowEnd)) return result.slots;
    return result.slots.filter((slot) => {
      const start = Date.parse(String(slot['start'] ?? ''));
      return Number.isFinite(start) && start >= windowStart && start < windowEnd;
    });
  }
  previewSlotMetric(slot: Record<string, unknown>, key: 'heater_power_w' | 'stored_energy_kwh' | 'stored_energy_next_kwh' | 'indoor_temperature_c' | 'indoor_temperature_next_c' | 'target_temperature_c' | 'heat_delivered_kwh' | 'thermal_loss_kwh' | 'temperature_shortfall_start_c' | 'temperature_shortfall_c' | 'charge_energy_kwh', heaterId: string): number {
    const values = slot[key] as Record<string, number> | undefined;
    return typeof values?.[heaterId] === 'number' ? values[heaterId] : 0;
  }
  previewPower(slot: Record<string, unknown>, heaterId: string, fallbackPowerW = 0): number {
    const values = slot['heater_power_w'] as Record<string, number> | undefined;
    const value = values?.[heaterId];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const heaterIds = slot['heater_ids'];
    if (!Array.isArray(heaterIds) || !heaterIds.some((id) => String(id) === heaterId)) return 0;
    if (fallbackPowerW > 0) return fallbackPowerW;
    return heaterIds.length === 1 ? this.previewSlotPower(slot) : 0;
  }
  previewChartPoint(slot: Record<string, unknown>, heaterId: string, fallbackPowerW = 0, index = 0): PreviewChartPoint {
    const power_w = this.previewPower(slot, heaterId, fallbackPowerW);
    return {
      x: index,
      y: this.kilowatts(power_w),
      power_w,
      stored_energy_kwh: this.previewSlotMetric(slot, 'stored_energy_kwh', heaterId),
      stored_energy_next_kwh: this.previewSlotMetric(slot, 'stored_energy_next_kwh', heaterId),
      indoor_temperature_c: this.previewSlotMetric(slot, 'indoor_temperature_c', heaterId),
      indoor_temperature_next_c: this.previewSlotMetric(slot, 'indoor_temperature_next_c', heaterId),
      target_temperature_c: this.previewSlotMetric(slot, 'target_temperature_c', heaterId),
      heat_delivered_kwh: this.previewSlotMetric(slot, 'heat_delivered_kwh', heaterId),
      thermal_loss_kwh: this.previewSlotMetric(slot, 'thermal_loss_kwh', heaterId),
      temperature_shortfall_start_c: this.previewSlotMetric(slot, 'temperature_shortfall_start_c', heaterId),
      temperature_shortfall_c: this.previewSlotMetric(slot, 'temperature_shortfall_c', heaterId),
      charge_energy_kwh: this.previewSlotMetric(slot, 'charge_energy_kwh', heaterId),
    };
  }
  previewSummaryText(summary: Record<string, unknown>): string {
    const delivered = summary['heat_delivered_kwh_by_heater'] as Record<string, number> | undefined;
    if (!delivered) return 'Sin resumen disponible.';
    return Object.entries(delivered).map(([heater, value]) => `${this.heaterText(heater)}: ${Number(value).toFixed(2)} kWh entregados`).join(' · ') || 'No se estima calor entregado.';
  }

  previewIntervalCount(result: PlanningPreviewDto): number {
    return this.previewWindowSlots(result).length;
  }

  private previewChartHeaters(data: PlanningDto, slots: Array<Record<string, unknown>>): Array<{ id: string; name: string; power_w: number }> {
    const configured = new Map(data.heaters.map((heater) => [heater.id, { id: heater.id, name: heater.name, power_w: heater.power_w }]));
    const ids = new Set(configured.keys());
    for (const slot of slots) {
      if (Array.isArray(slot['heater_ids'])) {
        for (const heaterId of slot['heater_ids']) ids.add(String(heaterId));
      }
      for (const key of ['heater_power_w', 'stored_energy_kwh', 'indoor_temperature_c']) {
        const values = slot[key];
        if (values && typeof values === 'object' && !Array.isArray(values)) {
          for (const heaterId of Object.keys(values)) ids.add(heaterId);
        }
      }
    }
    return [...ids].map((id) => configured.get(id) ?? { id, name: id, power_w: 0 });
  }

  displayTimeline(data: PlanningDto): PlanningTimelineSlotDto[] {
    return data.timeline.map((slot) => ({
      ...slot,
      temperature_c: slot.temperature_c === null ? null : truncateTemperature(slot.temperature_c),
      indoor_temperature_c_by_heater: Object.fromEntries(Object.entries(slot.indoor_temperature_c_by_heater).map(([id, value]) => [id, truncateTemperature(value)])),
      indoor_temperature_next_c_by_heater: Object.fromEntries(Object.entries(slot.indoor_temperature_next_c_by_heater).map(([id, value]) => [id, truncateTemperature(value)])),
      target_temperature_c_by_heater: Object.fromEntries(Object.entries(slot.target_temperature_c_by_heater).map(([id, value]) => [id, truncateTemperature(value)])),
    }));
  }

  private clearPreviewState(): void {
    const job = this.previewJob();
    if (job) this.dismissedPreviewJobId = job.job_id;
    this.preview.set(null);
    this.previewJob.set(null);
    this.previewPoller.stop();
    try { sessionStorage.removeItem(this.previewStorageKey); } catch { /* storage may be disabled */ }
  }

  private acceptPreviewJob(job: PlanningPreviewJobDto): void {
    if (job.job_id === this.dismissedPreviewJobId) return;
    this.previewJob.set(job);
    try { sessionStorage.setItem(this.previewStorageKey, job.job_id); } catch { /* storage may be disabled */ }
    if (job.result) {
      this.preview.set(job.result);
      this.previewPoller.stop();
      this.actionMessage.set(job.result.status === 'INVALID' ? 'La ventana no es planificable; revisa los avisos.' : 'Vista previa calculada. Todavía no modifica el plan activo.');
      this.scheduleChartRender();
    } else if (['completed', 'error', 'cancelled', 'interrupted'].includes(job.status)) {
      this.previewPoller.stop();
    } else {
      this.previewPoller.start(2);
    }
  }

  private pollPreviewJob(): void {
    const job = this.previewJob();
    if (!job || this.previewPollInFlight) return;
    this.previewPollInFlight = true;
    this.api.planningPreviewJob(job.job_id).subscribe({
      next: (value) => this.acceptPreviewJob(value),
      error: () => { this.previewPollInFlight = false; },
      complete: () => { this.previewPollInFlight = false; },
    });
  }

  private restorePreviewJob(): void {
    let jobId: string | null = null;
    try { jobId = sessionStorage.getItem(this.previewStorageKey); } catch { return; }
    if (!jobId) return;
    this.api.planningPreviewJob(jobId).subscribe({ next: (job) => this.acceptPreviewJob(job), error: () => { try { sessionStorage.removeItem(this.previewStorageKey); } catch { /* ignore */ } } });
  }

  private boundaryLabels(slots: PlanningTimelineSlotDto[]): string[] {
    if (!slots.length) return [];
    return [...slots.map((slot) => this.dateTime(slot.start)), this.dateTime(slots[slots.length - 1].end)];
  }

  private boundarySeries(
    slots: PlanningTimelineSlotDto[],
    startValue: (slot: PlanningTimelineSlotDto) => number | null | undefined,
    endValue: (slot: PlanningTimelineSlotDto) => number | null | undefined,
  ): Array<number | null> {
    if (!slots.length) return [];
    return [
      ...slots.map((slot) => startValue(slot) ?? null),
      endValue(slots[slots.length - 1]) ?? null,
    ];
  }

  private discreteSeries(slots: PlanningTimelineSlotDto[], value: (slot: PlanningTimelineSlotDto, index: number) => number): number[] {
    if (!slots.length) return [];
    const values = slots.map(value);
    return [...values, values[values.length - 1]];
  }

  private discreteBoundarySeries(
    slots: PlanningTimelineSlotDto[],
    startValue: (index: number) => number,
    endValue: (index: number) => number,
  ): number[] {
    if (!slots.length) return [];
    return [...slots.map((_slot, index) => startValue(index)), endValue(slots.length - 1)];
  }

  private discretePreviewSeries(slots: Array<Record<string, unknown>>, heaterId: string, fallbackPowerW: number): PreviewChartPoint[] {
    if (!slots.length) return [];
    const values = slots.map((slot, index) => this.previewChartPoint(slot, heaterId, fallbackPowerW, index));
    return [...values, this.previewChartPoint(slots[slots.length - 1], heaterId, fallbackPowerW, slots.length)];
  }

  private temperatureAxisRange(series: Array<Array<number | null>>): { min: number; max: number } | undefined {
    const values = series.flat().filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
    if (!values.length) return undefined;
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);
    const padding = Math.max(0.5, (maximum - minimum) * 0.1);
    return { min: minimum - padding, max: maximum + padding };
  }

  private renderCharts(): void {
    const data = this.snapshot();
    if (!data) return;
    const timeline = this.displayTimeline(data);
    this.destroyCharts();
    try {
      if (this.selectedTab() === 2) {
        if (data.forecast?.hourly_points.length && this.forecastCanvas) {
          const points = data.forecast.hourly_points;
          const fullLabels = points.map((point) => this.dateTime(point.timestamp));
          this.charts.push(new Chart(this.forecastCanvas.nativeElement, {
            type: 'line',
            data: { labels: this.intervalLabels(fullLabels), datasets: [{ label: 'Temperatura exterior (°C)', data: this.forecastTemperatures(points), borderColor: '#2457a6', backgroundColor: '#2457a622', tension: 0.25, spanGaps: false }] },
            options: this.chartOptions<'line'>(fullLabels, '°C', undefined, this.temperatureAxisRange([this.forecastTemperatures(points)])),
          }));
        }
        return;
      }
      const preview = this.preview() ?? data.preview_job?.result;
      if (this.selectedTab() === 1) {
        if (!preview || !this.previewCanvas) return;
        const slots = this.previewWindowSlots(preview);
        if (!slots.length) return;
        const fullLabels = [...slots.map((slot) => this.previewSlotLabel(slot)), this.dateTime(String(slots[slots.length - 1]['end'] ?? ''))];
        const colors = ['#2457a6', '#d46b28', '#3b8c68', '#8a4f9e', '#9b7a21'];
        const previewHeaters = this.previewChartHeaters(data, slots);
        this.charts.push(new Chart(this.previewCanvas.nativeElement, {
          type: 'line',
          data: {
            labels: this.intervalLabels(fullLabels),
            datasets: previewHeaters.map((heater, index) => ({
              label: heater.name,
              data: this.discretePreviewSeries(slots, heater.id, heater.power_w),
              borderColor: colors[index % colors.length],
              backgroundColor: `${colors[index % colors.length]}22`,
              stepped: 'after' as const,
              tension: 0,
              pointRadius: 0,
              spanGaps: false,
            })),
          },
          options: this.chartOptions<'line'>(fullLabels, 'Potencia (kW)', (context) => {
            const point = context.raw as PreviewChartPoint;
            return `${context.dataset.label ?? 'Acumulador'}: ${point.power_w} W · ${point.stored_energy_kwh.toFixed(2)}→${point.stored_energy_next_kwh.toFixed(2)} kWh almacenados · ${point.indoor_temperature_c.toFixed(1)}→${point.indoor_temperature_next_c.toFixed(1)} °C interior · ${point.heat_delivered_kwh.toFixed(2)} kWh entregados · ${point.thermal_loss_kwh.toFixed(2)} kWh intercambio`;
          }),
        }) as unknown as Chart);
        return;
      }
      if (!data.plan || !timeline.length || !this.temperatureCanvas || !this.heaterCanvas || !this.aggregateCanvas || !this.cumulativeCanvas) return;
      const fullLabels = this.boundaryLabels(timeline);
      const labels = this.intervalLabels(fullLabels);
      const colors = ['#2457a6', '#d46b28', '#3b8c68', '#8a4f9e', '#9b7a21'];
      const indoorSeries = data.heaters.map((heater) => this.boundarySeries(
        timeline,
        (slot) => slot.indoor_temperature_c_by_heater?.[heater.id],
        (slot) => slot.indoor_temperature_next_c_by_heater?.[heater.id],
      ));
      const targetSeries = data.heaters.map((heater) => this.boundarySeries(
        timeline,
        (slot) => slot.target_temperature_c_by_heater?.[heater.id],
        (slot) => slot.target_temperature_c_by_heater?.[heater.id],
      ));
      const outdoorSeries: Array<number | null> = [
        ...timeline.map((slot) => slot.temperature_c),
        timeline[timeline.length - 1].temperature_c,
      ];
      this.charts.push(new Chart(this.temperatureCanvas.nativeElement, {
        type: 'line',
        data: {
          labels,
          datasets: [
            ...data.heaters.map((heater, index) => ({
              label: `${heater.name} interior (°C)`,
              data: indoorSeries[index],
              borderColor: colors[index % colors.length],
              backgroundColor: `${colors[index % colors.length]}22`,
              tension: 0,
              spanGaps: false,
            })),
            ...data.heaters.map((heater, index) => ({
              label: `${heater.name} objetivo (°C)`,
              data: targetSeries[index],
              borderColor: colors[index % colors.length],
              borderDash: [4, 3],
              pointRadius: 0,
              tension: 0,
              spanGaps: false,
            })),
            {
              label: 'Previsión exterior (°C)',
              data: outdoorSeries,
              borderColor: '#6b7280',
              backgroundColor: '#6b728022',
              borderDash: [6, 4],
              tension: 0,
              spanGaps: false,
            },
          ],
        },
        options: this.chartOptions<'line'>(fullLabels, '°C', undefined, this.temperatureAxisRange([...indoorSeries, ...targetSeries, outdoorSeries])),
      }));

      this.charts.push(new Chart(this.heaterCanvas.nativeElement, {
        type: 'line',
        data: { labels, datasets: data.heaters.map((heater, index) => ({
          label: heater.name,
          data: this.discreteSeries(timeline, (_slot, slotIndex) => this.heaterActiveInSlot(data, slotIndex, heater.id) ? this.kilowatts(heater.power_w) : 0),
          borderColor: colors[index % colors.length],
          backgroundColor: `${colors[index % colors.length]}cc`,
          stepped: 'after' as const,
          tension: 0,
          pointRadius: 0,
        })) },
        options: this.chartOptions<'line'>(fullLabels, 'kW'),
      }));

      this.charts.push(new Chart(this.aggregateCanvas.nativeElement, {
        type: 'line',
        data: { labels, datasets: [{ label: 'Potencia agregada (kW)', data: this.discreteSeries(timeline, (_slot, slotIndex) => this.aggregatePowerKw(data, slotIndex)), borderColor: '#2457a6', backgroundColor: '#2457a688', stepped: 'after' as const, tension: 0, pointRadius: 0 }, { label: 'Carga base (kW)', data: this.discreteSeries(timeline, () => this.kilowatts(data.base_load_w)), borderColor: '#6b7280', borderDash: [3, 3], stepped: 'after' as const, pointRadius: 0 }, { label: 'Límite contratado (kW)', data: this.discreteSeries(timeline, () => this.kilowatts(data.max_total_power_w)), borderColor: '#b33a3a', stepped: 'after' as const, pointRadius: 0 }, { label: 'Límite calefacción (kW)', data: this.discreteSeries(timeline, () => this.kilowatts(data.max_heating_power_w || data.max_total_power_w)), borderColor: '#d46b28', stepped: 'after' as const, pointRadius: 0 }] },
        options: this.chartOptions<'line'>(fullLabels, 'kW'),
      }));

      this.charts.push(new Chart(this.cumulativeCanvas.nativeElement, {
        type: 'line',
        data: { labels, datasets: data.heaters.map((heater, index) => ({
          label: `${heater.name} (%)`,
          data: this.discreteBoundarySeries(timeline, (slotIndex) => this.storedEnergyPercent(data, heater.id, slotIndex), (slotIndex) => this.storedEnergyNextPercent(data, heater.id, slotIndex)),
          borderColor: colors[index % colors.length],
          backgroundColor: `${colors[index % colors.length]}22`,
          stepped: 'after' as const,
          tension: 0,
          pointRadius: 0,
        })) },
        options: this.chartOptions<'line'>(fullLabels, 'Energía almacenada (%)', undefined, { min: 0, max: 100 }),
      }));
    } catch {
      // Canvas is unavailable in some browsers/test environments. The table is
      // the normative accessible representation and remains fully usable.
      this.destroyCharts();
    }
  }

  private destroyCharts(): void {
    for (const chart of this.charts) chart.destroy();
    this.charts = [];
  }

  private chartRenderScheduled = false;

  private scheduleChartRender(): void {
    if (this.chartRenderScheduled) return;
    this.chartRenderScheduled = true;
    afterNextRender(() => {
      this.chartRenderScheduled = false;
      this.renderCharts();
    }, { injector: this.injector });
  }

  private chartOptions<T extends 'line' | 'bar'>(fullLabels: string[], yAxisTitle?: string, tooltipLabel?: (context: TooltipItem<T>) => string, yAxisRange?: { min: number; max: number }): ChartOptions<T> {
    const options = {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true },
        tooltip: {
          callbacks: {
            title: (items: TooltipItem<T>[]) => this.intervalTooltipLabel(fullLabels, items[0]?.dataIndex ?? 0),
            label: tooltipLabel ?? ((context: TooltipItem<T>) => `${(context.dataset as unknown as { label?: string }).label ?? 'Valor'}: ${context.formattedValue}`),
          },
        },
      },
      scales: {
        x: { ticks: { callback: (_value: string | number, index: number) => this.intervalLabels(fullLabels)[index] ?? '' } },
        y: { ...(yAxisRange ? { min: yAxisRange.min, max: yAxisRange.max, beginAtZero: false } : { beginAtZero: true }), ...(yAxisTitle ? { title: { display: true, text: yAxisTitle } } : {}) },
      },
    } as unknown as ChartOptions<T>;
    return options;
  }

  private describe(error: unknown): Explained {
    if (error instanceof HttpErrorResponse) {
      const body = error.error as ApiErrorDto | null;
      if (body && typeof body === 'object' && 'code' in body) return explain(body);
    }
    return UNREACHABLE;
  }

  private activationError(error: unknown): string {
    const apiMessage = this.apiMessage(error);
    if (apiMessage !== null) return `No se pudo guardar y activar: ${apiMessage}`;
    const explained = this.describe(error);
    const detail = explained.action ? `${explained.title}. ${explained.action}` : explained.title;
    return `No se pudo guardar y activar: ${detail}`;
  }

  private previewStartError(error: unknown): string {
    const apiMessage = this.apiMessage(error);
    return apiMessage === null
      ? 'No se pudo iniciar la vista previa. Revisa las consignas y la telemetría.'
      : `No se pudo iniciar la vista previa: ${apiMessage}`;
  }

  private apiMessage(error: unknown): string | null {
    if (!(error instanceof HttpErrorResponse)) return null;
    const body = error.error as ApiErrorDto | null;
    return body && typeof body === 'object' && 'code' in body ? messageFor(body) : null;
  }
}
