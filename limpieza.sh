#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Jesus Palencia <sinfallas@gmail.com> (Creado en Tecno Consultores)
# Limpia artefactos locales de QA/build de ESTE repositorio. No toca otras imágenes ni volúmenes del host.
set -euo pipefail

cd "$(dirname "$0")"

docker compose -f docker-compose.qa.yml down -v --remove-orphans 2>/dev/null || true

rm -rf .coverage .mutmut-cache .mypy_cache .pytest_cache .ruff_cache .tox .hypothesis .schemathesis \
    dist build mutants tests/__pycache__ __pycache__ .buildx-cache ./*.egg-info || {
    echo "ERROR: no se pudieron borrar algunos archivos (¿creados como root por versiones anteriores?)." >&2
    echo "Ejecute una vez: sudo chown -R \"$(id -u):$(id -g)\" ." >&2
    exit 1
}

echo "Finalizado."
