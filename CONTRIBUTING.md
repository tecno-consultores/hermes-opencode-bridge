# Guía de contribución

## Flujo de trabajo

1. Cree una rama desde `develop` (`feat/...`, `fix/...`, `docs/...`).
2. Use mensajes con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/):
   `feat: ...`, `fix: ...`, `docs: ...`, `chore: ...`, `test: ...`, `ci: ...`.
3. Abra un Pull Request hacia `develop`. Las publicaciones se hacen con PR de `develop` a `main`
   y un tag `vX.Y.Z`.
4. Todo PR debe pasar la CI y actualizar `CHANGELOG.md` (sección `[Unreleased]`).

## Versionado

- La versión está **solo** en `__version__` de `acp_api.py` (SemVer).
- Al publicar: mueva `[Unreleased]` a `[X.Y.Z] - AAAA-MM-DD`, cree el tag `vX.Y.Z` y publique la
  imagen con ese tag además de `latest`.

## QA local (sin instalar nada en el host)

Todas las herramientas se ejecutan en contenedores efímeros sin root:

```bash
export HOST_UID=$(id -u) HOST_GID=$(id -g)
docker compose -f docker-compose.qa.yml run --rm test                         # tox py3.10-3.14
docker compose -f docker-compose.qa.yml run --rm test ./scripts/qa.sh lint    # ruff + mypy --strict
docker compose -f docker-compose.qa.yml run --rm test ./scripts/qa.sh unit    # pytest + cobertura >= 95 %
docker compose -f docker-compose.qa.yml run --rm test ./scripts/qa.sh sast    # bandit + pip-audit
```

Requisitos de aceptación:

- `ruff check`, `ruff format --check` y `mypy --strict` sin errores.
- Cobertura de líneas y ramas ≥ 95 % **sin** añadir `# pragma: no cover`.
- Cada corrección de defecto incluye una prueba de regresión.
- Si cambia dependencias, regenere `uv.lock` (`uv lock`) en un contenedor.

## Seguridad

No reporte vulnerabilidades en issues públicos: consulte [SECURITY.md](SECURITY.md).
