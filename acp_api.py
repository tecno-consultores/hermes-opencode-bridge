import asyncio
import json
import os
import uuid
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

app = FastAPI(title="Orquestador ACP Hermes-OpenCode - BULLETPROOF")

# Diccionario para mapear múltiples colas SSE de forma independiente
active_sse_queues: dict[str, asyncio.Queue[Any]] = {}

@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}

class TaskRequest(BaseModel):
    instruction: str

async def consultar_hermes(accion: dict[str, Any]) -> tuple[str, str]:
    print("\n[Orquestador] -> 🚨 Consultando a Hermes sobre acción de seguridad...")
    api_key = os.environ.get("HERMES_API_KEY", "")
    url = os.environ.get("HERMES_API_URL", "http://hermes:8642/v1/chat/completions")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    
    # Extracción de la directiva de seguridad a una variable de entorno con exigencia de formato JSON
    base_prompt = os.environ.get(
        "HERMES_SECURITY_PROMPT", 
        "You are a strict security auditor. OpenCode wants to execute: {accion}. Evaluate its safety. Respond ONLY with a valid JSON object containing two keys: 'decision' (must be 'approved' or 'rejected') and 'suggestion' (feedback or alternative action, leave empty if approved). Do not include markdown formatting."
    )
    prompt = base_prompt.format(accion=json.dumps(accion))
    
    # Incremento de tokens máximos para permitir la generación de sugerencias
    data = {
        "model": "hermes", 
        "messages": [{"role": "user", "content": prompt}], 
        "max_tokens": 200, 
        "temperature": 0.1
    }
    
    # Utilización de httpx con tiempo de espera extendido para compensar la latencia de generación
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()
            res = response.json()
            content = res["choices"][0]["message"]["content"].strip()
            
            # Subrutina de corrección de formato
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
                
            parsed_data = json.loads(content)
            decision = parsed_data.get("decision", "rejected").lower()
            suggestion = parsed_data.get("suggestion", "")
            
            print(f"[Hermes] -> 🧠 Decisión: {decision.upper()} | Sugerencia: {suggestion}\n")
            return decision, suggestion
    except Exception as e:  # noqa: BLE001
        print(f"[Hermes] -> ⚠️ Error ({e}). Aprobando por defecto...")
        return "approved", ""

async def ejecutar_tarea_opencode(instruccion: str) -> str:
    print(f"\n🚀 Iniciando tarea: {instruccion}")
    process = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", "opencode", "opencode", "acp",
        stdin=asyncio.subprocess.PIPE, 
        stdout=asyncio.subprocess.PIPE, 
        stderr=asyncio.subprocess.DEVNULL
    )
    
    # Validación de tuberías (pipes) para satisfacer a Mypy y evitar errores en tiempo de ejecución
    if process.stdin is None or process.stdout is None:
        raise RuntimeError("No se pudieron inicializar los streams de comunicación con OpenCode.")
    
    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {"protocolVersion": 1, "clientInfo": {"name": "fastapi", "version": "1.0"}},
        "id": 1
    }
    process.stdin.write((json.dumps(init_payload) + "\n").encode("utf-8"))
    await process.stdin.drain()
    await process.stdout.readline()
    
    notif_payload = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    process.stdin.write((json.dumps(notif_payload) + "\n").encode("utf-8"))
    await process.stdin.drain()
    
    session_payload = {
        "jsonrpc": "2.0",
        "method": "session/new",
        "id": 2,
        "params": {"cwd": "/workspace", "mcpServers": []}
    }
    process.stdin.write((json.dumps(session_payload) + "\n").encode("utf-8"))
    await process.stdin.drain()

    respuesta_final = ""
    session_id = None
    current_prompt_id = 3

    while True:
        linea = await process.stdout.readline()
        if not linea: 
            break
            
        texto = linea.decode("utf-8").strip()
        if not texto:
            continue
            
        try:
            response = json.loads(texto)
            resp_method = response.get("method")
            resp_id = response.get("id")
            result = response.get("result", {})
            params = response.get("params", {})
            
            if resp_method == "session/update":
                update_data = params.get("update", {})
                if isinstance(update_data, dict) and update_data.get("sessionUpdate") == "agent_message_chunk":
                    content = update_data.get("content", {})
                    if isinstance(content, dict) and "text" in content:
                        respuesta_final += content["text"]

            if resp_id == 2 and isinstance(result, dict) and "sessionId" in result:
                session_id = result.get("sessionId")
                prompt_payload = {
                    "jsonrpc": "2.0",
                    "method": "session/prompt",
                    "id": current_prompt_id,
                    "params": {
                        "sessionId": session_id,
                        "prompt": [{"type": "text", "text": instruccion}]
                    }
                }
                process.stdin.write((json.dumps(prompt_payload) + "\n").encode("utf-8"))
                await process.stdin.drain()

            permiso_solicitado = False
            params_permiso = None
            
            if resp_method == "request_permission":
                permiso_solicitado = True
                params_permiso = params
            elif resp_method == "session/update":
                update_data = params.get("update", {})
                if isinstance(update_data, dict):
                    up_type = update_data.get("type")
                    if up_type in ["permission_request", "toolCall"] and (update_data.get("requiresConfirmation") or up_type == "permission_request"):
                        permiso_solicitado = True
                        params_permiso = update_data

            # Intercepción de permisos e inyección de la segunda fase (sugerencia)
            if permiso_solicitado and params_permiso:
                decision, sugerencia = await consultar_hermes(params_permiso)
                
                # Transmisión primitiva de la decisión
                decision_payload = {
                    "jsonrpc": "2.0",
                    "result": decision,
                    "id": resp_id
                }
                process.stdin.write((json.dumps(decision_payload) + "\n").encode("utf-8"))
                await process.stdin.drain()

                # Inyección del prompt de retroalimentación
                if decision == "rejected" and sugerencia and session_id:
                    current_prompt_id += 1
                    prompt_sugerencia = f"Tu acción fue rechazada por el auditor de seguridad. Sugerencia: {sugerencia}. Adapta tu estrategia y procede."
                    feedback_payload = {
                        "jsonrpc": "2.0",
                        "method": "session/prompt",
                        "id": current_prompt_id,
                        "params": {
                            "sessionId": session_id,
                            "prompt": [{"type": "text", "text": prompt_sugerencia}]
                        }
                    }
                    process.stdin.write((json.dumps(feedback_payload) + "\n").encode("utf-8"))
                    await process.stdin.drain()

            # Verificación dinámica del identificador para terminación del ciclo
            if resp_id == current_prompt_id and isinstance(result, dict) and result.get("stopReason") == "end_turn":
                process.terminate()
                break
                
        except json.JSONDecodeError:
            pass

    return respuesta_final.strip()

async def background_opencode_task(instruccion: str) -> None:
    try:
        resultado = await ejecutar_tarea_opencode(instruccion)
        print(f"\n[Orquestador] ✅ Tarea OpenCode finalizada: {resultado}\n")
    except Exception as e:  # noqa: BLE001
        print(f"\n[Orquestador] ❌ Error ejecutando tarea: {e}\n")

# ==========================================
# TRANSPORTE ACP NATIVO (Híbrido Sincrónico/Asincrónico)
# ==========================================
@app.api_route("/sse", methods=["GET", "POST", "HEAD"])
async def sse_bulletproof(request: Request, background_tasks: BackgroundTasks) -> Response:
    client_version = request.headers.get("mcp-protocol-version", "2024-11-05")
    res_headers = {"mcp-protocol-version": client_version}

    if request.method == "HEAD":
        return Response(status_code=200, headers=res_headers)

    # Manejo de conexión SSE mediante aislamiento de sesiones
    if request.method == "GET":
        session_id = str(uuid.uuid4())
        active_sse_queues[session_id] = asyncio.Queue()
        
        async def event_stream():  # type: ignore
            try:
                # Transmisión del identificador de sesión para enrutamiento de comandos POST
                yield {"event": "endpoint", "data": f"{request.url!s}?session_id={session_id}"}
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(active_sse_queues[session_id].get(), timeout=1.0)
                        yield {"event": "message", "data": json.dumps(msg)}
                    except asyncio.TimeoutError:
                        continue
            except asyncio.CancelledError:
                pass
            finally:
                active_sse_queues.pop(session_id, None)
                
        return EventSourceResponse(event_stream(), headers=res_headers)

    # Manejo de Comandos (POST)
    if request.method == "POST":
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            return Response(status_code=400, headers=res_headers)

        msg_id = data.get("id")
        method = data.get("method")
        print(f"\n[ACP] 📥 Procesando: {method}")

        if msg_id is None:
            return Response(status_code=202, headers=res_headers)

        respuesta: dict[str, Any] | None = None

        if method == "initialize":
            respuesta = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": data.get("params", {}).get("protocolVersion", client_version),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "acp-orchestrator", "version": "1.0.0"}
                }
            }
        elif method == "tools/list":
            respuesta = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": [{
                        "name": "delegar_a_opencode",
                        "description": "Delega una tarea de programación al worker OpenCode.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"instruction": {"type": "string"}},
                            "required": ["instruction"]
                        }
                    }]
                }
            }
        elif method == "tools/call":
            instruccion = data.get("params", {}).get("arguments", {}).get("instruction", "")
            background_tasks.add_task(background_opencode_task, instruccion)
            respuesta = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": "Status: Success. Tarea delegada a OpenCode asíncronamente."}]
                }
            }

        if respuesta:
            req_session_id = request.query_params.get("session_id")
            if req_session_id and req_session_id in active_sse_queues:
                await active_sse_queues[req_session_id].put(respuesta)
                
            return JSONResponse(content=respuesta, status_code=200, headers=res_headers)

        return Response(status_code=202, headers=res_headers)
    
    # Fallback requerido por el tipado de retorno
    return Response(status_code=405)
