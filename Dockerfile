# EGX Sentinel — deterministic decision engine.
#
# Analysis only. This image contains no broker client, no order path, and no AI
# provider credentials: the model is chosen in n8n and reaches the engine only
# as structured JSON.
#
# The repository layout is preserved inside the image because two code paths
# locate files by walking upward from the package: db/migrations (the migration
# runner) and config/telda-universe.csv (the universe loader).

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY data-engine/pyproject.toml ./data-engine/
COPY data-engine/src ./data-engine/src
RUN pip install --no-cache-dir ./data-engine

COPY db ./db
COPY config ./config

# Drop privileges: nothing here needs root at runtime.
RUN useradd --create-home --uid 10001 sentinel && chown -R sentinel:sentinel /app
USER sentinel

EXPOSE 8080

# Port 8080 is reachable only from the private Docker network; docker-compose.yml
# deliberately publishes no host mapping.
CMD ["python", "-m", "egx_engine.cli", "serve"]
