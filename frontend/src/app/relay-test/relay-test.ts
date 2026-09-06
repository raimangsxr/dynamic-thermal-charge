import { HttpErrorResponse } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { Component, computed, inject, OnDestroy, signal } from '@angular/core';

import { Api } from '../core/api';
import type { ApiErrorDto, RelayTestHeaterDto, RelayTestViewDto } from '../core/api.types';
import { type Explained, UNREACHABLE, explain } from '../core/errors';
import { RelayTestSession } from '../core/relay-test-session';
import { formatAge, formatInstant } from '../shared/age/age';

type RelaySession = NonNullable<RelayTestViewDto['session']>;
type RelaySessionStatus = RelaySession['status'];
type PageAction = 'start' | 'end' | null;

interface RelaySummary {
  readonly total: number;
  readonly confirmedOn: number;
  readonly confirmedOff: number;
  readonly pending: number;
  readonly unresolved: number;
  readonly powerW: number | null;
}

@Component({
  selector: 'dtc-relay-test',
  imports: [MatButtonModule, MatCardModule, MatIconModule],
  templateUrl: './relay-test.html',
  styleUrl: './relay-test.css',
})
export class RelayTest implements OnDestroy {
  private readonly api = inject(Api);
  private readonly stored = inject(RelayTestSession);

  private stateTimer: number | null = null;
  private stateTimerMs: number | null = null;
  private leaseTimer: number | null = null;
  private leaseTimerMs: number | null = null;
  private refreshInFlight = false;
  private refreshQueued = false;
  private leaseInFlight = false;
  private leaseRenewalDisabled = false;

  readonly view = signal<RelayTestViewDto | null>(null);
  readonly error = signal<Explained | null>(null);
  readonly loading = signal(true);
  readonly refreshing = signal(false);
  readonly action = signal<PageAction>(null);
  readonly pendingCommands = signal<ReadonlySet<string>>(new Set());

  readonly summary = computed<RelaySummary>(() => {
    const heaters = this.view()?.heaters ?? [];
    const confirmed = heaters.filter(
      (heater) => heater.result === 'confirmed' && heater.confirmed_state !== null,
    );
    return {
      total: heaters.length,
      confirmedOn: confirmed.filter((heater) => heater.confirmed_state === true).length,
      confirmedOff: confirmed.filter((heater) => heater.confirmed_state === false).length,
      pending: heaters.filter((heater) => heater.result === 'pending').length,
      unresolved: heaters.filter(
        (heater) => heater.result === 'unknown' || (heater.result === 'idle' && heater.confirmed_state === null),
      ).length,
      powerW: confirmed.length === heaters.length && heaters.length > 0
        ? confirmed.reduce((total, heater) => total + (heater.confirmed_state ? heater.power_w : 0), 0)
        : null,
    };
  });

  readonly canStart = computed(() => {
    const state = this.view();
    const session = state?.session;
    return !this.loading()
      && !this.refreshing()
      && this.action() === null
      && this.error() === null
      && (!session || this.isTerminal(session.status))
      && (!state || state.controller.state_is_current)
      && !state?.safety.fault_latched;
  });

  readonly canEnd = computed(() => {
    const session = this.view()?.session;
    return !this.loading()
      && this.action() === null
      && Boolean(
        session
        && session.owner
        && this.stored.credential()
        && (session.status === 'starting' || session.status === 'active'),
      );
  });

  constructor() {
    document.addEventListener('visibilitychange', this.visibility);
    this.refresh();
  }

  ngOnDestroy(): void {
    this.stopStateTimer();
    this.stopLeaseTimer();
    document.removeEventListener('visibilitychange', this.visibility);
  }

  start(): void {
    if (!this.canStart()) {
      return;
    }
    this.action.set('start');
    this.leaseRenewalDisabled = false;
    this.error.set(null);
    this.api.relayTestStart().subscribe({
      next: (started) => {
        this.stored.save(started.session_id, started.client_credential);
        this.refresh();
      },
      error: (error: unknown) => {
        this.handleError(error, 'No se pudo iniciar el modo test.');
        this.action.set(null);
      },
    });
  }

  refresh(keepError = false): void {
    if (this.refreshInFlight) {
      this.refreshQueued = true;
      return;
    }

    this.refreshInFlight = true;
    this.refreshing.set(true);
    if (this.view() === null) {
      this.loading.set(true);
    }

    const storedId = this.stored.id();
    const request = storedId
      ? this.api.relayTestById(storedId, this.stored.credential())
      : this.api.relayTest(this.stored.credential());
    request.subscribe({
      next: (view) => {
        this.view.set(view);
        this.stored.observe(view);
        if (!keepError) {
          this.error.set(null);
        }
        this.loading.set(false);
        this.reconcilePending(view);
        this.completeAction(view);
        this.syncTimers();
      },
      error: (error: unknown) => {
        this.handleError(error, 'No se puede confirmar el estado del controlador.');
        this.action.set(null);
        this.loading.set(false);
        this.syncTimers();
        this.finishRefresh();
      },
      complete: () => this.finishRefresh(),
    });
  }

  manualRefresh(): void {
    this.leaseRenewalDisabled = false;
    this.refresh();
  }

  toggle(id: string, state: boolean): void {
    const view = this.view();
    const session = view?.session;
    const credential = this.stored.credential();
    const heater = view?.heaters.find((item) => item.id === id);
    if (!heater || !credential || !session || this.refreshing() || !this.canCommand(heater)) {
      return;
    }

    this.pendingCommands.update((current) => new Set(current).add(id));
    this.error.set(null);
    this.api.relayTestSet(session.id, id, state, credential).subscribe({
      next: () => this.refresh(),
      error: (error: unknown) => {
        this.removePending(id);
        this.handleError(error, `No se pudo solicitar el cambio de ${heater.name}.`);
        this.refresh(true);
      },
    });
  }

  end(): void {
    const session = this.view()?.session;
    const credential = this.stored.credential();
    if (!session || !credential || !this.canEnd()) {
      return;
    }

    this.action.set('end');
    this.error.set(null);
    this.api.relayTestEnd(session.id, credential).subscribe({
      next: () => this.refresh(),
      error: (error: unknown) => {
        this.action.set(null);
        this.handleError(error, 'No se pudo solicitar el apagado.');
        this.refresh(true);
      },
    });
  }

  canCommand(heater: RelayTestHeaterDto): boolean {
    const state = this.view();
    const session = state?.session;
    return Boolean(
      session
      && session.owner
      && session.status === 'active'
      && this.stored.credential()
      && !this.refreshing()
      && state.controller.state_is_current
      && !state.safety.fault_latched
      && !this.pendingCommands().has(heater.id)
      && this.action() === null,
    );
  }

  isTerminal(status: RelaySessionStatus): boolean {
    return status === 'ended' || status === 'failed';
  }

  statusLabel(status: RelaySessionStatus): string {
    switch (status) {
      case 'starting': return 'Preparando la prueba';
      case 'active': return 'Prueba activa';
      case 'ending': return 'Apagando las salidas';
      case 'ended': return 'Prueba finalizada';
      case 'failed': return 'Recuperación necesaria';
    }
  }

  statusDescription(session: RelaySession): string {
    switch (session.status) {
      case 'starting': return 'El controlador está poniendo todas las salidas en estado seguro. Los botones se habilitarán cuando lo confirme.';
      case 'active': return session.owner
        ? 'El automático está suspendido mientras pruebas las salidas. Cada orden espera confirmación física.'
        : 'Otra pestaña controla la prueba. Puedes observar el resultado, pero no enviar órdenes.';
      case 'ending': return 'El controlador está apagando todas las salidas. Espera a que confirme el desenlace.';
      case 'ended': return 'La prueba terminó y el controlador confirmó el cierre de la sesión.';
      case 'failed': return 'El cierre no pudo confirmarse por completo. La recuperación de seguridad mantiene el automático bloqueado.';
    }
  }

  controllerLabel(current: boolean): string {
    return current ? 'Controlador disponible' : 'Estado no actualizado';
  }

  controllerDescription(current: boolean): string {
    return current
      ? 'Puede recibir y confirmar órdenes de prueba.'
      : 'No hay una confirmación reciente; las órdenes permanecen bloqueadas.';
  }

  resultText(result: RelayTestHeaterDto['result'], confirmed: boolean | null): string {
    switch (result) {
      case 'pending': return 'Esperando confirmación';
      case 'rejected': return 'Orden rechazada';
      case 'unknown': return 'Sin confirmar';
      case 'confirmed':
        return confirmed === null ? 'Sin confirmar' : confirmed ? 'Encendido confirmado' : 'Apagado confirmado';
      case 'idle': return confirmed === null ? 'Pendiente de una orden' : 'Último estado confirmado';
    }
  }

  resultDetail(heater: RelayTestHeaterDto): string {
    switch (heater.result) {
      case 'pending': return `Se ha solicitado ${heater.desired_state ? 'encender' : 'apagar'} esta salida.`;
      case 'rejected': return heater.result_code === 'power_limit'
        ? 'El límite de potencia impediría mantener esta salida encendida.'
        : 'La solicitud no se ha aplicado.';
      case 'unknown': return 'El controlador no puede confirmar si la salida está encendida o apagada.';
      case 'confirmed': return heater.confirmed_at
        ? `Confirmado ${formatInstant(heater.confirmed_at)}.`
        : 'El controlador ha confirmado la salida.';
      case 'idle': return heater.confirmed_state === null
        ? 'Todavía no hay una confirmación física para esta salida.'
        : `Último estado confirmado: ${heater.confirmed_state ? 'encendido' : 'apagado'}.`;
    }
  }

  requestText(heater: RelayTestHeaterDto): string {
    if (heater.result === 'idle' && heater.confirmed_state === null && heater.confirmed_at === null) {
      return 'Sin orden solicitada';
    }
    const prefix = heater.result === 'pending' ? 'Solicitud' : 'Última solicitud';
    return `${prefix}: ${heater.desired_state ? 'encender' : 'apagar'}`;
  }

  lastConfirmedText(state: boolean | null): string {
    if (state === null) {
      return 'Sin confirmación física';
    }
    return `Última confirmación: ${state ? 'encendido' : 'apagado'}`;
  }

  commandDisabledReason(heater: RelayTestHeaterDto): string {
    const state = this.view();
    const session = state?.session;
    if (this.pendingCommands().has(heater.id) || heater.result === 'pending') {
      return 'Esperando a que el controlador confirme la orden.';
    }
    if (session && this.isTerminal(session.status)) {
      return 'Esta sesión ya ha finalizado. Inicia otra prueba para volver a enviar órdenes.';
    }
    if (session && session.status !== 'active') {
      return 'Disponible cuando la sesión esté activa.';
    }
    if (!session?.owner) {
      return 'Solo la pestaña propietaria puede enviar órdenes.';
    }
    if (state?.safety.fault_latched) {
      return 'Bloqueado mientras se completa la recuperación de seguridad.';
    }
    if (!state?.controller.state_is_current) {
      return 'Bloqueado: el controlador no tiene un estado reciente.';
    }
    return '';
  }

  actionLabel(heater: RelayTestHeaterDto): string {
    if (this.pendingCommands().has(heater.id) || heater.result === 'pending') {
      return 'Esperando…';
    }
    const session = this.view()?.session;
    if (!session || session.status === 'ending') {
      return 'Apagando…';
    }
    if (session.status === 'starting') {
      return 'Preparando…';
    }
    if (this.isTerminal(session.status)) {
      return 'Prueba finalizada';
    }
    if (!session.owner) {
      return 'Solo consulta';
    }
    return heater.desired_state ? `Apagar ${heater.name}` : `Encender ${heater.name}`;
  }

  reasonText(reason: string | null): string {
    switch (reason) {
      case 'owner_finished': return 'Finalizada por el operador.';
      case 'off_sweep_failed': return 'No se pudieron apagar todas las salidas.';
      case 'configuration_changed': return 'La configuración cambió durante la prueba.';
      case 'session_invalid': return 'La sesión dejó de ser válida para el controlador.';
      case 'store_unavailable': return 'La coordinación con el controlador no estuvo disponible.';
      default: return reason ? 'El controlador informó un cierre no esperado.' : 'Sin motivo adicional.';
    }
  }

  power(watts: number | null): string {
    return watts === null ? '—' : `${(watts / 1000).toFixed(1)} kW`;
  }

  instant(value: string | null): string {
    return formatInstant(value);
  }

  age(value: number | null): string {
    return formatAge(value);
  }

  private readonly visibility = (): void => {
    if (document.hidden) {
      this.stopStateTimer();
      this.stopLeaseTimer();
      return;
    }
    this.leaseRenewalDisabled = false;
    this.refresh();
  };

  private renewLease(): void {
    if (this.leaseInFlight || document.hidden) {
      return;
    }
    const session = this.view()?.session;
    const credential = this.stored.credential();
    if (!session || !credential || !session.owner || this.view()?.safety.fault_latched || (session.status !== 'starting' && session.status !== 'active')) {
      return;
    }

    this.leaseInFlight = true;
    this.api.relayTestLease(session.id, credential).subscribe({
      next: (view) => {
        this.view.set(view);
        this.stored.observe(view);
        this.reconcilePending(view);
        this.syncTimers();
      },
      error: (error: unknown) => {
        this.leaseInFlight = false;
        const body = this.structuredError(error);
        if (body && ['relay_test_expired', 'relay_test_not_active', 'relay_test_not_owner', 'relay_test_fault_latched', 'relay_test_configuration_changed'].includes(body.code)) {
          this.leaseRenewalDisabled = true;
          this.stopLeaseTimer();
        }
        this.handleError(error, 'No se pudo renovar el modo test.');
        this.refresh(true);
      },
      complete: () => { this.leaseInFlight = false; },
    });
  }

  private syncTimers(): void {
    const view = this.view();
    const session = view?.session;
    const shouldPoll = !document.hidden && Boolean(
      view
      && (
        view.safety.fault_latched
        || (session && ['starting', 'active', 'ending'].includes(session.status))
        || view.heaters.some((heater) => heater.result === 'pending')
      ),
    );
    if (shouldPoll) {
      this.ensureStateTimer(this.intervalMs(view?.state_poll_seconds, 1));
    } else {
      this.stopStateTimer();
    }

    const shouldRenew = !document.hidden && Boolean(
      session
      && this.stored.credential()
      && session.owner
      && (session.status === 'starting' || session.status === 'active')
      && !view?.safety.fault_latched
      && !this.leaseRenewalDisabled,
    );
    if (shouldRenew) {
      this.ensureLeaseTimer(this.intervalMs(view?.lease_renew_seconds, 5));
    } else {
      this.stopLeaseTimer();
    }
  }

  private intervalMs(seconds: number | undefined, fallback: number): number {
    const value = seconds ?? fallback;
    return Number.isFinite(value) && value > 0 ? Math.max(250, value * 1000) : fallback * 1000;
  }

  private ensureStateTimer(intervalMs: number): void {
    if (this.stateTimer !== null && this.stateTimerMs === intervalMs) {
      return;
    }
    this.stopStateTimer();
    this.stateTimerMs = intervalMs;
    this.stateTimer = window.setInterval(() => this.refresh(), intervalMs);
  }

  private ensureLeaseTimer(intervalMs: number): void {
    if (this.leaseTimer !== null && this.leaseTimerMs === intervalMs) {
      return;
    }
    this.stopLeaseTimer();
    this.leaseTimerMs = intervalMs;
    this.leaseTimer = window.setInterval(() => this.renewLease(), intervalMs);
  }

  private stopStateTimer(): void {
    if (this.stateTimer !== null) {
      window.clearInterval(this.stateTimer);
      this.stateTimer = null;
    }
    this.stateTimerMs = null;
  }

  private stopLeaseTimer(): void {
    if (this.leaseTimer !== null) {
      window.clearInterval(this.leaseTimer);
      this.leaseTimer = null;
    }
    this.leaseTimerMs = null;
  }

  private finishRefresh(): void {
    this.refreshInFlight = false;
    this.refreshing.set(false);
    if (this.refreshQueued) {
      this.refreshQueued = false;
      this.refresh(true);
    }
  }

  private completeAction(view: RelayTestViewDto | null): void {
    const session = view?.session;
    if (this.action() === 'start' && session?.id === this.stored.id()) {
      this.action.set(null);
    }
    if (this.action() === 'end' && session && (session.status === 'ending' || this.isTerminal(session.status))) {
      this.action.set(null);
    }
  }

  private reconcilePending(view: RelayTestViewDto | null): void {
    const pending = new Set(this.pendingCommands());
    for (const id of pending) {
      const heater = view?.heaters.find((item) => item.id === id);
      if (!heater || heater.result !== 'pending') {
        pending.delete(id);
      }
    }
    this.pendingCommands.set(pending);
  }

  private removePending(id: string): void {
    this.pendingCommands.update((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }

  private handleError(error: unknown, fallback: string): void {
    const body = this.structuredError(error);
    if (error instanceof HttpErrorResponse) {
      if (error.status === 401) {
        this.stored.clear();
        this.view.set(null);
      } else if (error.status === 403) {
        this.stored.clearCredential();
      } else if (error.status === 404) {
        this.stored.clear();
        this.view.set(null);
      }
    }
    if (body?.code === 'relay_test_active' && this.action() === 'start') {
      this.stored.clear();
      this.view.set(null);
      this.refresh(true);
    }
    this.error.set(body ? explain(body) : this.fallbackError(fallback));
  }

  private structuredError(error: unknown): ApiErrorDto | null {
    if (!(error instanceof HttpErrorResponse)) {
      return null;
    }
    const body: unknown = error.error;
    if (body && typeof body === 'object' && 'code' in body && typeof body.code === 'string') {
      return body as ApiErrorDto;
    }
    return null;
  }

  private fallbackError(title: string): Explained {
    return {
      title,
      action: UNREACHABLE.action,
      onDevice: UNREACHABLE.onDevice,
      fieldScoped: false,
    };
  }
}
