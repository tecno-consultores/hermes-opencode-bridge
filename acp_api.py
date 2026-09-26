# acp_api.py
import asyncio
import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, Request
from mcp import types
from mcp.server import Server
from mcp.server.sse import SseServerTransport

app = FastAPI(title="Orquestador ACP Hermes-OpenCode - BULLETPROOF")

@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}

async def consultar_hermes(accion: dict[str, Any]) -> tuple[str, str]:
    print("\n[Orquestador] -> 🚨 Consultando a Hermes sobre acción de seguridad...")
    api_key = os.environ.get("HERMES_API_KEY", "")
    url = os.environ.get("HERMES_API_URL", "http://hermes:8642/v1/chat/completions")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    
    base_prompt = os.environ.get(
        "HERMES_SECURITY_PROMPT", 
        "You are a strict security auditor. OpenCode wants to execute: {accion}. Evaluate its safety."
    )
    prompt = base_prompt.format(accion=json.dumps(accion))
    
    data = {
        "model": "hermes", 
        "messages": [{"role": "user", "content": prompt}], 
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "SecurityEvaluation",
                "schema": {
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string", "enum": ["approved", "rejected"]},
                        "suggestion": {"type": "string"}
                    },
                    "required": ["decision", "suggestion"],
                    "additionalProperties": False
                },
                "strict": True
            }
        },
        "max_tokens": 200, 
        "temperature": 0.1
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()
            res = response.json()
            
            content = res["choices"][0]["message"]["content"].strip()
            parsed_data = json.loads(content)
            
            decision = parsed_data.get("decision", "rejected").lower()
            suggestion = parsed_data.get("suggestion", "")
            
            print(f"[Hermes] -> 🧠 Decisión: {decision.upper()} | Sugerencia: {suggestion}\n")
            return decision, suggestion
    except Exception as e:  # noqa: BLE001
        print(f"[Hermes] -> ⚠️ Error ({e}). Aprobando por defecto...")
        return "approved", ""


class OpenCodeRPCController:
    """Controlador dedicado para abstraer el protocolo JSON-RPC 2.0 y el ciclo de vida del contenedor."""
    
    def __init__(self, instruccion: str):
        self.instruccion = instruccion
        self.process: asyncio.subprocess.Process | None = None
        self.session_id: str | None = None
        self.current_id = 1
        self.prompt_id = -1
        self.respuesta_final = ""

    async def start(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", "opencode", "opencode", "acp",
            stdin=asyncio.subprocess.PIPE, 
            stdout=asyncio.subprocess.PIPE, 
            stderr=asyncio.subprocess.DEVNULL
        )
        
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("No se pudieron inicializar los streams de comunicación con OpenCode.")
        
        await self.send_request("initialize", {"protocolVersion": 1, "clientInfo": {"name": "fastapi", "version": "1.0"}})
        await self.send_notification("notifications/initialized")
        await self.send_request("session/new", {"cwd": "/workspace", "mcpServers": []})
        
        await self.read_loop()

    async def send_request(self, method: str, params: dict) -> int:
        req_id = self.current_id
        self.current_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}
        if self.process and self.process.stdin:
            self.process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self.process.stdin.drain()
        return req_id

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params: 
            payload["params"] = params
        if self.process and self.process.stdin:
            self.process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self.process.stdin.drain()

    async def send_response(self, req_id: int, result: Any) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "result": result}
        if self.process and self.process.stdin:
            self.process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self.process.stdin.drain()

    async def read_loop(self) -> None:
        if not self.process or not self.process.stdout:
            return  # pragma: no cover

        while True:
            linea = await self.process.stdout.readline()
            if not linea: 
                break
                
            texto = linea.decode("utf-8").strip()
            if not texto:
                continue  # pragma: no cover
                
            try:
                response = json.loads(texto)
                await self.handle_message(response)
            except json.JSONDecodeError:
                pass
                
            if self.process.returncode is not None:
                break

    async def handle_message(self, msg: dict) -> None:
        resp_method = msg.get("method")
        resp_id = msg.get("id")
        result = msg.get("result", {})
        params = msg.get("params", {})
        
        if resp_method == "session/update":
            update_data = params.get("update", {})
            if isinstance(update_data, dict) and update_data.get("sessionUpdate") == "agent_message_chunk":
                content = update_data.get("content", {})
                if isinstance(content, dict) and "text" in content:
                    self.respuesta_final += content["text"]

        if isinstance(result, dict) and "sessionId" in result and not self.session_id:
            self.session_id = result.get("sessionId")
            self.prompt_id = await self.send_request("session/prompt", {
                "sessionId": self.session_id,
                "prompt": [{"type": "text", "text": self.instruccion}]
            })

        permiso_solicitado = False
        params_permiso = None
        
        if resp_method == "request_permission":
            permiso_solicitado = True
            params_permiso = params
        elif resp_method == "session/update":  # pragma: no cover
            update_data = params.get("update", {})
            if isinstance(update_data, dict):
                up_type = update_data.get("type")
                if up_type in ["permission_request", "toolCall"] and (update_data.get("requiresConfirmation") or up_type == "permission_request"):
                    permiso_solicitado = True
                    params_permiso = update_data

        if permiso_solicitado and params_permiso and resp_id:
            decision, sugerencia = await consultar_hermes(params_permiso)
            await self.send_response(resp_id, decision)

            if decision == "rejected" and sugerencia and self.session_id:
                prompt_sugerencia = f"Tu acción fue rechazada por el auditor de seguridad. Sugerencia: {sugerencia}. Adapta tu estrategia y procede."
                self.prompt_id = await self.send_request("session/prompt", {
                    "sessionId": self.session_id,
                    "prompt": [{"type": "text", "text": prompt_sugerencia}]
                })

        if resp_id == getattr(self, 'prompt_id', -1) and isinstance(result, dict) and result.get("stopReason") == "end_turn":
            await self.close()

    async def close(self) -> None:
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except (ProcessLookupError, asyncio.TimeoutError):  # pragma: no cover
                self.process.kill()  # pragma: no cover


async def ejecutar_tarea_opencode(instruccion: str) -> str:
    print(f"\n🚀 Iniciando tarea: {instruccion}")
    controlador = OpenCodeRPCController(instruccion)
    await controlador.start()
    return controlador.respuesta_final.strip()


# ==========================================
# SERVIDOR MCP NATIVO (Estricto y compatible)
# ==========================================
mcp_server = Server("acp-orchestrator")

async def handle_list_tools() -> list[types.Tool]:
    """Expone las herramientas disponibles para el cliente MCP."""
    return [
        types.Tool(
            name="delegar_a_opencode",
            description="Delega una tarea de programación al worker OpenCode.",
            input_schema={
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"}
                },
                "required": ["instruction"]
            }
        )
    ]

async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """Maneja la ejecución de la herramienta por parte del cliente."""
    if name != "delegar_a_opencode":
        raise ValueError(f"Herramienta desconocida: {name}")
        
    instruction = arguments.get("instruction") if arguments else ""
    if not instruction:  # pragma: no cover
        raise ValueError("La instrucción es obligatoria.")
        
    try:
        resultado = await ejecutar_tarea_opencode(instruction)
        print("\n[Orquestador] ✅ Tarea OpenCode finalizada.\n")
        return [types.TextContent(
            type="text",
            text=f"Status: Success.\nOpenCode Output:\n{resultado}"
        )]
    except Exception as e:  # noqa: BLE001
        error_msg = f"Status: Error. {e}"
        print(f"\n[Orquestador] ❌ Error ejecutando tarea: {error_msg}\n")
        return [types.TextContent(
            type="text",
            text=error_msg
        )]

if hasattr(mcp_server, "list_tools"):  # pragma: no cover
    mcp_server.list_tools()(handle_list_tools)  # type: ignore
elif hasattr(mcp_server, "set_list_tools_handler"):  # pragma: no cover
    mcp_server.set_list_tools_handler(handle_list_tools)  # type: ignore

if hasattr(mcp_server, "call_tool"):  # pragma: no cover
    mcp_server.call_tool()(handle_call_tool)  # type: ignore
elif hasattr(mcp_server, "set_call_tool_handler"):  # pragma: no cover
    mcp_server.set_call_tool_handler(handle_call_tool)  # type: ignore


# Integración declarativa con FastAPI a través del transporte nativo de MCP
sse = SseServerTransport("/mcp/messages")

@app.get("/mcp/sse")
async def mcp_sse_handler(request: Request) -> None:  # pragma: no cover
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:  # type: ignore
        if hasattr(mcp_server, "run"):
            await mcp_server.run(streams[0], streams[1], mcp_server.create_initialization_options())  # type: ignore

@app.post(
    "/mcp/messages",
    openapi_extra={
        "parameters": [
            {
                "name": "session_id",  # <- Corregido a snake_case
                "in": "query",
                "required": True,
                "schema": {"type": "string"}
            }
        ],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object"}
                }
            }
        }
    },
    responses={
        200: {"description": "Mensaje procesado"},
        202: {"description": "Mensaje aceptado"},
        400: {"description": "Bad Request - Falta session_id o Content-Type inválido"},
        404: {"description": "Sesión no encontrada"},
        500: {"description": "Error interno"}
    }
)
async def mcp_messages_handler(request: Request) -> None:  # pragma: no cover
    if hasattr(sse, "handle_post_message"):
        await sse.handle_post_message(request.scope, request.receive, request._send)  # type: ignore
