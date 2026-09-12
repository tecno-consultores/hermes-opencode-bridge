# Hermes-OpenCode Bridge 🌉🤖

[![Python & FastAPI](https://img.shields.io/badge/Python-3.11%20|%20FastAPI-blue)](https://fastapi.tiangolo.com/)

Esta imagen fue diseñada para trabajar dentro del proyecto: https://github.com/tecno-consultores/llm-lab

Un microservicio ultrarrápido construido con FastAPI y `uv` que funciona como servidor nativo **Model Context Protocol (MCP)** y puente de comunicación asíncrona entre **Hermes (Agente Manager)** y **OpenCode (Agente Worker)**. 

Esta nueva arquitectura resuelve los bloqueos de interfaz ("abrazos mortales") procesando las tareas pesadas en segundo plano. El puente expone la herramienta `delegar_a_opencode` nativamente a través de MCP (vía SSE), permitiendo a Hermes delegar tareas de programación y ejecución en terminal dentro de un entorno Dockerizado (`/workspace`), manteniendo una **capa de auditoría de seguridad interactiva**.

Para ejecutar la integracion completa ejecuta el siguiente comando:

```bash
docker compose -f docker-compose.yml --env-file env.example --profile acp-orchestrator --profile hermes --profile opencode up -d
```

## ✨ Características Principales

* **Protocolo MCP Híbrido (SSE):** Soporte total para la especificación Model Context Protocol con aislamiento de sesiones (UUID) y ruteo a prueba de fallos, compatible con versiones estrictas del SDK de NousResearch.
* **Ejecución Zero-Blocking Asíncrona:** Las tareas delegadas liberan inmediatamente la interfaz de Hermes (HTTP 202 Accepted), ejecutando OpenCode en *background* y permitiendo paralelismo real.
* **Comunicación Nativa ACP:** Habla directamente con el servidor de OpenCode a través de flujos `stdio` usando `docker exec`.
* **Auditoría de Seguridad (Safety Layer):** Intercepta peticiones de permisos de OpenCode y realiza un "Security Audit" consultando al motor de Hermes antes de aprobar acciones destructivas.
* **Auto-Ensamblaje "Zero-Touch":** Capacidad para que el agente manager detecte y registre la herramienta por sí mismo en caliente.

## 🏗️ Arquitectura del Flujo Asíncrono

1. **Auto-Registro:** Hermes detecta la ausencia del servidor MCP y se auto-configura vía CLI.
2. **Handshake MCP:** Hermes se conecta al endpoint `/sse`. El Bridge responde adaptándose dinámicamente a la versión del protocolo y entregando la herramienta `delegar_a_opencode`.
3. **Delegación (Non-Blocking):** El usuario pide una tarea. Hermes invoca la herramienta. El Bridge devuelve un éxito inmediato para liberar la UI y levanta el túnel hacia OpenCode en segundo plano.
4. **Auditoría:** Si OpenCode intenta algo peligroso, pide permiso. El Bridge pausa, consulta a Hermes vía API interna, y continúa si es aprobado.

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
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    depends_on:
      opencode:
        condition: service_started
```

## 🔌 Integración Automática (System Prompt)

Para lograr un despliegue "Zero-Touch" donde Hermes se conecte a este orquestador de manera autónoma, configura la siguiente variable de entorno (`learning_acp_orchestrator`) en tu contenedor de Hermes. Esta instrucción incluye el protocolo de auto-ensamblaje y la separación de roles:

```bash
Role: Lead DevOps Manager. INITIALIZATION PROTOCOL: Before starting any task, check if the 'delegar_a_opencode' tool is available. If NOT, use your local terminal to execute exactly: '/opt/hermes/.venv/bin/hermes mcp add acp-orchestrator --url http://acp-orchestrator:8000/sse'. OPERATING RULES: You are the orchestrator. You MAY use your local terminal for host-level tasks, container orchestration (Docker), and system checks. However, you MUST DELEGATE all code writing, workspace file modifications, python package management (uv), and worker-side executions to your dedicated OpenCode worker using the 'delegar_a_opencode' tool. Provide the worker with highly detailed, step-by-step instructions. IMPORTANT SECURITY AUDIT: You monitor the worker. If prompted to evaluate a potentially dangerous action from OpenCode, switch to auditor mode and reply ONLY with 'approved' or 'rejected'.
```

## 🧪 Verificación de Conexión

Una vez levantado el entorno, puedes confirmar que el puente está escuchando el protocolo MCP nativo comprobando el endpoint híbrido:

```bash
# Debería devolver HTTP 200 y las cabeceras de protocolo MCP inyectadas
curl -I -X HEAD http://localhost:8000/sse
```

Obtener la imagen en Docker Hub: https://hub.docker.com/r/sinfallas/hermes-opencode-bridge
