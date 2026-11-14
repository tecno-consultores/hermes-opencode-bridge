# SPDX-License-Identifier: GPL-2.0-only
"""Prueba de carga: salud y handshake MCP (Streamable HTTP) autenticado.

Requiere la API levantada (docker compose -f docker-compose.qa.yml up -d api) y
el mismo ACP_API_KEY en el entorno.
"""

import os

from locust import HttpUser, between, task

TOKEN = os.environ.get("ACP_API_KEY", "")
MCP_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "locust", "version": "1"}},
}


class ACPOrchestratorUser(HttpUser):
    # Retraso humano/agente entre peticiones (1 a 3 segundos)
    wait_time = between(1, 3)

    @task(3)
    def check_health(self) -> None:
        self.client.get("/health", name="/health")

    @task(1)
    def mcp_initialize(self) -> None:
        """Handshake MCP completo: solo un 200 con serverInfo cuenta como éxito."""
        with self.client.post(
            "/mcp", json=INITIALIZE, headers=MCP_HEADERS, name="/mcp initialize", catch_response=True
        ) as response:
            if response.status_code == 200 and "acp-orchestrator" in response.text:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")

    @task(1)
    def mcp_sin_token(self) -> None:
        """La autenticación debe rechazar con 401 incluso bajo carga."""
        with self.client.post("/mcp", json=INITIALIZE, name="/mcp sin token", catch_response=True) as response:
            if response.status_code == 401:
                response.success()
            else:
                response.failure(f"Se esperaba 401 y se obtuvo {response.status_code}")
