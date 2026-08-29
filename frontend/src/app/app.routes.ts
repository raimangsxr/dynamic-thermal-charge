import type { Routes } from '@angular/router';

import { requireCredential } from './core/auth.guard';
import { requireOnboarded } from './core/onboarding.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'inicio' },
  { path: 'inicio', loadComponent: () => import('./onboarding/onboarding').then((m) => m.Onboarding) },
  {
    path: 'acceso',
    loadComponent: () => import('./core/login/login').then((m) => m.Login),
  },
  {
    path: 'estado',
    canActivate: [requireOnboarded, requireCredential],
    loadComponent: () => import('./status/status').then((m) => m.Status),
  },
  {
    path: 'configuracion',
    canActivate: [requireOnboarded, requireCredential],
    loadComponent: () => import('./config/config').then((m) => m.Config),
  },
  {
    path: 'configuracion-sistema',
    canActivate: [requireOnboarded, requireCredential],
    loadComponent: () => import('./system-config/system-config').then((m) => m.SystemConfig),
  },
  {
    path: 'historico',
    canActivate: [requireOnboarded, requireCredential],
    loadComponent: () => import('./history/history').then((m) => m.History),
  },
  {
    path: 'diagnostico',
    canActivate: [requireOnboarded, requireCredential],
    loadComponent: () => import('./diagnostics/diagnostics').then((m) => m.Diagnostics),
  },
  { path: 'prueba-reles', canActivate: [requireOnboarded, requireCredential], loadComponent: () => import('./relay-test/relay-test').then((m) => m.RelayTest) },
  { path: '**', redirectTo: 'estado' },
];
