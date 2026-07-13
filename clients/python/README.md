# PiCub CubOS Client

PiCub is the supported Python client and command-line sender for the versioned
CubOS appliance API. It sends gantry, deck, and protocol YAML to the same
`/api/v1/runs` backend used by the Zoo web interface.

The Raspberry Pi no longer runs a separate Flask station worker. CubOS owns the
single persistent gantry session, run gate, policy checks, artifacts, and run
history. This directory is the released `cubos-client` package inside the CubOS
monorepo, and its Git history includes the original PiCub sender and worker.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Submit a protocol

```bash
cubos-send \
  --base-url http://cub.local:8742 \
  --experiment-id protocol-test-001 \
  --gantry path/to/gantry.yaml \
  --deck path/to/deck.yaml \
  --protocol path/to/protocol.yaml
```

The command checks `/api/v1/health`, submits the bundle with
`POST /api/v1/runs`, and polls the returned run resource until it reaches
`succeeded`, `failed`, or `cancelled`. Pressing Ctrl+C requests cancellation
through `POST /api/v1/runs/{run_id}/cancel`.

Useful options:

```text
--mock-mode
--no-health-check
--metadata-json '{"sample":"A1"}'
--timeout-s 900
--poll-interval-s 0.5
```

## Authentication

Do not place the device token directly in a shell command. Use either a
root-readable token file or the environment:

```bash
export CUB_API_TOKEN_FILE=/path/to/cub-api-token
cubos-send ...
```

or:

```bash
export CUB_API_TOKEN='device-token'
cubos-send ...
```

The client sends `Authorization: Bearer <token>` on state-changing requests.

## Python API

`cubos_client` provides:

- `ProtocolBundle.from_paths(...)`
- `StationClient.health(...)`
- `StationClient.submit_run(...)`
- `StationClient.get_run(...)`
- `StationClient.wait_for_run(...)`
- `StationClient.run_protocol(...)`
- `StationClient.cancel_run(...)`
- `StationClient.events(...)`
- `StationClient.artifacts(...)`

Run records retain CubOS `campaign_id` and per-step `results`, so
instrument-specific senders such as the ASMI CSV example can consume the same
standard response.

## Test

```bash
python -m pytest -q
```

Tests are offline and do not connect to or move hardware.
