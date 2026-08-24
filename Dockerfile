# EGX Sentinel — deterministic decision engine.
#
# Analysis only. This image contains no broker client, no order path, and no AI
# provider credentials: the model is chosen in n8n and reaches the engine only
# as structured JSON.
#
# The migrations and the seed universe travel inside the installed package
# (see [tool.setuptools.package-data]), so the image needs nothing but the
# distribution itself. Copying the repository layout in alongside it would not
# help: an installed package cannot resolve paths relative to a repository root
# it shares no ancestor with.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY data-engine/pyproject.toml ./data-engine/
COPY data-engine/src ./data-engine/src
RUN pip install --no-cache-dir ./data-engine

# Fail the build rather than ship an image whose migrations are missing.
RUN python -m egx_engine.db.migrate --check-files

# Drop privileges: nothing here needs root at runtime.
RUN useradd --create-home --uid 10001 sentinel && chown -R sentinel:sentinel /app
USER sentinel

EXPOSE 8080

# Port 8080 is reachable only from the private Docker network; docker-compose.yml
# deliberately publishes no host mapping.
CMD ["python", "-m", "egx_engine.cli", "serve"]
