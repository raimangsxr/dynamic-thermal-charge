# Lenguaje y patrones compartidos de interfaz

Status: approved

## Goal
Eliminar divergencias de terminología y comportamiento visual mediante un conjunto pequeño de patrones compartidos, preservando la identidad y funcionalidad actuales.

## Requirements
- R1: Existirá una única fuente frontend para etiquetas de pasos, estados, severidades, causas y acciones conocidas.
- R2: Cabecera de página, panel, banner, chip de estado, estado vacío/cargando y bloque de acciones usarán patrones compartidos donde ya exista equivalencia funcional.
- R3: Los patrones definirán espaciado, jerarquía, foco, semántica accesible y comportamiento responsive coherentes.
- R4: Los módulos podrán conservar variantes justificadas sin copiar de nuevo el patrón completo.
- R5: La consolidación no cambiará reglas de negocio, llamadas API ni permisos.
- R6: Los estilos duplicados retirados no provocarán regresiones visuales en Estado, Planificación, Configuración, Histórico, Diagnóstico o Prueba de relés.

## Acceptance
- A1: Las traducciones duplicadas de pasos de planificación desaparecen y cada código produce una única etiqueta.
- A2: Los seis módulos usan los patrones compartidos acordados y mantienen sus estados existentes.
- A3: Pruebas verifican fallbacks para códigos desconocidos y estados accesibles de foco, error, vacío y carga.
- A4: El build no aumenta los presupuestos CSS existentes a causa de la extracción.

## Decisions
- D1: Se extraerán únicamente patrones ya repetidos o requeridos por los cambios aprobados; no se creará un sistema de diseño general ni un rediseño visual.
- D2: Este cambio precede a los cambios funcionales de UX para evitar nuevas duplicaciones.

## Tasks
- [ ] T1: Inventariar y consolidar el catálogo de presentación.
- [ ] T2: Extraer los patrones visuales mínimos y migrar los módulos.
- [ ] T3: Añadir regresiones de accesibilidad, responsive y tamaño.
