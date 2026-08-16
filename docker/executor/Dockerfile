FROM python:3.9.6-slim

LABEL maintainer="thinkdome"
LABEL description="thinkdome Python executor - ephemeral sandbox"

# ---- Make apt more reliable in unstable networks ----
RUN echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4 && \
    echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/99retries

# ---- System dependencies ----
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        iputils-ping \
        net-tools \
        iproute2 \
        curl \
        procps \
    && rm -rf /var/lib/apt/lists/*

# ---- Python dependencies (keep in one layer for caching efficiency) ----
RUN pip install --no-cache-dir \
    numpy \
    pandas \
    matplotlib \
    scipy \
    sympy \
    requests \
    httpx \
    tenacity \
    pydantic \
    pillow \
    scikit-learn \
    seaborn \
    openpyxl \
    xlsxwriter \
    beautifulsoup4 \
    lxml \
    pyyaml \
    jsonschema

# ---- Sandbox user setup ----
RUN useradd -m -s /bin/bash -u 1000 sandbox && \
    mkdir -p /workspace && \
    chown sandbox:sandbox /workspace

WORKDIR /workspace

USER sandbox

CMD ["python3", "-u", "-c", "print('executor ready')"]