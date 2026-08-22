FROM node:22-alpine AS frontend-build

WORKDIR /opt/thinkdome/frontend
COPY frontend/package.json frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/index.html ./index.html
COPY frontend/src ./src
RUN npm install --no-audit --no-fund && npm run build

FROM python:3.9.6-slim

LABEL maintainer="thinkdome"
LABEL description="thinkdome API service"

RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/thinkdome

COPY pyproject.toml .
COPY README.md .
COPY thinkdome/ ./thinkdome/
COPY docker/ ./docker/
COPY --from=frontend-build /opt/thinkdome/thinkdome/static/console ./thinkdome/static/console

RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir .

COPY docker/thinkdome/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
