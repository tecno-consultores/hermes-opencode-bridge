# Hermes-OpenCode Bridge 🌉🤖

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/tecno-consultores/hermes-opencode-bridge)  [![Descargas de Docker](https://img.shields.io/docker/pulls/sinfallas/hermes-opencode-bridge?style=flat&logo=docker&color=blue)](https://hub.docker.com/r/sinfallas/hermes-opencode-bridge)

Esta imagen fue diseñada para trabajar dentro del proyecto: https://github.com/tecno-consultores/llm-lab

Un microservicio ultrarrápido construido con FastAPI y `uv` que funciona como servidor nativo **Model Context Protocol (MCP)** y puente de comunicación asíncrona entre **Hermes (Agente Manager)** y **OpenCode (Agente Worker)**. 

Esta nueva arquitectura resuelve los bloqueos de interfaz ("abrazos mortales") procesando las tareas pesadas en segundo plano. El puente expone la herramienta `delegar_a_opencode` nativamente a través de MCP (vía SSE), permitiendo a Hermes delegar tareas de programación y ejecución en terminal dentro de un entorno Dockerizado (`/workspace`), manteniendo una **capa de auditoría de seguridad interactiva**.

Para ejecutar la integración completa ejecute el siguiente comando:

```bash
docker compose -f docker-compose.yml --env-file env.example --profile acp-orchestrator --profile hermes --profile opencode up -d
```

## ✨ Características Principales

* **Protocolo MCP Híbrido (SSE):** Soporte total para la especificación Model Context Protocol con aislamiento de sesiones (UUID) y ruteo a prueba de fallos, compatible con versiones estrictas del SDK de NousResearch.
* **Ejecución Zero-Blocking Asíncrona:** Las tareas delegadas liberan inmediatamente la interfaz de Hermes (HTTP 202 Accepted), ejecutando OpenCode en *background* y permitiendo paralelismo real.
* **Comunicación Nativa ACP:** Habla directamente con el servidor de OpenCode a través de flujos `stdio` usando `docker exec`.
* **Auditoría de Seguridad Avanzada (Safety Layer):** Intercepta peticiones de permisos de OpenCode y realiza una auditoría de seguridad consultando al motor de Hermes. Implementa un **ciclo de retroalimentación de dos fases**, el cual extrae decisiones y sugerencias de mitigación en formato JSON para inyectarlas directamente en la memoria del agente.
* **Auto-Ensamblaje "Zero-Touch":** Capacidad para que el agente manager detecte y registre la herramienta por sí mismo en caliente.

## 🏗️ Arquitectura del Flujo Asíncrono

1. **Auto-Registro:** Hermes detecta la ausencia del servidor MCP y se auto-configura vía CLI.
2. **Handshake MCP:** Hermes se conecta al endpoint `/sse`. El Bridge responde adaptándose dinámicamente a la versión del protocolo y entregando la herramienta `delegar_a_opencode`.
3. **Delegación (Non-Blocking):** El usuario pide una tarea. Hermes invoca la herramienta. El Bridge devuelve un éxito inmediato para liberar la UI y levanta el túnel hacia OpenCode en segundo plano.
4. **Auditoría y Retroalimentación:** Si OpenCode intenta ejecutar una acción destructiva, solicita permiso. El orquestador pausa el flujo y consulta a Hermes. Si la acción es rechazada, se extrae una directiva de mitigación en formato estructurado y se inyecta dinámicamente como un nuevo *prompt* en la sesión de OpenCode para que el agente adapte su estrategia operativa.

## 🚀 Instalación y Despliegue

Integre el orquestador en su stack usando Docker Compose. Asegúrese de que el contenedor de OpenCode esté en la misma red o entorno.

```yaml
services:
  acp-orchestrator:
    image: sinfallas/hermes-opencode-bridge:latest
    container_name: acp-orchestrator
    ports:
      - "8000:8000"
    environment:
      - HERMES_API_URL=http://hermes:8642/v1/chat/completions
      - HERMES_API_KEY=${HERMES_API_KEY:-}
      # Opcional: Personalizar la directiva de auditoría de seguridad
      - HERMES_SECURITY_PROMPT=${HERMES_SECURITY_PROMPT:-}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    group_add:
      # Crucial: Sustituir por el ID del grupo docker en el host (ej. 998)
      - ${DOCKER_GID:-999}
    depends_on:
      opencode:
        condition: service_healthy
      hermes:
        condition: service_healthy
```

## 🔌 Integración Automática (System Prompt)

Para lograr un despliegue "Zero-Touch" donde Hermes se conecte a este orquestador de manera autónoma, configure la siguiente variable de entorno (`learning_acp_orchestrator`) en su contenedor de Hermes. Esta instrucción incluye el protocolo de auto-ensamblaje, la separación de roles y la exigencia de respuestas estructuradas en JSON para la auditoría:

```bash
Role: Lead DevOps Manager. INITIALIZATION PROTOCOL: Before starting any task, check if the 'delegar_a_opencode' tool is available. If NOT, use your local terminal to execute exactly: '/opt/hermes/.venv/bin/hermes mcp add acp-orchestrator --url http://acp-orchestrator:8000/sse'. OPERATING RULES: You are the orchestrator. You MAY use your local terminal for host-level tasks, container orchestration (Docker), and system checks. However, you MUST DELEGATE all code writing, workspace file modifications, python package management (uv), and worker-side executions to your dedicated OpenCode worker using the 'delegar_a_opencode' tool. Provide the worker with highly detailed, step-by-step instructions. IMPORTANT SECURITY AUDIT: You monitor the worker. If prompted to evaluate a potentially dangerous action from OpenCode, switch to auditor mode. Evaluate its safety and respond ONLY with a valid JSON object containing two keys: 'decision' (must be 'approved' or 'rejected') and 'suggestion' (feedback or alternative action, leave empty if approved). Do not include markdown formatting.
```

## 🧪 Verificación de Conexión

Una vez levantado el entorno, usted puede confirmar que el puente está escuchando el protocolo MCP nativo comprobando el endpoint híbrido:

```bash
# Debería devolver HTTP 200 y las cabeceras de protocolo MCP inyectadas
curl -I -X HEAD http://localhost:8000/sse
```

## 🛠️ Ejecución de Pruebas y Aseguramiento de Calidad (QA)

El proyecto cuenta con un entorno estricto de validación aislado mediante el manifiesto `docker-compose.qa.yml`. Este pipeline garantiza la cobertura del código, la ausencia de vulnerabilidades y la robustez general de la API.

**Fase 1: Preparación y Pruebas Base (Unitarias)**
Ejecuta la suite con `pytest` (mockeando las conexiones externas), validando tipos con `mypy` y verificando estilo con el linter `ruff`:
```bash
docker compose -f docker-compose.qa.yml run --rm test bash -c "uv pip install --system -e '.[dev]' && tox"
```

**Fase 2: Seguridad y Análisis Estático (SAST)**
Escanea el árbol de dependencias buscando vulnerabilidades (CVEs) con `pip-audit` y audita el código fuente buscando patrones inseguros de Python con `bandit`:
```bash
docker compose -f docker-compose.qa.yml run --rm test bash -c "uv pip install --system -U pip && uv pip install --system -e '.[dev]' && pip-audit && bandit -r acp_api.py"
```

**Fase 3: Pruebas de Mutación**
Evalúa la robustez de la suite de pruebas inyectando fallos artificiales en el código base mediante `mutmut`, garantizando que no existan falsos positivos en el reporte de cobertura:
```bash
docker compose -f docker-compose.qa.yml run --rm test bash -c "uv pip install --system -e '.[dev]' && pytest --cov=acp_api && rm -f .mutmut-cache && mutmut run"
```

para ver el resultado de las pruebas de mutacion:
```bash
docker compose -f docker-compose.qa.yml run --rm test bash -c "uv pip install --system -e '.[dev]' && mutmut results"
```

**Fase 4: Pruebas de Estrés y Carga**
Simula 100 usuarios concurrentes asediando la API mediante `locust` para validar el rendimiento asíncrono y la latencia (requiere levantar la API previamente con `docker compose -f docker-compose.qa.yml up -d api`):
```bash
docker compose -f docker-compose.qa.yml run --rm test bash -c "uv pip install --system -e '.[dev]' && locust -f locustfile.py --headless -u 100 -r 10 -t 1m --host http://api:8000"
```

**Fase 5: Pruebas de Contratos y Fuzzing (Schemathesis)**
Bombardea los endpoints expuestos con datos aleatorios y malformados basándose en el esquema OpenAPI para garantizar que la aplicación soporte entradas extremas sin colapsar (requiere la API levantada):
```bash
docker compose -f docker-compose.qa.yml run --rm test bash -c "uv pip install --system -e '.[dev]' && schemathesis run http://api:8000/openapi.json --exclude-path /mcp/sse --exclude-checks positive_data_acceptance"
```

Obtener la imagen en Docker Hub: https://hub.docker.com/r/sinfallas/hermes-opencode-bridge
