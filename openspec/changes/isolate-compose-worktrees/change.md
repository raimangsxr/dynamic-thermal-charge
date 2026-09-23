# Aislamiento de Docker Compose por worktree

Status: approved

## Goal
Evitar que dos checkouts compartan accidentalmente contenedores, redes o volúmenes durante desarrollo y verificación local.

## Requirements
- R1: Los comandos de desarrollo asignarán automáticamente un nombre de proyecto Compose estable y distinto para cada ruta de checkout.
- R2: Contenedores, redes y volúmenes de desarrollo quedarán bajo ese nombre sin cambiar los nombres internos de servicios.
- R3: Todas las variantes SQLite y PostgreSQL usarán exactamente la misma identidad calculada para un checkout.
- R4: Los comandos de parada y limpieza solo afectarán al proyecto del checkout desde el que se ejecutan.
- R5: Producción conservará nombres y rutas de datos explícitos y no dependerá del identificador de un worktree.
- R6: El nombre calculado será válido para Compose y podrá sobrescribirse explícitamente para automatización.

## Acceptance
- A1: Dos clones o worktrees pueden levantar simultáneamente el entorno sin compartir recursos ni detenerse entre sí.
- A2: Repetir el comando desde el mismo checkout reutiliza el mismo proyecto y sus datos.
- A3: Las variantes de base de datos pasan `docker compose config` con la identidad acordada.
- A4: La documentación explica identidad, sobrescritura y limpieza segura.

## Decisions
- D1: El aislamiento se aplicará mediante el contrato de comandos del repositorio, no mediante nombres codificados en cada YAML.

## Tasks
- [ ] T1: Incorporar el cálculo y la propagación del nombre de proyecto.
- [ ] T2: Adaptar comandos de desarrollo, comprobación y limpieza.
- [ ] T3: Añadir pruebas y documentación para dos checkouts simultáneos.
