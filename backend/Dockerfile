FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# System dependencies (postgresql-client for pg_isready / psql)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium plus the OS libraries it needs (without --with-deps it fails to launch on slim images)
RUN playwright install --with-deps chromium

# Unprivileged runtime user
RUN useradd --create-home --uid 10001 appuser

# Application code (.dockerignore keeps .env, .venv, data and tests out of the image)
COPY --chown=appuser:appuser . .

RUN mkdir -p /app/chroma_data /app/uploads /app/logs \
    && chown -R appuser:appuser /app/chroma_data /app/uploads /app/logs

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
