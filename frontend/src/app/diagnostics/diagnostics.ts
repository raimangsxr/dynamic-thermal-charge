import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { RouterLink } from '@angular/router';
import { DestroyRef, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../core/api';
import type { ControllerLogEventDto, ControllerLogLevel } from '../core/api.types';
import { formatInstant } from '../shared/age/age';
import {
  controllerLogLevelLabel,
  planningActionForCause,
  planningRecoveryActionLabel,
  planningRecoveryCauseLabel,
} from '../shared/presentation/presentation';

type RecoveryCause =
  | 'missing_aemet_coverage'
  | 'missing_required_state'
  | 'invalid_configuration'
  | 'insufficient_capacity_or_power'
  | 'solver_failure'
  | 'no_plan_available';

interface DiagnosticCatalogEntry {
  cause?: RecoveryCause;
  match: RegExp;
  title: string;
  summary: string;
  origin: string;
}

interface DiagnosticPresentation {
  cause: RecoveryCause | null;
  title: string;
  summary: string;
  origin: string;
}

const RECOVERY_DESTINATIONS: Record<RecoveryCause, { action: string; destination: string }> = {
  missing_aemet_coverage: { action: 'check_weather', destination: '/configuracion' },
  missing_required_state: { action: 'check_telemetry', destination: '/estado#telemetry-title' },
  invalid_configuration: { action: 'review_configuration', destination: '/configuracion' },
  insufficient_capacity_or_power: { action: 'review_power', destination: '/configuracion' },
  solver_failure: { action: 'contact_support', destination: '/diagnostico' },
  no_plan_available: { action: 'review_configuration', destination: '/planificacion' },
};

/**
 * Only stable codes and well-known controller messages are localized here.
 * Free-text history stays visible in the technical detail when it is unknown.
 */
const DIAGNOSTIC_CATALOG: DiagnosticCatalogEntry[] = [
  {
    cause: 'missing_aemet_coverage',
    match: /missing_(?:aemet|forecast|guard_forecast)_coverage|forecast_not_eligible|(?:aemet|forecast).*(?:coverage|not eligible|unavailable|failed|error)/i,
    title: 'Previsión meteorológica no disponible',
    summary: 'La previsión AEMET no cubre el horizonte necesario para planificar.',
    origin: 'Previsión meteorológica',
  },
  {
    cause: 'missing_required_state',
    match: /missing_required_state|missing (?:required )?(?:mqtt )?state|missing telemetry|telemetry.*(?:missing|stale|incomplete)/i,
    title: 'Telemetría incompleta',
    summary: 'Faltan lecturas recientes de uno o más acumuladores para planificar.',
    origin: 'Telemetría',
  },
  {
    cause: 'invalid_configuration',
    match: /invalid_configuration|invalid (?:temperature )?schedule|configuration.*invalid|schedule.*invalid/i,
    title: 'Configuración de planificación no válida',
    summary: 'Las consignas o parámetros actuales impiden generar un plan válido.',
    origin: 'Planificación',
  },
  {
    cause: 'insufficient_capacity_or_power',
    match: /insufficient_capacity_or_power|insufficient_stored_energy_or_power|heater_power_exceeds_global_limit|projected_deficit|(?:insufficient|not enough).*(?:capacity|power|energy)|power.*(?:limit|insufficient)/i,
    title: 'Capacidad o potencia insuficiente',
    summary: 'La instalación no puede cumplir el objetivo térmico con los recursos disponibles.',
    origin: 'Planificación',
  },
  {
    cause: 'solver_failure',
    match: /solver_(?:failure|unavailable|time_limit|status)|optimi[sz](?:er|ador)|optimizer/i,
    title: 'Cálculo de planificación no disponible',
    summary: 'El optimizador no ha podido resolver el plan solicitado.',
    origin: 'Planificación',
  },
  {
    cause: 'no_plan_available',
    match: /no_active_automatic_plan|no_current_or_next_plan|no valid plan|no plan available|all outputs remain off/i,
    title: 'No hay un plan utilizable',
    summary: 'Las salidas permanecen apagadas porque no hay un plan automático válido.',
    origin: 'Planificación',
  },
  {
    match: /mqtt.*(?:credential|broker|connect|publish)|(?:credential|broker|connection).*mqtt/i,
    title: 'Conexión MQTT con incidencias',
    summary: 'El controlador ha registrado una incidencia de comunicación con MQTT.',
    origin: 'Conexión MQTT',
  },
  {
    match: /gpio|output|relay/i,
    title: 'Salidas del controlador',
    summary: 'El controlador ha registrado una operación o incidencia en sus salidas.',
    origin: 'Controlador y salidas',
  },
];

function presentationFor(event: ControllerLogEventDto): DiagnosticPresentation {
  const text = `${event.logger} ${event.message}`;
  const entry = DIAGNOSTIC_CATALOG.find((candidate) => candidate.match.test(text));
  if (!entry) {
    return {
      cause: null,
      title: 'Evento técnico',
      summary: event.message,
      origin: 'Origen técnico',
    };
  }
  return {
    cause: entry.cause ?? null,
    title: entry.title,
    summary: entry.summary,
    origin: entry.origin,
  };
}

@Component({
  selector: 'dtc-diagnostics',
  imports: [
    FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule,
    MatInputModule, MatSelectModule, RouterLink,
  ],
  templateUrl: './diagnostics.html',
  styleUrl: './diagnostics.css',
})
export class Diagnostics {
  private readonly api = inject(Api);
  readonly events = signal<ControllerLogEventDto[]>([]);
  readonly level = signal<ControllerLogLevel | ''>('');
  readonly query = signal('');
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly error = signal('');
  readonly more = signal<number | null>(null);
  readonly copyFeedback = signal('');
  private timer: number | null = null;

  constructor() {
    this.load();
    this.timer = window.setInterval(() => this.refresh(), 5000);
    inject(DestroyRef).onDestroy(() => {
      if (this.timer) window.clearInterval(this.timer);
    });
  }

  load(beforeId?: number): void {
    const loadingOlder = beforeId !== undefined;
    if (loadingOlder) {
      this.loadingMore.set(true);
    } else {
      this.loading.set(true);
    }
    this.api.controllerLog({
      limit: 100,
      beforeId,
      level: this.level() || undefined,
      q: this.query() || undefined,
    }).subscribe({
      next: (page) => {
        this.events.set(loadingOlder ? [...this.events(), ...page.items] : page.items);
        this.more.set(page.next_before_id);
        this.error.set('');
        this.loading.set(false);
        this.loadingMore.set(false);
      },
      error: () => {
        this.error.set('No se pudieron cargar los eventos. Inténtalo de nuevo.');
        this.loading.set(false);
        this.loadingMore.set(false);
      },
    });
  }

  apply(): void { this.load(); }

  refresh(): void {
    if (document.visibilityState !== 'visible' || !this.events().length || this.loading() || this.loadingMore()) {
      return;
    }
    const newest = this.events()[0].id;
    this.api.controllerLog({
      afterId: newest,
      level: this.level() || undefined,
      q: this.query() || undefined,
    }).subscribe({
      next: (page) => {
        if (page.items.length) this.events.set([...page.items, ...this.events()].slice(0, 300));
      },
      error: () => undefined,
    });
  }

  levelIcon(level: ControllerLogLevel): string {
    switch (level) {
      case 'DEBUG': return 'bug_report';
      case 'INFO': return 'info';
      case 'WARNING': return 'warning';
      case 'ERROR': return 'error_outline';
      case 'CRITICAL': return 'report';
    }
  }

  eventTitle(event: ControllerLogEventDto): string {
    return presentationFor(event).title;
  }

  eventSummary(event: ControllerLogEventDto): string {
    return presentationFor(event).summary;
  }

  eventOrigin(event: ControllerLogEventDto): string {
    return presentationFor(event).origin;
  }

  eventSeverity(event: ControllerLogEventDto): string {
    return controllerLogLevelLabel(event.level);
  }

  eventCause(event: ControllerLogEventDto): string | null {
    const cause = presentationFor(event).cause;
    return cause ? planningRecoveryCauseLabel(cause) : null;
  }

  eventActionText(event: ControllerLogEventDto): string | null {
    const cause = presentationFor(event).cause;
    return cause ? planningActionForCause(cause) : null;
  }

  eventActionLabel(event: ControllerLogEventDto): string | null {
    const cause = presentationFor(event).cause;
    if (!cause) return null;
    return planningRecoveryActionLabel(RECOVERY_DESTINATIONS[cause].action);
  }

  eventDestination(event: ControllerLogEventDto): string | null {
    const cause = presentationFor(event).cause;
    return cause ? RECOVERY_DESTINATIONS[cause].destination : null;
  }

  recoveryRoute(value: string | null | undefined): string[] {
    return [String(value ?? '/').split('#', 1)[0] || '/'];
  }

  recoveryFragment(value: string | null | undefined): string | undefined {
    const fragment = String(value ?? '').split('#', 2)[1];
    return fragment || undefined;
  }

  technicalCode(event: ControllerLogEventDto): string {
    const code = event.message.match(/\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/i)?.[0];
    return code ?? 'No identificado';
  }

  technicalDetail(event: ControllerLogEventDto): string {
    return [
      `Código detectado: ${this.technicalCode(event)}`,
      `Nivel: ${event.level}`,
      `Origen: ${event.logger || 'No indicado'}`,
      `Fecha: ${event.occurred_at}`,
      `Mensaje: ${event.message || 'No indicado'}`,
    ].join('\n');
  }

  async copyTechnical(event: ControllerLogEventDto): Promise<void> {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(this.technicalDetail(event));
      this.copyFeedback.set('Detalle técnico copiado.');
    } catch {
      this.copyFeedback.set('No se pudo copiar el detalle técnico.');
    }
  }

  instant(value: string): string { return formatInstant(value); }
}
