/** No view shows anything about the installation without a credential (FR-001). */

import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';

import { Auth } from './auth';

export const requireCredential: CanActivateFn = () => {
  const auth = inject(Auth);
  if (auth.authenticated()) {
    return true;
  }
  return inject(Router).createUrlTree(['/acceso']);
};
