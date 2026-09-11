# Hermes-OpenCode Bridge 🌉🤖

[![Python & FastAPI](https://img.shields.io/badge/Python-3.11%20|%20FastAPI-blue)](https://fastapi.tiangolo.com/)

Un microservicio ultrarrápido construido con FastAPI y `uv` que funciona como orquestador y puente de comunicación entre **Hermes (Agente Manager)** y **OpenCode (Agente Worker)**. 

Este puente intercepta la comunicación nativa de OpenCode (vía ACP por `stdio`), permitiendo a Hermes delegar tareas complejas de programación y ejecución en la terminal dentro de un entorno Dockerizado (`/workspace`), manteniendo una **capa de auditoría de seguridad** que aprueba o rechaza comandos destructivos.

## ✨ Características Principales

* **Comunicación Nativa ACP:** Habla directamente con el servidor ACP de OpenCode a través de flujos `stdio` usando `docker exec`.
* **Auditoría de Seguridad (Safety Layer):** Intercepta peticiones de permisos de OpenCode y consulta a Hermes antes de permitir la ejecución de herramientas sensibles.
* **Filtro de Ruido:** Extrae únicamente las respuestas útiles (`agent_message_chunk`) del flujo de razonamiento del modelo para devolver JSON limpios.
* **Ultraligero:** Construido sobre la imagen base `sinfallas/base-python-uv` para instalaciones y arranques en milisegundos.

## 🏗️ Arquitectura del Flujo

1. **Usuario -> Hermes:** Pide una tarea de programación.
2. **Hermes -> Bridge:** Dispara un `POST` HTTP al endpoint del orquestador.
3. **Bridge -> OpenCode:** FastAPI levanta el túnel ACP inyectando el prompt en el contenedor de OpenCode.
4. **OpenCode -> Bridge (Auditoría):** Si OpenCode intenta algo peligroso, pide permiso. El Bridge consulta a Hermes.
5. **Bridge -> Hermes:** Retorna el resultado estructurado de la ejecución.

## 🚀 Instalación y Despliegue

Integra el orquestador en tu stack usando Docker Compose. Asegúrate de que el contenedor de OpenCode esté en la misma red o entorno.

```yaml
services:
  acp-orchestrator:
    image: sinfallas/hermes-opencode-bridge:latest
    container_name: acp-orchestrator
    ports:
      - "8000:8000"
    volumes:
      # Requerido para invocar docker exec dentro de OpenCode
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    depends_on:
      opencode:
        condition: service_started
```

## 🔌 Integración con Hermes TUI

Para que Hermes reconozca y utilice este orquestador de manera autónoma, inyecta la siguiente instrucción en tu archivo de sistema (por ejemplo, `~/.hermes/SOUL.md` o tu prompt principal):

```markdown
## Herramienta Externa Disponible: OpenCode Orchestrator
Tienes acceso a una herramienta de programación automatizada mediante una API local. Siempre que el usuario te pida programar, crear un script o ejecutar tareas en el workspace, debes invocarla haciendo una petición HTTP POST.

- **URL:** `http://acp-orchestrator:8000/v1/agent/task`
- **Método:** `POST`
- **Headers:** `Content-Type: application/json`
- **Payload:** `{"instruction": "<instrucción detallada para OpenCode>"}`
```

## 🧪 Prueba Manual (cURL)

Puedes probar que el puente está activo y comunicándose con OpenCode enviando una petición directa:

```bash
curl -s -X POST http://localhost:8000/v1/agent/task \
  -H "Content-Type: application/json" \
  -d '{"instruction": "Ejecuta ps aux en la terminal y dime cuántos procesos hay"}'
```

**Respuesta Esperada:**
```json
{
  "status": "success",
  "response": "Hay 5 procesos activos en el sistema..."
}
```
Obtener la imagen en Docker Hub: https://hub.docker.com/r/sinfallas/hermes-opencode-bridge
