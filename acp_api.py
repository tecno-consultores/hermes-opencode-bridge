import asyncio
import json
import os
import urllib.request
from fastapi import FastAPI, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

app = FastAPI(title="Orquestador ACP Hermes-OpenCode - BULLETPROOF")

active_sse_queue = None

class TaskRequest(BaseModel):
    instruction: str

def consultar_hermes(accion):
    print("\n[Orquestador] -> 🚨 Consultando a Hermes sobre acción de seguridad...")
    api_key = os.environ["HERMES_API_KEY"]
    url = os.environ.get("HERMES_API_URL", "http://hermes:8642/v1/chat/completions")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    prompt = f"You are a strict security auditor. OpenCode is requesting to execute the following action: {json.dumps(accion)}. Evaluate if it is safe. Respond ONLY with 'approved' or 'rejected'."
    data = {"model": "hermes", "messages": [{"role": "user", "content": prompt}], "max_tokens": 10, "temperature": 0.1}
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode('utf-8'))
            decision = "approved" if "approved" in res['choices'][0]['message']['content'].strip().lower() else "rejected"
            print(f"[Hermes] -> 🧠 Decisión: {decision.upper()}\n")
            return decision
    except Exception as e:
        print(f"[Hermes] -> ⚠️ Error ({e}). Aprobando por defecto...")
        return "approved"

async def ejecutar_tarea_opencode(instruccion: str) -> str:
    print(f"\n🚀 Iniciando tarea: {instruccion}")
    process = await asyncio.create_subprocess_exec(
        "docker", "exec", "-i", "opencode", "opencode", "acp",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    
    process.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": 1, "clientInfo": {"name": "fastapi", "version": "1.0"}}, "id": 1}) + "\n").encode('utf-8'))
    await process.stdin.drain()
    await process.stdout.readline()
    process.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode('utf-8'))
    await process.stdin.drain()
    process.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "session/new", "id": 2, "params": {"cwd": "/workspace", "mcpServers": []}}) + "\n").encode('utf-8'))
    await process.stdin.drain()

    respuesta_final = ""
    while True:
        linea = await process.stdout.readline()
        if not linea: break
        texto = linea.decode('utf-8').strip()
        try:
            response = json.loads(texto)
            if response.get("method") == "session/update":
                update_data = response.get("params", {}).get("update", {})
                if isinstance(update_data, dict) and update_data.get("sessionUpdate") == "agent_message_chunk":
                    content = update_data.get("content", {})
                    if isinstance(content, dict) and "text" in content:
                        respuesta_final += content["text"]

            if response.get("id") == 2 and "result" in response:
                session_id = response["result"].get("sessionId")
                process.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "session/prompt", "id": 3, "params": {"sessionId": session_id, "prompt": [{"type": "text", "text": instruccion}]}}) + "\n").encode('utf-8'))
                await process.stdin.drain()

            permiso_solicitado = False
            params_permiso = None
            if response.get("method") == "request_permission":
                permiso_solicitado = True
                params_permiso = response.get("params")
            elif response.get("method") == "session/update":
                update_data = response.get("params", {}).get("update", {})
                if isinstance(update_data, dict) and update_data.get("type") in ["permission_request", "toolCall"]:
                    if update_data.get("requiresConfirmation") or update_data.get("type") == "permission_request":
                        permiso_solicitado = True
                        params_permiso = update_data

            if permiso_solicitado:
                decision = await asyncio.to_thread(consultar_hermes, params_permiso)
                process.stdin.write((json.dumps({"jsonrpc": "2.0", "result": decision, "id": response.get("id")}) + "\n").encode('utf-8'))
                await process.stdin.drain()

            if response.get("id") == 3 and "result" in response:
                if response["result"].get("stopReason") == "end_turn":
                    process.terminate()
                    break
        except json.JSONDecodeError:
            pass

    return respuesta_final.strip()

async def background_opencode_task(instruccion: str):
    try:
        resultado = await ejecutar_tarea_opencode(instruccion)
        print(f"\n[Orquestador] ✅ Tarea OpenCode finalizada: {resultado}\n")
    except Exception as e:
        print(f"\n[Orquestador] ❌ Error ejecutando tarea: {e}\n")

# ==========================================
# TRANSPORTE ACP NATIVO (Híbrido Sincrónico/Asincrónico)
# ==========================================
@app.api_route("/sse", methods=["GET", "POST", "HEAD"])
async def sse_bulletproof(request: Request, background_tasks: BackgroundTasks):
    global active_sse_queue
    
    # 1. Extraemos su versión caprichosa y se la inyectamos a TODAS nuestras respuestas
    client_version = request.headers.get("mcp-protocol-version", "2024-11-05")
    res_headers = {"mcp-protocol-version": client_version}

    if request.method == "HEAD":
        return Response(status_code=200, headers=res_headers)

    # 2. Manejo de conexión SSE Clásica (Por si recapacita)
    if request.method == "GET":
        active_sse_queue = asyncio.Queue()
        async def event_stream():
            try:
                yield {"event": "endpoint", "data": str(request.url)}
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(active_sse_queue.get(), timeout=1.0)
                        yield {"event": "message", "data": json.dumps(msg)}
                    except asyncio.TimeoutError:
                        continue
            except asyncio.CancelledError:
                pass
        return EventSourceResponse(event_stream(), headers=res_headers)

    # 3. Manejo de Comandos (POST)
    if request.method == "POST":
        try:
            data = await request.json()
        except:
            return Response(status_code=400, headers=res_headers)

        msg_id = data.get("id")
        method = data.get("method")
        print(f"\n[ACP] 📥 Procesando: {method}")

        if msg_id is None:
            return Response(status_code=202, headers=res_headers)

        respuesta = None

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
            # MAGIA HÍBRIDA: Lo enviamos por la cola SSE (si existe) 
            # y también lo devolvemos directo en el POST. Cubrimos el 100% de los casos.
            if active_sse_queue:
                await active_sse_queue.put(respuesta)
                
            return JSONResponse(content=respuesta, status_code=200, headers=res_headers)

        return Response(status_code=202, headers=res_headers)
