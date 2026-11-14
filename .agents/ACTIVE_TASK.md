# ACTIVE TASK — Remediación de auditoría (v1.6.0)

Status: COMPLETED (100%)

- [x] C1 Imagen: instala deps desde uv.lock (mcp incluido), build no-root, Trivy HIGH/CRITICAL = 0
- [x] C2 Auditoría fail-closed (+ validación de decisión, prompt sin str.format)
- [x] C3 ACP: session/request_permission + outcome/optionId; sin allow_always; sin notifications/initialized
- [x] C4 Auth ACP_API_KEY, puertos en 127.0.0.1, socket-proxy con allowlist (exec en opencode), auth web OpenCode
- [x] C5 env.example con placeholders CHANGE_ME
- [x] C6 Handlers MCP con firma mcp 2.x (on_list_tools/on_call_tool) + test con mcp.Client real
- [x] A1–A8 prompt vacío, timeout global, cierre garantizado, límite 16 MiB, re-prompt post-turno, anti-inyección, semáforo, deps acotadas
- [x] Compose/QA: healthchecks, comillas, QA sin root, limpieza.sh acotado, dev override
- [x] Tests: 138 unit (99.6 % ramas, 0 pragma), tox py3.10–3.14, SAST, fuzz, load
- [x] Mutación paralela (scripts/mutation_parallel.py): ~10 min -> ~33 s, MSI 93.6 %
- [x] E2E real: OpenCode 1.19.5 + socket-proxy + puente + Hermes simulado (aprobar / rechazar + feedback)
- [x] Docs: readme, CHANGELOG.md, SECURITY.md, CONTRIBUTING.md, AGENTS.md
- [x] Gobernanza: CI, Dependabot, CODEOWNERS, plantillas, .editorconfig, .dockerignore, .gitignore, SPDX
- [x] Grafo AST actualizado (graphify-out/, ignorado por git)
- [ ] git push (pendiente de autorización del usuario)
