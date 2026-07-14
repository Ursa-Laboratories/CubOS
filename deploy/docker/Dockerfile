# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS web-build
WORKDIR /build/web
COPY apps/operator-web/package.json apps/operator-web/package-lock.json ./
RUN npm ci
COPY apps/operator-web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS python-build
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
WORKDIR /build

RUN python -m venv "${VIRTUAL_ENV}"
COPY packages/core/ ./packages/core/
COPY services/api/pyproject.toml ./services/api/pyproject.toml
COPY services/api/src/ ./services/api/src/
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir "./packages/core[asmi]" \
    && python -m pip install --no-cache-dir ./services/api

FROM python:3.12-slim-bookworm AS runtime
ARG BUILD_VERSION=0.0.0-dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="CubOS Appliance" \
      org.opencontainers.image.description="CubOS API and operator web app for Raspberry Pi" \
      org.opencontainers.image.source="https://github.com/Ursa-Laboratories/CubOS" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CUBOS_BUILD_VERSION="${BUILD_VERSION}" \
    CUBOS_WEB_DIST=/opt/cubos/web/dist \
    CUBOS_HOST=0.0.0.0 \
    CUBOS_PORT=8742 \
    CUBOS_OPEN_BROWSER=false \
    CUBOS_CONFIG_DIR=/var/lib/cub/configs \
    CUBOS_RUN_DIR=/var/lib/cub/runs \
    CUBOS_DATA_DB_PATH=/var/lib/cub/data/cubos.db

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 cub \
    && useradd --uid 10001 --gid cub --no-create-home --home-dir /nonexistent cub \
    && mkdir -p /opt/cubos/web /opt/cubos/config-seed /var/lib/cub/configs /var/lib/cub/runs /var/lib/cub/data \
    && chown -R cub:cub /opt/cubos /var/lib/cub

COPY --from=python-build /opt/venv /opt/venv
COPY --from=web-build --chown=cub:cub /build/web/dist /opt/cubos/web/dist
COPY --chown=cub:cub services/api/configs/ /opt/cubos/config-seed/
COPY --chown=cub:cub deploy/docker/entrypoint.sh /usr/local/bin/cubos-entrypoint
RUN chmod 0755 /usr/local/bin/cubos-entrypoint

USER cub:cub
WORKDIR /var/lib/cub
VOLUME ["/var/lib/cub"]
EXPOSE 8742
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent --show-error http://127.0.0.1:8742/api/v1/health >/dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/cubos-entrypoint"]
CMD ["uvicorn", "cubos_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8742"]
