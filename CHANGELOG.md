# Changelog

Todos los cambios relevantes de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el proyecto
adhiere a [Versionado Semántico](https://semver.org/lang/es/). La versión vive en un único
lugar: `__version__` en `acp_api.py` (leída dinámicamente por `pyproject.toml`).

## [Unreleased]

### Corregido
- **CI (GitHub Actions)**: se fija `aquasecurity/trivy-action` por SHA de commit (`v0.36.0`, las etiquetas sin prefijo `v` como `0.28.0` fueron retiradas por Aqua Security) y se refuerzan `BUILD_DATE` en `pull_request` y el *smoke test*.

## [1.6.0] - 2026-11-14

### Seguridad
- **Auditoría fail-closed**: cualquier error al consultar a Hermes (timeout, JSON inválido,
  decisión desconocida, prompt mal formado) ahora **rechaza** la acción en lugar de aprobarla.
- **Protocolo ACP de permisos corregido**: se atiende `session/request_permission` y se responde
  con `{"outcome": {"outcome": "selected", "optionId": ...}}` / `cancelled`. Antes se escuchaba un
  método inexistente (`request_permission`) y la auditoría nunca se ejecutaba. Nunca se elige
  `allow_always`, para que OpenCode no omita auditorías futuras.
- **Autenticación obligatoria** de los endpoints MCP con `ACP_API_KEY` (cabecera Bearer o
  `?token=`); sin clave configurada se rechazan todas las conexiones.
- El puente ya **no monta `/var/run/docker.sock`**: usa `wollomatic/socket-proxy` con lista
  blanca que solo permite `docker exec` en el contenedor `opencode`, en una red interna aislada.
- Imagen sin root (UID 10001), sistema de archivos de solo lectura, `cap_drop: ALL` y
  `no-new-privileges`; solo se copia el binario del cliente Docker (sin daemon, nano ni wget).
- Puertos del puente y de OpenCode publicados solo en `127.0.0.1` por defecto; la interfaz web de
  OpenCode ahora recibe `OPENCODE_SERVER_USERNAME/PASSWORD`.
- `env.example` ya no contiene credenciales reales (placeholders `CHANGE_ME`).
- Mitigación de *prompt injection*: la acción auditada se delimita en `<action>` y se escapan `<`/`>`.
- `uvicorn --no-access-log` para no registrar tokens en la URL.
- Swagger/OpenAPI desactivados por defecto (`ACP_ENABLE_DOCS=true` solo en QA/desarrollo).
- Parches del SO aplicados en el build: Trivy HIGH/CRITICAL = 0 en la imagen.

### Corregido
- La imagen Docker no instalaba `mcp` y fallaba al importar `acp_api` (`ModuleNotFoundError`).
  Además no podía construirse: la imagen base corre como usuario sin privilegios y `apt` fallaba.
- Los handlers MCP tenían la firma de `mcp` 1.x; con `mcp` 2.x `tools/list` y `tools/call`
  devolvían error interno. Ahora se registran con `on_list_tools` / `on_call_tool`.
- `HERMES_SECURITY_PROMPT` vacío (valor por defecto del compose) enviaba un prompt vacío a Hermes.
- El flujo ACP solo terminaba con `stopReason == "end_turn"`; ahora cualquier `stopReason` cierra el turno.
- Re-prompt tras un rechazo enviado mientras el turno anterior seguía activo; ahora se envía al
  terminar el turno, con un máximo configurable (`MAX_FEEDBACK_ROUNDS`).
- Procesos `docker exec` huérfanos ante errores o cancelaciones (cierre garantizado con escalado
  stdin → terminate → kill) y timeout global por tarea (`OPENCODE_TASK_TIMEOUT`).
- Límite de 64 KiB por línea del `StreamReader` elevado a 16 MiB, con manejo controlado del desbordamiento.
- Se eliminó `notifications/initialized` (es de MCP, no de ACP) y se declaran `clientCapabilities`.
- Healthcheck de OpenCode con el puerto fijo `4096` (ahora usa `${OCPORT}` y autenticación).
- `docker-compose.qa.yml`: las comillas de los valores por defecto quedaban dentro de las variables.
- `limpieza.sh` ejecutaba `docker system prune -af` y `docker volume prune -af` sobre todo el host;
  ahora solo limpia los artefactos de este repositorio y no requiere root.

### Cambiado
- Nuevo transporte MCP **Streamable HTTP** en `/mcp` (stateless) además de SSE en `/mcp/sse`.
- Se eliminó el uso de `request._send` y de `BypassedResponse`: los endpoints MCP son ASGI puros.
- `logging` estructurado (`LOG_LEVEL`) en lugar de `print`; el stderr de OpenCode se registra en DEBUG.
- Contenedor y workspace de OpenCode configurables (`OPENCODE_CONTAINER`, `OPENCODE_WORKSPACE`) y
  límite de tareas concurrentes (`MAX_CONCURRENT_TASKS`, por defecto 1).
- Dependencias acotadas (`mcp>=2.3,<3`, etc.) y bloqueadas en `uv.lock`; el Dockerfile instala
  desde el lock con verificación de hashes.
- Configuración de pytest, coverage, ruff, mypy (`--strict`) y mutmut unificada en `pyproject.toml`
  (se eliminaron `pytest.ini` y `setup.cfg`).
- Suite de pruebas reescrita: agente ACP simulado, cliente MCP real en proceso, autenticación y
  regresiones de cada defecto; cobertura de ramas sin exclusiones `pragma: no cover`.
- `locustfile.py` mide el handshake MCP autenticado y el rechazo 401, en lugar de un POST siempre inválido.
- Imágenes con tag configurable (`OPENCODE_TAG`, `HERMES_TAG`, `ACP_TAG`, `SOCKET_PROXY_TAG`) y
  `pull_policy=missing` por defecto.
- Este `CHANGELOG.md` sustituye al volcado automático de `git log` (`changelog`).

### Añadido
- CI en GitHub Actions (tox 3.10–3.14, SAST, build y Trivy de la imagen, smoke test).
- `SECURITY.md`, `CONTRIBUTING.md`, `TESTING.md`, `Makefile`, `CODEOWNERS`, plantillas de issues/PR, Dependabot,
  `.dockerignore`, `.editorconfig`, `AGENTS.md` y cabeceras SPDX.
- `scripts/qa.sh` con las fases de QA (tox, lint, unit, sast, mutation, load, fuzz).
- `scripts/mutation_parallel.py`: mutación en paralelo (hijos sobresuscritos y *shards* opcionales
  con `MUTATION_SHARDS`), resumen de sobrevivientes y puerta MSI ≥ 80 % (`MUTATION_MIN_MSI`).
  Con `--timeout=2` para mutantes que cuelgan y pruebas sin esperas innecesarias, la fase pasa de
  ~10 min a ~35 s (MSI 93,6 %).
- Pruebas de contrato exactas (payloads JSON-RPC, mensajes y logs) para matar mutantes.

## [1.5.1] - 2026-09-12

### Cambiado
- Actualización a Python 3.13, healthcheck y ajustes del docker compose.

## [1.5.0] - 2026-09-12

### Añadido
- Ejecución de OpenCode en tarea de segundo plano y timeout en la consulta a Hermes.

## [1.0.0] - 2026-09-12

### Añadido
- Versión inicial del puente MCP/ACP entre Hermes y OpenCode.

[Unreleased]: https://github.com/tecno-consultores/hermes-opencode-bridge/compare/v1.6.0...HEAD
[1.6.0]: https://github.com/tecno-consultores/hermes-opencode-bridge/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/tecno-consultores/hermes-opencode-bridge/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/tecno-consultores/hermes-opencode-bridge/compare/v1.0.0...v1.5.0
[1.0.0]: https://github.com/tecno-consultores/hermes-opencode-bridge/releases/tag/v1.0.0
