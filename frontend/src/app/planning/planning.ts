import { HttpErrorResponse } from '@angular/common/http';
import { AfterViewInit, Component, ElementRef, Injector, OnDestroy, ViewChild, afterNextRender, inject, signal } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { FormsModule } from '@angular/forms';
import { Chart } from 'chart.js/auto';
import type { ChartOptions, TooltipItem } from 'chart.js';

import { Api } from '../core/api';
import type { ApiErrorDto, HourlyForecastPointDto, PlanningConstraintRequest, PlanningDto, PlanningDeficitDto, PlanningPreviewDto, PlanningSlotDto } from '../core/api.types';
import { type Explained, UNREACHABLE, explain } from '../core/errors';

interface PlanningDetailDialogData {
  kind: 'forecast' | 'planning';
  planning: PlanningDto;
}

interface ConstraintDraft extends Omit<PlanningConstraintRequest, 'target_charge'> {
  target_charge: number;
}

@Component({
  selector: 'dtc-planning-detail-dialog',
  imports: [MatButtonModule, MatDialogModule],
  template: `
    <h2 mat-dialog-title>{{ data.kind === 'forecast' ? 'Detalle de la previsión' : 'Detalle de la planificación' }}</h2>
    <mat-dialog-content>
      @if (data.kind === 'forecast' && data.planning.forecast; as forecast) {
        <dl class="detail-list">
          <div><dt>Origen</dt><dd>{{ sourceText(forecast.source) }}</dd></div>
          <div><dt>Fecha</dt><dd>{{ dateText(forecast.date) }}</dd></div>
          <div><dt>Municipio</dt><dd>{{ forecast.municipality || 'no disponible' }}</dd></div>
          <div><dt>Rango horario</dt><dd>{{ forecastRange(forecast.hourly_points) }}</dd></div>
          <div><dt>Registros horarios</dt><dd>{{ forecast.hourly_points.length }}</dd></div>
          <div><dt>Temperaturas</dt><dd>{{ temperatures(forecast) }}</dd></div>
          <div><dt>Última consulta</dt><dd>{{ dateTime(data.planning.forecast_last_attempt_at) }}</dd></div>
          <div><dt>Próxima consulta</dt><dd>{{ dateTime(data.planning.forecast_next_run_at) }}</dd></div>
        </dl>
        @if (forecast.hourly_points.length) {
          <div class="table-scroll">
            <table><caption>Registros horarios recibidos</caption><thead><tr><th>Hora</th><th>Temperatura</th></tr></thead><tbody>
              @for (point of forecast.hourly_points; track point.timestamp) {
                <tr><th scope="row">{{ dateTime(point.timestamp) }}</th><td>{{ point.temperature_c }} °C</td></tr>
              }
            </tbody></table>
          </div>
        }
      } @else if (data.kind === 'forecast') {
        <p>No hay datos de previsión horaria disponibles.</p>
        <p>Última consulta: {{ dateTime(data.planning.forecast_last_attempt_at) }} · Próxima consulta: {{ dateTime(data.planning.forecast_next_run_at) }}</p>
      } @else if (data.planning.plan; as plan) {
        <dl class="detail-list">
          <div><dt>Ventana</dt><dd>{{ dateTime(plan.window_start) }}–{{ dateTime(plan.window_end) }}</dd></div>
          <div><dt>Horizonte</dt><dd>{{ dateTime(data.planning.horizon_start) }}–{{ dateTime(data.planning.horizon_end) }}</dd></div>
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

  temperatures(forecast: NonNullable<PlanningDto['forecast']>): string {
    const minimum = forecast.minimum_temperature_c === null ? 'no disponible' : `${forecast.minimum_temperature_c} °C`;
    const maximum = forecast.maximum_temperature_c === null ? 'no disponible' : `${forecast.maximum_temperature_c} °C`;
    return `media ${forecast.average_temperature_c} °C · mínima ${minimum} · máxima ${maximum}`;
  }
}

@Component({
  selector: 'dtc-planning',
  imports: [FormsModule],
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

  @ViewChild('temperatureChart') private temperatureCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('forecastChart') private forecastCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('heaterChart') private heaterCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('aggregateChart') private aggregateCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('cumulativeChart') private cumulativeCanvas?: ElementRef<HTMLCanvasElement>;
  private charts: Chart[] = [];

  constructor() {
    this.refresh();
  }

  ngAfterViewInit(): void {
    this.scheduleChartRender();
  }

  ngOnDestroy(): void {
    this.destroyCharts();
  }

  refresh(): void {
    this.api.planning().subscribe({
      next: (planning) => {
        this.snapshot.set(planning);
        this.draftConstraints.set((planning.constraints ?? []).map((item) => ({ heater_id: item.heater_id, target_charge: item.target_charge * 100, at_time: item.at_time, weekdays: item.weekdays })));
        this.failure.set(null);
        this.loading.set(false);
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
    this.actionError.set(''); this.actionMessage.set('Calculando vista previa…');
    this.api.planningPreview(this.apiConstraints(), this.snapshot()?.constraints_revision).subscribe({
      next: (value) => { this.preview.set(value); this.actionMessage.set('Vista previa calculada. Todavía no modifica el plan activo.'); },
      error: () => { this.actionMessage.set(''); this.actionError.set('No se pudo calcular la vista previa. Revisa las constraints y la telemetría.'); },
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
    const minimum = forecast.minimum_temperature_c === null ? 'no disponible' : `${forecast.minimum_temperature_c} °C`;
    const maximum = forecast.maximum_temperature_c === null ? 'no disponible' : `${forecast.maximum_temperature_c} °C`;
    return `media ${forecast.average_temperature_c} °C · mínima ${minimum} · máxima ${maximum}`;
  }

  openForecastDetails(): void {
    const planning = this.snapshot();
    if (planning) this.dialog.open(PlanningDetailDialog, { width: 'min(92vw, 72rem)', data: { kind: 'forecast', planning }, ariaLabel: 'Detalle de la previsión', ariaModal: true });
  }

  openPlanningDetails(): void {
    const planning = this.snapshot();
    if (planning) this.dialog.open(PlanningDetailDialog, { width: 'min(92vw, 72rem)', data: { kind: 'planning', planning }, ariaLabel: 'Detalle de la planificación', ariaModal: true });
  }

  intervalLabels(labels: string[]): string[] {
    return labels.map((label, index) => index % 5 === 0 ? label : '');
  }

  intervalTooltipLabel(labels: string[], index: number): string {
    return labels[index] ?? '';
  }

  forecastTemperatures(points: HourlyForecastPointDto[]): number[] {
    return points.map((point) => point.temperature_c);
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

  cumulativeLabel(data: PlanningDto, slotIndex: number): string {
    return data.heaters
      .map((heater) => `${heater.name}: ${this.cumulativeMinutes(data, heater.id, slotIndex)} min`)
      .join(' · ');
  }

  private renderCharts(): void {
    const data = this.snapshot();
    const timeline = data?.timeline ?? [];
    if (!data) return;
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
      if (!data.plan || !timeline.length || !this.temperatureCanvas || !this.heaterCanvas || !this.aggregateCanvas || !this.cumulativeCanvas) return;
      const fullLabels = timeline.map((slot) => this.slotLabel(slot));
      const labels = this.intervalLabels(fullLabels);
      const colors = ['#2457a6', '#d46b28', '#3b8c68', '#8a4f9e', '#9b7a21'];
      this.charts.push(new Chart(this.temperatureCanvas.nativeElement, {
        type: 'line',
        data: { labels, datasets: [{ label: 'Temperatura exterior (°C)', data: timeline.map((slot) => slot.temperature_c), borderColor: colors[0], backgroundColor: '#2457a622', tension: 0.25, spanGaps: false }] },
        options: this.chartOptions<'line'>(fullLabels),
      }));

      this.charts.push(new Chart(this.heaterCanvas.nativeElement, {
        type: 'bar',
        data: { labels, datasets: data.heaters.map((heater, index) => ({
          label: heater.name,
          data: timeline.map((slot) => slot.heater_ids.includes(heater.id) ? heater.power_w : 0),
          backgroundColor: `${colors[index % colors.length]}cc`,
        })) },
        options: this.chartOptions<'bar'>(fullLabels, 'W'),
      }));

      this.charts.push(new Chart(this.aggregateCanvas.nativeElement, {
        type: 'line',
        data: { labels, datasets: [{ label: 'Potencia agregada (W)', data: timeline.map((slot) => slot.total_power_w), borderColor: '#2457a6', backgroundColor: '#2457a688', tension: 0.15 }, { label: 'Límite configurado (W)', data: timeline.map(() => data.max_total_power_w), borderColor: '#b33a3a', pointRadius: 0 }] },
        options: this.chartOptions<'line'>(fullLabels, 'W'),
      }));

      const cumulativeFullLabels = ['Inicio', ...timeline.map((slot) => this.dateTime(slot.end))];
      this.charts.push(new Chart(this.cumulativeCanvas.nativeElement, {
        type: 'line',
        data: { labels: this.intervalLabels(cumulativeFullLabels), datasets: data.heaters.map((heater, index) => ({
          label: `${heater.name} (min)`,
          data: [0, ...timeline.map((_slot, slotIndex) => this.cumulativeMinutes(data, heater.id, slotIndex))],
          borderColor: colors[index % colors.length],
          backgroundColor: `${colors[index % colors.length]}22`,
          stepped: true,
          tension: 0,
        })) },
        options: this.chartOptions<'line'>(cumulativeFullLabels, 'Minutos de carga acumulada'),
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
