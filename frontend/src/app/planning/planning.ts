import { HttpErrorResponse } from '@angular/common/http';
import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Chart } from 'chart.js/auto';

import { Api } from '../core/api';
import type { ApiErrorDto, PlanningConstraintRequest, PlanningDto, PlanningPreviewDto, PlanningSlotDto } from '../core/api.types';
import { type Explained, UNREACHABLE, explain } from '../core/errors';

@Component({
  selector: 'dtc-planning',
  imports: [FormsModule],
  templateUrl: './planning.html',
  styleUrl: './planning.css',
})
export class Planning implements AfterViewInit, OnDestroy {
  private readonly api = inject(Api);
  readonly snapshot = signal<PlanningDto | null>(null);
  readonly failure = signal<Explained | null>(null);
  readonly loading = signal(true);
  readonly draftConstraints = signal<PlanningConstraintRequest[]>([]);
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
    this.renderCharts();
  }

  ngOnDestroy(): void {
    this.destroyCharts();
  }

  refresh(): void {
    this.api.planning().subscribe({
      next: (planning) => {
        this.snapshot.set(planning);
        this.draftConstraints.set((planning.constraints ?? []).map((item) => ({ heater_id: item.heater_id, target_charge: item.target_charge, at_time: item.at_time, weekdays: item.weekdays })));
        this.failure.set(null);
        this.loading.set(false);
        queueMicrotask(() => this.renderCharts());
      },
      error: (error: unknown) => {
        this.loading.set(false);
        this.failure.set(this.describe(error));
      },
    });
  }

  addConstraint(heaterId = ''): void { this.draftConstraints.update((items) => [...items, { heater_id: heaterId || this.snapshot()?.heaters[0]?.id || '', target_charge: 1, at_time: '07:00', weekdays: [0, 1, 2, 3, 4, 5, 6] }]); }
  removeConstraint(index: number): void { this.draftConstraints.update((items) => items.filter((_item, itemIndex) => itemIndex !== index)); }
  editConstraint(index: number, field: keyof PlanningConstraintRequest, value: unknown): void {
    this.draftConstraints.update((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: field === 'target_charge' ? Number(value) : value } as PlanningConstraintRequest : item));
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
    this.api.planningPreview(this.draftConstraints(), this.snapshot()?.constraints_revision).subscribe({
      next: (value) => { this.preview.set(value); this.actionMessage.set('Vista previa calculada. Todavía no modifica el plan activo.'); },
      error: () => { this.actionMessage.set(''); this.actionError.set('No se pudo calcular la vista previa. Revisa las constraints y la telemetría.'); },
    });
  }
  activate(): void {
    const preview = this.preview(); const revision = this.snapshot()?.constraints_revision;
    if (!preview || revision === undefined) return;
    this.actionError.set(''); this.actionMessage.set('Guardando y activando…');
    this.api.planningActivate(preview.token, this.draftConstraints(), revision).subscribe({
      next: () => { this.actionMessage.set('Constraints y plan activados.'); this.preview.set(null); this.refresh(); },
      error: () => { this.actionMessage.set(''); this.actionError.set('Los datos cambiaron o el plan ya no es válido. Calcula una nueva vista previa.'); },
    });
  }

  sourceText(source: string): string {
    return source === 'aemet' ? 'AEMET' : source === 'fallback' ? 'fallback' : 'simulado';
  }

  slotLabel(slot: PlanningSlotDto): string {
    return `${this.dateTime(slot.start)}–${this.dateTime(slot.end)}`;
  }

  dateTime(value: string): string {
    return new Date(value).toLocaleString([], { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
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
        this.charts.push(new Chart(this.forecastCanvas.nativeElement, {
          type: 'line',
          data: { labels: points.map((point) => this.dateTime(point.timestamp)), datasets: [{ label: 'Temperatura exterior (°C)', data: points.map((point) => point.temperature_c), borderColor: '#2457a6', backgroundColor: '#2457a622', tension: 0.25, spanGaps: false }] },
          options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: true } } },
        }));
      }
      if (!data.plan || !timeline.length || !this.temperatureCanvas || !this.heaterCanvas || !this.aggregateCanvas || !this.cumulativeCanvas) return;
      const labels = timeline.map((slot) => this.slotLabel(slot));
      const colors = ['#2457a6', '#d46b28', '#3b8c68', '#8a4f9e', '#9b7a21'];
      this.charts.push(new Chart(this.temperatureCanvas.nativeElement, {
        type: 'line',
        data: { labels, datasets: [{ label: 'Temperatura exterior (°C)', data: timeline.map((slot) => slot.temperature_c), borderColor: colors[0], backgroundColor: '#2457a622', tension: 0.25, spanGaps: false }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: true } } },
      }));

      this.charts.push(new Chart(this.heaterCanvas.nativeElement, {
        type: 'bar',
        data: { labels, datasets: data.heaters.map((heater, index) => ({
          label: heater.name,
          data: timeline.map((slot) => slot.heater_ids.includes(heater.id) ? heater.power_w : 0),
          backgroundColor: `${colors[index % colors.length]}cc`,
        })) },
        options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, title: { display: true, text: 'W' } } } },
      }));

      this.charts.push(new Chart(this.aggregateCanvas.nativeElement, {
        type: 'bar',
        data: { labels, datasets: [{ label: 'Potencia agregada (W)', data: timeline.map((slot) => slot.total_power_w), backgroundColor: '#2457a6cc' }, { label: 'Límite configurado (W)', data: timeline.map(() => data.max_total_power_w), type: 'line', borderColor: '#b33a3a', pointRadius: 0 }] },
        options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, title: { display: true, text: 'W' } } } },
      }));

      const cumulativeLabels = ['Inicio', ...timeline.map((slot) => this.dateTime(slot.end))];
      this.charts.push(new Chart(this.cumulativeCanvas.nativeElement, {
        type: 'line',
        data: { labels: cumulativeLabels, datasets: data.heaters.map((heater, index) => ({
          label: `${heater.name} (min)`,
          data: [0, ...timeline.map((_slot, slotIndex) => this.cumulativeMinutes(data, heater.id, slotIndex))],
          borderColor: colors[index % colors.length],
          backgroundColor: `${colors[index % colors.length]}22`,
          stepped: true,
          tension: 0,
        })) },
        options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, title: { display: true, text: 'Minutos de carga acumulada' } } } },
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

  private describe(error: unknown): Explained {
    if (error instanceof HttpErrorResponse) {
      const body = error.error as ApiErrorDto | null;
      if (body && typeof body === 'object' && 'code' in body) return explain(body);
    }
    return UNREACHABLE;
  }
}
