ARG GOTENBERG_FONT_IMAGE=gotenberg/gotenberg:8.30.0@sha256:d3c9e0ed2450c9a4631de6d14b51c75fd6051512c33aa8a6df622f085592c48b
ARG PYTHON_BASE_IMAGE=python:3.13-slim@sha256:7ce4b6dfe35e55397b7cda544f8a13f191b7ae28dc5aad71fe664dbc9bc2623f

FROM ${GOTENBERG_FONT_IMAGE} AS renderer-fonts
FROM ${PYTHON_BASE_IMAGE}

ARG ATTACHMENT_FONT_MANIFEST_VERSION=noto-cjk-gotenberg-8.30.0-d3c9e0ed2450
ARG ATTACHMENT_RENDERER_IMAGE_DIGEST=gotenberg/gotenberg:8.30.0@sha256:d3c9e0ed2450c9a4631de6d14b51c75fd6051512c33aa8a6df622f085592c48b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system ata && useradd --system --gid ata --home-dir /app ata
WORKDIR /app

COPY requirements-build.lock requirements-runtime.lock ./
RUN python -m pip install --require-hashes -r requirements-build.lock \
    && python -m pip install --no-build-isolation --require-hashes -r requirements-runtime.lock

COPY pyproject.toml README.md ./
COPY ai_hunter ./ai_hunter
COPY config ./config
COPY sql ./sql
COPY --from=renderer-fonts /usr/share/fonts/opentype/noto /usr/share/fonts/opentype/noto
RUN python -m pip install --no-deps --no-build-isolation . \
    && python -m ai_hunter.annual_audit.scripts.verify_attachment_runtime \
        --write-manifest-version "${ATTACHMENT_FONT_MANIFEST_VERSION}" \
        --renderer-image-digest "${ATTACHMENT_RENDERER_IMAGE_DIGEST}" \
    && chown -R ata:ata /app /usr/local/share/ata

USER ata
CMD ["python", "-m", "ai_hunter"]
