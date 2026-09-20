FROM sinfallas/base-python-uv:3.13
LABEL org.opencontainers.image.authors="sinfallas@gmail.com"

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/root/.local/bin:$PATH"
WORKDIR /app

RUN apt update && apt -y dist-upgrade && apt -y install --no-install-recommends --no-install-suggests nano wget docker.io curl && apt clean && apt -y autoremove && rm -rf /var/lib/{apt,dpkg,cache,log} && rm -rf /var/cache/* && rm -rf /var/log/apt/* && rm -rf /tmp/*
RUN uv pip install --system fastapi uvicorn pydantic sse-starlette httpx
COPY acp_api.py .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD curl -f http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "acp_api:app", "--host", "0.0.0.0", "--port", "8000"]
ARG BUILD_DATE
LABEL org.opencontainers.image.created=$BUILD_DATE
