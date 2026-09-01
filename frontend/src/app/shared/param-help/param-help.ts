import { Component, computed, input, signal } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

import { paramHelpText } from '../../core/param-help-text';

@Component({
  selector: 'dtc-param-help',
  imports: [MatIconModule],
  template: `
    <span
      class="param-help"
      (mouseenter)="open()"
      (mouseleave)="close()"
      (focusin)="open()"
      (focusout)="close()"
    >
      <button
        type="button"
        class="param-help-trigger"
        [attr.aria-label]="ariaLabel()"
        [attr.aria-expanded]="visible()"
        data-testid="param-help-trigger"
      >
        <mat-icon aria-hidden="true">help_outline</mat-icon>
      </button>
      @if (visible()) {
        <div class="param-help-popup" role="tooltip" [attr.id]="popupId()">{{ text() }}</div>
      }
    </span>
  `,
  styleUrl: './param-help.css',
})
export class ParamHelp {
  readonly field = input.required<string>();
  readonly section = input<string | undefined>(undefined);
  readonly label = input<string | undefined>(undefined);

  readonly visible = signal(false);
  readonly text = computed(() => paramHelpText(this.field(), this.section()));
  readonly ariaLabel = computed(() => `Ayuda: ${this.label() ?? this.field()}`);
  readonly popupId = computed(() => `param-help-${this.section() ?? 'config'}-${this.field()}`);

  open(): void { this.visible.set(true); }
  close(): void { this.visible.set(false); }
}
