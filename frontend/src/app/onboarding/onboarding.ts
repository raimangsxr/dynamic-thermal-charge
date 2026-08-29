import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { Api } from '../core/api';
import { Auth } from '../core/auth';

@Component({
  selector: 'dtc-onboarding',
  imports: [FormsModule],
  templateUrl: './onboarding.html',
  styleUrl: './onboarding.css',
})
export class Onboarding {
  private readonly api = inject(Api);
  private readonly auth = inject(Auth);
  private readonly router = inject(Router);
  credential = '';
  administratorToken = '';
  confirmation = '';
  readonly required = signal<boolean | null>(null);
  readonly error = signal('');
  readonly busy = signal(false);

  constructor() {
    this.api.onboardingStatus().subscribe({
      next: (status) => this.required.set(status.required),
      error: () => this.error.set('No se pudo consultar el estado de inicialización.'),
    });
  }

  complete(): void {
    this.error.set('');
    if (this.administratorToken.length < 32 || this.administratorToken !== this.confirmation) {
      this.error.set('El token administrativo debe tener al menos 32 caracteres y coincidir.');
      return;
    }
    this.busy.set(true);
    this.api.completeOnboarding(this.credential, this.administratorToken).subscribe({
      next: () => {
        const token = this.administratorToken;
        this.credential = '';
        this.administratorToken = '';
        this.confirmation = '';
        this.auth.signIn(token);
        void this.router.navigateByUrl('/configuracion-sistema');
      },
      error: (error: unknown) => {
        this.busy.set(false);
        this.error.set(error instanceof HttpErrorResponse && error.status === 401
          ? 'La credencial de inicialización no es válida, ha caducado o ya fue usada.'
          : 'No se pudo completar la inicialización. No se guardó el token.');
      },
    });
  }
}
