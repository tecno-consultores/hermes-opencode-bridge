# Estrategia de pruebas (QA)

Todas las pruebas se ejecutan en contenedores efímeros sin root (`docker-compose.qa.yml`), nunca en el host.
Atajos: `make <fase>` o `docker compose -f docker-compose.qa.yml run --rm test ./scripts/qa.sh <fase>`.

## Pirámide

| Capa | Herramienta | Qué cubre | Umbral |
|---|---|---|---|
| Estática y tipos | `ruff check`, `ruff format --check`, `mypy --strict` | Estilo, bugs comunes (`B`, `S`, `ASYNC`, `PL`), tipos | 0 errores |
| Unitarias | `pytest` + `pytest-asyncio` | Auditoría Hermes, cliente ACP, servidor MCP, autenticación, HTTP | Cobertura de líneas y ramas ≥ 95 % sin `pragma: no cover` |
| Contrato | `tests/test_contratos.py` | Payloads JSON-RPC/ACP exactos, esquema del auditor, mensajes y logs | Incluidas en unitarias |
| MCP real | `mcp.Client` en proceso (`tests/test_mcp_http.py`) | `tools/list` y `tools/call` con el SDK `mcp` 2.x | Incluidas en unitarias |
| Mutación | `scripts/mutation_parallel.py` (mutmut) | Calidad de las aserciones | MSI ≥ 80 % (actual 93,6 %) |
| Seguridad | `bandit`, `pip-audit`, Trivy (CI) | Código, dependencias, imagen y configuración | HIGH/CRITICAL = 0 |
| Matriz | `tox` | Python 3.10 – 3.14 | Todas en verde |
| Contratos HTTP / fuzzing | `schemathesis` (`ACP_ENABLE_DOCS=true` en la API de QA) | Esquema OpenAPI | Sin fallos |
| Carga | `locust` | `/health`, handshake MCP autenticado, rechazo 401 | 0 % de errores |
| Integración | `pytest -m integration` | Hermes y OpenCode reales en `acp-net` | Manual |

## Dobles de prueba

`tests/fakes.py` implementa `FakeOpenCode`, un agente ACP simulado sobre `asyncio.StreamReader` que
responde al handshake (`initialize`, `session/new`), emite `session/update`, solicita
`session/request_permission` con opciones reales (`allow_once`, `allow_always`, `reject_once`) y permite
simular errores, cuelgues, líneas basura y desbordamiento del límite de línea.

## Prueba end-to-end verificada (v1.6.0)

Stack real de `docker-compose.yml` con OpenCode 1.19.5, `socket-proxy`, la imagen del puente y un Hermes
simulado: autenticación 401/200, `docker exec` a través del proxy (y bloqueo de `docker ps`/`run`/`exec`
en otros contenedores), permiso aprobado (archivo creado) y permiso rechazado con re-prompt de
retroalimentación (OpenCode adapta su estrategia).

## Reglas

- Cada corrección de defecto incluye una prueba de regresión (docstring `Regresión ...`).
- Las pruebas unitarias no acceden a red ni a Docker; las de integración llevan el marcador `integration`.
