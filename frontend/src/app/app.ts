import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { Auth } from './core/auth';
import { Api } from './core/api';
import { RelayTestSession } from './core/relay-test-session';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    @if (auth.authenticated()) {
      <nav>
        <a routerLink="/estado" routerLinkActive="active">Estado</a>
        <a routerLink="/configuracion" routerLinkActive="active">Configuración</a>
        <a routerLink="/historico" routerLinkActive="active">Histórico</a>
        <a routerLink="/prueba-reles" routerLinkActive="active">Prueba de relés</a>
        @if (relay.view()?.session || relay.view()?.safety?.fault_latched || relay.id()) {
          <a class="relay-alert" routerLink="/prueba-reles">Prueba/recovery activa</a>
        }
        <button type="button" (click)="signOut()">Cerrar sesión</button>
      </nav>
    }
    <router-outlet />
  `,
  styles: `
    nav {
      display: flex; flex-wrap: wrap; gap: 0.25rem 1rem; align-items: center;
      padding: 0.75rem 1rem; border-bottom: 1px solid #ddd;
    }
    a { text-decoration: none; padding: 0.25rem 0; color: #05408a; }
    a.active { font-weight: 700; border-bottom: 2px solid currentColor; }
    button { margin-left: auto; font: inherit; cursor: pointer; padding: 0.3rem 0.6rem; }
  `,
})
export class App {
  readonly auth = inject(Auth);
  readonly relay = inject(RelayTestSession);
  private readonly api = inject(Api);
  private readonly router = inject(Router);

  constructor() {
    // This initial read makes an externally-owned session or persistent latch
    // visible from every authenticated route.  It never renews a lease.
    if (this.auth.authenticated()) {
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
