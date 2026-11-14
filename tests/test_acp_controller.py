# SPDX-License-Identifier: GPL-2.0-only
"""Cliente ACP contra un OpenCode simulado (protocolo session/request_permission real)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import acp_api
from acp_api import ACPError, OpenCodeRPCController, ejecutar_tarea_opencode
from tests.fakes import TOOL_CALL, FakeOpenCode

pytestmark = pytest.mark.unit


@pytest.fixture
def hermes() -> Iterator[AsyncMock]:
    with patch("acp_api.consultar_hermes", new_callable=AsyncMock) as mock:
        mock.return_value = ("approved", "")
        yield mock


def _spawn(agent: FakeOpenCode) -> Any:
    return patch("acp_api.asyncio.create_subprocess_exec", new=AsyncMock(return_value=agent.process))


class TestFlujoBasico:
    @pytest.mark.asyncio
    async def test_handshake_prompt_y_cierre(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENCODE_CONTAINER", "worker")
        monkeypatch.setenv("OPENCODE_WORKSPACE", "/srv/ws")
        agent = FakeOpenCode(stderr_lines=(b"log de opencode\n",))
        with _spawn(agent) as spawn:
            resultado = await OpenCodeRPCController("saluda").run()

        assert resultado == "Hola mundo"
        assert spawn.call_args.args[:6] == ("docker", "exec", "-i", "worker", "opencode", "acp")
        assert spawn.call_args.kwargs["limit"] == acp_api.STREAM_LIMIT
        init = agent.requests("initialize")[0]["params"]
        assert init["protocolVersion"] == 1
        assert init["clientCapabilities"] == {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}
        assert "notifications/initialized" not in {m.get("method") for m in agent.received}
        assert agent.requests("session/new")[0]["params"] == {"cwd": "/srv/ws", "mcpServers": []}
        assert agent.prompts == ["saluda"]
        assert agent.process.stdin.closed is True
        assert agent.process.returncode == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stop_reason", ["end_turn", "max_tokens", "refusal", "cancelled"])
    async def test_cualquier_stop_reason_termina(self, stop_reason: str) -> None:
        """Regresión A2: solo `end_turn` cerraba el flujo; el resto colgaba la tarea."""
        agent = FakeOpenCode(stop_reason=stop_reason)
        with _spawn(agent):
            assert await OpenCodeRPCController("x").run() == "Hola mundo"

    @pytest.mark.asyncio
    async def test_lineas_basura_se_ignoran(self) -> None:
        agent = FakeOpenCode(
            extra_lines=(
                b"\n",
                b"no es json\n",
                b"[1, 2]\n",
                b'{"jsonrpc": "2.0", "id": 999, "result": {}}\n',
                b'{"jsonrpc": "2.0", "id": "x", "result": {}}\n',
                b'{"jsonrpc": "2.0", "method": "session/update", "params": {"update": "raro"}}\n',
                b'{"jsonrpc": "2.0", "method": "otra/notificacion", "params": []}\n',
                b'{"jsonrpc": "2.0", "method": "session/update", "params": {"update": '
                b'{"sessionUpdate": "agent_message_chunk", "content": {"type": "image"}}}}\n',
            )
        )
        with _spawn(agent):
            assert await OpenCodeRPCController("x").run() == "Hola mundo"


class TestPermisos:
    @pytest.mark.asyncio
    async def test_aprobado_responde_allow_once(self, hermes: AsyncMock) -> None:
        agent = FakeOpenCode(permissions_per_prompt=1)
        with _spawn(agent):
            await OpenCodeRPCController("x").run()

        hermes.assert_awaited_once_with(TOOL_CALL)
        assert agent.permission_responses[0]["result"] == {"outcome": {"outcome": "selected", "optionId": "allow-once"}}
        assert agent.prompts == ["x"]

    @pytest.mark.asyncio
    async def test_rechazo_con_sugerencia_reprompt_tras_el_turno(self, hermes: AsyncMock) -> None:
        hermes.return_value = ("rejected", "usa una ruta dentro de /workspace")
        agent = FakeOpenCode(permissions_per_prompt=1)
        with _spawn(agent):
            await OpenCodeRPCController("x").run()

        assert agent.permission_responses[0]["result"] == {
            "outcome": {"outcome": "selected", "optionId": "reject-once"}
        }
        assert len(agent.prompts) == 2
        assert "usa una ruta dentro de /workspace" in agent.prompts[1]
        # El re-prompt solo se envía cuando el turno anterior ha terminado.
        prompt_ids = [m["id"] for m in agent.requests("session/prompt")]
        assert len(set(prompt_ids)) == 2

    @pytest.mark.asyncio
    async def test_rechazo_sin_sugerencia_no_reprompt(self, hermes: AsyncMock) -> None:
        hermes.return_value = ("rejected", "")
        agent = FakeOpenCode(permissions_per_prompt=1)
        with _spawn(agent):
            await OpenCodeRPCController("x").run()
        assert agent.prompts == ["x"]

    @pytest.mark.asyncio
    async def test_limite_de_rondas_de_feedback(self, hermes: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_FEEDBACK_ROUNDS", "2")
        hermes.return_value = ("rejected", "no")
        agent = FakeOpenCode(permissions_per_prompt=1, permissions_every_prompt=True)
        with _spawn(agent):
            await OpenCodeRPCController("x").run()
        assert len(agent.prompts) == 3

    @pytest.mark.asyncio
    async def test_sin_opciones_compatibles_cancela(self, hermes: AsyncMock) -> None:
        agent = FakeOpenCode(permissions_per_prompt=1, options=[{"optionId": "a", "kind": "allow_always"}])
        with _spawn(agent):
            await OpenCodeRPCController("x").run()
        assert agent.permission_responses[0]["result"] == {"outcome": {"outcome": "cancelled"}}

    @pytest.mark.asyncio
    async def test_peticion_sin_toolcall_audita_params(self, hermes: AsyncMock) -> None:
        controller = OpenCodeRPCController("x")
        result = await controller._resolve_permission({"options": []})
        hermes.assert_awaited_once_with({"request": {"options": []}})
        assert result == {"outcome": {"outcome": "cancelled"}}

    @pytest.mark.asyncio
    async def test_metodo_no_soportado_devuelve_error_jsonrpc(self) -> None:
        agent = FakeOpenCode(agent_requests=(("fs/read_text_file", {"path": "/etc/passwd"}),))
        with _spawn(agent):
            await OpenCodeRPCController("x").run()
        error = agent.agent_request_responses[0]["error"]
        assert error["code"] == acp_api.JSONRPC_METHOD_NOT_FOUND


class TestErrores:
    @pytest.mark.asyncio
    async def test_sin_pipes(self) -> None:
        process = MagicMock(stdin=None, stdout=None, returncode=None)
        process.wait = AsyncMock(return_value=0)
        spawn = patch("acp_api.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process))
        with spawn, pytest.raises(RuntimeError, match="streams"):
            await OpenCodeRPCController("x").run()

    @pytest.mark.asyncio
    async def test_error_jsonrpc_de_opencode(self) -> None:
        agent = FakeOpenCode(errors={"session/new": {"code": -32000, "message": "boom"}})
        with _spawn(agent), pytest.raises(ACPError, match="boom"):
            await OpenCodeRPCController("x").run()
        assert agent.process.returncode is not None

    @pytest.mark.asyncio
    async def test_session_id_invalido(self) -> None:
        agent = FakeOpenCode(results={"session/new": {"sessionId": ""}})
        with _spawn(agent), pytest.raises(ACPError, match="sessionId"):
            await OpenCodeRPCController("x").run()

    @pytest.mark.asyncio
    async def test_canal_cerrado_falla_peticiones_pendientes(self) -> None:
        agent = FakeOpenCode(hang_prompt=True)
        with _spawn(agent):
            controller = OpenCodeRPCController("x")
            tarea = asyncio.create_task(controller.run())
            await asyncio.wait_for(agent.prompt_received.wait(), timeout=2)
            agent.process.exit(1)
            with pytest.raises(ACPError, match="cerró"):
                await tarea
        with pytest.raises(ACPError, match="cerrado"):
            await controller.request("session/prompt", {})

    @pytest.mark.asyncio
    async def test_linea_demasiado_larga_cierra_canal(self) -> None:
        """Regresión A4: líneas > límite del StreamReader abortaban sin control."""
        agent = FakeOpenCode(stdout_limit=256, chunks=("x" * 1000,))
        with _spawn(agent), pytest.raises(ACPError, match="cerró"):
            await OpenCodeRPCController("x").run()

    @pytest.mark.asyncio
    async def test_write_sin_proceso(self) -> None:
        with pytest.raises(ACPError, match="no está iniciado"):
            await OpenCodeRPCController("x")._write({})

    @pytest.mark.asyncio
    async def test_timeout_global_escala_a_kill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regresión A2/A3: sin timeout global ni limpieza garantizada del proceso."""
        monkeypatch.setenv("OPENCODE_TASK_TIMEOUT", "0.05")
        monkeypatch.setattr(OpenCodeRPCController, "CLOSE_TIMEOUT", 0.01)
        agent = FakeOpenCode(hang_prompt=True, ignore_stdin_close=True)
        agent.process.ignore_terminate = True
        with _spawn(agent), pytest.raises(ACPError, match="límite"):
            await OpenCodeRPCController("x").run()
        assert agent.process.terminated is True
        assert agent.process.killed is True

    @pytest.mark.asyncio
    async def test_close_idempotente_sin_proceso(self) -> None:
        controller = OpenCodeRPCController("x")
        await controller.close()
        await controller.close()


class TestEjecutarTarea:
    @pytest.mark.asyncio
    async def test_respeta_limite_de_concurrencia(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_CONCURRENT_TASKS", "1")
        activos = 0
        maximo = 0

        async def fake_run(self: OpenCodeRPCController) -> str:
            nonlocal activos, maximo
            activos += 1
            maximo = max(maximo, activos)
            await asyncio.sleep(0.01)
            activos -= 1
            return self.instruccion

        monkeypatch.setattr(OpenCodeRPCController, "run", fake_run)
        resultados = await asyncio.gather(*(ejecutar_tarea_opencode(f"t{i}") for i in range(3)))
        assert resultados == ["t0", "t1", "t2"]
        assert maximo == 1
