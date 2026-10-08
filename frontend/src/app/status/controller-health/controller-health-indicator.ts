import { Component, computed, input, signal } from '@angular/core';

import type { ControllerHealthDto } from '../../core/api.types';
import { describeControllerHealth, type ControllerHealthPresentation } from './controller-health';

type IndicatorColor = 'green' | 'yellow' | 'red';

interface IndicatorState {
  readonly color: IndicatorColor;
  readonly label: string;
}

@Component({
  selector: 'dtc-controller-health-indicator',
  template: `
    <div
      class="health-indicator"
      [class.health-indicator-open]="detailsVisible()"
      [attr.data-health-state]="state().color"
      [attr.data-liveness]="readFailed() ? 'read_error' : (health()?.liveness ?? null)"
      data-testid="controller-health-indicator"
      (mouseenter)="showDetails()"
      (mouseleave)="hideDetails()"
      (focusin)="handleFocusIn()"
      (focusout)="handleFocusOut()"
    >
      <button
        class="health-indicator-trigger"
        type="button"
        [class.health-green]="state().color === 'green'"
        [class.health-yellow]="state().color === 'yellow'"
        [class.health-red]="state().color === 'red'"
        [attr.aria-label]="state().label"
        [attr.aria-expanded]="detailsVisible()"
        aria-controls="controller-health-detail"
        [attr.aria-describedby]="detailsVisible() ? 'controller-health-detail' : null"
        data-testid="controller-health-trigger"
        (click)="activateDetails()"
        (focus)="handleFocusIn()"
        (mouseenter)="showDetails()"
        (blur)="handleFocusOut()"
        (keydown.enter)="activateDetails($event)"
        (keydown.space)="activateDetails($event)"
      >
        <span class="health-indicator-dot" aria-hidden="true"></span>
        <span>{{ state().label }}</span>
      </button>

      <div
        id="controller-health-detail"
        class="health-indicator-details"
        [class.health-indicator-details-visible]="detailsVisible()"
        [hidden]="!detailsVisible()"
        [attr.aria-hidden]="!detailsVisible()"
        role="tooltip"
        data-testid="controller-health-detail"
      >
        @for (line of detailLines(); track $index) {
          <p>{{ line }}</p>
        }
      </div>
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .health-indicator {
      position: relative;
      display: inline-flex;
      max-width: min(30rem, 70vw);
    }
    .health-indicator-trigger {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      min-height: 2.25rem;
      max-width: 100%;
      padding: 0.35rem 0.7rem;
      border: 1px solid;
      border-radius: 999px;
      background: var(--surface, #fff);
      font: inherit;
      font-size: 0.82rem;
      font-weight: 700;
      line-height: 1.2;
      text-align: left;
      cursor: pointer;
    }
    .health-indicator-trigger:focus-visible {
      outline: 3px solid color-mix(in srgb, currentColor 35%, transparent);
      outline-offset: 2px;
    }
    .health-indicator-dot {
      width: 0.65rem;
      height: 0.65rem;
      flex: 0 0 auto;
      border-radius: 50%;
      background: currentColor;
    }
    .health-green {
      border-color: #0a6b2d;
      color: #0a6b2d;
    }
    .health-yellow {
      border-color: #7a4a00;
      color: #7a4a00;
    }
    .health-red {
      border-color: #a00;
      color: #a00;
    }
    .health-indicator-details {
      position: absolute;
      z-index: 2;
      top: calc(100% + 0.45rem);
      right: 0;
      width: min(30rem, 82vw);
      padding: 0.75rem 0.85rem;
      border: 1px solid var(--border, #d9dee8);
      border-radius: 0.65rem;
      background: var(--surface, #fff);
      box-shadow: 0 8px 24px #17203326;
      color: var(--ink, #172033);
      opacity: 0;
      pointer-events: none;
      transform: translateY(-0.2rem);
      transition:
        opacity 120ms ease,
        transform 120ms ease;
    }
    .health-indicator-details[hidden] {
      display: none;
    }
    .health-indicator-details-visible {
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }
    .health-indicator-details p {
      margin: 0.35rem 0 0;
      line-height: 1.4;
    }
    @media (prefers-reduced-motion: reduce) {
      .health-indicator-details {
        transition: none;
      }
    }
  `,
})
export class ControllerHealthIndicator {
  readonly health = input<ControllerHealthDto | null>(null);
  readonly readFailed = input(false);
  readonly detailsVisible = signal(false);
  private triggerFocused = false;
  private activationHeld = false;

  readonly state = computed<IndicatorState>(() => {
    if (this.readFailed()) {
      return { color: 'red', label: 'Controlador: estado no confirmado' };
    }

    const current = this.health();
    if (current === null) {
      return { color: 'red', label: 'Controlador: estado no confirmado' };
    }

    switch (current.liveness) {
      case 'live':
        if (current.multiple_controllers_suspected) {
          return { color: 'yellow', label: 'Controlador: varios sospechados' };
        }
        return { color: 'green', label: 'Controlador: estable' };
      case 'live_degraded':
        return { color: 'yellow', label: 'Controlador: degradado' };
      case 'stale':
        return { color: 'red', label: 'Controlador: sin señal actual' };
      case 'never_seen':
        return { color: 'red', label: 'Controlador: nunca visto' };
    }
  });

  readonly detailLines = computed(() => {
    const current = this.health();
    if (this.readFailed()) {
      const lines = current === null ? [] : this.healthDetailLines(current);
      lines.unshift('La lectura ha fallado: no se puede confirmar el estado actual del controlador.');
      if (current !== null) {
        lines.push('La vista conserva la última lectura como información no actual.');
      }
      return lines;
    }

    if (current === null) {
      return ['No se puede confirmar el estado actual del controlador.'];
    }

    return this.healthDetailLines(current);
  });

  showDetails(event?: Event): void {
    event?.preventDefault();
    this.detailsVisible.set(true);
  }

  activateDetails(event?: Event): void {
    this.activationHeld = true;
    this.showDetails(event);
  }

  handleFocusIn(): void {
    this.triggerFocused = true;
    this.showDetails();
  }

  handleFocusOut(): void {
    this.triggerFocused = false;
    this.activationHeld = false;
    this.detailsVisible.set(false);
  }

  hideDetails(): void {
    if (this.triggerFocused || this.activationHeld) return;
    this.detailsVisible.set(false);
  }

  private healthDetailLines(current: ControllerHealthDto): string[] {
    const presentation = describeControllerHealth(current);
    const lines = this.presentationLines(presentation);
    if (current.multiple_controllers_suspected) {
      lines.push(
        'Parece haber más de un controlador en marcha. Dos procesos conmutando los mismos relés es un riesgo eléctrico; comprueba el despliegue.',
      );
    }
    if (!current.state_is_current) {
      lines.push(
        'El estado que se muestra no es actual: los valores son el último dato conocido y no se muestra potencia instantánea porque nadie puede confirmarla.',
      );
    }
    return lines;
  }

  private presentationLines(presentation: ControllerHealthPresentation): string[] {
    const lines = [presentation.heading, presentation.detail];
    if (presentation.check) {
      lines.push(`Comprueba: ${presentation.check}.`);
    }
    return lines;
  }
}
