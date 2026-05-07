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

# Copiar solo pyproject.toml primero (cache de dependencias)
COPY backend/pyproject.toml backend/poetry.lock* ./

# Instilar Poetry y dependencias
RUN pip install poetry==1.8.5 && \
    poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-ansi

# ---- Stage 2: Runtime ----
FROM python:3.11-slim AS runtime

# Variables de entorno
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    APP_HOST=0.0.0.0 \
    APP_PORT=4000 \
    WORKER_CONCURRENCY=4

# Instilar solo lo necesario para runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
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
COPY backend/migrations ./migrations
COPY backend/pyproject.toml ./

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
