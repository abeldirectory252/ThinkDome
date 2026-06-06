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

RUN pip install --no-cache-dir -e .

COPY docker/thinkdome/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]