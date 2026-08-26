/**
 * The three fields whose mistake is paid for at the electrical panel.
 *
 * Only these ask for confirmation. Asking for everything teaches the operator to
 * confirm without reading, which is worse than not asking at all.
 */

export const ELECTRICAL_FIELDS = new Set([
  // A value too high overloads the consumer unit.
  'max_total_power_kw',
  // The wrong pin drives the wrong relay.
  'pin',
  // Inverting it leaves the relay closed at rest.
  'active_high',
]);

export function needsConfirmation(field: string): boolean {
  return ELECTRICAL_FIELDS.has(field);
}

export function confirmationText(field: string, value: string): string {
  switch (field) {
    case 'max_total_power_kw':
      return (
        `Vas a cambiar la potencia máxima simultánea a ${value} kW. Un valor ` +
        'demasiado alto sobrecarga el cuadro eléctrico. ¿Continuar?'
      );
    case 'pin':
      return (
        `Vas a cambiar el pin BCM a ${value}. Un pin equivocado gobierna el relé ` +
        'equivocado. ¿Continuar?'
      );
    case 'active_high':
      return (
        `Vas a cambiar el nivel activo a ${value}. Invertirlo puede dejar el relé ` +
        'cerrado en reposo. ¿Continuar?'
      );
    default:
      return `¿Cambiar ${field} a ${value}?`;
  }
}
