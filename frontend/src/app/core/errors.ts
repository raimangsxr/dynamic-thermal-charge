/**
 * Every API error code, translated into something the operator can act on.
 *
 * The union of codes is closed, so a new code added to the API becomes a compile
 * error here rather than falling through to a generic message.
 *
 * The two schema rows matter most. The panel CANNOT fix a schema problem, and
 * saying so explicitly stops the operator hunting for a button that does not
 * exist.
 */

import type { ApiErrorCode, ApiErrorDto } from './api.types';

export interface Explained {
  /** One line, for a heading or a banner. */
  readonly title: string;
  /** What to do about it. Empty when there is nothing to do. */
  readonly action: string;
  /** True when the operator has to do something on the device itself. */
  readonly onDevice: boolean;
  /** True when the message belongs next to a form field rather than in a banner. */
  readonly fieldScoped: boolean;
}

const TABLE: Record<ApiErrorCode, Omit<Explained, 'action'> & { action: string }> = {
  unauthorized: {
    title: 'La credencial no es válida o ha caducado',
    action: 'Introdúcela de nuevo.',
    onDevice: false,
    fieldScoped: false,
  },
  not_found: {
    title: 'Eso no existe',
    action: '',
    onDevice: false,
    fieldScoped: true,
  },
  already_exists: {
    title: 'Ese identificador ya está en uso',
    action: 'Elige otro.',
    onDevice: false,
    fieldScoped: true,
  },
  config_conflict: {
    title: 'La configuración cambió mientras editabas',
    action: 'Vuelve a leerla y repite el cambio. No se ha sobrescrito nada.',
    onDevice: false,
    fieldScoped: false,
  },
  validation_failed: {
    title: 'El valor no es válido',
    action: 'Corrígelo. No se ha cambiado nada.',
    onDevice: false,
    fieldScoped: true,
  },
  secret_rejected: {
    title: 'Eso parece una credencial',
    action:
      'Los secretos no se guardan en la configuración: se sirven por variable ' +
      'de entorno en el dispositivo.',
    onDevice: false,
    fieldScoped: true,
  },
  bad_request: {
    title: 'La consulta no es válida',
    action: 'Revisa el filtro o el rango de fechas.',
    onDevice: false,
    fieldScoped: true,
  },
  no_configuration: {
    title: 'La base de datos no tiene ninguna instalación',
    // The panel cannot seed it: doing so from an HTTP request would let a client
    // create configuration out of nothing.
    action: 'Ejecuta «dynamic-thermal-charge db init» en el dispositivo. El panel no puede hacerlo.',
    onDevice: true,
    fieldScoped: false,
  },
  schema_unusable: {
    title: 'La base de datos necesita atención',
    // Migrating from a browser would let a client alter the database structure.
    action:
      'Ejecuta «dynamic-thermal-charge db upgrade» en el dispositivo, o actualiza el servicio si ' +
      'el esquema es más nuevo que él. El panel no puede migrar la base de datos.',
    onDevice: true,
    fieldScoped: false,
  },
  store_unavailable: {
    title: 'La base de datos no responde',
    action:
      'Si es remota, comprueba la red. El controlador sigue ejecutando su plan ' +
      'mientras se recupera.',
    onDevice: true,
    fieldScoped: false,
  },
  relay_test_active: {
    title: 'La configuración está protegida por una prueba de relés',
    action: 'Abre la prueba de relés para terminarla antes de cambiar el cableado.',
    onDevice: false,
    fieldScoped: false,
  },
  relay_test_fault_latched: {
    title: 'La recuperación de seguridad sigue pendiente',
    action: 'Espera a que el controlador confirme el apagado completo.',
    onDevice: true,
    fieldScoped: false,
  },
  degraded_mode: {
    title: 'El sistema está en modo degradado',
    action: 'La configuración es de solo lectura hasta recuperar la base canónica.',
    onDevice: true,
    fieldScoped: false,
  },
  operation_in_progress: {
    title: 'Ya hay una operación en curso',
    action: 'Espera a que termine antes de iniciar otra.',
    onDevice: false,
    fieldScoped: false,
  },
  connection_test_failed: {
    title: 'La prueba de conexión ha fallado',
    action: 'Revisa host, TLS, credenciales y permisos.',
    onDevice: false,
    fieldScoped: false,
  },
  internal_error: {
    title: 'La petición no se pudo completar',
    action: 'Consulta los registros del servicio en el dispositivo.',
    onDevice: true,
    fieldScoped: false,
  },
};

/** Shown when the API cannot be reached at all: there is no code to translate. */
export const UNREACHABLE: Explained = {
  title: 'No se puede contactar con la API',
  action:
    'Se muestra la última información conocida, que ya no es actual. Comprueba ' +
    'que el servicio de la API está en marcha.',
  onDevice: true,
  fieldScoped: false,
};

export function explain(error: ApiErrorDto | null): Explained {
  if (error === null) {
    return UNREACHABLE;
  }
  const entry = TABLE[error.code];
  if (entry === undefined) {
    // A code the API added and this table does not know. Say so honestly rather
    // than inventing an explanation.
    return {
      title: 'La API devolvió un error que este panel no reconoce',
      action: 'Consulta los registros del servicio en el dispositivo.',
      onDevice: true,
      fieldScoped: false,
    };
  }
  return entry;
}

/** The message to show, preferring the API's own words when it named a field. */
export function messageFor(error: ApiErrorDto): string {
  const explained = explain(error);
  if (explained.fieldScoped && error.message) {
    return error.message;
  }
  return explained.title;
}

export function allCodes(): ApiErrorCode[] {
  return Object.keys(TABLE) as ApiErrorCode[];
}
