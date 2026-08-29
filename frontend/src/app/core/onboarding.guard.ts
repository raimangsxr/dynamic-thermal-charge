import { inject } from '@angular/core';
import { Router, type CanActivateFn } from '@angular/router';
import { catchError, map, of } from 'rxjs';

import { Api } from './api';

export const requireOnboarded: CanActivateFn = () => {
  const api = inject(Api);
  const router = inject(Router);
  return api.onboardingStatus().pipe(
    map((status) => status.required ? router.createUrlTree(['/inicio']) : true),
    catchError(() => of(router.createUrlTree(['/inicio']))),
  );
};
