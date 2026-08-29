import type { Routes } from '@angular/router';

import { requireCredential } from './core/auth.guard';
import { requireOnboarded } from './core/onboarding.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'estado' },
  { path: 'inicio', loadComponent: () => import('./onboarding/onboarding').then((m) => m.Onboarding) },
  {
    path: 'login',
    loadComponent: () => import('./core/login/login').then((m) => m.Login),
  },
  {
    path: 'estado',
    canActivate: [requireCredential, requireOnboarded],
    loadComponent: () => import('./status/status').then((m) => m.Status),
  },
  {
    path: 'configuracion',
    canActivate: [requireCredential, requireOnboarded],
    loadComponent: () => import('./config/config').then((m) => m.Config),
  },
  {
    path: 'configuracion-sistema',
    canActivate: [requireCredential, requireOnboarded],
    loadComponent: () => import('./system-config/system-config').then((m) => m.SystemConfig),
  },
  {
    path: 'historico',
    canActivate: [requireCredential, requireOnboarded],
    loadComponent: () => import('./history/history').then((m) => m.History),
  },
  {
    path: 'diagnostico',
    canActivate: [requireCredential, requireOnboarded],
    loadComponent: () => import('./diagnostics/diagnostics').then((m) => m.Diagnostics),
  },
  { path: 'prueba-reles', canActivate: [requireCredential, requireOnboarded], loadComponent: () => import('./relay-test/relay-test').then((m) => m.RelayTest) },
  { path: '**', redirectTo: 'estado' },
];
