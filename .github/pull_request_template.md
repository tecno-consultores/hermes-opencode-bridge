## Descripción

<!-- ¿Qué cambia y por qué? Enlace al issue: Closes #... -->

## Tipo de cambio

- [ ] fix (corrección de defecto)
- [ ] feat (nueva funcionalidad)
- [ ] docs / chore / ci
- [ ] Cambio incompatible (requiere nueva versión mayor)

## Checklist

- [ ] La CI pasa (tox, SAST, build + Trivy).
- [ ] Cobertura ≥ 95 % sin nuevos `# pragma: no cover`.
- [ ] Añadí pruebas de regresión para cada defecto corregido.
- [ ] Actualicé `CHANGELOG.md` (sección `[Unreleased]`).
- [ ] Actualicé `readme.md` / `env.example` si cambian variables o comportamiento.
- [ ] Si cambié dependencias, regeneré `uv.lock`.
