FROM python:3.9.6-slim

LABEL maintainer="thinkdome"
LABEL description="thinkdome Python executor - ephemeral sandbox"

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

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

RUN useradd -m -s /bin/bash -u 1000 sandbox
RUN mkdir -p /workspace && chown sandbox:sandbox /workspace

WORKDIR /workspace
USER sandbox

ENTRYPOINT ["python3", "-u"]
CMD ["-c", "print('executor ready')"]