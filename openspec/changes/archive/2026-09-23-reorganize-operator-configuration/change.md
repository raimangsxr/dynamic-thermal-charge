# Reorganización de la configuración del operador

Status: approved

## Goal
Agrupar la configuración según el modelo mental del operador y separar las opciones habituales de los ajustes avanzados, sin cambiar el almacenamiento ni los valores efectivos.

## Requirements
- R1: La programación de consultas AEMET se mostrará dentro de Meteorología, junto al proveedor, ubicación y cadencias.
- R2: Los campos meteorológicos existentes aparecerán en grupos no vacíos y con títulos que describan su contenido real.
- R3: Planificación distinguirá parámetros básicos de operación y parámetros avanzados del solver o de sensibilidad.
- R4: Los metadatos de revisión, esquema y versión técnica se moverán de la vista general a Diagnóstico o a un detalle avanzado.
- R5: Mover un campo en la interfaz no cambiará su nombre, persistencia, valor ni comportamiento backend.
- R6: Ayudas y etiquetas describirán el efecto operativo en español y evitarán jerga de implementación cuando no sea necesaria.

## Acceptance
- A1: No se renderizan grupos vacíos ni campos bajo un título incorrecto.
- A2: Los valores guardados antes del cambio se cargan y guardan sin migración ni pérdida.
- A3: Un operador encuentra proveedor, ubicación, horario y actualización de AEMET en una única sección.
- A4: Las opciones avanzadas siguen siendo accesibles, pero no dominan la vista inicial.
