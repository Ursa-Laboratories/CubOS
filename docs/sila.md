# Control CubOS through SiLA 2

The optional `services/sila/` package exposes the Cub appliance as a SiLA 2
server. An orchestrator can inspect its features, execute configured protocols,
observe progress, request cancellation, and retrieve run artifacts as binary
content. Mounted instruments continue to use the existing CubOS drivers.

```text
SiLA client -> CubOS SiLA server -> authenticated CubOS HTTP API
                                                -> GantrySession and drivers
```

The HTTP API owns hardware access and run persistence. The SiLA service loads
an administrator-controlled catalog of complete gantry/deck/protocol bundles;
clients choose a preset by name. Clients cannot submit arbitrary motion or
instrument commands through this interface.

## Local mock demonstration

Run these commands from the repository root with Python 3.11 or later. This
uses the real CubOS HTTP API and protocol engine with offline instruments and
gantry. No machine connection is needed.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e packages/core -e services/api -e sdk/python -e services/sila
python -m cubos.tools.validate_setup \
  services/sila/examples/mock/gantry.yaml \
  services/sila/examples/mock/deck.yaml \
  services/sila/examples/mock/protocol.yaml
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell and use
PowerShell environment assignments (`$env:CUBOS_OPEN_BROWSER = "false"`, for
example) in place of `export` below.

Start the CubOS API in one terminal. The example token is only for this local
demo; use your deployment's secret when connecting to an existing API. These
paths keep the demo's configs and run artifacts separate from operator data.

```bash
source .venv/bin/activate
export CUBOS_CONFIG_DIR="$PWD/.cubos-sila-demo/configs"
export CUBOS_RUN_DIR="$PWD/.cubos-sila-demo/runs"
export CUBOS_DATA_DB_PATH="$PWD/.cubos-sila-demo/data.sqlite"
export CUBOS_OPEN_BROWSER=false
export CUBOS_API_TOKEN=cubos-local-demo
python -m cubos_api
```

Missing compiled Operator web assets do not prevent this API-only demo. Start
the SiLA server in a second terminal:

```bash
source .venv/bin/activate
export CUBOS_API_TOKEN=cubos-local-demo
python -m cubos_sila --config services/sila/examples/config.yaml
```

In a third terminal, inspect the server and execute the mock preset:

```bash
source .venv/bin/activate
python services/sila/examples/client.py inspect --feature-dir /tmp/cubos-sila-features
python services/sila/examples/client.py execute mock-measurement --run-id demo-001
python services/sila/examples/client.py get-run demo-001
python services/sila/examples/client.py artifacts demo-001
python services/sila/examples/client.py download demo-001 result.json /tmp/cubos-sila-result.json
python -m json.tool /tmp/cubos-sila-result.json
```

The protocol pauses for one second, then makes a synthetic Filmetrics
measurement at the configured sample position. The recorded result includes
`thickness_nm: 150.0` and `goodness_of_fit: 0.95`. Its `result.json` is retrieved
through SiLA binary transfer; the client needs no HTTP token or direct access
to the API filesystem. Mock results are demonstration data, not measurements
from an instrument. This API mock path records the run result artifact and
does not create a scientific measurement campaign in SQLite.

Use a new run ID for each intentional new experiment. Reusing the same ID with
the same server UUID, preset, bundle, and mode resumes observation of that run
without executing it again. A conflicting request using that ID is rejected. The client prints its run ID
before submission, then the SiLA execution UUID, execution status, intermediate
progress, and final response. Progress can be brief for short protocols.

## Features and client operations

The server implements standard `org.silastandard/core/SiLAService/v1` identity
and introspection plus these CubOS features:

| Feature identifier | Surface |
| --- | --- |
| `ai.ursalabs/cubos.appliance/CubStatus/v1` | `SoftwareVersion`, `ServiceAvailable`, `HardwareConnectionState`, `ExecutionState`, `ActiveRunId` |
| `ai.ursalabs/cubos.appliance/ProtocolExecution/v1` | `ListProtocols`, observable `ExecuteProtocol(ProtocolName, RunId)`, `CancelRun(RunId)` |
| `ai.ursalabs/cubos.appliance/RunResults/v1` | `GetRun(RunId)`, `GetArtifacts(RunId)`, `GetArtifact(RunId, ArtifactName)` |

`ListProtocols` includes each preset's name, description, mode, and bundle
digest. `GetRun` returns the authoritative CubOS run record as `RunJson`;
`GetArtifacts` returns names; `GetArtifact` returns bytes as `Content`.
The downloaded feature XML is the detailed typed contract, including declared
errors. GroundControl or another ordinary SiLA client can inspect the same
definitions through `SiLAService`.

`ExecuteProtocol` intermediate responses contain a `Progress` structure with
the run ID, state, event sequence, top-level step index, command, substep,
outcome, completed and total steps, and message. Absent step indexes or unknown
totals use `-1`. Substep events do not inflate the number of completed top-level
steps. The service does not estimate remaining time.

API availability and hardware readiness are distinct. `ServiceAvailable`
indicates backend access; `HardwareConnectionState` reflects the API's observed
connection state and can be unknown or unavailable. Neither a healthy API nor
the installed instrument capabilities prove a calibrated, physically ready
machine.

The current HTTP API offers no global run-state endpoint. Accordingly,
`ExecutionState` currently returns `unknown` and `ActiveRunId` returns an empty
string. Use `GetRun` with a known run ID for that run's authoritative state;
these status properties cannot identify a run started by another client.

The included client uses the `unitelabs-sila` asynchronous client API. An
equivalent external call looks like:

```python
from sila.client import Client, ClientConfig

async with Client(ClientConfig(hostname="127.0.0.1", port=50051, tls=False)) as client:
    command = client.get_command(
        "ai.ursalabs/cubos.appliance/RunResults/v1/Command/GetRun"
    )
    response = await command.execute({"RunId": "demo-001"})
    print(response["RunJson"])
```

## Configuration and deployment

Copy `services/sila/examples/config.yaml` to a deployment-specific location.
Paths in it resolve relative to that configuration file. The service reads and
freezes each YAML bundle at startup; restart it after changing preset files.

| Setting | Meaning/default |
| --- | --- |
| `server_uuid` | Required stable UUID identifying this appliance; assign a unique UUID per deployment |
| `server_name` | Display name, default `CubOS` |
| `host`, `port` | Listen address, default `127.0.0.1:50051` |
| `discovery` | Advertise the server using discovery, default `false` |
| `api_url` | CubOS API base URL, default `http://127.0.0.1:8742` |
| `api_token_env` | Environment variable holding the API token, default `CUBOS_API_TOKEN` |
| `api_token_file` | Optional alternative token file; keep credentials out of the catalog |
| `certificate`, `private_key` | Paired PEM files for SiLA TLS |
| `allow_hardware` | Programmatic configuration permission; the CLI requires `--allow-hardware` |
| `request_timeout_s`, `poll_interval_s` | Backend request timeout and event poll interval, default `10` and `0.25` seconds |
| `max_artifact_bytes` | Per-artifact transfer limit, default `16777216` bytes |
| `max_response_bytes` | Backend JSON response limit, default `4194304` bytes |
| `presets` | Mapping from preset names to `description`, `gantry_file`, `deck_file`, `protocol_file`, and `mock_mode` |

The sample UUID is for the demonstration only. Keep the deployment UUID stable
across restarts so clients can recognize the same appliance. Preset
`mock_mode` defaults to `true`; the CLI requires `--allow-hardware` to load a hardware preset, regardless of the configuration value.

The default unencrypted listener is confined to loopback. To use a protected
remote connection, configure `certificate` and `private_key`, choose the
intended listening address, and pass the trusted PEM certificate to the client:

```bash
python services/sila/examples/client.py --host cub.example.org --ca cub-ca.pem inspect
```

The certificate must cover the hostname used by the client. Discovery is
optional; direct host/port connections work without multicast. TLS encrypts
the SiLA connection. This first service does not add a SiLA client authorization
policy: restrict network access to authorized orchestrators before enabling
hardware presets. The API token authenticates the service to CubOS; it is not
a credential for external SiLA callers.

## Failures, cancellation, and recovery

Declared errors distinguish invalid presets/requests, busy or conflicting
runs, backend authentication, backend unavailability, unknown runs/artifacts,
oversized responses/artifacts, and failed or cancelled protocol execution.
The example client prints the error type/message and exits nonzero. Inspect
the saved run record for the detailed runtime failure; do not infer a hardware
fault from an API authentication or connection error.

For a cancellation request from another terminal:

```bash
python services/sila/examples/client.py cancel demo-001
python services/sila/examples/client.py get-run demo-001
```

`cancel_requested` means a request was recorded. It does not mean motion or an
instrument has stopped. Real runs use the existing API feed-hold behavior;
blocking instrument calls may continue, and mock runs can still succeed after
a cancellation request. Observe the terminal run state and actual hardware.
Use the normal operator emergency procedure when necessary.

Closing a client observation or pressing Ctrl-C does not cancel the CubOS run.
After a disconnect or SiLA-service restart, reconnect and call `GetRun` with
the original run ID, then retrieve its artifacts. Existing API runs remain
owned by the API. SiLA command execution handles are process-local and are
not restored after restart. If submission times out, query the original ID;
do not create a new ID until you have resolved whether the original was
accepted. Restarting the HTTP API during a physical run is outside this
recovery guarantee.

## Operator-led physical validation

The example has been validated offline; physical validation is pending. Hardware presets can
affect the Cub gantry and every mounted instrument used by the selected
protocol. Before enabling them, an operator must complete this procedure on
the intended machine:

1. Copy a known, calibrated gantry/deck/protocol triple into the local preset
   catalog. Start with a bounded, reversible workflow already proven through
   the Operator interface. Check serial identity, mounted tools, offsets,
   travel heights, limits, sample locations, and instrument host dependencies.
2. Run `python -m cubos.tools.validate_setup <gantry.yaml> <deck.yaml>
   <protocol.yaml>` on those exact files. Review every resolved motion target.
3. Configure the preset with `mock_mode: false` and explicitly enable hardware
   execution with `python -m cubos_sila --config <config.yaml> --allow-hardware`.
   Connect and confirm calibration
   through the existing Operator workflow. Keep the normal E-stop accessible.
4. Inspect SiLA identity/status and the preset digest. Execute it once using a
   unique recorded run ID. Observe homing/approach/action/retract behavior and
   instrument action, and compare progress and final data with CubOS.
5. While a suitably slow, reversible test runs, attempt a competing Operator
   or SiLA run and confirm the shared API rejects conflicting access. Request
   cancellation; observe both gantry and instrument behavior until settled.
   Record any delay and terminal outcome.
6. Disconnect the SiLA client, reconnect, and retrieve the original run and
   artifact without executing again. With the API remaining online, restart
   only the SiLA service and repeat that retrieval.

Record the machine/instruments tested, exact preset files and commands,
observed actions, cancellation behavior, and anything left untested in the PR
hardware-validation report before merging hardware-facing changes.
