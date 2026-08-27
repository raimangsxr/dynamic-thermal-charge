# Contract — Panel de prueba de relés

**Feature**: `005-relay-test-mode` | **Ruta**: `/prueba-reles`

## Entrada y ownership

- Explica que conmuta cargas reales y exige acción explícita.
- Guarda `session_id` y `client_credential` solo en `sessionStorage`, nunca URL, localStorage,
  logs, telemetría o texto visible.
- Solo la pestaña con credencial habilita orden, lease y fin. Una sesión ajena es observador sin
  atribución humana.
- Cerrar sesión web borra credencial y deja de renovar; no envía DELETE implícito.

## Presentación segura

- Orden por position/nombre/id; hasta 20 tarjetas por teclado y sin scroll principal a 320 px.
- Estados textuales sin depender de color: apagado/encendido confirmado, pendiente, rechazado,
  sin confirmar.
- Nunca cambia a ON al enviar; espera confirmación.
- `starting`: automático aún puede estar activo; controles deshabilitados.
- `active` owner: «MODO TEST · automático suspendido», lease y finalizar visibles.
- `ending`: «Apagando todas las salidas», sin controles.
- `failed`/latch: «Recuperación de seguridad: automático bloqueado», causa/último intento; no
  ofrece limpiar latch.
- Auditoría degradada: aviso separado; no presenta conmutación como fallida por ello.
- Unknown/API caída/heartbeat viejo no afirman ON/OFF ni aceptan órdenes.
- Consulta terminal por id muestra desenlace/salidas aunque ya no sea sesión actual.

## Cadencias independientes

- Estado: GET cada 1 s durante starting/active/ending/recuperación o salida pending; se detiene en
  terminal estable sin latch. Nunca renueva.
- Lease: POST cada 5 s solo con documento visible, owner, starting/active y sin latch.
- Temporizadores independientes, cancelables e inyectables; no se encadenan.
- Al volver visible, consultar primero; solo entonces reanudar lease si sigue válido. Nunca recrear.
- 401 borra autenticación y credencial; 403 borra solo credencial y pasa a observador.

## Navegación y compatibilidad

- Añadir navegación autenticada e indicador global para sesión o latch.
- Configuración traduce conflicto y enlaza a prueba; no reintenta.
- Ruta diferida y mismo presupuesto de bundle.
- `Poller` global de status conserva defaults 5 s/mínimo 2 s. El coordinador de esta feature
  implementa expresamente 1 s y 5 s para no alterar otras vistas.
