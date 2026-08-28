## Purpose

Ofrece un panel operativo coherente, legible y accesible para entender, configurar y diagnosticar la instalación en escritorio y móvil.

## ADDED Requirements

### Requirement: Marco de navegación operativo y adaptable
El panel autenticado SHALL mostrar una identidad de producto y una navegación persistente hacia Estado, Configuración, Histórico, Prueba de relés y Diagnóstico. SHALL indicar de forma inequívoca la sección activa, mantener visible el cierre de sesión y adaptarse a pantallas estrechas sin desplazamiento horizontal de la página.

#### Scenario: Navegación en pantalla pequeña
- **WHEN** un operador abre el panel autenticado en un teléfono
- **THEN** puede acceder a cada sección y al cierre de sesión sin que el contenido principal requiera desplazamiento horizontal

#### Scenario: Sección activa
- **WHEN** el operador navega a una sección del panel
- **THEN** la navegación identifica visualmente esa sección como activa

### Requirement: Jerarquía y estados de las vistas operativas
Cada vista del panel SHALL identificar su propósito, priorizar la información o acción principal y representar explícitamente sus estados de carga, vacío, error y datos no actuales. La interfaz SHALL conservar las advertencias de seguridad existentes —incluido controller no actual, degradado o múltiple y prueba de relés activa— con una jerarquía visual que no las confunda con información ordinaria.

#### Scenario: Estado del controller no confirmable
- **WHEN** la API informa que el estado del controller no es actual
- **THEN** la vista de Estado muestra una advertencia prominente y no representa potencia ni relés como actuales

#### Scenario: Fallo recuperable de carga
- **WHEN** una vista no puede cargar sus datos por un fallo recuperable
- **THEN** explica que no se pudieron obtener los datos, preserva cualquier contenido previamente confirmado cuando exista y ofrece reintentar

#### Scenario: Colección vacía
- **WHEN** una vista de histórico o diagnóstico no tiene resultados para los filtros aplicados
- **THEN** muestra un estado vacío comprensible en lugar de una tabla o área sin contenido

### Requirement: Sistema visual accesible y consistente
El panel SHALL aplicar componentes, espaciado, tipografía, color y estados interactivos coherentes en sus áreas operativas. El contraste de texto y controles SHALL permitir la lectura y el uso normal, y la información crítica SHALL incluir texto o iconografía además del color.

#### Scenario: Advertencia sin dependencia exclusiva del color
- **WHEN** se muestra una advertencia de seguridad o diagnóstico
- **THEN** su significado sigue siendo identificable por texto o iconografía aunque el operador no distinga el color
