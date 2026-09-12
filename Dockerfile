FROM sinfallas/base-python-uv:3.11
LABEL maintainer="Jesus Palencia sinfallas@gmail.com"

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/root/.local/bin:$PATH"
WORKDIR /app

RUN apt update && apt -y dist-upgrade && apt -y install --no-install-recommends --no-install-suggests nano wget docker.io curl && apt clean && apt -y autoremove && rm -rf /var/lib/{apt,dpkg,cache,log} && rm -rf /var/cache/* && rm -rf /var/log/apt/* && rm -rf /tmp/*
RUN uv pip install --system fastapi uvicorn pydantic sse-starlette
COPY acp_api.py .

EXPOSE 8000

CMD ["uvicorn", "acp_api:app", "--host", "0.0.0.0", "--port", "8000"]
