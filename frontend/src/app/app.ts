import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { Auth } from './core/auth';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    @if (auth.authenticated()) {
      <nav>
        <a routerLink="/estado" routerLinkActive="active">Estado</a>
        <a routerLink="/configuracion" routerLinkActive="active">Configuración</a>
        <a routerLink="/historico" routerLinkActive="active">Histórico</a>
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
  private readonly router = inject(Router);

  signOut(): void {
    this.auth.signOut();
    void this.router.navigateByUrl('/acceso');
  }
}
