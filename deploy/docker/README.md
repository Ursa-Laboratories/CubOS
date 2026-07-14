# CubOS Application Image

This directory builds the application image consumed by `PiCub-Appliance`.
The image contains CubOS, the FastAPI server, and precompiled CubOS web assets.
It does not configure host networking, Docker, systemd, mDNS, or OS updates.

## Build ARM64

```bash
docker buildx build \
  --platform linux/arm64 \
  --build-arg BUILD_VERSION=0.1.0-dev \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  --load \
  --tag cubos-appliance:dev \
  --file deploy/docker/Dockerfile \
  .
```

The multi-stage build compiles `apps/operator-web/` with Node, installs the
CubOS runtime and `cubos_api` into a Python virtual environment, and copies only runtime artifacts into the
final Debian image. Customer devices do not run npm, pip, or Git.

## Runtime contract

- Runs as UID/GID `10001`, never privileged.
- Persists all mutable state under `/var/lib/cub`.
- Reads the API bearer token from `CUBOS_API_TOKEN_FILE`.
- Accepts only explicitly mapped serial devices.
- Starts the API/UI but never connects, homes, calibrates, or moves hardware.
- Health checks `/api/v1/health`, which verifies package/build/schema identity
  and writable config, run, and data paths without touching hardware.

For a local offline smoke test:

```bash
mkdir -p /tmp/cubos-smoke/configs /tmp/cubos-smoke/runs /tmp/cubos-smoke/data
docker run --rm \
  --name cubos-smoke \
  --publish 8742:8742 \
  --volume /tmp/cubos-smoke:/var/lib/cub \
  --env 'CUBOS_TRUSTED_HOSTS=["localhost","localhost:8742"]' \
  cubos-appliance:dev
```

Do not map a real serial device for the smoke test.

## Publishing

The Docker workflow publishes tagged `linux/arm64` images to
`ghcr.io/ursa-laboratories/cubos-appliance`. Deploy semantic-version tags pinned
to the workflow-produced digest. Neither `main` nor `latest` is a deployment
target.
