FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src

ARG CHAMBER_CTL_SOURCE="https://github.com/IPI-EUVL/chamber-ctl/archive/refs/heads/main.tar.gz"

RUN python -m pip install --no-cache-dir "$CHAMBER_CTL_SOURCE" \
    && python -m pip install --no-cache-dir . \
    && rm -rf /build/*

RUN groupadd --gid 1000 webview \
    && useradd --uid 1000 --gid 1000 --create-home webview

USER 1000:1000
WORKDIR /app

EXPOSE 8000

CMD ["uvicorn", "ipi_webview.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]