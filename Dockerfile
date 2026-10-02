FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ ./src/

# The SQLite DB and the generated admin key are written at runtime.
RUN useradd --create-home --uid 1000 appuser && mkdir -p /data && chown -R appuser /app /data
USER appuser

ENV KAYKAY_DB=/data/kaykay.db

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "src.gateway:app", "--host", "0.0.0.0", "--port", "8000"]
