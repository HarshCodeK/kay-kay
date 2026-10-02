# Kay-Kay gateway
#
# Small image on purpose: the gateway has no torch, no numpy and no embedding
# model. Its whole argument is that it is cheap to run — an image with a 2GB
# inference stack in it would contradict that.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ ./src/

# The SQLite DB and the generated admin key are written at runtime, so they
# need a writable location outside the source tree.
RUN mkdir -p /data && useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app /data
USER appuser

ENV KAYKAY_DB=/data/kaykay.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/dashboard', timeout=4).status==200 else 1)"

CMD ["uvicorn", "src.gateway:app", "--host", "0.0.0.0", "--port", "8000"]
