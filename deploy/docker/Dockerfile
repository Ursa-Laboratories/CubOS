# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS web-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS python-build
ARG CUBOS_EXTRAS=server,asmi
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
WORKDIR /build/cubos

RUN python -m venv "${VIRTUAL_ENV}"
COPY pyproject.toml README.md setup.cfg ./
COPY src/ ./src/
COPY data/ ./data/
COPY setup/ ./setup/
COPY server/ ./server/
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir ".[${CUBOS_EXTRAS}]" \
    && python -m pip install --no-cache-dir --no-deps ./server

FROM python:3.12-slim-bookworm AS runtime
ARG BUILD_VERSION=0.0.0-dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="CubOS Appliance" \
      org.opencontainers.image.description="CubOS server and Zoo operator UI for Raspberry Pi" \
      org.opencontainers.image.source="https://github.com/Ursa-Laboratories/CubOS" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CUB_BUILD_VERSION="${BUILD_VERSION}" \
    CUB_WEB_DIST=/opt/cubos/web/dist \
    ZOO_HOST=0.0.0.0 \
    ZOO_PORT=8742 \
    ZOO_OPEN_BROWSER=false \
    ZOO_CONFIG_DIR=/var/lib/cub/configs \
    ZOO_RUN_DIR=/var/lib/cub/runs \
    ZOO_DATA_DB_PATH=/var/lib/cub/data/cubos.db

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 cub \
    && useradd --uid 10001 --gid cub --no-create-home --home-dir /nonexistent cub \
    && mkdir -p /opt/cubos/web /opt/cubos/config-seed /var/lib/cub/configs /var/lib/cub/runs /var/lib/cub/data \
    && chown -R cub:cub /opt/cubos /var/lib/cub

COPY --from=python-build /opt/venv /opt/venv
COPY --from=web-build --chown=cub:cub /build/web/dist /opt/cubos/web/dist
COPY --chown=cub:cub server/configs/ /opt/cubos/config-seed/
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
CMD ["uvicorn", "zoo.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8742"]
