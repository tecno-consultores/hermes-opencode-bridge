# SPDX-License-Identifier: GPL-2.0-only
"""Pruebas de contrato exactas (payloads, mensajes y logs) para elevar el MSI de mutación."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient

import acp_api
from acp_api import OpenCodeRPCController, ejecutar_tarea_opencode
from tests.fakes import TOOL_CALL, FakeOpenCode

pytestmark = pytest.mark.unit

TOKEN = "token-de-prueba-0123456789abcdef"


def _spawn(agent: FakeOpenCode) -> Any:
    return patch("acp_api.asyncio.create_subprocess_exec", new=AsyncMock(return_value=agent.process))


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "acp_api"]


# ------------------------------------------------------------ auditoría
class TestContratoHermes:
    def test_payload_exacto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HERMES_MODEL", "modelo-x")
        assert acp_api._audit_payload("P") == {
            "model": "modelo-x",
            "messages": [{"role": "user", "content": "P"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "SecurityEvaluation",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "decision": {"type": "string", "enum": ["approved", "rejected"]},
                            "suggestion": {"type": "string"},
                        },
                        "required": ["decision", "suggestion"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
            "max_tokens": 200,
            "temperature": 0.1,
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("timeout_env", "esperado"), [(None, 15.0), ("7", 7.0)])
    async def test_request_hermes_contrato(
        self, monkeypatch: pytest.MonkeyPatch, timeout_env: str | None, esperado: float
    ) -> None:
        if timeout_env:
            monkeypatch.setenv("HERMES_TIMEOUT", timeout_env)
        monkeypatch.setenv("HERMES_API_KEY", "k")
        response = MagicMock()
        response.json.return_value = {"choices": [{"message": {"content": " texto "}}]}
        client = AsyncMock()
        client.post.return_value = response
        with patch("acp_api.httpx.AsyncClient") as cls:
            cls.return_value.__aenter__.return_value = client
            assert await acp_api._request_hermes("P") == " texto "
        assert cls.call_args == call(timeout=esperado)
        assert client.post.call_args.kwargs["headers"] == {
            "Content-Type": "application/json",
            "Authorization": "Bearer k",
        }
        assert client.post.call_args.kwargs["json"] == acp_api._audit_payload("P")
        response.raise_for_status.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_logs_de_exito(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger="acp_api")
        with patch("acp_api._request_hermes", new=AsyncMock(return_value='{"decision":"approved","suggestion":"s"}')):
            assert await acp_api.consultar_hermes({"a": 1}) == ("approved", "s")
        assert _messages(caplog) == [
            "Consultando a Hermes sobre una solicitud de permiso de OpenCode",
            "Hermes decidió APPROVED",
            "Sugerencia del auditor: s",
        ]

    @pytest.mark.asyncio
    async def test_log_fail_closed(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="acp_api")
        with patch("acp_api._request_hermes", new=AsyncMock(side_effect=RuntimeError("boom"))):
            assert await acp_api.consultar_hermes({"a": 1}) == ("rejected", "")
        record = caplog.records[-1]
        assert record.levelno == logging.WARNING
        assert record.getMessage() == (
            "Auditoría no disponible (RuntimeError: boom); acción RECHAZADA por política fail-closed"
        )

    def test_env_number_log(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("HERMES_TIMEOUT", "abc")
        assert acp_api._env_number("HERMES_TIMEOUT", 15.0) == 15.0
        assert _messages(caplog) == ["Valor inválido para HERMES_TIMEOUT='abc'; usando 15.0"]

    def test_prompt_exacto_unicode_y_no_serializable(self) -> None:
        fecha = dt.date(2026, 1, 2)
        prompt = acp_api.build_audit_prompt({"ruta": "año", "fecha": fecha})
        assert prompt == acp_api.DEFAULT_SECURITY_PROMPT.replace("{accion}", '{"ruta": "año", "fecha": "2026-01-02"}')

    def test_truncado_exacto(self) -> None:
        prompt = acp_api.build_audit_prompt({"d": "x" * 9000})
        bloque = prompt.split("<action>\n", 1)[1].split("\n</action>", 1)[0]
        assert len(bloque) == acp_api.MAX_ACTION_CHARS + len("...[truncated]")
        assert bloque.endswith("...[truncated]")
        assert acp_api.MAX_ACTION_CHARS == 8000

    def test_accion_justo_en_el_limite_no_se_trunca(self) -> None:
        relleno = "x" * (acp_api.MAX_ACTION_CHARS - len('{"d": ""}'))
        prompt = acp_api.build_audit_prompt({"d": relleno})
        assert "...[truncated]" not in prompt

    @pytest.mark.parametrize(
        ("entrada", "salida"),
        [("```\n{}\n```", "{}"), ("  {} ", "{}"), ("```json{}```", ""), ("```json\n{}", "{}")],
    )
    def test_strip_code_fence(self, entrada: str, salida: str) -> None:
        assert acp_api._strip_code_fence(entrada) == salida

    @pytest.mark.parametrize(
        ("content", "mensaje"),
        [
            ("[]", "La respuesta del auditor no es un objeto JSON"),
            ('{"decision": "x"}', "Decisión inválida del auditor: 'x'"),
        ],
    )
    def test_mensajes_de_error(self, content: str, mensaje: str) -> None:
        with pytest.raises(ValueError) as exc:
            acp_api.parse_decision(content)
        assert str(exc.value) == mensaje

    def test_constantes(self) -> None:
        assert acp_api.MAX_SUGGESTION_CHARS == 1000
        assert acp_api.STREAM_LIMIT == 16 * 1024 * 1024
        assert acp_api.JSONRPC_METHOD_NOT_FOUND == -32601
        assert acp_api.PERMISSION_KINDS == {
            "approved": ("allow_once",),
            "rejected": ("reject_once", "reject_always"),
        }


# ------------------------------------------------------------ ACP
class TestContratoACP:
    @pytest.mark.asyncio
    async def test_mensajes_exactos(self) -> None:
        agent = FakeOpenCode()
        with _spawn(agent) as spawn:
            controller = OpenCodeRPCController("tarea")
            assert controller.container == "opencode"
            assert controller.workspace == "/workspace"
            assert controller.respuesta_final == ""
            await controller.run()

        assert spawn.call_args == call(
            "docker",
            "exec",
            "-i",
            "opencode",
            "opencode",
            "acp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=acp_api.STREAM_LIMIT,
        )
        assert agent.received[:2] == [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": 1,
                    "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                    "clientInfo": {"name": "hermes-opencode-bridge", "version": acp_api.__version__},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {"cwd": "/workspace", "mcpServers": []},
            },
        ]
        assert agent.requests("session/prompt") == [
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/prompt",
                "params": {"sessionId": "s-1", "prompt": [{"type": "text", "text": "tarea"}]},
            }
        ]
        assert all(raw.endswith(b"\n") and raw.count(b"\n") == 1 for raw in agent.process.stdin.raw)

    @pytest.mark.asyncio
    async def test_respuestas_jsonrpc_exactas(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="acp_api")
        agent = FakeOpenCode(permissions_per_prompt=1, agent_requests=(("fs/read_text_file", {"path": "/x"}),))
        with patch("acp_api.consultar_hermes", new=AsyncMock(return_value=("approved", ""))), _spawn(agent):
            await OpenCodeRPCController("x").run()
        assert agent.permission_responses == [
            {
                "jsonrpc": "2.0",
                "id": "agent-1",
                "result": {"outcome": {"outcome": "selected", "optionId": "allow-once"}},
            }
        ]
        assert agent.agent_request_responses == [
            {
                "jsonrpc": "2.0",
                "id": "agent-2",
                "error": {"code": -32601, "message": "Método no soportado: fs/read_text_file"},
            }
        ]
        mensajes = _messages(caplog)
        assert "Petición ACP no soportada por el puente: fs/read_text_file" in mensajes
        assert "Turno de OpenCode finalizado (stopReason=end_turn)" in mensajes

    @pytest.mark.asyncio
    async def test_rondas_por_defecto_y_texto_de_feedback(self) -> None:
        agent = FakeOpenCode(permissions_per_prompt=1, permissions_every_prompt=True)
        with (
            patch("acp_api.consultar_hermes", new=AsyncMock(return_value=("rejected", "usa /tmp"))),
            _spawn(agent),
        ):
            await OpenCodeRPCController("x").run()
        assert len(agent.prompts) == 4  # 1 prompt + MAX_FEEDBACK_ROUNDS (3) por defecto
        assert agent.prompts[1] == (
            "Una o más acciones fueron rechazadas por el auditor de seguridad. "
            "Sugerencias:\n- usa /tmp\n"
            "Adapta tu estrategia y continúa con la tarea original."
        )

    def test_consume_feedback_multiple_y_limpia(self) -> None:
        controller = OpenCodeRPCController("x")
        controller._feedback.extend(["a", "b"])
        assert "Sugerencias:\n- a\n- b\n" in controller._consume_feedback()
        assert controller._feedback == []

    @pytest.mark.asyncio
    async def test_logs_stderr_y_linea_no_json(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger="acp_api")
        agent = FakeOpenCode(stderr_lines=(b"aviso \xff\n",), extra_lines=(b"basura\n", b"\xff\xfe\n"))
        with _spawn(agent):
            assert await OpenCodeRPCController("x").run() == "Hola mundo"
        mensajes = _messages(caplog)
        assert "[opencode] aviso \ufffd" in mensajes
        assert mensajes.count("Línea no JSON ignorada en el canal ACP") == 2

    @pytest.mark.asyncio
    async def test_log_error_de_lectura(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.ERROR, logger="acp_api")
        agent = FakeOpenCode(stdout_limit=256, chunks=("x" * 1000,))
        with _spawn(agent), pytest.raises(acp_api.ACPError) as exc:
            await OpenCodeRPCController("x").run()
        assert str(exc.value) == "OpenCode cerró el canal ACP"
        assert _messages(caplog)[0].startswith("Fallo leyendo el canal ACP: ")

    @pytest.mark.asyncio
    async def test_mensajes_de_error_exactos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = FakeOpenCode(errors={"initialize": {"code": 1, "message": "m"}})
        with _spawn(agent), pytest.raises(acp_api.ACPError) as exc:
            await OpenCodeRPCController("x").run()
        assert str(exc.value) == "OpenCode devolvió un error: {'code': 1, 'message': 'm'}"

        monkeypatch.setenv("OPENCODE_TASK_TIMEOUT", "0.02")
        agent = FakeOpenCode(hang_prompt=True)
        with _spawn(agent), pytest.raises(acp_api.ACPError) as exc:
            await OpenCodeRPCController("x").run()
        assert str(exc.value) == "La tarea de OpenCode superó el límite de 0s"

    @pytest.mark.asyncio
    async def test_close_cancela_tareas_y_cierra_canal(self) -> None:
        agent = FakeOpenCode(hang_prompt=True)
        with _spawn(agent):
            controller = OpenCodeRPCController("x")
            await controller.start()
            await controller.close()
        assert all(t.done() for t in controller._tasks)
        assert controller._channel_closed is True
        assert agent.process.stdin.closed is True
        assert agent.process.terminated is False

    @pytest.mark.asyncio
    async def test_proceso_que_ya_termino_no_se_toca(self) -> None:
        agent = FakeOpenCode()
        agent.process.exit(0)
        with _spawn(agent):
            controller = OpenCodeRPCController("x")
            await controller.start()
            await controller.close()
        assert agent.process.stdin.closed is False

    @pytest.mark.asyncio
    async def test_terminate_suficiente_no_hace_kill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(OpenCodeRPCController, "CLOSE_TIMEOUT", 0.01)
        agent = FakeOpenCode(ignore_stdin_close=True)
        controller = OpenCodeRPCController("x")
        await controller._wait_or_kill(agent.process)  # type: ignore[arg-type]
        assert agent.process.terminated is True
        assert agent.process.killed is False

    def test_close_timeout_por_defecto(self) -> None:
        assert OpenCodeRPCController.CLOSE_TIMEOUT == 5.0

    @pytest.mark.asyncio
    async def test_resolve_ignora_futuro_ya_resuelto(self) -> None:
        controller = OpenCodeRPCController("x")
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        future.set_result({"ok": 1})
        controller._pending[1] = future
        controller._resolve_response({"id": 1, "result": {"otro": 2}})
        assert future.result() == {"ok": 1}

    @pytest.mark.asyncio
    async def test_resultado_no_dict_se_normaliza(self) -> None:
        controller = OpenCodeRPCController("x")
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        controller._pending[7] = future
        controller._resolve_response({"id": 7, "result": None})
        assert future.result() == {}
        assert 7 not in controller._pending

    @pytest.mark.asyncio
    async def test_notificacion_con_params_no_dict(self) -> None:
        controller = OpenCodeRPCController("x")
        await controller.handle_message({"method": "session/update", "params": ["x"]})
        controller._handle_notification(
            "otra", {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "no"}}}
        )
        assert controller.respuesta_final == ""

    @pytest.mark.asyncio
    async def test_permiso_audita_toolcall(self) -> None:
        controller = OpenCodeRPCController("x")
        with patch("acp_api.consultar_hermes", new=AsyncMock(return_value=("approved", "ignorada"))) as hermes:
            await controller._resolve_permission({"toolCall": TOOL_CALL, "options": []})
        hermes.assert_awaited_once_with(TOOL_CALL)
        assert controller._feedback == []


class TestConcurrencia:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("valor", "esperado"), [(None, 1), ("0", 1), ("2", 2)])
    async def test_limite(self, monkeypatch: pytest.MonkeyPatch, valor: str | None, esperado: int) -> None:
        if valor is not None:
            monkeypatch.setenv("MAX_CONCURRENT_TASKS", valor)
        activos = maximo = 0

        async def fake_run(self: OpenCodeRPCController) -> str:
            nonlocal activos, maximo
            activos += 1
            maximo = max(maximo, activos)
            await asyncio.sleep(0.01)
            activos -= 1
            return ""

        monkeypatch.setattr(OpenCodeRPCController, "run", fake_run)
        await asyncio.gather(*(ejecutar_tarea_opencode("t") for _ in range(4)))
        assert maximo == esperado
        assert acp_api._get_task_semaphore() is acp_api._get_task_semaphore()

    @pytest.mark.asyncio
    async def test_logs(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG, logger="acp_api")
        monkeypatch.setattr(OpenCodeRPCController, "run", AsyncMock(return_value="r"))
        assert await ejecutar_tarea_opencode("hola") == "r"
        assert _messages(caplog) == ["Iniciando tarea OpenCode (4 caracteres)", "Instrucción: hola"]


# ------------------------------------------------------------ MCP / HTTP
class TestContratoHTTP:
    def test_definicion_de_la_herramienta(self) -> None:
        tool = acp_api.TOOL_DEFINITION
        assert tool.name == "delegar_a_opencode"
        assert tool.description is not None
        assert tool.description.startswith("Delega una tarea de programación al worker OpenCode.")
        assert tool.input_schema == {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "Instrucciones detalladas, paso a paso, para OpenCode.",
                }
            },
            "required": ["instruction"],
        }

    @pytest.mark.asyncio
    async def test_logs_de_handle_call_tool(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="acp_api")
        params = acp_api.types.CallToolRequestParams(name="delegar_a_opencode", arguments={"instruction": "x"})
        with patch("acp_api.ejecutar_tarea_opencode", new=AsyncMock(return_value="ok")):
            result = await acp_api.handle_call_tool(None, params)
        assert result.is_error is not True
        assert _messages(caplog)[-1] == "Tarea OpenCode finalizada"
        with patch("acp_api.ejecutar_tarea_opencode", new=AsyncMock(side_effect=ValueError("v"))):
            await acp_api.handle_call_tool(None, params)
        assert _messages(caplog)[-1] == "Error ejecutando tarea OpenCode: ValueError: v"

    def test_tool_error(self) -> None:
        result = acp_api._tool_error("m")
        assert result.is_error is True
        assert result.content[0].type == "text"
        assert result.content[0].text == "m"  # type: ignore[union-attr]

    def test_401_exacto(self, caplog: pytest.LogCaptureFixture) -> None:
        response = TestClient(acp_api.app).get("/mcp/sse")
        assert response.status_code == 401
        assert response.json() == {"detail": "Unauthorized"}
        assert response.headers["content-type"] == "application/json"
        assert "Conexión MCP no autorizada a /mcp/sse" in _messages(caplog)

    def test_405_exacto(self) -> None:
        response = TestClient(acp_api.app).head("/mcp/sse", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 405
        assert response.headers["allow"] == "GET"
        assert response.headers["content-type"] == "application/json"

    def test_503_exacto(self) -> None:
        response = TestClient(acp_api.app).post("/mcp", json={}, headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.json() == {"detail": "MCP session manager not running"}

    def test_sse_pasa_opciones_de_inicializacion(self) -> None:
        @contextlib.asynccontextmanager
        async def fake_connect(scope: Any, receive: Any, send: Any) -> Any:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            yield ("r", "w")

        sentinel = object()
        with (
            patch.object(acp_api.sse, "connect_sse", new=fake_connect),
            patch.object(acp_api.mcp_server, "run", new=AsyncMock()) as run,
            patch.object(acp_api.mcp_server, "create_initialization_options", return_value=sentinel),
        ):
            TestClient(acp_api.app).get("/mcp/sse", headers={"Authorization": f"Bearer {TOKEN}"})
        run.assert_awaited_once_with("r", "w", sentinel)

    @pytest.mark.parametrize(
        "headers",
        [
            [(b"Authorization", f"Bearer {TOKEN}".encode())],
            [(b"authorization", f"BEARER   {TOKEN}  ".encode())],
            [(b"x-otra", b"1"), (b"authorization", f"Bearer {TOKEN}".encode())],
        ],
    )
    def test_extract_token_variantes(self, headers: list[tuple[bytes, bytes]]) -> None:
        assert acp_api._extract_token({"headers": headers}) == TOKEN

    def test_extract_token_query_con_otros_parametros(self) -> None:
        assert acp_api._extract_token({"query_string": f"a=1&token={TOKEN}".encode()}) == TOKEN
        assert acp_api._extract_token({}) == ""

    def test_log_sin_clave(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("ACP_API_KEY", "")
        assert acp_api.is_authorized({}) is False
        assert _messages(caplog) == ["ACP_API_KEY no configurado: se rechazan todas las conexiones MCP"]

    def test_endpoint_guarda_configuracion(self) -> None:
        handler = AsyncMock()
        endpoint = acp_api.MCPEndpoint(handler, require_auth=False)
        assert endpoint.handler is handler
        assert endpoint.require_auth is False

    def test_transport_security_ignora_vacios(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", " , ")
        assert acp_api._transport_security() is None
