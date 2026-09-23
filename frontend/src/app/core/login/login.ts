/** The sign-in screen. Nothing about the installation is shown until the
 *  credential is in place (FR-001). */

import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { Api } from '../api';
import { Auth } from '../auth';

@Component({
  selector: 'dtc-login',
  imports: [FormsModule],
  template: `
    <main class="login">
      <h1>Dynamic Thermal Charge</h1>
      <p class="hint">
        Introduce la credencial de la API. Es el valor de
        <code>DTC_API_TOKEN</code> en el dispositivo.
      </p>
      <form (submit)="submit($event)">
        <label for="token">Credencial</label>
        <input
          id="token"
          name="token"
          type="password"
          autocomplete="current-password"
          [(ngModel)]="value"
          [disabled]="busy()"
          required
        />
        @if (message() || auth.sessionExpired()) {
          <p class="error" role="alert">{{ message() || 'La sesión ya no es válida. Introduce la credencial de nuevo.' }}</p>
        }
        <button type="submit" [disabled]="busy()" [attr.aria-busy]="busy()">{{ busy() ? 'Comprobando…' : 'Entrar' }}</button>
      </form>
      <p class="hint small">
        Se recuerda mientras esta pestaña esté abierta y se olvida al cerrarla.
      </p>
    </main>
  `,
  styles: `
    .login { max-width: 26rem; margin: 4rem auto; padding: 0 1rem; }
    form { display: grid; gap: 0.5rem; }
    input { padding: 0.5rem; font: inherit; }
    button { padding: 0.6rem; font: inherit; cursor: pointer; }
    .hint { color: #555; }
    .small { font-size: 0.85rem; }
    .error { color: #a00; font-weight: 600; }
  `,
})
export class Login {
  private readonly api = inject(Api);
  readonly auth = inject(Auth);
  private readonly router = inject(Router);

  value = '';
  readonly message = signal('');
  readonly busy = signal(false);

  submit(event: Event): void {
    event.preventDefault();
    if (this.value.trim().length === 0) {
      // Deliberately says nothing about what a valid credential looks like.
      this.message.set('Introduce la credencial.');
      return;
    }
    this.message.set('');
    this.busy.set(true);
    const token = this.value.trim();
    this.api.authenticate(token).subscribe({
      next: () => {
        this.auth.signIn(token);
        this.value = '';
        this.busy.set(false);
        void this.router.navigateByUrl('/estado');
      },
      error: () => {
        this.value = '';
        this.busy.set(false);
        this.message.set('La credencial no es válida.');
      },
    });
  }
}
