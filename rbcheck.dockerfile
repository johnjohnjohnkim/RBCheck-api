FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Dependencies first, so editing app code doesn't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Run as an unprivileged user.
RUN useradd --system --uid 10001 --no-create-home rbcheck
USER rbcheck

EXPOSE 8000

# /healthz needs no token and reveals nothing. start-period covers table creation at startup.
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

# Behind Caddy only: it is the sole route to this port, so its X-Forwarded-* headers
# are trusted (keeps redirects on https). Never publish port 8000 directly.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*", "--no-server-header"]
