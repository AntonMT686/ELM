# ADA-ELM backend (FastAPI). Offline-capable: if ./wheels contains pre-downloaded wheels, no network is used.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
COPY wheels* /wheels/
RUN if ls /wheels/*.whl >/dev/null 2>&1; then pip install --no-index --find-links=/wheels -r requirements.txt; else pip install -r requirements.txt; fi \
 && rm -rf /wheels /root/.cache
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN useradd -r -u 10001 elm && mkdir -p /data/storage /data/pki && chown -R elm /data
USER elm
ENV ELM_STORAGE_DIR=/data/storage ELM_PKI_DIR=/data/pki
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["sh", "-c", "if [ \"$ELM_ENVIRONMENT\" != \"dev\" ]; then alembic upgrade head && python -m app.seed; fi; uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
