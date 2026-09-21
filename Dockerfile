FROM python:3.11.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EKI_HOST=0.0.0.0 \
    EKI_PORT=8000 \
    EKI_TRACE_DIR=/var/lib/eki/traces

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /var/lib/eki/traces \
    && chown -R 10001:10001 /var/lib/eki
COPY --chown=10001:10001 configs ./configs
COPY --chown=10001:10001 src ./src
COPY --chown=10001:10001 scripts/run_dense_retrieval.py scripts/validate_retrieval_benchmark.py ./scripts/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()" || exit 1
CMD ["python", "-m", "src.api"]
