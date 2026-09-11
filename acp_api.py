import asyncio
import json
import os
import sys
import urllib.request
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Orquestador ACP Hermes-OpenCode")

class TaskRequest(BaseModel):
    instruction: str

def consultar_hermes(accion):
    print("\n[Orquestador] -> 🚨 Consultando a Hermes sobre acción de seguridad...")
    
    api_key = os.environ["HERMES_API_KEY"]
    url = os.environ.get("HERMES_API_URL", "http://hermes:8642/v1/chat/completions")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}" 
    }
    
    prompt = f"You are a strict security auditor. OpenCode is requesting to execute the following action: {json.dumps(accion)}. Evaluate if it is safe. Respond ONLY with 'approved' or 'rejected'."
    
    data = {
        "model": "hermes",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 10,
        "temperature": 0.1
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
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
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    
    # 1. Inicialización
    handshake = {
        "jsonrpc": "2.0", "method": "initialize",
        "params": {"protocolVersion": 1, "clientInfo": {"name": "fastapi-orquestador", "version": "1.0"}},
        "id": 1
    }
    process.stdin.write((json.dumps(handshake) + "\n").encode('utf-8'))
    await process.stdin.drain()
    await process.stdout.readline()
    
    # 2. Confirmación
    process.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode('utf-8'))
    await process.stdin.drain()

    # 3. Nueva Sesión
    session_req = {
        "jsonrpc": "2.0", "method": "session/new", "id": 2,
        "params": {"cwd": "/workspace", "mcpServers": []}
    }
    process.stdin.write((json.dumps(session_req) + "\n").encode('utf-8'))
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
                if isinstance(update_data, dict):
                    # Solo atrapamos los "agent_message_chunk" (el texto final que genera)
                    if update_data.get("sessionUpdate") == "agent_message_chunk":
                        content = update_data.get("content", {})
                        if isinstance(content, dict) and "text" in content:
                            respuesta_final += content["text"]
            
            # --- ENVÍO DEL PROMPT ---
            if response.get("id") == 2 and "result" in response:
                session_id = response["result"].get("sessionId")
                msg_req = {
                    "jsonrpc": "2.0", "method": "session/prompt", "id": 3,
                    "params": {
                        "sessionId": session_id,
                        "prompt": [{"type": "text", "text": instruccion}]
                    }
                }
                process.stdin.write((json.dumps(msg_req) + "\n").encode('utf-8'))
                await process.stdin.drain()

            # --- AUDITORÍA DE HERMES ---
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
                aprobacion = {
                    "jsonrpc": "2.0",
                    "result": decision,
                    "id": response.get("id")
                }
                process.stdin.write((json.dumps(aprobacion) + "\n").encode('utf-8'))
                await process.stdin.drain()
            
            # --- CONDICIÓN DE SALIDA ---
            if response.get("id") == 3 and "result" in response:
                if response["result"].get("stopReason") == "end_turn":
                    process.terminate()
                    break
                
        except json.JSONDecodeError:
            pass 

    return respuesta_final.strip()

@app.post("/v1/agent/task")
async def execute_task(request: TaskRequest):
    try:
        resultado = await ejecutar_tarea_opencode(request.instruction)
        return {"status": "success", "response": resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
