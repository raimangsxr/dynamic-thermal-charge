## 1. Persistencia de eventos del controller

- [x] 1.1 Definir los ajustes de retención y el modelo/migración de eventos de diagnóstico, incluidos índices para id e instante, y verificar la actualización de esquema en SQLite y PostgreSQL.
- [x] 1.2 Implementar el repositorio de escritura, purga y lectura paginada con filtros de nivel y texto, y verificarlo con pruebas unitarias de límites, cursores, filtros y retención.
- [x] 1.3 Implementar y conectar al proceso controller un handler de logging aislado que proyecte eventos sin detener el control si falla, y verificar mediante pruebas que el fallo de persistencia no propaga excepciones al ciclo de control.

## 2. API de diagnóstico protegida

- [x] 2.1 Añadir esquemas y `GET /api/v1/controller-log` con validación de `limit`, cursores, nivel y texto, y verificar respuestas de primera página e incrementalidad con pruebas de API.
- [x] 2.2 Registrar la ruta bajo la autenticación existente y conservar las restricciones de imports de la API, y verificar accesos sin credencial, parámetros no admitidos y ausencia de acceso a controller/drivers/journal.
- [x] 2.3 Documentar configuración, límites y retención del log visible en los ejemplos y guía de despliegue, y verificar que no se requieren permisos de journal ni lectura de archivos para la API.

## 3. Fundaciones UI/UX del panel

- [x] 3.1 Rediseñar el shell autenticado con identidad, navegación responsive a Estado, Configuración, Histórico, Prueba de relés y Diagnóstico, y verificar ruta activa, cierre de sesión y ausencia de scroll horizontal en viewport móvil.
- [x] 3.2 Crear tokens y primitives globales de interfaz para superficies, tipografía, formularios, botones, foco, banners y tablas responsivas, y verificar contraste y que las alertas críticas no dependan solo del color.
- [x] 3.3 Migrar las vistas existentes a la jerarquía y primitives compartidas sin cambiar su comportamiento, y verificar sus pruebas actuales más estados explícitos de carga, vacío y error recuperable.
- [x] 3.4 Revalidar las advertencias de estado no actual/degradado/múltiple y de prueba de relés dentro del rediseño, y verificar con pruebas de componentes que nunca se afirma estado o potencia actual cuando la API no lo confirma.

## 4. Visor de diagnóstico web

- [x] 4.1 Añadir tipos y cliente Angular para el contrato de controller-log, y verificar con pruebas unitarias la serialización de filtros, cursores y límites.
- [x] 4.2 Implementar la ruta protegida y componente `/diagnostico` con tabla de eventos, hora local, nivel, origen, mensaje, filtros y estado vacío/error, y verificar sus escenarios de interacción mediante pruebas de componente.
- [x] 4.3 Incorporar polling incremental limitado a la vista activa, deduplicación por id, preservación de filtros y carga explícita de páginas anteriores, y verificar que eventos nuevos no duplican ni reinician la lectura.

## 5. Verificación integrada

- [ ] 5.1 Ejecutar la suite Python completa y verificar migraciones, API de logs, aislamiento del controller y contratos existentes.
- [x] 5.2 Ejecutar las pruebas y build de Angular, y verificar que las rutas protegidas, el visor de diagnóstico y las vistas rediseñadas compilan y pasan sus pruebas.
- [ ] 5.3 Realizar una comprobación manual responsive de Estado, Configuración, Histórico, Prueba de relés y Diagnóstico con datos sanos, degradados, vacíos y con error, y documentar los resultados de aceptación.
