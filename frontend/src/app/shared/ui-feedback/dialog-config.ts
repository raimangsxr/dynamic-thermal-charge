import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogConfig, MatDialogModule } from '@angular/material/dialog';
import { Component, inject } from '@angular/core';

export interface ConfirmDialogData {
  readonly title: string;
  readonly message: string;
  readonly confirmLabel: string;
}

export const CONTENT_DIALOG_CONFIG = {
  width: 'min(98vw, 192rem)',
  maxWidth: '98vw',
  panelClass: 'dtc-content-dialog',
  ariaModal: true,
} satisfies Pick<MatDialogConfig<unknown>, 'width' | 'maxWidth' | 'panelClass' | 'ariaModal'>;

export const CONFIRM_DIALOG_CONFIG = {
  width: 'min(28rem, calc(100vw - 2rem))',
  maxWidth: 'calc(100vw - 2rem)',
  panelClass: 'dtc-confirm-dialog',
  ariaModal: true,
} satisfies Pick<MatDialogConfig<unknown>, 'width' | 'maxWidth' | 'panelClass' | 'ariaModal'>;

@Component({
  selector: 'dtc-confirm-dialog',
  imports: [MatButtonModule, MatDialogModule],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <mat-dialog-content>{{ data.message }}</mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="false" data-testid="confirm-cancel">Cancelar</button>
      <button mat-flat-button color="warn" type="button" [mat-dialog-close]="true" data-testid="confirm-delete">{{ data.confirmLabel }}</button>
    </mat-dialog-actions>
  `,
})
export class ConfirmDialog {
  readonly data = inject<ConfirmDialogData>(MAT_DIALOG_DATA);
}
