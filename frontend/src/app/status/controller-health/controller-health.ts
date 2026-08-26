/**
 * The controller's health, and the warning that the state may not be current.
 *
 * Four situations, deliberately distinguished (FR-012). "It never started" is not
 * "it stopped answering": one means the service is not running, the other means
 * it died or hung, and the operator checks different things.
 *
 * The two-controller warning is prominent on purpose (FR-013). Two processes
 * switching the same relays is an electrical hazard, and the worst possible
 * outcome is a panel that shows normality.
 */

import { Component, computed, input } from '@angular/core';

import type { ControllerHealthDto } from '../../core/api.types';
import { formatAge, formatInstant } from '../../shared/age/age';

interface Presentation {
  readonly heading: string;
  readonly detail: string;
  readonly check: string;
  readonly severity: 'ok' | 'warn' | 'alert';
}

@Component({
  selector: 'dtc-controller-health',
  template: `
    @if (health().multiple_controllers_suspected) {
      <div class="banner alert" role="alert">
        <strong>⚠ Parece haber más de un controlador en marcha</strong>
        <p>
          Dos procesos conmutando los mismos relés es un riesgo eléctrico.
          Comprueba el despliegue: debería haber exactamente un servicio
          <code>dynamic-thermal-charge</code> apuntando a esta base de datos.
        </p>
      </div>
    }

    <div class="banner {{ presentation().severity }}" [attr.data-liveness]="health().liveness">
      <strong>{{ presentation().heading }}</strong>
      <p>{{ presentation().detail }}</p>
      @if (presentation().check) {
        <p class="check">Comprueba: {{ presentation().check }}</p>
      }
      @if (!health().state_is_current) {
        <p class="warning">
          <strong>El estado que se muestra no es actual.</strong>
          Los valores de cada acumulador son el último dato conocido, no lo que
          está pasando ahora, y no se muestra potencia instantánea porque nadie
          puede confirmarla.
        </p>
      }
    </div>
  `,
  styles: `
    .banner { padding: 0.75rem 1rem; border-left: 4px solid; margin-bottom: 1rem; }
    .banner p { margin: 0.35rem 0 0; }
    /* Severity adds colour, but the heading and the text already say it. */
    .ok { border-color: #0a6b2d; background: #f2f9f4; }
    .warn { border-color: #7a4a00; background: #fdf7ee; }
    .alert { border-color: #a00; background: #fdf0f0; }
    .check { font-size: 0.9em; color: #444; }
    .warning { font-size: 0.95em; }
  `,
})
export class ControllerHealth {
  readonly health = input.required<ControllerHealthDto>();

  readonly presentation = computed<Presentation>(() => {
    const current = this.health();
    const age = formatAge(current.age_seconds);
    const seen = formatInstant(current.last_seen_at);

    switch (current.liveness) {
      case 'live':
        return {
          heading: 'El controlador responde con normalidad',
          detail: `Última señal ${age}. Arrancó ${formatInstant(current.started_at)}` +
            (current.driver_kind ? ` con salidas ${this.driverText(current.driver_kind)}.` : '.'),
          check: '',
          severity: 'ok',
        };
      case 'live_degraded':
        return {
          heading: 'El controlador responde, pero está degradado',
          detail:
            `Última señal ${age}. Sigue ejecutando su plan, pero no alcanza ` +
            'algo que necesita.',
          check: 'la base de datos, y el proveedor meteorológico si es remoto',
          severity: 'warn',
        };
      case 'stale':
        return {
          heading: 'No se sabe qué está pasando ahora',
          detail:
            `El controlador no da señales desde ${seen} (${age}). Puede estar ` +
            'parado o colgado.',
          check: 'que el servicio dynamic-thermal-charge esté en marcha',
          severity: 'alert',
        };
      case 'never_seen':
        return {
          heading: 'El controlador no ha arrancado nunca',
          detail:
            'Nunca ha publicado una señal de vida contra esta base de datos, así ' +
            'que no hay ningún estado que mostrar.',
          check:
            'que el servicio esté instalado y arrancado, y que apunte a esta ' +
            'misma base de datos',
          severity: 'alert',
        };
    }
  });

  private driverText(kind: 'simulated' | 'gpio'): string {
    return kind === 'gpio' ? 'reales (GPIO)' : 'simuladas';
  }
}
