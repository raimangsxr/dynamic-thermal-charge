# Entrega reproducible

Status: approved

## Goal
Hacer que un commit resuelva dependencias e imágenes de producción de forma controlada y auditable en las arquitecturas soportadas, incluida ARMv7.

## Requirements
- R1: Las dependencias Python de producción se resolverán desde un lock versionado compatible con las arquitecturas soportadas.
- R2: Las instalaciones conservarán la restricción de no requerir compiladores ni dependencias sin soporte ARMv7.
- R3: Las imágenes base de build y runtime quedarán fijadas por versión inmutable o digest y se actualizarán deliberadamente.
- R4: El paquete CBC del runtime tendrá una procedencia y versión verificables dentro del proceso de build.
- R5: Cada imagen publicada incluirá inventario de componentes y metadatos que permitan relacionarla con el commit y locks usados.
- R6: Existirá un procedimiento explícito para actualizar locks, bases y dependencias y verificar el resultado con `make check`.

## Acceptance
- A1: Dos builds limpios del mismo commit usan las mismas versiones de dependencias e imágenes base.
- A2: CI verifica que los locks están sincronizados con sus manifiestos y que no se omiten durante el build.
- A3: La imagen backend se construye para el objetivo ARMv7 sin introducir toolchain de compilación.
- A4: El artefacto publicado expone versión, commit y un SBOM generado sin secretos.

## Decisions
- D1: Los manifiestos siguen expresando compatibilidad; los locks versionados gobiernan instalaciones y builds concretos.
- D2: Las actualizaciones serán cambios revisables, no resolución flotante durante un build de producción.

## Tasks
- [ ] T1: Seleccionar e integrar el lock Python compatible con el build multiplataforma.
- [ ] T2: Fijar imágenes y CBC, y añadir comprobaciones de sincronización.
- [ ] T3: Generar metadatos/SBOM y documentar el procedimiento de actualización.
