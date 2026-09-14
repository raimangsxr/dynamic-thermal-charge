import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MAT_SNACK_BAR_DATA, MatSnackBar, MatSnackBarModule, MatSnackBarRef } from '@angular/material/snack-bar';
import { Component, inject, Injectable } from '@angular/core';

export type FeedbackKind = 'success' | 'error' | 'warning' | 'info';

export interface FeedbackData {
  readonly kind: FeedbackKind;
  readonly message: string;
}

const FEEDBACK_LABELS: Record<FeedbackKind, string> = {
  success: 'Correcto',
  error: 'Error',
  warning: 'Aviso',
  info: 'Información',
};

const FEEDBACK_ICONS: Record<FeedbackKind, string> = {
  success: 'check_circle',
  error: 'error',
  warning: 'warning',
  info: 'info',
};

@Component({
  selector: 'dtc-feedback-snackbar',
  imports: [MatButtonModule, MatIconModule, MatSnackBarModule],
  template: `
    <div class="dtc-feedback-snackbar-content" [attr.data-feedback-type]="data.kind" [attr.role]="data.kind === 'error' ? 'alert' : 'status'">
      <mat-icon aria-hidden="true">{{ icon }}</mat-icon>
      <span>{{ data.message }}</span>
      <button mat-button type="button" (click)="dismiss()" aria-label="Cerrar notificación">Cerrar</button>
    </div>
  `,
  styles: `
    :host { display: block; }
    .dtc-feedback-snackbar-content { display: flex; align-items: center; gap: .7rem; min-width: min(32rem, calc(100vw - 2rem)); max-width: min(48rem, calc(100vw - 2rem)); }
    .dtc-feedback-snackbar-content mat-icon { flex: 0 0 auto; }
    .dtc-feedback-snackbar-content span { flex: 1 1 auto; min-width: 0; line-height: 1.35; }
    .dtc-feedback-snackbar-content button { flex: 0 0 auto; color: inherit; }
  `,
})
export class FeedbackSnackbar {
  readonly data = inject<FeedbackData>(MAT_SNACK_BAR_DATA);
  private readonly snackBarRef = inject(MatSnackBarRef<FeedbackSnackbar>);

  get icon(): string {
    return FEEDBACK_ICONS[this.data.kind];
  }

  dismiss(): void {
    this.snackBarRef.dismiss();
  }
}

@Injectable({ providedIn: 'root' })
export class UiFeedback {
  private readonly snackBar = inject(MatSnackBar);

  show(kind: FeedbackKind, message: string): MatSnackBarRef<FeedbackSnackbar> {
    return this.snackBar.openFromComponent(FeedbackSnackbar, {
      data: { kind, message },
      duration: 6000,
      horizontalPosition: 'center',
      verticalPosition: 'top',
      panelClass: ['dtc-snackbar-container', `dtc-snackbar-${kind}`],
      announcementMessage: `${FEEDBACK_LABELS[kind]}: ${message}`,
      politeness: kind === 'error' ? 'assertive' : 'polite',
    });
  }

  success(message: string): MatSnackBarRef<FeedbackSnackbar> {
    return this.show('success', message);
  }

  error(message: string): MatSnackBarRef<FeedbackSnackbar> {
    return this.show('error', message);
  }

  warning(message: string): MatSnackBarRef<FeedbackSnackbar> {
    return this.show('warning', message);
  }

  info(message: string): MatSnackBarRef<FeedbackSnackbar> {
    return this.show('info', message);
  }
}
