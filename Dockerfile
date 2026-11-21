# syntax=docker/dockerfile:1
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 Jesus Palencia <sinfallas@gmail.com> (Creado en Tecno Consultores)

# Solo se necesita el binario del cliente Docker (no el daemon): se copia desde la imagen oficial.
ARG DOCKER_CLI_IMAGE=docker:29-cli
FROM ${DOCKER_CLI_IMAGE} AS docker-cli

FROM sinfallas/base-python-uv:3.15
LABEL org.opencontainers.image.authors="Jesus Palencia <sinfallas@gmail.com> (Creado en Tecno Consultores)" \
      org.opencontainers.image.title="hermes-opencode-bridge" \
      org.opencontainers.image.description="Puente MCP <-> ACP entre Hermes y OpenCode con auditoría de seguridad fail-closed" \
      org.opencontainers.image.source="https://github.com/tecno-consultores/hermes-opencode-bridge" \
      org.opencontainers.image.licenses="GPL-2.0-only"

# La imagen base corre como appuser (10001); root solo para instalar dependencias.
USER root
WORKDIR /app

# Parches de seguridad del SO publicados después de la imagen base (objetivo Trivy HIGH/CRITICAL = 0).
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

# Dependencias reproducibles desde uv.lock (con hashes), sin herramientas de desarrollo.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY acp_api.py ./

USER 10001:10001
ENV DOCKER_CONFIG=/tmp/.docker

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# --no-access-log: evita registrar el token si un cliente usa ?token= en la URL.
CMD ["uvicorn", "acp_api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

ARG BUILD_DATE
LABEL org.opencontainers.image.created=$BUILD_DATE
