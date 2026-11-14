# SPDX-License-Identifier: GPL-2.0-only
"""Dobles de prueba compartidos: un agente OpenCode ACP simulado sobre stdio."""

from __future__ import annotations

import asyncio
import json
from typing import Any

PERMISSION_OPTIONS = [
    {"optionId": "allow-always", "name": "Permitir siempre", "kind": "allow_always"},
    {"optionId": "allow-once", "name": "Permitir", "kind": "allow_once"},
    {"optionId": "reject-once", "name": "Rechazar", "kind": "reject_once"},
]
TOOL_CALL = {"toolCallId": "call-1", "title": "rm -rf /", "kind": "execute"}
DEFAULT_RESULTS: dict[str, dict[str, Any]] = {
    "initialize": {"protocolVersion": 1, "agentCapabilities": {}},
    "session/new": {"sessionId": "s-1"},
}


class FakeStdin:
    def __init__(self, agent: FakeOpenCode) -> None:
        self._agent = agent
        self.closed = False
        self.raw: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.raw.append(data)
        for line in data.decode("utf-8").splitlines():
            if line.strip():
                self._agent.on_client_message(json.loads(line))

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self.closed = True
        if not self._agent.ignore_stdin_close:
            self._agent.process.exit(0)


class FakeProcess:
    def __init__(self, agent: FakeOpenCode, stdout_limit: int) -> None:
        self.stdin = FakeStdin(agent)
        self.stdout = asyncio.StreamReader(limit=stdout_limit)
        self.stderr = asyncio.StreamReader()
        self.returncode: int | None = None
        self.ignore_terminate = False
        self.terminated = False
        self.killed = False
        self._exited = asyncio.Event()

    def exit(self, code: int) -> None:
        if self.returncode is None:
            self.returncode = code
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self._exited.set()

    def terminate(self) -> None:
        self.terminated = True
        if not self.ignore_terminate:
            self.exit(-15)

    def kill(self) -> None:
        self.killed = True
        self.exit(-9)

    async def wait(self) -> int | None:
        await self._exited.wait()
        return self.returncode


class FakeOpenCode:
    """Simula `opencode acp`: responde al handshake, emite chunks y pide permisos."""

    def __init__(
        self,
        *,
        chunks: tuple[str, ...] = ("Hola", " mundo"),
        permissions_per_prompt: int = 0,
        permissions_every_prompt: bool = False,
        options: list[dict[str, Any]] | None = None,
        stop_reason: str = "end_turn",
        errors: dict[str, dict[str, Any]] | None = None,
        results: dict[str, dict[str, Any]] | None = None,
        hang_prompt: bool = False,
        extra_lines: tuple[bytes, ...] = (),
        agent_requests: tuple[tuple[str, dict[str, Any]], ...] = (),
        stdout_limit: int = 2**16,
        ignore_stdin_close: bool = False,
        stderr_lines: tuple[bytes, ...] = (),
    ) -> None:
        self.chunks = chunks
        self.permissions_per_prompt = permissions_per_prompt
        self.permissions_every_prompt = permissions_every_prompt
        self.options = PERMISSION_OPTIONS if options is None else options
        self.stop_reason = stop_reason
        self.errors = errors or {}
        self.results = results or {}
        self.hang_prompt = hang_prompt
        self.extra_lines = extra_lines
        self.agent_requests = agent_requests
        self.ignore_stdin_close = ignore_stdin_close
        self.received: list[dict[str, Any]] = []
        self.prompts: list[str] = []
        self.permission_responses: list[dict[str, Any]] = []
        self.agent_request_responses: list[dict[str, Any]] = []
        self.process = FakeProcess(self, stdout_limit)
        self._waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._counter = 0
        self.prompt_received = asyncio.Event()
        for line in stderr_lines:
            self.process.stderr.feed_data(line)

    # -- canal hacia el cliente
    def emit_raw(self, data: bytes) -> None:
        if self.process.returncode is None:
            self.process.stdout.feed_data(data)

    def emit(self, payload: dict[str, Any]) -> None:
        self.emit_raw((json.dumps(payload) + "\n").encode("utf-8"))

    def requests(self, method: str) -> list[dict[str, Any]]:
        return [m for m in self.received if m.get("method") == method]

    # -- mensajes del cliente
    def on_client_message(self, msg: dict[str, Any]) -> None:
        self.received.append(msg)
        if "method" not in msg:
            waiter = self._waiters.pop(msg.get("id"), None)
            if waiter is not None and not waiter.done():
                waiter.set_result(msg)
            return
        method = msg["method"]
        if method in self.errors:
            self.emit({"jsonrpc": "2.0", "id": msg["id"], "error": self.errors[method]})
        elif method == "session/prompt":
            self._tasks.append(asyncio.get_running_loop().create_task(self._prompt(msg)))
        else:
            result = self.results.get(method, DEFAULT_RESULTS.get(method, {}))
            self.emit({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    async def _agent_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._counter += 1
        req_id = f"agent-{self._counter}"
        waiter: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._waiters[req_id] = waiter
        self.emit({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        return await waiter

    async def _prompt(self, msg: dict[str, Any]) -> None:
        self.prompts.append(msg["params"]["prompt"][0]["text"])
        self.prompt_received.set()
        first = len(self.prompts) == 1
        for raw in self.extra_lines if first else ():
            self.emit_raw(raw)
        for chunk in self.chunks:
            self.emit(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "s-1",
                        "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": chunk}},
                    },
                }
            )
        count = self.permissions_per_prompt if (first or self.permissions_every_prompt) else 0
        for _ in range(count):
            response = await self._agent_request(
                "session/request_permission",
                {"sessionId": "s-1", "toolCall": TOOL_CALL, "options": self.options},
            )
            self.permission_responses.append(response)
        for method, params in self.agent_requests if first else ():
            self.agent_request_responses.append(await self._agent_request(method, params))
        if not self.hang_prompt:
            self.emit({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": self.stop_reason}})
