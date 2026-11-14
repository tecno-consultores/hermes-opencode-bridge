# Política de seguridad

## Versiones soportadas

Solo la última versión publicada (rama `main` e imagen `sinfallas/hermes-opencode-bridge` con el
tag semver más reciente) recibe correcciones de seguridad.

## Reportar una vulnerabilidad

**No abra un issue público.** Use el aviso privado de GitHub
(*Security → Report a vulnerability*) o escriba a <sinfallas@gmail.com> con:

- descripción e impacto, versión/tag afectado,
- pasos para reproducir o prueba de concepto,
- mitigaciones conocidas.

Se acusará recibo en un máximo de 5 días hábiles y se coordinará la divulgación tras publicar la corrección.

## Modelo de amenazas

Este puente permite que un agente LLM (Hermes) **ejecute código** a través de otro agente
(OpenCode). Es, por diseño, una capacidad de ejecución remota. Los controles son:

| Riesgo | Control |
|---|---|
| Invocación no autorizada de `delegar_a_opencode` | `ACP_API_KEY` obligatorio en `/mcp/sse` y `/mcp` (comparación en tiempo constante). Sin clave configurada se rechaza todo. El `session_id` de `/mcp/messages` es un UUID aleatorio emitido solo tras autenticar. |
| Exposición en red | El puerto del puente se publica solo en `127.0.0.1`; Hermes lo alcanza por la red interna `acp-net`. Protección DNS-rebinding opcional (`MCP_ALLOWED_HOSTS`). |
| Escape al host vía Docker | El puente **no** monta `docker.sock`. Usa `wollomatic/socket-proxy` en una red `internal` con lista blanca: solo `docker exec` sobre el contenedor `opencode` (no puede crear contenedores, montar volúmenes ni ejecutar en otros contenedores). |
| Acciones destructivas de OpenCode | Cada `session/request_permission` se audita con Hermes. Política **fail-closed**. Nunca se concede `allow_always`. |
| Prompt injection en la auditoría | La acción se trata como dato no confiable, se delimita en `<action>` y se escapan `<`/`>`. |
| Agotamiento de recursos | Timeout global por tarea, límite de concurrencia, límite de tamaño por línea ACP y límites de memoria en compose. |
| Fuga de secretos | `env.example` sin secretos reales, `.env` ignorado por git, sin access log de uvicorn (el token puede viajar en `?token=`). |

## Riesgos residuales aceptados

1. **Hermes monta `/var/run/docker.sock`**: su rol de orquestador (ver `learning_acp_orchestrator`)
   incluye gestionar contenedores, lo que equivale a root en el host. Si no lo necesita, elimine ese
   montaje en `docker-compose.yml`.
2. **`docker exec` en `opencode` sin restricciones de cuerpo**: el proxy filtra rutas, no el
   contenido de la petición; quien controle el puente podría pedir un `exec` privilegiado dentro
   del contenedor `opencode`. Proteja `ACP_API_KEY` y la red `acp-docker-net`.
3. **La auditoría depende de un LLM**: es una capa de defensa adicional, no un sandbox. El
   aislamiento real lo da el contenedor de OpenCode y su workspace montado.
4. **`?token=` en la URL**: soportado porque `hermes mcp add --url` no permite cabeceras. Prefiera
   la cabecera `Authorization: Bearer` en `~/.hermes/config.yaml` cuando sea posible.
