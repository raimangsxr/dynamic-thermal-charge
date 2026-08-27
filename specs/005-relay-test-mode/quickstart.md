# Quickstart de validación — Prueba manual de relés

**Feature**: `005-relay-test-mode`

Guía para validar la futura implementación. CI no conecta hardware.

## Prerrequisitos

- Python 3.12 con extras dev y frontend instalado.
- SQLite temporal migrada a `0004_relay_test_mode`; dos acumuladores simulados.
- Token API válido. Hardware físico solo tras validación automática y con carga segura.

## Validación automática

```bash
pytest
npm --prefix frontend run test
npm --prefix frontend run build
```

Esperado: sin red/hardware/sleeps reales; bundle dentro de presupuesto.

## 1 — Ciclo feliz y ownership

1. Arrancar controlador/driver/reloj falsos y API en proceso.
2. POST inicio: `starting`, credencial cliente una vez, estado=1 s, lease=5 s.
3. Ciclo controlador: OFF completo, `active`, sin plan automático.
4. Cliente B con mismo Bearer pero sin credencial puede observar; mutaciones devuelven 403 y no
   cambian secuencia/driver.
5. Cliente A ordena ON/OFF; cada PUT queda pending antes de confirmed y solo cambia su acumulador.
6. DELETE, OFF completo, `ended`; automático solo en ciclo siguiente.

## 2 — Cadencias independientes

Con temporizador y visibilidad falsos:

1. Durante `starting/active/pending`, verificar GET exactamente cada 1 s.
2. Verificar lease cada 5 s solo owner visible; GET nunca renueva.
3. Ocultar: lease se detiene sin convertir GET en renovación.
4. Volver visible: GET inmediato; renovar solo si sigue owner/vigente/no terminal.
5. Terminal estable sin latch detiene estado; una recuperación activa mantiene seguimiento.

## 3 — Límite, id obsoleto y guardia config

1. Dos acumuladores cuya suma excede máximo: ON segundo se rechaza, primero no cambia.
2. Id eliminado/ausente se rechaza sin GPIO.
3. Intentar config por HTTP y repositorio/CLI durante sesión: conflicto atómico.
4. Simular proceso antiguo que cambia revisión: siguiente ciclo barre OFF y termina por cambio.

## 4 — Fault latch persistente

1. Dos salidas ON; hacer fallar OFF de una y permitir OFF de otra.
2. Finalizar: se intentan ambas; fallida queda unknown, sesión `failed/off_sweep_failed`.
3. Verificar `fault_latched=true`, generación incrementada, automático bloqueado, control singleton
   sin sesión operable, POST inicio/config rechazados.
4. Reintento OFF parcial rearma generación; una limpieza CAS con generación vieja falla.
5. Reintento completo limpia latch; ese ciclo no aplica plan. Ciclo siguiente restaura automático.
6. Reiniciar entre pasos: latch persiste y no se reproduce `desired_state=true`.

## 5 — Caída SQL durante fallo

1. Activar salida y hacer fallar coordinación.
2. Verificar OFF best-effort, latch local y ningún automático aunque no se pueda persistir.
3. Recuperar SQL: primero reconciliar terminal/latch; solo después intentar OFF de recuperación.
4. Si inicialización/recovery OFF falla, automático sigue bloqueado. Si completa, limpiar por CAS y
   esperar al ciclo siguiente.

## 6 — Auditoría degradada sin bloquear seguridad

1. Hacer fallar solo insert de `relay_test_event`; ejecutar OFF/cierre.
2. Verificar que GPIO/latch/terminal continúan sin espera ni excepción del recorder.
3. Verificar `audit.degraded=true` si el marcador best-effort puede escribirse; si también falla,
   exigir log redactado y continuidad.
4. Restaurar eventos: persistir recuperación, limpiar marcador y exponer transición una sola vez.
5. Confirmar que respuestas/logs no contienen credencial, digest, URL, pin ni traza.

## 7 — Consulta terminal por `session_id`

1. Terminar mientras se pierde respuesta HTTP; liberar singleton.
2. `GET /relay-test/{session_id}` recupera status, razón, ended_at y salidas confirmed/unknown.
3. GET no renueva ni revive; credencial opcional solo calcula owner.
4. Tras poda por retención devuelve 404; con retención ilimitada permanece.

## 8 — Panel honesto y responsive

- 20 tarjetas ordenadas, teclado y 320 px sin scroll principal.
- starting/pending/unknown/ending/sesión ajena nunca habilitan toggle optimista.
- latch muestra automático bloqueado sin botón de limpieza; auditoría degradada es aviso separado.
- credencial solo en header/sessionStorage; 401 borra auth+credencial, 403 solo credencial.

## Prueba física manual controlada

Tras pasar todo: confirmar pines/active_high, desconectar cargas cuando sea posible, probar un
acumulador cada vez y medir relé. Forzar un cierre normal y verificar eléctricamente OFF antes de
operación automática. No simular fallo de OFF sobre cargas energizadas. Véanse contratos
[HTTP](./contracts/http-api.md), [controlador](./contracts/controller-coordination.md) y
[panel](./contracts/panel.md).
