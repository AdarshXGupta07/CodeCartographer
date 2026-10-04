# CodeCartographer - CPU-only image
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    CARTO_MODEL_CACHE=/app/.models \
    CARTO_INDEX_HOME=/data/index

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cartographer ./cartographer
COPY web ./web
COPY eval ./eval
COPY sample_repo ./sample_repo
COPY tests ./tests

# Bake the CPU code-embedding model and the sample index into the image so the
# container starts instantly and works offline.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('jinaai/jina-embeddings-v2-base-code', cache_dir='/app/.models')" \
 && python -m cartographer index sample_repo/nova-assistant

EXPOSE 8000
# Index your own repo by mounting it at /repo and setting CARTO_REPO=/repo (see docker-compose.yml)
CMD ["python", "-m", "cartographer", "serve", "--host", "0.0.0.0", "--port", "8000"]
