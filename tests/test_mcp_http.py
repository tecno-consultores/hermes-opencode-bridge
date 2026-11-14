# SPDX-License-Identifier: GPL-2.0-only
"""Servidor MCP (cliente MCP real en proceso) y capa HTTP con autenticación."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from mcp import Client, types

import acp_api
from acp_api import TOOL_NAME, app, handle_call_tool, handle_list_tools, is_authorized, mcp_server

pytestmark = pytest.mark.unit

TOKEN = "token-de-prueba-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
MCP_HEADERS = {**AUTH, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
}


def _params(name: str, arguments: dict[str, Any] | None) -> types.CallToolRequestParams:
    return types.CallToolRequestParams(name=name, arguments=arguments)


# ------------------------------------------------------------ MCP (SDK real)
class TestServidorMCP:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["legacy", "auto"])
    async def test_cliente_mcp_real_lista_y_llama(self, mode: str) -> None:
        """Regresión C6: los handlers tenían la firma de mcp 1.x y fallaban con mcp 2.x."""
        with patch("acp_api.ejecutar_tarea_opencode", new=AsyncMock(return_value="hecho")) as ejecutar:
            async with Client(mcp_server, mode=mode) as client:  # type: ignore[arg-type]
                tools = await client.list_tools()
                result = await client.call_tool(TOOL_NAME, {"instruction": "  escribe un test  "})

        assert [t.name for t in tools.tools] == [TOOL_NAME]
        assert tools.tools[0].input_schema["required"] == ["instruction"]
        assert result.is_error is not True
        assert isinstance(result.content[0], types.TextContent)
        assert result.content[0].text == "Status: Success.\nOpenCode Output:\nhecho"
        ejecutar.assert_awaited_once_with("escribe un test")

    @pytest.mark.asyncio
    async def test_list_tools_directo(self) -> None:
        result = await handle_list_tools(None, None)
        assert result.tools[0].name == TOOL_NAME

    @pytest.mark.asyncio
    async def test_herramienta_desconocida(self) -> None:
        result = await handle_call_tool(None, _params("falsa", {"instruction": "x"}))
        assert result.is_error is True
        assert "Herramienta desconocida" in result.content[0].text  # type: ignore[union-attr]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("arguments", [None, {}, {"instruction": "   "}, {"instruction": 5}])
    async def test_instruccion_obligatoria(self, arguments: dict[str, Any] | None) -> None:
        result = await handle_call_tool(None, _params(TOOL_NAME, arguments))
        assert result.is_error is True
        assert "obligatoria" in result.content[0].text  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_error_de_ejecucion_se_devuelve_como_is_error(self) -> None:
        with patch("acp_api.ejecutar_tarea_opencode", new=AsyncMock(side_effect=RuntimeError("Fallo Docker"))):
            result = await handle_call_tool(None, _params(TOOL_NAME, {"instruction": "x"}))
        assert result.is_error is True
        assert result.content[0].text == "Status: Error. RuntimeError: Fallo Docker"  # type: ignore[union-attr]

    def test_nombre_y_version(self) -> None:
        assert mcp_server.name == "acp-orchestrator"


# ------------------------------------------------------------ autenticación
def _scope(headers: list[tuple[bytes, bytes]] | None = None, query: bytes = b"") -> dict[str, Any]:
    return {"type": "http", "headers": headers or [], "query_string": query}


class TestAutenticacion:
    def test_bearer_valido(self) -> None:
        assert is_authorized(_scope([(b"authorization", f"Bearer {TOKEN}".encode())])) is True

    def test_query_token_valido(self) -> None:
        assert is_authorized(_scope(query=f"token={TOKEN}".encode())) is True

    @pytest.mark.parametrize(
        "scope",
        [
            _scope(),
            _scope([(b"authorization", b"Bearer otro")]),
            _scope([(b"authorization", f"Basic {TOKEN}".encode())]),
            _scope(query=b"token=otro"),
        ],
    )
    def test_token_invalido(self, scope: dict[str, Any]) -> None:
        assert is_authorized(scope) is False

    @pytest.mark.parametrize("valor", ["", "CHANGE_ME", "changeme"])
    def test_sin_clave_configurada_rechaza_todo(self, monkeypatch: pytest.MonkeyPatch, valor: str) -> None:
        monkeypatch.setenv("ACP_API_KEY", valor)
        assert is_authorized(_scope(query=f"token={valor}".encode())) is False

    def test_transport_security_opcional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert acp_api._transport_security() is None
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", "acp-orchestrator:*, localhost:*")
        settings = acp_api._transport_security()
        assert settings is not None
        assert settings.enable_dns_rebinding_protection is True
        assert settings.allowed_hosts == ["acp-orchestrator:*", "localhost:*"]


# ------------------------------------------------------------ HTTP
class TestHTTP:
    def test_health(self) -> None:
        response = TestClient(app).get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": acp_api.__version__}

    @pytest.mark.parametrize("path", ["/mcp/sse", "/mcp"])
    def test_endpoints_mcp_exigen_token(self, path: str) -> None:
        response = TestClient(app).get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_sse_autorizado_delega_en_el_transporte(self) -> None:
        @contextlib.asynccontextmanager
        async def fake_connect(scope: Any, receive: Any, send: Any) -> AsyncIterator[tuple[str, str]]:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            yield ("read", "write")

        with (
            patch.object(acp_api.sse, "connect_sse", new=fake_connect),
            patch.object(acp_api.mcp_server, "run", new=AsyncMock()) as run,
        ):
            response = TestClient(app).get("/mcp/sse", headers=AUTH)
        assert response.status_code == 200
        assert run.await_args.args[:2] == ("read", "write")

    def test_sse_head_no_permitido(self) -> None:
        assert TestClient(app).head("/mcp/sse", headers=AUTH).status_code == 405

    def test_messages_con_sesion_inexistente(self) -> None:
        response = TestClient(app).post(
            "/mcp/messages?session_id=00000000000000000000000000000000", json={"jsonrpc": "2.0", "method": "ping"}
        )
        assert response.status_code in {400, 404}

    def test_streamable_http_initialize(self) -> None:
        with TestClient(app) as client:
            response = client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        assert response.status_code == 200
        assert "acp-orchestrator" in response.text

    def test_streamable_http_sin_lifespan_devuelve_503(self) -> None:
        response = TestClient(app).post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        assert response.status_code == 503

    def test_openapi_y_docs_desactivados_por_defecto(self) -> None:
        """SEC-07 (OWASP API8): sin Swagger/OpenAPI en producción."""
        client = TestClient(app)
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/docs").status_code == 404

    @pytest.mark.parametrize(("valor", "esperado"), [("true", True), ("1", True), ("", False), ("no", False)])
    def test_docs_enabled(self, monkeypatch: pytest.MonkeyPatch, valor: str, esperado: bool) -> None:
        monkeypatch.setenv("ACP_ENABLE_DOCS", valor)
        assert acp_api.docs_enabled() is esperado
