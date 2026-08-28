import type { Routes } from '@angular/router';

import { requireCredential } from './core/auth.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'estado' },
  {
    path: 'acceso',
    loadComponent: () => import('./core/login/login').then((m) => m.Login),
  },
  {
    path: 'estado',
    canActivate: [requireCredential],
    loadComponent: () => import('./status/status').then((m) => m.Status),
  },
  {
    path: 'configuracion',
    canActivate: [requireCredential],
    loadComponent: () => import('./config/config').then((m) => m.Config),
  },
  {
    path: 'historico',
    canActivate: [requireCredential],
    loadComponent: () => import('./history/history').then((m) => m.History),
  },
  {
    path: 'diagnostico',
    canActivate: [requireCredential],
    loadComponent: () => import('./diagnostics/diagnostics').then((m) => m.Diagnostics),
  },
  { path: 'prueba-reles', canActivate: [requireCredential], loadComponent: () => import('./relay-test/relay-test').then((m) => m.RelayTest) },
  { path: '**', redirectTo: 'estado' },
];
