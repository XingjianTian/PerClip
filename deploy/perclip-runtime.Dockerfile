FROM python:3.11-slim@sha256:cdbd05fb6f457ca275ff51ce00d93d865ca0b6a25f5ffb08262d94f6835771e5

ARG PERCLIP_COMMIT
LABEL org.opencontainers.image.title="PerClip unified runtime"
LABEL org.opencontainers.image.revision="${PERCLIP_COMMIT}"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /opt/perclip/server

COPY deploy/perclip-runtime-requirements.txt /tmp/perclip-runtime-requirements.txt
RUN python -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --no-deps \
    --requirement /tmp/perclip-runtime-requirements.txt \
    && rm /tmp/perclip-runtime-requirements.txt

COPY server/perclip_ingest /opt/perclip/server/perclip_ingest
COPY server/tools/__init__.py \
    server/tools/run_operator_verified_worker.py \
    server/tools/unix_ragflow_operator_verifier.py \
    /opt/perclip/server/tools/

CMD ["python", "-m", "uvicorn", "perclip_ingest.main:create_app", "--factory"]
