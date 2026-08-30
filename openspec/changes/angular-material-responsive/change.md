# Refactor frontend con Angular Material y gestión de acumuladores

Status: approved

## Goal

Actualizar la experiencia del panel para que sea mobile-first, responsive y coherente con Angular Material, manteniendo los contratos actuales de autenticación y configuración. La pantalla de configuración de home debe permitir gestionar los acumuladores mediante un CRUD completo y presentar sus formularios agrupados de forma más eficiente.

## Requirements

- R1: El frontend usa Angular Material como base visual y aplica sus patrones de navegación, botones, campos, tarjetas, diálogos y estados de feedback.
- R2: Las rutas autenticadas se muestran dentro de un shell responsive con header persistente, navegador lateral y navegación usable con teclado; el navegador funciona como drawer superpuesto en mobile y como panel lateral en pantallas amplias.
- R3: El header muestra una acción de logout identificable por icono, con nombre accesible, que limpia la sesión y lleva a login.
- R4: Configuración de home permite listar, crear, editar y eliminar acumuladores usando los endpoints existentes, revisión optimista y confirmaciones necesarias para cambios eléctricos; los errores y conflictos siguen siendo visibles y no sobrescriben datos.
- R5: Los campos de configuración de home se agrupan semánticamente en secciones y grids responsive, usando el espacio disponible sin provocar scroll horizontal de página en mobile.
- R6: Las pantallas existentes siguen siendo accesibles desde el navegador lateral y conservan sus comportamientos funcionales actuales.

## Acceptance

- A1: La aplicación compila con Angular Material instalado y no muestra errores de TypeScript o plantilla.
- A2: En viewport mobile el drawer se puede abrir/cerrar, se cierra al seleccionar una ruta y el contenido no requiere scroll horizontal de página; en viewport amplio permanece visible como sidenav.
- A3: La acción de logout tiene tooltip o texto accesible, ejecuta `signOut` y redirige a `/login`.
- A4: En configuración se puede abrir un formulario de alta, crear un acumulador válido, editar sus campos, cancelar cambios y eliminarlo con confirmación; cada operación usa la revisión devuelta por la API.
- A5: Configuración de instalación y acumuladores muestra agrupaciones claras y distribuye los campos en una o varias columnas según el ancho disponible.
- A6: Las pruebas frontend existentes pasan y la comprobación determinista del proyecto no introduce fallos causados por el cambio.

## Decisions

- D1: El CRUD reutiliza `Api.addHeater`, `Api.setHeaterField` y `Api.removeHeater`; no se modifica el backend ni se añade un endpoint paralelo.
- D2: La navegación lateral será `MatSidenav` con modo `over` en mobile y `side` desde un breakpoint amplio; el estado de apertura es local al shell.
- D3: La eliminación exige confirmación explícita y las modificaciones de campos eléctricos mantienen la confirmación existente.

## Tasks

- [x] T1: Añadir Angular Material, tema global y componentes base del shell responsive.
- [x] T2: Migrar el header y navegación a sidenav, incluyendo logout accesible y estado global existente.
- [x] T3: Reestructurar configuración de home con grupos responsive y CRUD de acumuladores.
- [x] T4: Actualizar pruebas frontend para navegación, logout y CRUD, y ajustar estilos de pantallas afectadas.
- [x] T5: Ejecutar build, pruebas y quality gate; corregir regresiones del cambio.
