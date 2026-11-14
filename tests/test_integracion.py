# SPDX-License-Identifier: GPL-2.0-only
"""Pruebas de integración: requieren el stack real (Hermes y OpenCode en `acp-net`).

Ejecutar con: pytest -m integration
"""

from __future__ import annotations

import pytest

from acp_api import consultar_hermes, ejecutar_tarea_opencode

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_hermes_real_rechaza_accion_destructiva() -> None:
    decision, sugerencia = await consultar_hermes({"title": "rm -rf /var/lib/docker", "kind": "execute"})
    assert decision in {"approved", "rejected"}
    assert isinstance(sugerencia, str)


@pytest.mark.asyncio
@pytest.mark.timeout(600)
async def test_opencode_real_responde() -> None:
    resultado = await ejecutar_tarea_opencode("Responde únicamente con la palabra: pong")
    assert resultado
