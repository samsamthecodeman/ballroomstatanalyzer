# Ballroom Stats Analyzer: ballroomcompexpress.com results analysis, as a public website.
# Build and run with:  docker compose up -d --build   (see DOCKER.md)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bce_web.py bce_analyze.py bce_export.py bce_partners.py bce_store.py bce_cache.py bce_o2cm.py bce_sources.py bce_upcoming.py bce_explore.py ./

# Run as an unprivileged user; saved pages live in /data/cache (a Docker volume)
RUN useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin app \
 && mkdir -p /data/cache \
 && chown -R app:app /data
USER app

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/ping', timeout=3).status == 200 else 1)"]

# Listens on all interfaces *inside* the container; docker-compose.yml only publishes it to the host's
# 127.0.0.1, so the only way in from outside is through nginx.
CMD ["python", "bce_web.py", "--public", "--host", "0.0.0.0", "--port", "8765", \
     "--cache", "/data/cache", "--trust-proxy", "private"]
