import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSidenav, MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { Auth } from './core/auth';
import { Api } from './core/api';
import { RelayTestSession } from './core/relay-test-session';

declare const __APP_VERSION__: string;

@Component({
  selector: 'app-root',
  imports: [
    RouterOutlet, RouterLink, RouterLinkActive, MatButtonModule, MatIconModule,
    MatSidenavModule, MatToolbarModule,
  ],
  template: `
    @if (auth.authenticated()) {
      <mat-sidenav-container class="shell">
        <mat-sidenav #drawer class="navigation" [mode]="mobile() ? 'over' : 'side'" [opened]="!mobile()" aria-label="Navegación principal">
          <div class="navigation-header">
            <a class="brand" routerLink="/estado" (click)="closeDrawer(drawer)">
              <span class="brand-mark" aria-hidden="true">DTC</span>
              <span>Dynamic Thermal Charge</span>
              <span class="version" aria-label="Versión {{ version }}">v{{ version }}</span>
            </a>
          </div>
          <nav class="nav-list" aria-label="Secciones">
            <a class="nav-link" routerLink="/estado" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: true }" (click)="closeDrawer(drawer)">
              <mat-icon aria-hidden="true">dashboard</mat-icon><span>Estado</span>
            </a>
            <a class="nav-link" routerLink="/planificacion" routerLinkActive="active" (click)="closeDrawer(drawer)">
              <mat-icon aria-hidden="true">schedule</mat-icon><span>Planificación</span>
            </a>
            <a class="nav-link" routerLink="/configuracion" routerLinkActive="active" (click)="closeDrawer(drawer)">
              <mat-icon aria-hidden="true">tune</mat-icon><span>Configuración</span>
            </a>
            <a class="nav-link" routerLink="/configuracion-sistema" routerLinkActive="active" (click)="closeDrawer(drawer)">
              <mat-icon aria-hidden="true">settings</mat-icon><span>Sistema</span>
            </a>
            <a class="nav-link" routerLink="/historico" routerLinkActive="active" (click)="closeDrawer(drawer)">
              <mat-icon aria-hidden="true">history</mat-icon><span>Histórico</span>
            </a>
            <a class="nav-link" routerLink="/diagnostico" routerLinkActive="active" (click)="closeDrawer(drawer)">
              <mat-icon aria-hidden="true">medical_services</mat-icon><span>Diagnóstico</span>
            </a>
            <a class="nav-link" routerLink="/prueba-reles" routerLinkActive="active" (click)="closeDrawer(drawer)">
              <mat-icon aria-hidden="true">electrical_services</mat-icon><span>Prueba de relés</span>
            </a>
            @if (relay.view()?.session || relay.view()?.safety?.fault_latched || relay.id()) {
              <a class="nav-link relay-alert" routerLink="/prueba-reles" (click)="closeDrawer(drawer)">
                <mat-icon aria-hidden="true">warning</mat-icon><span>Prueba/recovery activa</span>
              </a>
            }
          </nav>
        </mat-sidenav>

        <mat-sidenav-content>
          <mat-toolbar class="app-toolbar" color="primary">
            @if (mobile()) {
              <button mat-icon-button type="button" class="menu-button" (click)="drawer.toggle()" aria-label="Abrir navegación principal">
                <mat-icon aria-hidden="true">menu</mat-icon>
              </button>
            }
            <span class="toolbar-title">Panel de control</span><span class="toolbar-spacer"></span>
            <button mat-icon-button type="button" (click)="signOut()" aria-label="Cerrar sesión" data-testid="logout">
              <mat-icon aria-hidden="true">logout</mat-icon>
            </button>
          </mat-toolbar>

          @if (topology(); as state) {
            @if (state.mode !== 'normal') {
              <div class="global-mode" role="alert">Modo {{ state.mode }}: configuración de solo lectura · {{ state.pending_events }} eventos pendientes</div>
            }
          }
          <main class="page-content"><router-outlet /></main>
        </mat-sidenav-content>
      </mat-sidenav-container>
    } @else {
      <router-outlet />
    }
  `,
  styles: `
    :host { display: block; min-height: 100dvh; }
    .shell { min-height: 100dvh; background: var(--canvas); }
    .navigation { width: 17rem; border-right: 1px solid var(--border); background: var(--surface); }
    .navigation-header { padding: 1.25rem 1rem .9rem; border-bottom: 1px solid var(--border); }
    .brand { display: grid; grid-template-columns: auto 1fr; align-items: center; column-gap: .65rem; color: var(--ink); text-decoration: none; font-weight: 700; line-height: 1.2; }
    .brand-mark { display: grid; place-items: center; width: 2.25rem; height: 2.25rem; border-radius: .7rem; background: var(--primary); color: #fff; font-size: .72rem; letter-spacing: .04em; }
    .version { grid-column: 2; color: var(--muted); font-size: .72rem; font-weight: 500; margin-top: -.35rem; }
    .nav-list { display: grid; gap: .15rem; padding: .65rem .5rem; }
    .nav-link { display: flex; align-items: center; gap: .8rem; min-height: 3rem; padding: .6rem .85rem; border-radius: .5rem; color: var(--ink); text-decoration: none; }
    .nav-link mat-icon { color: var(--muted); }
    .nav-link.active { background: color-mix(in srgb, var(--primary) 12%, transparent); color: var(--primary); font-weight: 700; }
    .nav-link.active mat-icon { color: var(--primary); }
    .nav-link.relay-alert { color: var(--danger); }
    .app-toolbar { position: sticky; top: 0; z-index: 10; box-shadow: 0 1px 5px #15223a20; }
    .menu-button { margin-right: .5rem; }
    .toolbar-title { font-size: 1rem; font-weight: 500; }
    .toolbar-spacer { flex: 1 1 auto; }
    .page-content { min-width: 0; }
    .global-mode { padding: .65rem max(1rem, calc((100vw - 76rem) / 2)); background: #fff1c7; border-bottom: 2px solid var(--warning); }
    @media (max-width: 47.99rem) { .navigation { width: min(17rem, 86vw); } }
  `,
})
export class App {
  readonly version = __APP_VERSION__;
  readonly auth = inject(Auth);
  readonly relay = inject(RelayTestSession);
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly mediaQuery = globalThis.matchMedia?.('(max-width: 47.99rem)') ?? null;
  readonly mobile = signal(false);
  readonly topology = signal<import('./core/api.types').TopologyDto | null>(null);

  constructor() {
    if (this.mediaQuery) {
      this.mobile.set(this.mediaQuery.matches);
      const updateViewport = (event: MediaQueryListEvent) => this.mobile.set(event.matches);
      this.mediaQuery.addEventListener('change', updateViewport);
      this.destroyRef.onDestroy(() => this.mediaQuery?.removeEventListener('change', updateViewport));
    }

    // This initial read makes an externally-owned session or persistent latch
    // visible from every authenticated route. It never renews a lease.
    if (this.auth.authenticated()) {
      this.api.topology().subscribe({ next: (state) => this.topology.set(state), error: () => undefined });
      this.api.relayTest(this.relay.credential()).subscribe({ next: (view) => this.relay.observe(view), error: () => undefined });
    }
  }

  closeDrawer(drawer: MatSidenav): void {
    if (this.mobile()) void drawer.close();
  }

  signOut(): void {
    this.auth.signOut();
    this.relay.clear();
    this.topology.set(null);
    void this.router.navigateByUrl('/login');
  }
}
