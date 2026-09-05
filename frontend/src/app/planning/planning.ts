import { HttpErrorResponse } from '@angular/common/http';
import { JsonPipe } from '@angular/common';
import { AfterViewInit, Component, ElementRef, Injector, OnDestroy, ViewChild, afterNextRender, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { FormsModule } from '@angular/forms';
import { Chart } from 'chart.js/auto';
import type { ChartOptions, TooltipItem } from 'chart.js';

import { Api } from '../core/api';
import { Poller } from '../core/poll';
import type { ApiErrorDto, HourlyForecastPointDto, PlanningCheckDto, PlanningConstraintRequest, PlanningDto, PlanningDeficitDto, PlanningPreviewDto, PlanningPreviewJobDto, PlanningSlotDto, PlanningTimelineSlotDto } from '../core/api.types';
import { type Explained, UNREACHABLE, explain } from '../core/errors';
import { formatTemperature, truncateTemperature } from '../shared/temperature/temperature';

interface PlanningDetailDialogData {
  kind: 'forecast' | 'planning' | 'failure';
  planning?: PlanningDto;
  check?: PlanningCheckDto;
  job?: PlanningPreviewJobDto;
}

interface ConstraintDraft extends Omit<PlanningConstraintRequest, 'target_charge'> {
  target_charge: number;
}

@Component({
  selector: 'dtc-planning-detail-dialog',
  imports: [MatButtonModule, MatDialogModule],
  template: `
    <h2 mat-dialog-title>{{ data.kind === 'forecast' ? 'Detalle de la previsión' : data.kind === 'failure' ? 'Detalle del fallo de la vista previa' : 'Detalle de la planificación' }}</h2>
    <mat-dialog-content>
      @if (data.kind === 'failure') {
        <dl class="detail-list">
          <div><dt>Paso</dt><dd>{{ data.check ? checkText(data.check.name) : 'Trabajo de vista previa' }}</dd></div>
          <div><dt>Estado</dt><dd>{{ data.check ? checkStatusText(data.check.status) : 'error' }}</dd></div>
          <div><dt>Detalle</dt><dd>{{ data.check?.detail || 'No hay detalle adicional.' }}</dd></div>
          @if (data.job?.error_detail) { <div><dt>Error general</dt><dd>{{ data.job?.error_detail }}</dd></div> }
        </dl>
      } @else if (data.kind === 'forecast' && data.planning?.forecast; as forecast) {
        <dl class="detail-list">
          <div><dt>Origen</dt><dd>{{ sourceText(forecast.source) }}</dd></div>
          <div><dt>Fecha</dt><dd>{{ dateText(forecast.date) }}</dd></div>
          <div><dt>Municipio</dt><dd>{{ forecast.municipality || 'no disponible' }}</dd></div>
          <div><dt>Rango horario</dt><dd>{{ forecastRange(forecast.hourly_points) }}</dd></div>
          <div><dt>Registros horarios</dt><dd>{{ forecast.hourly_points.length }}</dd></div>
          <div><dt>Temperaturas</dt><dd>{{ temperatures(forecast) }}</dd></div>
          <div><dt>Última consulta</dt><dd>{{ dateTime(data.planning?.forecast_last_attempt_at) }}</dd></div>
          <div><dt>Próxima consulta</dt><dd>{{ dateTime(data.planning?.forecast_next_run_at) }}</dd></div>
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
        <p>Última consulta: {{ dateTime(data.planning?.forecast_last_attempt_at) }} · Próxima consulta: {{ dateTime(data.planning?.forecast_next_run_at) }}</p>
      } @else if (data.planning?.plan; as plan) {
        <dl class="detail-list">
          <div><dt>Ventana</dt><dd>{{ dateTime(plan.window_start) }}–{{ dateTime(plan.window_end) }}</dd></div>
          <div><dt>Horizonte</dt><dd>{{ dateTime(data.planning?.horizon_start) }}–{{ dateTime(data.planning?.horizon_end) }}</dd></div>
          <div><dt>Intervalo</dt><dd>{{ plan.slot_minutes }} minutos</dd></div>
          <div><dt>Registros de planificación</dt><dd>{{ plan.slots.length }}</dd></div>
          <div><dt>Creado</dt><dd>{{ dateTime(plan.created_at) }}</dd></div>
          <div><dt>Revisión de configuración</dt><dd>{{ plan.installation_revision }}</dd></div>
        </dl>
        <div class="table-scroll">
          <table><caption>Intervalos planificados</caption><thead><tr><th>Intervalo</th><th>Acumuladores</th><th>Potencia</th></tr></thead><tbody>
            @for (slot of plan.slots; track slot.start) {
              <tr><th scope="row">{{ dateTime(slot.start) }}–{{ dateTime(slot.end) }}</th><td>{{ slot.heater_ids.length ? slot.heater_ids.join(', ') : 'ninguno' }}</td><td>{{ slot.total_power_w }} W</td></tr>
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
    .table-scroll { overflow-x: auto; margin-top: 1.25rem; }
    table { border-collapse: collapse; width: 100%; min-width: 30rem; }
    th, td { padding: .5rem .65rem; border-bottom: 1px solid var(--border); text-align: left; }
    caption { text-align: left; padding: .5rem 0; font-weight: 600; }
    @media (max-width: 36rem) { .detail-list div { grid-template-columns: 1fr; gap: .1rem; } }
  `,
})
export class PlanningDetailDialog {
  readonly data = inject<PlanningDetailDialogData>(MAT_DIALOG_DATA);

  sourceText(source: string): string {
    return source === 'aemet' ? 'AEMET' : source === 'fallback' ? 'Fallback (última previsión válida)' : 'Simulación local';
  }

  dateText(value: string | null | undefined): string {
    if (!value) return 'no disponible';
    const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00`) : new Date(value);
    return date.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' });
  }

  dateTime(value: string | null | undefined): string {
    if (!value) return 'no disponible';
    return new Date(value).toLocaleString('es-ES', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
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

  checkText(name: string): string {
    return ({ input_validation: 'Validación de inputs', telemetry: 'Telemetría', aemet_coverage: 'Cobertura AEMET', demand_estimation: 'Estimación de demanda', constraints: 'Materialización de constraints', resolution: 'Resolución', safety_validation: 'Validación de seguridad', operator_summary: 'Resumen final' } as Record<string, string>)[name] ?? name;
  }

  checkStatusText(status: string): string {
    return ({ pending: 'pendiente', running: 'en curso', completed: 'completado', error: 'error', cancelled: 'cancelado', skipped: 'omitido' } as Record<string, string>)[status] ?? status;
  }
}

@Component({
  selector: 'dtc-planning',
  imports: [FormsModule, JsonPipe],
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
  readonly draftConstraints = signal<ConstraintDraft[]>([]);
  readonly preview = signal<PlanningPreviewDto | null>(null);
  readonly actionMessage = signal('');
  readonly actionError = signal('');
  readonly previewJob = signal<PlanningPreviewJobDto | null>(null);

  @ViewChild('temperatureChart') private temperatureCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('forecastChart') private forecastCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('heaterChart') private heaterCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('aggregateChart') private aggregateCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('cumulativeChart') private cumulativeCanvas?: ElementRef<HTMLCanvasElement>;
  private charts: Chart[] = [];
  private readonly previewPoller = new Poller(() => this.pollPreviewJob());
  private readonly previewStorageKey = 'dtc.planning.preview-job';

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

  refresh(): void {
    this.api.planning().subscribe({
      next: (planning) => {
        this.snapshot.set(planning);
        this.draftConstraints.set((planning.constraints ?? []).map((item) => ({ heater_id: item.heater_id, target_charge: item.target_charge * 100, at_time: item.at_time, weekdays: item.weekdays })));
        this.failure.set(null);
        this.loading.set(false);
        if (planning.preview_job) this.acceptPreviewJob(planning.preview_job);
        this.scheduleChartRender();
      },
      error: (error: unknown) => {
        this.loading.set(false);
        this.failure.set(this.describe(error));
      },
    });
  }

  addConstraint(heaterId = ''): void { this.draftConstraints.update((items) => [...items, { heater_id: heaterId || this.snapshot()?.heaters[0]?.id || '', target_charge: 100, at_time: '07:00', weekdays: [0, 1, 2, 3, 4, 5, 6] }]); }
  removeConstraint(index: number): void { this.draftConstraints.update((items) => items.filter((_item, itemIndex) => itemIndex !== index)); }
  editConstraint(index: number, field: keyof ConstraintDraft, value: unknown): void {
    this.draftConstraints.update((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: field === 'target_charge' ? Number(value) : value } as ConstraintDraft : item));
  }
  toggleDay(index: number, day: number): void {
    this.draftConstraints.update((items) => items.map((item, itemIndex) => {
      if (itemIndex !== index) return item;
      const weekdays = item.weekdays.includes(day) ? item.weekdays.filter((value) => value !== day) : [...item.weekdays, day].sort((a, b) => a - b);
      return { ...item, weekdays };
    }));
  }
  recalculate(): void {
    this.actionError.set(''); this.actionMessage.set('Iniciando vista previa…'); this.preview.set(null);
    this.api.planningPreviewJobStart(this.apiConstraints(), this.snapshot()?.constraints_revision).subscribe({
      next: (job) => { this.acceptPreviewJob(job); this.actionMessage.set('Vista previa en curso. Puedes seguir sus comprobaciones o cancelarla.'); },
      error: () => { this.actionMessage.set(''); this.actionError.set('No se pudo iniciar la vista previa. Revisa las constraints y la telemetría.'); },
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
    const preview = this.preview(); const revision = this.snapshot()?.constraints_revision;
    if (!preview || revision === undefined) return;
    this.actionError.set(''); this.actionMessage.set('Guardando y activando…');
    this.api.planningActivate(preview.token, this.apiConstraints(), revision).subscribe({
      next: () => { this.actionMessage.set('Constraints y plan activados.'); this.preview.set(null); this.refresh(); },
      error: () => { this.actionMessage.set(''); this.actionError.set('Los datos cambiaron o el plan ya no es válido. Calcula una nueva vista previa.'); },
    });
  }

  private apiConstraints(): PlanningConstraintRequest[] {
    return this.draftConstraints().map((item) => ({ ...item, target_charge: item.target_charge / 100 }));
  }

  sourceText(source: string): string {
    return source === 'aemet' ? 'AEMET' : source === 'fallback' ? 'Fallback (última previsión válida)' : 'Simulación local';
  }

  slotLabel(slot: PlanningSlotDto): string {
    return this.dateTime(slot.start);
  }

  dateTime(value: string | null | undefined): string {
    if (!value) return 'no disponible';
    return new Date(value).toLocaleString('es-ES', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
  }

  dateText(value: string | null | undefined): string {
    if (!value) return 'no disponible';
    const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00`) : new Date(value);
    return date.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' });
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

  formatTemperature(value: number | null | undefined): string {
    return formatTemperature(value);
  }

  temperatureMap(values: Record<string, number>): string {
    return Object.entries(values).map(([heaterId, value]) => `${heaterId}: ${formatTemperature(value)} °C`).join(' · ');
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

  deficitExplanation(item: PlanningDeficitDto): string {
    const detail = item.reason.includes(':') ? item.reason.split(':', 2)[1].trim() : item.reason;
    if (item.reason.startsWith('forecast_not_eligible')) {
      return 'La previsión activa no es de AEMET. La planificación automática solo usa forecast horario AEMET.';
    }
    if (item.reason.startsWith('missing_aemet_coverage')) {
      return 'No hay cobertura horaria AEMET continua desde el inicio del horizonte planificado.';
    }
    if (item.reason.startsWith('missing_required_state')) {
      return `Falta telemetría MQTT completa y reciente: ${detail}.`;
    }
    if (item.reason.startsWith('invalid_configuration')) {
      return `Configuración o constraint inválida: ${detail}.`;
    }
    if (item.reason.startsWith('solver_failure') || item.reason.startsWith('solver_unavailable')) {
      return 'El optimizador no pudo resolver el plan; revisa la instalación o contacta soporte.';
    }
    return detail || item.reason;
  }

  cumulativeMinutes(data: PlanningDto, heaterId: string, throughSlot: number): number {
    const timelineSlot = data.timeline[throughSlot];
    if (timelineSlot) return timelineSlot.charge_minutes_by_heater[heaterId] ?? 0;
    if (!data.plan) return 0;
    return data.plan.slots
      .slice(0, throughSlot + 1)
      .filter((slot) => slot.heater_ids.includes(heaterId))
      .reduce((total, slot) => total + data.plan!.slot_minutes, 0);
  }

  storedChargePercent(data: PlanningDto, heaterId: string, slotIndex: number): number {
    const fromPlan = data.plan?.slots[slotIndex]?.stored_charge_percent_by_heater?.[heaterId];
    if (fromPlan !== undefined) return fromPlan;
    return data.timeline[slotIndex]?.stored_charge_percent_by_heater[heaterId] ?? 0;
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
      .map((heater) => `${heater.name}: ${this.storedChargePercent(data, heater.id, slotIndex).toFixed(1)} %`)
      .join(' · ');
  }

  jobStatusText(status: string): string {
    return ({ queued: 'pendiente', running: 'en curso', cancelling: 'cancelando', completed: 'completado', error: 'error', cancelled: 'cancelado', interrupted: 'interrumpido' } as Record<string, string>)[status] ?? status;
  }

  checkStatusText(status: string): string {
    return ({ pending: 'pendiente', running: 'en curso', completed: 'completado', error: 'error', cancelled: 'cancelado', skipped: 'omitido' } as Record<string, string>)[status] ?? status;
  }

  checkText(name: string): string {
    return ({ input_validation: 'Validación de inputs', telemetry: 'Telemetría', aemet_coverage: 'Cobertura AEMET', demand_estimation: 'Estimación de demanda', constraints: 'Materialización de constraints', resolution: 'Resolución', safety_validation: 'Validación de seguridad', operator_summary: 'Resumen final' } as Record<string, string>)[name] ?? name;
  }

  previewSlotLabel(slot: Record<string, unknown>): string { return this.dateTime(String(slot['start'] ?? '')); }
  previewSlotPower(slot: Record<string, unknown>): number { return Number(slot['power_w'] ?? 0); }
  previewSlotHeaters(slot: Record<string, unknown>): string { return Array.isArray(slot['heater_ids']) && slot['heater_ids'].length ? slot['heater_ids'].join(', ') : 'ninguno'; }
  previewChargingSlots(result: PlanningPreviewDto): Array<Record<string, unknown>> {
    return result.slots.filter((slot) => this.previewSlotPower(slot) > 0);
  }
  matrixCell(slot: Record<string, unknown>, heaterId: string): string {
    const power = (slot['heater_power_w'] as Record<string, number> | undefined)?.[heaterId] ?? 0;
    const energy = (slot['energy_delivered_kwh'] as Record<string, number> | undefined)?.[heaterId] ?? 0;
    const capacity = (slot['capacity_percent_by_heater'] as Record<string, number> | undefined)?.[heaterId] ?? 0;
    const soc = (slot['stored_charge_percent'] as Record<string, number> | undefined)?.[heaterId] ?? 0;
    return `${power} W · ${energy.toFixed(2)} kWh · ${capacity.toFixed(1)} % capacidad · SOC ${soc.toFixed(1)} %`;
  }
  previewSummaryText(summary: Record<string, unknown>): string {
    const demand = summary['demand_kwh_by_heater'] as Record<string, number> | undefined;
    if (!demand) return 'Sin resumen disponible.';
    return Object.entries(demand).map(([heater, value]) => `${heater}: ${Number(value).toFixed(2)} kWh`).join(' · ') || 'No se estima demanda.';
  }

  displayTimeline(data: PlanningDto): PlanningTimelineSlotDto[] {
    const result = this.preview() ?? data.preview_job?.result;
    if (!result) return data.timeline.map((slot) => ({
      ...slot,
      temperature_c: slot.temperature_c === null ? null : truncateTemperature(slot.temperature_c),
      estimated_temperature_c_by_heater: Object.fromEntries(Object.entries(slot.estimated_temperature_c_by_heater).map(([id, value]) => [id, truncateTemperature(value)])),
    }));
    return result.slots.map((slot) => {
      const soc = (slot['stored_charge_percent'] as Record<string, number> | undefined) ?? {};
      const indoor = (slot['indoor_temperature_c'] as Record<string, number> | undefined) ?? {};
      const heaters = Array.isArray(slot['heater_ids']) ? slot['heater_ids'] as string[] : [];
      return {
        start: String(slot['start'] ?? ''), end: String(slot['end'] ?? ''), heater_ids: heaters,
        total_power_w: Number(slot['power_w'] ?? 0), temperature_c: typeof slot['outdoor_temperature_c'] === 'number' ? truncateTemperature(Number(slot['outdoor_temperature_c'])) : null,
        temperature_interpolated: false, charge_minutes_by_heater: {}, stored_charge_percent_by_heater: soc,
        estimated_temperature_c_by_heater: Object.fromEntries(Object.entries(indoor).map(([id, value]) => [id, truncateTemperature(value)])),
      };
    });
  }

  private acceptPreviewJob(job: PlanningPreviewJobDto): void {
    this.previewJob.set(job);
    try { sessionStorage.setItem(this.previewStorageKey, job.job_id); } catch { /* storage may be disabled */ }
    if (job.result) {
      this.preview.set(job.result);
      this.previewPoller.stop();
      this.actionMessage.set(job.result.status === 'INVALID' ? 'La ventana no es planificable; revisa los avisos.' : 'Vista previa calculada. Todavía no modifica el plan activo.');
    } else if (['completed', 'error', 'cancelled', 'interrupted'].includes(job.status)) {
      this.previewPoller.stop();
    } else {
      this.previewPoller.start(2);
    }
  }

  private pollPreviewJob(): void {
    const job = this.previewJob();
    if (!job) return;
    this.api.planningPreviewJob(job.job_id).subscribe({ next: (value) => this.acceptPreviewJob(value) });
  }

  private restorePreviewJob(): void {
    let jobId: string | null = null;
    try { jobId = sessionStorage.getItem(this.previewStorageKey); } catch { return; }
    if (!jobId) return;
    this.api.planningPreviewJob(jobId).subscribe({ next: (job) => this.acceptPreviewJob(job), error: () => { try { sessionStorage.removeItem(this.previewStorageKey); } catch { /* ignore */ } } });
  }

  private renderCharts(): void {
    const data = this.snapshot();
    if (!data) return;
    const timeline = this.displayTimeline(data);
    this.destroyCharts();
    try {
      if (data.forecast?.hourly_points.length && this.forecastCanvas) {
        const points = data.forecast.hourly_points;
        const fullLabels = points.map((point) => this.dateTime(point.timestamp));
        this.charts.push(new Chart(this.forecastCanvas.nativeElement, {
          type: 'line',
          data: { labels: this.intervalLabels(fullLabels), datasets: [{ label: 'Temperatura exterior (°C)', data: this.forecastTemperatures(points), borderColor: '#2457a6', backgroundColor: '#2457a622', tension: 0.25, spanGaps: false }] },
          options: this.chartOptions<'line'>(fullLabels),
        }));
      }
      const preview = this.preview() ?? data.preview_job?.result;
      if (preview && this.temperatureCanvas && this.heaterCanvas && this.aggregateCanvas && this.cumulativeCanvas) {
        const slots = preview.slots;
        const fullLabels = slots.map((slot) => this.previewSlotLabel(slot));
        const labels = this.intervalLabels(fullLabels);
        const colors = ['#2457a6', '#d46b28', '#3b8c68', '#8a4f9e', '#9b7a21'];
        const numberMap = (slot: Record<string, unknown>, key: string, heaterId: string): number | null => {
          const values = slot[key] as Record<string, number> | undefined;
          return values && typeof values[heaterId] === 'number' ? truncateTemperature(values[heaterId]) : null;
        };
        this.charts.push(new Chart(this.temperatureCanvas.nativeElement, { type: 'line', data: { labels, datasets: [
          ...data.heaters.map((heater, index) => ({ label: `${heater.name} estimada (°C)`, data: slots.map((slot) => numberMap(slot, 'indoor_temperature_c', heater.id)), borderColor: colors[index % colors.length], tension: 0.25 })),
          { label: 'Previsión exterior (°C)', data: slots.map((slot) => typeof slot['outdoor_temperature_c'] === 'number' ? truncateTemperature(Number(slot['outdoor_temperature_c'])) : null), borderColor: '#6b7280', borderDash: [6, 4], tension: 0.25 },
        ] }, options: this.chartOptions<'line'>(fullLabels, '°C') }));
        this.charts.push(new Chart(this.heaterCanvas.nativeElement, { type: 'bar', data: { labels, datasets: data.heaters.map((heater, index) => ({ label: heater.name, data: slots.map((slot) => Array.isArray(slot['heater_ids']) && (slot['heater_ids'] as string[]).includes(heater.id) ? this.kilowatts(heater.power_w) : 0), backgroundColor: `${colors[index % colors.length]}cc` })) }, options: this.chartOptions<'bar'>(fullLabels, 'kW') }));
        const limits = preview.operator_summary['power_limits'] as Record<string, number | null> | undefined;
        const contracted = limits?.['contracted_w'] ?? data.max_total_power_w;
        const heating = limits?.['heating_w'];
        this.charts.push(new Chart(this.aggregateCanvas.nativeElement, { type: 'line', data: { labels, datasets: [{ label: 'Potencia agregada (kW)', data: slots.map((slot) => this.kilowatts(this.previewSlotPower(slot))), borderColor: '#2457a6' }, { label: 'Carga base (kW)', data: slots.map(() => this.kilowatts(data.base_load_w)), borderColor: '#6b7280', borderDash: [3, 3], pointRadius: 0 }, { label: 'Límite contratado (kW)', data: slots.map(() => this.kilowatts(contracted)), borderColor: '#b33a3a', pointRadius: 0 }, ...(heating === null || heating === undefined ? [] : [{ label: 'Límite calefacción (kW)', data: slots.map(() => this.kilowatts(heating)), borderColor: '#d46b28', pointRadius: 0 }]) ] }, options: this.chartOptions<'line'>(fullLabels, 'kW') }));
        this.charts.push(new Chart(this.cumulativeCanvas.nativeElement, { type: 'line', data: { labels, datasets: data.heaters.map((heater, index) => ({ label: `${heater.name} (%)`, data: slots.map((slot) => numberMap(slot, 'stored_charge_percent', heater.id)), borderColor: colors[index % colors.length], stepped: true })) }, options: this.chartOptions<'line'>(fullLabels, 'Carga (%)') }));
        return;
      }
      if (!data.plan || !timeline.length || !this.temperatureCanvas || !this.heaterCanvas || !this.aggregateCanvas || !this.cumulativeCanvas) return;
      const fullLabels = timeline.map((slot) => this.slotLabel(slot));
      const labels = this.intervalLabels(fullLabels);
      const colors = ['#2457a6', '#d46b28', '#3b8c68', '#8a4f9e', '#9b7a21'];
      this.charts.push(new Chart(this.temperatureCanvas.nativeElement, {
        type: 'line',
        data: {
          labels,
          datasets: [
            ...data.heaters.map((heater, index) => ({
              label: `${heater.name} estimada (°C)`,
              data: timeline.map((slot) => slot.estimated_temperature_c_by_heater?.[heater.id] ?? null),
              borderColor: colors[index % colors.length],
              backgroundColor: `${colors[index % colors.length]}22`,
              tension: 0.25,
              spanGaps: false,
            })),
            {
              label: 'Previsión exterior (°C)',
              data: timeline.map((slot) => slot.temperature_c),
              borderColor: '#6b7280',
              backgroundColor: '#6b728022',
              borderDash: [6, 4],
              tension: 0.25,
              spanGaps: false,
            },
          ],
        },
        options: this.chartOptions<'line'>(fullLabels, '°C'),
      }));

      this.charts.push(new Chart(this.heaterCanvas.nativeElement, {
        type: 'line',
        data: { labels, datasets: data.heaters.map((heater, index) => ({
          label: heater.name,
          data: timeline.map((_slot, slotIndex) => this.heaterActiveInSlot(data, slotIndex, heater.id) ? this.kilowatts(heater.power_w) : 0),
          backgroundColor: `${colors[index % colors.length]}cc`,
        })) },
        options: this.chartOptions<'line'>(fullLabels, 'kW'),
      }));

      this.charts.push(new Chart(this.aggregateCanvas.nativeElement, {
        type: 'line',
        data: { labels, datasets: [{ label: 'Potencia agregada (kW)', data: timeline.map((_slot, slotIndex) => this.aggregatePowerKw(data, slotIndex)), borderColor: '#2457a6', backgroundColor: '#2457a688', tension: 0.15 }, { label: 'Carga base (kW)', data: timeline.map(() => this.kilowatts(data.base_load_w)), borderColor: '#6b7280', borderDash: [3, 3], pointRadius: 0 }, { label: 'Límite contratado (kW)', data: timeline.map(() => this.kilowatts(data.max_total_power_w)), borderColor: '#b33a3a', pointRadius: 0 }, { label: 'Límite calefacción (kW)', data: timeline.map(() => this.kilowatts(data.max_heating_power_w || data.max_total_power_w)), borderColor: '#d46b28', pointRadius: 0 }] },
        options: this.chartOptions<'line'>(fullLabels, 'kW'),
      }));

      this.charts.push(new Chart(this.cumulativeCanvas.nativeElement, {
        type: 'line',
        data: { labels, datasets: data.heaters.map((heater, index) => ({
          label: `${heater.name} (%)`,
          data: timeline.map((_slot, slotIndex) => this.storedChargePercent(data, heater.id, slotIndex)),
          borderColor: colors[index % colors.length],
          backgroundColor: `${colors[index % colors.length]}22`,
          stepped: true,
          tension: 0,
        })) },
        options: this.chartOptions<'line'>(fullLabels, 'Carga (%)'),
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

  private chartOptions<T extends 'line' | 'bar'>(fullLabels: string[], yAxisTitle?: string): ChartOptions<T> {
    const options = {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true },
        tooltip: {
          callbacks: {
            title: (items: TooltipItem<T>[]) => this.intervalTooltipLabel(fullLabels, items[0]?.dataIndex ?? 0),
            label: (context: TooltipItem<T>) => `${(context.dataset as unknown as { label?: string }).label ?? 'Valor'}: ${context.formattedValue}`,
          },
        },
      },
      scales: {
        x: { ticks: { callback: (_value: string | number, index: number) => this.intervalLabels(fullLabels)[index] ?? '' } },
        y: { beginAtZero: true, ...(yAxisTitle ? { title: { display: true, text: yAxisTitle } } : {}) },
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
}
