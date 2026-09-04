/** Descripciones detalladas para iconos de ayuda en formularios de configuración. */

const INSTALLATION: Record<string, string> = {
  max_total_power_kw:
    'Potencia máxima que puede consumir la instalación en un intervalo. El planificador legado y la vista de estado usan este límite; el optimizador automático usa contracted_power_w en Sistema → planning.',
  slot_minutes:
    'Duración de cada intervalo del plan de carga (minutos). Alinea restricciones, slots del plan automático y el planificador legado.',
  retention_days:
    'Días que se conservan planes, previsiones y transiciones en el histórico antes del recorte automático. «none» desactiva el recorte por antigüedad.',
  poll_seconds:
    'Intervalo entre ciclos del controlador que lee telemetría, evalúa el plan activo y publica estados.',
  log_level:
    'Nivel mínimo de los eventos del controlador guardados en la base de datos y visibles en Diagnóstico.',
  indoor_max_age_minutes:
    'Antigüedad máxima aceptada de una lectura de temperatura interior MQTT antes de considerarla obsoleta.',
  indoor_min_plausible_c:
    'Temperatura interior mínima plausible (°C). Lecturas por debajo se descartan para evitar datos erróneos.',
  indoor_max_plausible_c:
    'Temperatura interior máxima plausible (°C). Lecturas por encima se descartan para evitar datos erróneos.',
};

const HEATER: Record<string, string> = {
  id:
    'Identificador único del acumulador en la configuración, histórico y planificación. No se puede cambiar tras la creación.',
  name: 'Nombre visible en el panel para este acumulador.',
  model: 'Modelo o referencia del equipo; solo informativo.',
  power_kw:
    'Potencia nominal del resistivo (kW). El optimizador usa este valor para calcular cuánta energía puede cargar en cada intervalo.',
  full_charge_hours:
    'Horas necesarias a potencia plena para llenar el acumulador. Define la capacidad energética (kWh) junto con la potencia.',
  target_charge:
    'Fracción de carga deseada (0–1) que el planificador legado intenta alcanzar al final de la ventana de carga.',
  reserve_percent:
    'Margen multiplicativo (%) sobre la demanda estimada del modelo degree-hours. Aumenta la energía objetivo sin cambiar el factor base.',
  demand_factor:
    'Factor multiplicativo de la demanda térmica estimada. Valores mayores planifican más carga; debe ser positivo.',
  priority:
    'Orden de preferencia cuando la potencia disponible no alcanza para todos. Menor número = mayor prioridad.',
  enabled:
    'Si está desactivado, el acumulador no participa en nuevos planes ni recibe asignación de potencia.',
  output:
    'Tipo de salida del relé: simulada (sin GPIO) o GPIO en el dispositivo donde corre el controlador.',
  pin: 'Número de pin BCM del GPIO que controla el relé de este acumulador.',
  active_high:
    'Nivel lógico que energiza el relé: alto (3,3 V) o bajo (0 V). Debe coincidir con el cableado.',
  indoor_topic:
    'Tópico MQTT de temperatura interior. Si está vacío, se usa el prefijo global y el identificador del acumulador.',
  temperature_topic:
    'Tópico MQTT de temperatura del acumulador. Obligatorio para planificación automática con MQTT habilitado.',
  target_temperature_topic:
    'Tópico MQTT del objetivo de temperatura del acumulador.',
  stored_charge_topic:
    'Tópico MQTT del estado de carga almacenada (%). La planificación automática lo usa como SOC inicial.',
};

const SYSTEM: Record<string, Record<string, string>> = {
  database: {
    driver: 'Motor de base de datos: SQLite local o PostgreSQL remoto.',
    host: 'Host del servidor PostgreSQL. No se usa con SQLite.',
    port: 'Puerto TCP de PostgreSQL (1–65535).',
    database: 'Nombre de la base de datos PostgreSQL.',
    tls: 'Exige conexión TLS al servidor PostgreSQL.',
    trusted_no_tls:
      'Permite PostgreSQL sin TLS solo en redes consideradas seguras. Requiere confirmación explícita al guardar.',
  },
  api: {
    host:
      'Interfaz de red donde escucha la API. 127.0.0.1 limita el acceso al equipo local; 0.0.0.0 expone en todas las interfaces.',
    port: 'Puerto TCP de la API HTTP (1–65535).',
    cors_origins:
      'Orígenes permitidos para peticiones cross-origin, separados por comas. Vacío = solo mismo origen.',
    stale_seconds:
      'Segundos sin actividad del controlador tras los cuales el estado se considera no actual. Vacío = sin umbral adicional.',
  },
  mqtt: {
    enabled:
      'Activa la conexión al broker MQTT para telemetría y publicación de estados. Si está desactivado, se usan los valores fijos de prueba.',
    host: 'Host del broker MQTT. Obligatorio cuando MQTT está habilitado.',
    port: 'Puerto del broker MQTT (1–65535).',
    tls: 'Usa TLS al conectar con el broker.',
    prefix: 'Prefijo base de los tópicos publicados por este sistema.',
    discovery_prefix: 'Prefijo de descubrimiento para integraciones tipo Home Assistant.',
    publish_seconds: 'Intervalo entre publicaciones periódicas de estado al broker.',
    fixed_temperature_c:
      'Temperatura fija del acumulador usada en planificación cuando MQTT está desactivado.',
    fixed_target_temperature_c:
      'Objetivo de temperatura fijo usado en planificación cuando MQTT está desactivado.',
    fixed_stored_charge_percent:
      'Carga almacenada fija (%) usada como SOC en planificación cuando MQTT está desactivado.',
    fixed_indoor_temperature_c:
      'Temperatura interior fija usada en el modelo de demanda cuando MQTT está desactivado.',
  },
  weather: {
    provider: 'Fuente de previsión: AEMET (datos reales) o simulada (valores configurados aquí).',
    municipality_code:
      'Código INE de 5 dígitos del municipio para AEMET. Obligatorio con proveedor AEMET.',
    timeout_seconds: 'Tiempo máximo de espera de cada petición HTTP a la API meteorológica.',
    simulated_average_temperature_c:
      'Temperatura media diaria cuando el proveedor es simulado.',
    simulated_minimum_temperature_c:
      'Temperatura mínima diaria cuando el proveedor es simulado.',
    fallback_average_temperature_c:
      'Temperatura media de respaldo si falla la consulta AEMET.',
    fallback_minimum_temperature_c:
      'Temperatura mínima de respaldo si falla la consulta AEMET.',
    retry_minutes: 'Minutos entre reintentos tras un error de consulta meteorológica.',
    refresh_minutes: 'Minutos entre consultas automáticas de previsión.',
  },
  planning: {
    forecast_horizon_hours:
      'Horas hacia delante que cubre el optimizador MILP y la vista de Planificación (1–48).',
    replan_minutes:
      'Cadencia prevista de replanificación automática. Guardado en configuración; el runtime puede replanificar también al cambiar restricciones o forecast.',
    aemet_query_hour:
      'Hora local (0–23) preferida para la consulta diaria de previsión AEMET.',
    contracted_power_w:
      'Límite total de potencia del emplazamiento (W) para el optimizador automático.',
    max_heating_power_w:
      'Límite de potencia dedicada a calefacción/acumuladores (W) en el optimizador.',
    base_load_w:
      'Carga base simultánea de la vivienda (W), que se descuenta de la potencia contratada.',
    design_indoor_temperature_c:
      'Temperatura interior de diseño (°C) del modelo degree-hours para estimar demanda.',
    design_outdoor_temperature_c:
      'Temperatura exterior de diseño (°C). Debe ser inferior a la interior de diseño.',
    feedback_horizon_hours:
      'Horas de histórico de temperatura interior usadas para ajustar la demanda estimada.',
    mqtt_simulation_enabled:
      'Activa un cliente MQTT que publica telemetría simulada de acumuladores. Requiere MQTT habilitado en la sección mqtt.',
    mqtt_simulation_initial_temperature_c:
      'Temperatura inicial (°C) de todos los acumuladores al arrancar o reiniciar la simulación.',
    mqtt_simulation_publish_seconds:
      'Intervalo entre publicaciones MQTT de temperatura, objetivo y carga almacenada simuladas.',
    mqtt_simulation_topic_prefix:
      'Prefijo base de los tópicos simulados. Cada acumulador publica en {prefijo}/{id}/temperature (y target/stored_charge) salvo que tenga tópicos propios configurados.',
    mqtt_simulation_thermal_loss_c_per_hour:
      'Pérdida térmica general (°C/h) aplicada a todos los acumuladores en reposo. Se invierte mientras el acumulador está cargando.',
  },
  output: {
    driver: 'Driver de salida física: simulada (sin relés) o GPIO en el dispositivo controlador.',
  },
  logging: {
    level: 'Nivel mínimo de los logs del proceso API en consola y archivos del sistema.',
    max_events: 'Número máximo de eventos de log del controlador retenidos en memoria antes de rotar.',
  },
  operations: {
    controller_poll_seconds: 'Intervalo del bucle principal del controlador (sondeo, plan, MQTT).',
    heartbeat_stale_multiplier:
      'Multiplicador del intervalo de sondeo para marcar el controlador como silencioso.',
    relay_test_lease_seconds:
      'Duración inicial de la concesión de prueba de relés antes de exigir renovación.',
    relay_test_state_poll_seconds:
      'Intervalo de lectura del estado de relés durante una prueba activa.',
    relay_test_lease_renew_seconds:
      'Intervalo de renovación de la concesión mientras la prueba de relés sigue abierta.',
    retention_days:
      'Días de retención de histórico en la base de aplicación (planes, transiciones, auditoría).',
    fallback_max_age_minutes:
      'Antigüedad máxima (min) de un snapshot de configuración en modo fallback antes de rechazar escrituras.',
  },
};

const SECRETS: Record<string, string> = {
  admin_token_digest:
    'Hash del token de administrador para autenticar el panel. El valor en claro nunca se devuelve al navegador.',
  postgres_username: 'Usuario de PostgreSQL. Solo se usa con driver PostgreSQL.',
  postgres_password: 'Contraseña de PostgreSQL. Solo se usa con driver PostgreSQL.',
  mqtt_username: 'Usuario de autenticación en el broker MQTT, si el broker lo exige.',
  mqtt_password: 'Contraseña del broker MQTT. El valor guardado no se muestra en el panel.',
  aemet_api_key:
    'Clave de API de AEMET para consultar la previsión meteorológica. Obligatoria con proveedor AEMET.',
};

export function paramHelpText(field: string, section?: string): string {
  if (section) {
    const scoped = SYSTEM[section]?.[field];
    if (scoped) return scoped;
  }
  return INSTALLATION[field] ?? HEATER[field] ?? SECRETS[field] ?? `Parámetro de configuración: ${field}.`;
}
