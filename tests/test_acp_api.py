# test_acp_api.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from acp_api import (
    OpenCodeRPCController,
    app,
    consultar_hermes,
    handle_call_tool,
    handle_list_tools,
    mcp_server,
)

# --- Fixtures ---

@pytest.fixture
def client():
    """Provee un cliente de pruebas para la app principal FastAPI."""
    return TestClient(app)

# ==========================================
# 1. PRUEBAS UNITARIAS (Aisladas, sin red, mocking de todo)
# ==========================================
pytestmark_unit = pytest.mark.unit

class TestUnitariasAcpApi:
    
    @pytestmark_unit
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.httpx.AsyncClient")
    async def test_consultar_hermes_approved(self, mock_httpx_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"decision": "approved", "suggestion": ""}'}}]
        }
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value.__aenter__.return_value = mock_client_instance

        decision, sugerencia = await consultar_hermes({"accion": "leer archivo"})
        
        call_args = mock_client_instance.post.call_args[1]
        assert "response_format" in call_args["json"]
        assert call_args["json"]["response_format"]["type"] == "json_schema"
        
        assert decision == "approved"
        assert sugerencia == ""

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.httpx.AsyncClient")
    async def test_consultar_hermes_rejected_with_suggestion(self, mock_httpx_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"decision": "rejected", "suggestion": "usa ruta relativa"}'}}]
        }
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value.__aenter__.return_value = mock_client_instance

        decision, sugerencia = await consultar_hermes({"accion": "rm -rf /"})
        assert decision == "rejected"
        assert sugerencia == "usa ruta relativa"

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.httpx.AsyncClient")
    async def test_consultar_hermes_exception_fallback(self, mock_httpx_client):
        mock_client_instance = AsyncMock()
        mock_client_instance.post.side_effect = Exception("Simulated Timeout")
        mock_httpx_client.return_value.__aenter__.return_value = mock_client_instance

        decision, _ = await consultar_hermes({"accion": "test"})
        assert decision == "approved"

    # --- Pruebas del Controlador JSON-RPC (OpenCodeRPCController) ---

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.asyncio.create_subprocess_exec")
    async def test_opencode_rpc_controller_basico(self, mock_create_subprocess):
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.stdin = MagicMock()
        mock_process.stdin.write = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdout = MagicMock()
        mock_process.stdout.readline = AsyncMock()
        
        mock_process.stdout.readline.side_effect = [
            b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
            b'{"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-123"}}\n',
            b'{"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "Hola"}}}}\n',
            b'{"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}}\n',
            b''
        ]
        mock_process.wait = AsyncMock()
        mock_create_subprocess.return_value = mock_process

        controller = OpenCodeRPCController("saluda")
        await controller.start()
        
        assert controller.respuesta_final == "Hola"
        mock_process.terminate.assert_called_once()

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.consultar_hermes")
    @patch("acp_api.asyncio.create_subprocess_exec")
    async def test_opencode_rpc_controller_flujo_rechazo(self, mock_create_subprocess, mock_consultar):
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.stdin = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdout = MagicMock()
        mock_process.stdout.readline = AsyncMock()
        mock_process.wait = AsyncMock()
        
        mock_process.stdout.readline.side_effect = [
            b'{"jsonrpc": "2.0", "id": 1, "result": {}}\n',
            b'{"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "s-123"}}\n',
            b'bad json\n',
            b'{"jsonrpc": "2.0", "method": "request_permission", "params": {"accion": "rm -rf /"}, "id": 99}\n',
            b'{"jsonrpc": "2.0", "id": 4, "result": {"stopReason": "end_turn"}}\n',
            b''
        ]
        
        mock_consultar.return_value = ("rejected", "no lo hagas")
        mock_create_subprocess.return_value = mock_process

        controller = OpenCodeRPCController("haz algo malo")
        await controller.start()
        
        mock_consultar.assert_called_once()

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.asyncio.create_subprocess_exec")
    async def test_opencode_rpc_controller_sin_pipes(self, mock_create_subprocess):
        mock_process = MagicMock()
        mock_process.stdin = None
        mock_create_subprocess.return_value = mock_process
        
        controller = OpenCodeRPCController("test")
        with pytest.raises(RuntimeError):
            await controller.start()

    # --- Pruebas Herramienta MCP Nativas ---

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.ejecutar_tarea_opencode")
    async def test_handle_call_tool_success(self, mock_ejecutar):
        mock_ejecutar.return_value = "Código generado correctamente"
        
        resultado = await handle_call_tool("delegar_a_opencode", {"instruction": "escribe un test"})
        texto = resultado[0].text
        
        assert "Status: Success." in texto
        assert "Código generado correctamente" in texto

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.ejecutar_tarea_opencode")
    async def test_handle_call_tool_error(self, mock_ejecutar):
        mock_ejecutar.side_effect = Exception("Fallo en el contenedor Docker")
        
        resultado = await handle_call_tool("delegar_a_opencode", {"instruction": "escribe un test"})
        texto = resultado[0].text
        
        assert "Status: Error." in texto
        assert "Fallo en el contenedor Docker" in texto

    @pytestmark_unit
    @pytest.mark.asyncio
    async def test_handle_call_tool_unknown(self):
        with pytest.raises(ValueError, match="Herramienta desconocida"):
            await handle_call_tool("herramienta_falsa", {"instruction": "test"})

    @pytestmark_unit
    @pytest.mark.asyncio
    async def test_handle_list_tools(self):
        tools = await handle_list_tools()
        assert len(tools) == 1
        assert tools[0].name == "delegar_a_opencode"

    @pytestmark_unit
    def test_mcp_server_registration(self):
        """Verifica que el servidor subyacente se instanció correctamente."""
        assert mcp_server.name == "acp-orchestrator"

# ==========================================
# 2. PRUEBAS DE INTEGRACIÓN (Requieren entorno Docker / Red real)
# ==========================================
pytestmark_integration = pytest.mark.integration

class TestIntegracionAcpApi:

    @pytestmark_integration
    @pytest.mark.asyncio
    async def test_integracion_hermes_real(self):
        accion_peligrosa = {"comando": "rm -rf /var/lib/docker"}
        decision, sugerencia = await consultar_hermes(accion_peligrosa)
        
        assert decision in ["approved", "rejected"]
        assert isinstance(sugerencia, str)

    @pytestmark_integration
    @patch("acp_api.mcp_server.run", new_callable=AsyncMock)
    def test_integracion_mcp_endpoint_montado(self, mock_run, client):
        """Verifica que la app FastAPI ha delegado correctamente el enrutamiento a MCP sin atascarse en el stream."""
        response = client.get("/mcp/sse")
        assert response.status_code == 200
