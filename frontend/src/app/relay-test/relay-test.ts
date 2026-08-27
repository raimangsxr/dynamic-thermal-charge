import { Component, OnDestroy, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Api } from '../core/api';
import type { RelayTestViewDto } from '../core/api.types';
import { RelayTestSession } from '../core/relay-test-session';
@Component({ selector: 'dtc-relay-test', templateUrl: './relay-test.html', styleUrl: './relay-test.css' })
export class RelayTest implements OnDestroy {
  private readonly api = inject(Api); private readonly stored = inject(RelayTestSession);
  private stateTimer: number | null = null; private leaseTimer: number | null = null;
  readonly view = signal<RelayTestViewDto | null>(null); readonly error = signal('');
  constructor() { document.addEventListener('visibilitychange', this.visibility); this.refresh(); }
  ngOnDestroy(): void { if (this.stateTimer !== null) window.clearInterval(this.stateTimer); if (this.leaseTimer !== null) window.clearInterval(this.leaseTimer); document.removeEventListener('visibilitychange', this.visibility); }
  private readonly visibility = (): void => { if (!document.hidden) this.refresh(); else this.stopLeaseTimer(); };
  start(): void { this.api.relayTestStart().subscribe({ next: x => { this.stored.save(x.session_id, x.client_credential); this.refresh(); }, error: (e) => this.handleError(e, 'No se pudo iniciar el modo test.') }); }
  refresh(): void {
    const storedId = this.stored.id();
    const request = storedId ? this.api.relayTestById(storedId, this.stored.credential()) : this.api.relayTest(this.stored.credential());
    request.subscribe({ next: x => { this.view.set(x); this.stored.observe(x); this.error.set(''); this.syncTimers(); }, error: (e) => { this.handleError(e, 'No se puede confirmar el estado del controlador.'); this.syncTimers(); } });
  }
  private renewLease(): void { const s=this.view()?.session, c=this.stored.credential(); if (document.hidden || !s || !c || !s.owner || !['starting','active'].includes(s.status) || this.view()?.safety.fault_latched) return; this.api.relayTestLease(s.id,c).subscribe({next:()=>undefined,error:e=>this.handleError(e, 'No se pudo renovar el modo test.')}); }
  private handleError(error: unknown, message: string): void { if (error instanceof HttpErrorResponse) { if (error.status === 401 || error.status === 404) this.stored.clear(); if (error.status === 403) this.stored.clearCredential(); } this.error.set(message); }
  toggle(id: string, state: boolean): void { const s=this.view()?.session, c=this.stored.credential(); if (s && c && s.owner && s.status==='active' && !this.view()?.safety.fault_latched && this.view()?.controller.state_is_current) this.api.relayTestSet(s.id,id,state,c).subscribe({next:()=>this.refresh(),error:()=>this.refresh()}); }
  end(): void { const s=this.view()?.session, c=this.stored.credential(); if(s&&c) this.api.relayTestEnd(s.id,c).subscribe({next:()=>this.refresh(), error:e=>this.handleError(e, 'No se pudo solicitar el apagado.')}); }
  resultText(result: string, confirmed: boolean | null): string { if (result === 'pending') return 'Pendiente de confirmación'; if (result === 'rejected') return 'Orden rechazada'; if (result === 'unknown' || confirmed === null) return 'Sin confirmar'; return confirmed ? 'Encendido confirmado' : 'Apagado confirmado'; }
  private syncTimers(): void {
    const view = this.view(); const session = view?.session;
    const poll = Boolean(view && (view.safety.fault_latched || session && ['starting', 'active', 'ending'].includes(session.status) || view.heaters.some((heater) => heater.result === 'pending')));
    if (poll && this.stateTimer === null) this.stateTimer = window.setInterval(() => this.refresh(), 1000);
    if (!poll && this.stateTimer !== null) { window.clearInterval(this.stateTimer); this.stateTimer = null; }
    const lease = Boolean(!document.hidden && session && this.stored.credential() && session.owner && ['starting', 'active'].includes(session.status) && !view?.safety.fault_latched);
    if (lease && this.leaseTimer === null) this.leaseTimer = window.setInterval(() => this.renewLease(), 5000);
    if (!lease) this.stopLeaseTimer();
  }
  private stopLeaseTimer(): void { if (this.leaseTimer !== null) { window.clearInterval(this.leaseTimer); this.leaseTimer = null; } }
}
