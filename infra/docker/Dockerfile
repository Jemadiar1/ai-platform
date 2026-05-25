# ============================================================
# Dockerfile para AI Platform - Producción
# ============================================================
# Multi-stage build para minimizar tamaño de imagen
# Stage 1: Build - instala dependencias
# Stage 2: Runtime - solo código y dependencias compiladas
# ============================================================

# ---- Stage 1: Build ----
FROM python:3.11-slim AS builder

# Variables de entorno para Python sin buffer de salida
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Instilar herramientas de build necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Crear directorio de trabajo
WORKDIR /build

# Copiar pyproject.toml y generar requirements.txt desde él
COPY backend/pyproject.toml ./

# Instilar Poetry, exportar a requirements.txt, instalar con pip
RUN pip install poetry==1.8.5 && \
    poetry export --only main --format requirements.txt --output requirements.txt --without-hashes && \
    pip install -r requirements.txt && \
    # Instalar Playwright browsers
    pip install playwright && \
    python -m playwright install --with-deps chromium

# ---- Stage 2: Runtime ----
FROM python:3.11-slim AS runtime

# Variables de entorno
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    APP_HOST=0.0.0.0 \
    APP_PORT=4000 \
    WORKER_CONCURRENCY=4 \
    PYTHONPATH=/app/src

# Instilar solo lo necesario para runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Web research: Playwright (Chromium)
    libglib2.0-0 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    # Web research: content extraction
    libicu72 \
    # Vision OCR: OpenCV dependencies
    libgstreamer1.0-0 \
    libgstreamer-plugins-base1.0-0 \
    # Document ingestion: Tesseract OCR
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
    libleptonica-dev \
    # Document ingestion: python-magic
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario no-root para seguridad
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Copiar dependencias instaladas desde builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copiar código de la aplicación
WORKDIR /app
COPY backend/src ./src
COPY backend/pyproject.toml ./
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./

# Crear directorio para logs y datos
RUN mkdir -p /app/logs /data && chown -R appuser:appuser /app /data

# Cambiar a usuario no-root
USER appuser

# Exponer puerto de la API
EXPOSE 4000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:4000/api/v1/health || exit 1

# Entrypoint: ejecutar migraciones + iniciar servidor
CMD ["uvicorn", "ai_platform.main:app", "--host", "0.0.0.0", "--port", "4000", "--workers", "4"]
