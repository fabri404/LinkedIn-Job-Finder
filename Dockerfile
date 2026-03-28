# ============================================================
# STAGE 1 — builder
# ============================================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .

# psycopg2-binary requiere libpq-dev para compilar
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install psycopg2-binary==2.9.9 \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && apt-get purge -y --auto-remove gcc \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# STAGE 2 — runtime con Chromium del sistema (headless)
# ============================================================
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.11/site-packages" \
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Chromium desde repo Debian — sin apt-key deprecated
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        libpq5 \
        curl \
        libglib2.0-0 \
        libnss3 \
        libfontconfig1 \
        xvfb \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && chromium --version \
    && chromedriver --version

COPY --from=builder /install /install

WORKDIR /app

# Crear usuario no-root
RUN groupadd --gid 1001 django \
    && useradd --uid 1001 --gid django --shell /bin/bash --create-home django

COPY --chown=django:django . .

# collectstatic en el entrypoint, no aquí — evita el || true que silencia errores
USER django

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/ || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--log-level", "info", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
