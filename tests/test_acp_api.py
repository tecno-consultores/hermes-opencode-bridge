import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from acp_api import (
    active_sse_queues,
    app,
    background_opencode_task,
    consultar_hermes,
    ejecutar_tarea_opencode,
    sse_bulletproof,
)

# --- Fixtures ---

@pytest.fixture
def client():
    """Provee un cliente de pruebas para FastAPI."""
    return TestClient(app)

@pytest.fixture(autouse=True)
def reset_sse_queues():
    """Limpia el diccionario global de colas SSE antes de cada prueba."""
    active_sse_queues.clear()
    yield

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
    async def test_consultar_hermes_markdown_correction(self, mock_httpx_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '```json\n{"decision": "approved", "suggestion": ""}\n```'}}]
        }
        
        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_httpx_client.return_value.__aenter__.return_value = mock_client_instance

        decision, _ = await consultar_hermes({"accion": "test"})
        assert decision == "approved"

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.httpx.AsyncClient")
    async def test_consultar_hermes_exception_fallback(self, mock_httpx_client):
        mock_client_instance = AsyncMock()
        mock_client_instance.post.side_effect = Exception("Simulated Timeout")
        mock_httpx_client.return_value.__aenter__.return_value = mock_client_instance

        decision, _ = await consultar_hermes({"accion": "test"})
        assert decision == "approved"

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.asyncio.create_subprocess_exec")
    async def test_ejecutar_tarea_opencode_basico(self, mock_create_subprocess):
        mock_process = MagicMock()
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
        mock_create_subprocess.return_value = mock_process

        resultado = await ejecutar_tarea_opencode("saluda")
        assert resultado == "Hola"
        mock_process.terminate.assert_called_once()

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.consultar_hermes")
    @patch("acp_api.asyncio.create_subprocess_exec")
    async def test_ejecutar_tarea_opencode_flujo_complejo(self, mock_create_subprocess, mock_consultar):
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdin.drain = AsyncMock()
        mock_process.stdout = MagicMock()
        mock_process.stdout.readline = AsyncMock()
        
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

        await ejecutar_tarea_opencode("haz algo malo")
        mock_consultar.assert_called_once()

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.asyncio.create_subprocess_exec")
    async def test_ejecutar_tarea_opencode_sin_pipes(self, mock_create_subprocess):
        mock_process = MagicMock()
        mock_process.stdin = None
        mock_create_subprocess.return_value = mock_process
        
        with pytest.raises(RuntimeError):
            await ejecutar_tarea_opencode("test")

    @pytestmark_unit
    @pytest.mark.asyncio
    @patch("acp_api.ejecutar_tarea_opencode")
    async def test_background_opencode_task(self, mock_ejecutar):
        mock_ejecutar.return_value = "Todo bien"
        await background_opencode_task("test")
        
        mock_ejecutar.side_effect = Exception("Fallo catastrófico")
        await background_opencode_task("test")
        
        assert mock_ejecutar.call_count == 2

    # --- Pruebas SSE (FastAPI Routing) ---
    
    @pytestmark_unit
    @patch("acp_api.asyncio.Queue")
    def test_sse_endpoint_get_stream(self, mock_queue_cls, client):
        """Cubre el generador SSE y suprime warnings de corrutinas no esperadas."""
        mock_queue_instance = MagicMock()
        mock_queue_instance.get = AsyncMock(side_effect=[asyncio.TimeoutError(), asyncio.CancelledError()])
        mock_queue_cls.return_value = mock_queue_instance
        
        response = client.get("/sse")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    @pytestmark_unit
    def test_sse_endpoint_head(self, client):
        response = client.head("/sse")
        assert response.status_code == 200
        assert "mcp-protocol-version" in response.headers

    @pytestmark_unit
    def test_sse_endpoint_post_invalid_json(self, client):
        response = client.post("/sse", content=b"esto_no_es_json")
        assert response.status_code == 400

    @pytestmark_unit
    def test_sse_endpoint_post_no_id(self, client):
        response = client.post("/sse", json={"method": "notifications/initialized"})
        assert response.status_code == 202

    @pytestmark_unit
    def test_sse_endpoint_post_initialize(self, client):
        payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        response = client.post("/sse", json=payload)
        assert response.status_code == 200
        assert response.json()["id"] == 1

    @pytestmark_unit
    @patch("acp_api.BackgroundTasks.add_task")
    def test_sse_endpoint_post_tools_call(self, mock_add_task, client):
        payload = {
            "jsonrpc": "2.0", 
            "id": 3, 
            "method": "tools/call",
            "params": {"arguments": {"instruction": "print('Hola')"}}
        }
        response = client.post("/sse", json=payload)
        assert response.status_code == 200
        mock_add_task.assert_called_once()

    @pytestmark_unit
    @pytest.mark.asyncio
    async def test_sse_endpoint_post_routes_to_queue(self):
        """Verifica que si existe un session_id en la URL, el payload se envía a su cola."""
        # Fix: Usar MagicMock para los métodos sincrónicos y AsyncMock sólo para el JSON.
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.headers = {}
        mock_request.json = AsyncMock(return_value={"id": 99, "method": "initialize"})
        mock_request.query_params.get.return_value = "fake-session"
        
        active_sse_queues["fake-session"] = AsyncMock()
        await sse_bulletproof(mock_request, MagicMock())
        active_sse_queues["fake-session"].put.assert_called_once()

    @pytestmark_unit
    @pytest.mark.asyncio
    async def test_sse_endpoint_fallback_405(self):
        mock_request = MagicMock()
        mock_request.method = "PUT"
        mock_request.headers = {}
        response = await sse_bulletproof(mock_request, MagicMock())
        assert response.status_code == 405

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
    def test_integracion_sse_stream(self):
        import requests
        try:
            url = "http://127.0.0.1:8000/sse"
            response = requests.get(url, stream=True, timeout=5)
            assert response.status_code == 200
            
            primer_evento = next(response.iter_lines()).decode('utf-8')
            assert "event: endpoint" in primer_evento or "data:" in primer_evento
            response.close()
        except requests.exceptions.ConnectionError:
            pytest.skip("API de integración no disponible en http://127.0.0.1:8000")
