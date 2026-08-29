import { Component, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { Auth } from './core/auth';
import { Api } from './core/api';
import { RelayTestSession } from './core/relay-test-session';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    @if (auth.authenticated()) {
      <nav aria-label="Navegación principal">
        <a class="brand" routerLink="/estado">Dynamic Thermal Charge</a>
        <div class="links">
        <a routerLink="/estado" routerLinkActive="active">Estado</a>
        <a routerLink="/configuracion" routerLinkActive="active">Configuración</a>
        <a routerLink="/configuracion-sistema" routerLinkActive="active">Sistema</a>
        <a routerLink="/historico" routerLinkActive="active">Histórico</a>
        <a routerLink="/diagnostico" routerLinkActive="active">Diagnóstico</a>
        <a routerLink="/prueba-reles" routerLinkActive="active">Prueba de relés</a>
        @if (relay.view()?.session || relay.view()?.safety?.fault_latched || relay.id()) {
          <a class="relay-alert" routerLink="/prueba-reles">Prueba/recovery activa</a>
        }
        </div>
        <button type="button" (click)="signOut()">Cerrar sesión</button>
      </nav>
    }
    @if (topology(); as state) {
      @if (state.mode !== 'normal') {
        <div class="global-mode" role="alert">Modo {{ state.mode }}: configuración de solo lectura · {{ state.pending_events }} eventos pendientes</div>
      }
    }
    <router-outlet />
  `,
  styles: `
    nav {
      display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; align-items: center;
      padding: 0.75rem max(1rem, calc((100vw - 76rem) / 2)); border-bottom: 1px solid var(--border);
      background: var(--surface); position: sticky; top: 0; z-index: 10;
    }
    .brand { font-weight: 750; color: var(--ink); white-space: nowrap; }
    .links { display: flex; flex-wrap: wrap; gap: .25rem .8rem; }
    a { text-decoration: none; padding: 0.3rem 0; color: var(--primary); }
    a.active { font-weight: 700; border-bottom: 2px solid currentColor; }
    button { margin-left: auto; font: inherit; cursor: pointer; padding: 0.45rem 0.7rem; }
    .global-mode { padding: .65rem max(1rem, calc((100vw - 76rem) / 2)); background: #fff1c7; border-bottom: 2px solid var(--warning); }
    @media (max-width: 42rem) { .brand { width: 100%; } button { margin-left: 0; } }
  `,
})
export class App {
  readonly auth = inject(Auth);
  readonly relay = inject(RelayTestSession);
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  readonly topology = signal<import('./core/api.types').TopologyDto | null>(null);

  constructor() {
    // This initial read makes an externally-owned session or persistent latch
    // visible from every authenticated route.  It never renews a lease.
    if (this.auth.authenticated()) {
      this.api.topology().subscribe({ next: (state) => this.topology.set(state), error: () => undefined });
      this.api.relayTest(this.relay.credential()).subscribe({
        next: (view) => this.relay.observe(view),
        error: () => undefined,
      });
    }
  }

  signOut(): void {
    this.auth.signOut();
    this.relay.clear();
    void this.router.navigateByUrl('/acceso');
  }
}
